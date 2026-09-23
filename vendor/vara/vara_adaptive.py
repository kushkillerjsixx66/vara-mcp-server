"""
vara_adaptive.py — Adaptive threshold + multi-timescale feedback for Vara
Operator: JRM-01 @liminaljermo
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class AdaptiveState:
    pass_rate: float = 0.0
    block_rate: float = 0.0
    cycles: int = 0
    high_floor: float = 0.15
    weak_floor: float = 0.05
    window_pass_rates: Dict[int, float] = field(default_factory=dict)


@dataclass
class TimescaleSnapshot:
    window_hours: int
    signal_count: int
    avg_novelty: float
    pass_rate: float


def update_adaptive_thresholds(
    state: AdaptiveState,
    passed: int,
    blocked: int,
    total: int,
) -> AdaptiveState:
    if total <= 0:
        return state
    state.cycles += 1
    state.pass_rate = passed / total
    state.block_rate = blocked / total
    if state.pass_rate > 0.85:
        state.high_floor = min(0.25, state.high_floor + 0.01)
    elif state.pass_rate < 0.3:
        state.high_floor = max(0.10, state.high_floor - 0.01)
    if state.pass_rate > 0.7:
        state.weak_floor = min(0.12, state.weak_floor + 0.005)
    elif state.pass_rate < 0.2:
        state.weak_floor = max(0.03, state.weak_floor - 0.005)
    return state


def snapshot_timescale(
    window_hours: int,
    signals: list,
    passed: int,
    total: int,
) -> TimescaleSnapshot:
    novs = [float(s.get("novelty_score", 0)) for s in signals if isinstance(s, dict)]
    avg = sum(novs) / len(novs) if novs else 0.0
    return TimescaleSnapshot(
        window_hours=window_hours,
        signal_count=len(signals),
        avg_novelty=round(avg, 4),
        pass_rate=round(passed / total, 4) if total else 0.0,
    )


def multi_timescale_summary(
    windows: List[int],
    signals_by_window: Dict[int, list],
    pass_counts: Dict[int, int],
) -> list:
    out = []
    for w in windows:
        sigs = signals_by_window.get(w, [])
        p = pass_counts.get(w, 0)
        out.append(snapshot_timescale(w, sigs, p, len(sigs) or 1))
    return out
