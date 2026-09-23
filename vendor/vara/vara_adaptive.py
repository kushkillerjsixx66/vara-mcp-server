"""
vara_adaptive.py — Adaptive threshold feedback for Vara dual-track scoring.
Placeholder/minimal implementation for MCP packaging.
Full dual-track logic lives in vara_scan.py.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AdaptiveState:
    pass_rate: float = 0.0
    block_rate: float = 0.0
    cycles: int = 0
    high_floor: float = 0.15
    weak_floor: float = 0.05


def update_adaptive_thresholds(state: AdaptiveState, passed: int, blocked: int, total: int) -> AdaptiveState:
    if total <= 0:
        return state
    state.cycles += 1
    state.pass_rate = passed / total
    state.block_rate = blocked / total
    # Bounded adjustment — keep floors in safe range
    if state.pass_rate > 0.85:
        state.high_floor = min(0.25, state.high_floor + 0.01)
    elif state.pass_rate < 0.3:
        state.high_floor = max(0.10, state.high_floor - 0.01)
    return state
