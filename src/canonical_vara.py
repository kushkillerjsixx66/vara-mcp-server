"""Canonical Vara conformance boundary for the MCP operational scan.

This module deliberately mirrors the canonical Vault scan contracts without
creating a second promotion authority. The operational scan remains the
acquisition/analysis engine; this boundary projects its output into the
canonical result shape, validates lineage/integrity, and only then persists a
canonical scan artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


REQUIRED_LINEAGE = ("seq", "operator_id", "role", "altitude")


@dataclass
class CanonicalVaraScanResult:
    weak_signals: list[dict[str, Any]]
    trends: list[dict[str, Any]]
    anomalies: list[dict[str, Any]]
    unspecified: list[Any]
    lineage: list[dict[str, Any]]


class CanonicalVaraIntegrity:
    def validate(self, scan: CanonicalVaraScanResult) -> tuple[bool, list[str]]:
        errors: list[str] = []

        for index, entry in enumerate(scan.lineage):
            missing = [key for key in REQUIRED_LINEAGE if key not in entry]
            if missing:
                errors.append(f"lineage[{index}] missing: {','.join(missing)}")

        for index, signal in enumerate(scan.weak_signals):
            if not signal.get("key") or not signal.get("description"):
                errors.append(f"weak_signals[{index}] missing key/description")
            if "evidence" not in signal:
                errors.append(f"weak_signals[{index}] missing evidence")

        for index, anomaly in enumerate(scan.anomalies):
            if not anomaly.get("field") or "reason" not in anomaly:
                errors.append(f"anomalies[{index}] missing field/reason")

        return not errors, errors


class CanonicalVaraPromoter:
    def should_promote(self, scan: CanonicalVaraScanResult) -> bool:
        return bool(scan.lineage) and bool(scan.weak_signals or scan.anomalies)


class CanonicalVaraStore:
    """Canonical-shape storage boundary for the MCP deployment."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, scan: CanonicalVaraScanResult) -> Path:
        seq = scan.lineage[-1]["seq"]
        path = self.root / f"scan_{seq}.json"
        path.write_text(json.dumps(asdict(scan), indent=2, default=str), encoding="utf-8")
        return path


def _signal_to_weak(signal: dict[str, Any], index: int) -> dict[str, Any]:
    key = str(signal.get("signal_id") or signal.get("source_id") or f"signal-{index}")
    description = str(signal.get("content") or signal.get("title") or "Operational Vara signal")
    evidence = signal.get("source_url") or signal.get("source_id") or signal.get("observation_id") or ""
    return {
        "key": key,
        "description": description,
        "evidence": evidence,
        "signal": signal,
    }


def project_operational_report(
    report: dict[str, Any],
    lineage: list[dict[str, Any]] | None,
) -> tuple[CanonicalVaraScanResult, list[str]]:
    """Project the operational report into the canonical scan contract."""
    signals = report.get("signals") or []
    weak = [_signal_to_weak(s, i) for i, s in enumerate(signals) if isinstance(s, dict)]

    canonical = CanonicalVaraScanResult(
        weak_signals=weak,
        trends=[
            {
                "name": cluster.get("cluster_id") or f"cluster-{i}",
                "signals": cluster.get("members") or cluster.get("signal_ids") or [],
            }
            for i, cluster in enumerate(report.get("clusters") or [])
            if isinstance(cluster, dict)
        ],
        anomalies=[],
        unspecified=[] if not report.get("null_result") else [{"reason": "operational scan returned null result"}],
        lineage=list(lineage or []),
    )
    return canonical, []


def govern_operational_report(
    report: dict[str, Any],
    lineage: list[dict[str, Any]] | None,
    store_root: str | Path,
) -> dict[str, Any]:
    """Apply canonical integrity + promotion semantics to an operational report."""
    canonical, _ = project_operational_report(report, lineage)
    integrity = CanonicalVaraIntegrity()
    valid, errors = integrity.validate(canonical)
    promoter = CanonicalVaraPromoter()

    result = dict(report)
    result["canonical"] = asdict(canonical)
    result["canonical_conformance"] = {
        "lineage_present": bool(canonical.lineage),
        "integrity_valid": valid,
        "promotion_allowed": valid and promoter.should_promote(canonical),
        "errors": errors,
    }

    if valid and promoter.should_promote(canonical):
        path = CanonicalVaraStore(store_root).save(canonical)
        result["canonical_conformance"]["promotion_path"] = str(path)
        result["canonical_conformance"]["promotion_event"] = {
            "type": "vault_promotion",
            "source": "vara_mcp_canonical_boundary",
            "lineage": canonical.lineage,
            "path": str(path),
        }
    return result
