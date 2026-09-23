"""
VARA Sentinel — G1/G2/G3 Governance Gates (dual-track)
Operator: JRM-01 @liminaljermo
Spec ref: Lattice Unified Spec §7, §8, §10

Gate definitions:
  G1 — Coherence: novelty threshold (high track 0.15, weak track softened)
  G2 — Attention: budget per track
  G3 — Reversibility: always passes at harvest
"""

import datetime
import uuid
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

G1_NOVELTY_THRESHOLD = 0.15
G1_WEAK_NOVELTY_FLOOR = 0.05
G2_ATTENTION_BUDGET = 100
G2_WEAK_BUDGET = 50


class GateVerdict(Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    DEFER = "DEFER"
    PRUNE = "PRUNE"


@dataclass
class GateResult:
    gate: str
    verdict: GateVerdict
    reason: str
    signal_id: str
    score: Optional[float] = None


@dataclass
class SentinelReport:
    sentinel_id: str
    scan_id: str
    timestamp: str
    g1_threshold: float
    g2_budget: int
    total_input: int
    passed: int
    blocked: int
    pruned: int
    deferred: int
    gate_log: list
    passed_signals: list
    blocked_signals: list
    pruned_signals: list
    deferred_signals: list
    tier2_errors: list
    locked: bool = False


def gate_g1(signal: dict, weak_track: bool = False) -> GateResult:
    novelty = signal.get("novelty_score", 0.0)
    content = signal.get("content", "").strip()
    title = signal.get("title", "").strip()
    threshold = G1_WEAK_NOVELTY_FLOOR if weak_track else G1_NOVELTY_THRESHOLD
    sid = signal.get("signal_id", signal.get("source_id", "unknown"))

    if not content and not title:
        return GateResult("G1", GateVerdict.BLOCK, "empty content and title", sid, 0.0)
    if novelty < threshold:
        return GateResult("G1", GateVerdict.BLOCK, f"novelty {novelty:.3f} below {threshold}", sid, novelty)
    return GateResult("G1", GateVerdict.PASS, f"novelty {novelty:.3f} >= {threshold}", sid, novelty)


def gate_g2(signal: dict, current_count: int, budget: int = G2_ATTENTION_BUDGET) -> GateResult:
    sid = signal.get("signal_id", signal.get("source_id", "unknown"))
    if current_count >= budget:
        return GateResult("G2", GateVerdict.PRUNE, f"budget exhausted ({current_count}/{budget})", sid)
    if current_count >= int(budget * 0.90):
        return GateResult("G2", GateVerdict.DEFER, f"soft limit ({current_count}/{budget})", sid)
    return GateResult("G2", GateVerdict.PASS, f"within budget ({current_count}/{budget})", sid)


def gate_g3(signal: dict) -> GateResult:
    sid = signal.get("signal_id", signal.get("source_id", "unknown"))
    return GateResult("G3", GateVerdict.PASS, "harvest stage — reversibility preserved", sid)


def run_sentinel(signals: list, scan_id: str, weak_track: bool = False) -> SentinelReport:
    sentinel_id = str(uuid.uuid4())
    timestamp = datetime.datetime.utcnow().isoformat()
    budget = G2_WEAK_BUDGET if weak_track else G2_ATTENTION_BUDGET
    threshold = G1_WEAK_NOVELTY_FLOOR if weak_track else G1_NOVELTY_THRESHOLD

    passed_signals, blocked_signals, pruned_signals, deferred_signals = [], [], [], []
    gate_log, tier2_errors = [], []
    g2_count = 0

    for sig in signals:
        sid = sig.get("signal_id", sig.get("source_id", "unknown"))
        r1 = gate_g1(sig, weak_track=weak_track)
        gate_log.append({"gate": r1.gate, "verdict": r1.verdict.value, "reason": r1.reason, "signal_id": r1.signal_id, "score": r1.score})
        if r1.verdict == GateVerdict.BLOCK:
            blocked_signals.append(sig)
            tier2_errors.append(f"G1_BLOCK:{sid}")
            continue
        r2 = gate_g2(sig, g2_count, budget)
        gate_log.append({"gate": r2.gate, "verdict": r2.verdict.value, "reason": r2.reason, "signal_id": r2.signal_id})
        g2_count += 1
        if r2.verdict == GateVerdict.PRUNE:
            pruned_signals.append(sig)
            tier2_errors.append(f"G2_BUDGET_EXCEEDED:{sid}")
            continue
        if r2.verdict == GateVerdict.DEFER:
            deferred_signals.append(sig)
            continue
        r3 = gate_g3(sig)
        gate_log.append({"gate": r3.gate, "verdict": r3.verdict.value, "reason": r3.reason, "signal_id": r3.signal_id})
        passed_signals.append(sig)

    return SentinelReport(
        sentinel_id=sentinel_id, scan_id=scan_id, timestamp=timestamp,
        g1_threshold=threshold, g2_budget=budget, total_input=len(signals),
        passed=len(passed_signals), blocked=len(blocked_signals),
        pruned=len(pruned_signals), deferred=len(deferred_signals),
        gate_log=gate_log, passed_signals=passed_signals,
        blocked_signals=blocked_signals, pruned_signals=pruned_signals,
        deferred_signals=deferred_signals, tier2_errors=tier2_errors, locked=False,
    )


def sentinel_to_vault_handoff(report: SentinelReport) -> dict:
    return {
        "passed_signals": report.passed_signals,
        "deferred_signals": report.deferred_signals,
        "scan_id": report.scan_id,
        "sentinel_id": report.sentinel_id,
    }
