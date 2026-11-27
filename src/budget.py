"""Scan budget for vara_run_scan (operator ruling 2026-11-27).

The harvest is the expensive operation; reads of the existing archive are
free and stay unlimited. Two tiers, dials in config.py:

  anonymous — sweep/planes capped, one shared daily pool plus a per-caller
              cap so a single agent loop cannot drain the pool.
  keyed     — an operator-issued key (VARA_API_KEYS) unlocks full depth
              (the pinned 168h FIR configuration) with a per-key daily
              allowance.

Counters live in a small JSON state kept in the local data root (hot copy)
and mirrored to the durable store. Within a UTC day counters only grow,
so merging two instances' copies is a per-counter max — a warm instance
with a stale copy can under-count, never over-count, and the durable copy
bounds the drift. Enforcement is therefore deliberately soft across
concurrent serverless instances; it is a budget, not a vault lock.

Privacy: budget state stores only truncated hashes — sha256(key)[:12] for
keys, sha256(ip)[:16] for callers. Raw keys and raw IPs are never written.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Optional

from . import config
from . import durable

_STATE_FILE = "scan_budget.json"


def _today() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _empty_state(day: str) -> dict:
    return {"date": day, "anon_global": 0, "anon_callers": {}, "keyed": {}}


def _local_path() -> Path:
    return config.VARA_DATA_ROOT / _STATE_FILE


def _read_local() -> Optional[dict]:
    try:
        path = _local_path()
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _merge(a: Optional[dict], b: Optional[dict], day: str) -> dict:
    """Union two state copies for `day`, per-counter max (monotonic)."""
    out = _empty_state(day)
    for src in (a, b):
        if not src or src.get("date") != day:
            continue
        out["anon_global"] = max(out["anon_global"], int(src.get("anon_global") or 0))
        for bucket in ("anon_callers", "keyed"):
            for ident, n in (src.get(bucket) or {}).items():
                out[bucket][ident] = max(out[bucket].get(ident, 0), int(n or 0))
    return out


def load_state() -> dict:
    day = _today()
    return _merge(_read_local(), durable.load_budget_state(), day)


def _save_state(state: dict) -> None:
    try:
        path = _local_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass
    durable.save_budget_state(state)


def key_id_for(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def caller_id_for(ip: Optional[str]) -> str:
    if not ip:
        return "unknown"
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def resolve_tier(api_key: Optional[str]) -> dict:
    """Map a presented key to a tier. Unknown keys fall back to anonymous —
    a wrong key must never become an error that leaks which keys exist."""
    if api_key:
        for known in config.api_keys():
            if hmac.compare_digest(api_key, known):
                return {"tier": "keyed", "key_id": key_id_for(api_key)}
    return {"tier": "anonymous", "key_id": None}


def tier_caps(tier: str) -> dict:
    if tier == "keyed":
        return {
            "max_sweep_hours": config.KEYED_MAX_SWEEP_HOURS,
            "max_planes": config.KEYED_MAX_PLANES,
            "daily_budget": config.KEYED_DAILY_BUDGET,
        }
    return {
        "max_sweep_hours": config.ANON_MAX_SWEEP_HOURS,
        "max_planes": config.ANON_MAX_PLANES,
        "daily_budget": config.ANON_DAILY_BUDGET,
    }


def apply_caps(tier: str, sweep: int, planes: list) -> tuple[int, list, list]:
    """Clamp sweep/planes to the tier's caps. Returns (sweep, planes,
    notices) — clamping is always announced, never silent."""
    caps = tier_caps(tier)
    notices: list[str] = []
    if sweep > caps["max_sweep_hours"]:
        notices.append(
            f"sweep_depth_hours capped at {caps['max_sweep_hours']} for the "
            f"{tier} tier (requested {sweep})"
        )
        sweep = caps["max_sweep_hours"]
    if len(planes) > caps["max_planes"]:
        dropped = planes[caps["max_planes"]:]
        planes = planes[: caps["max_planes"]]
        notices.append(
            f"active_planes capped at {caps['max_planes']} for the {tier} "
            f"tier (dropped: {', '.join(dropped)})"
        )
    return sweep, planes, notices


def _counters_for(state: dict, tier: str, key_id: Optional[str], caller_id: str) -> dict:
    """Current usage against each limit that binds this caller."""
    if tier == "keyed":
        return {
            "scope_limits": [("key", int((state.get("keyed") or {}).get(key_id or "", 0)),
                              config.KEYED_DAILY_BUDGET)],
        }
    return {
        "scope_limits": [
            ("global", int(state.get("anon_global") or 0), config.ANON_DAILY_BUDGET),
            ("caller", int((state.get("anon_callers") or {}).get(caller_id, 0)),
             config.ANON_PER_CALLER_DAILY),
        ],
    }


def reserve(tier: str, key_id: Optional[str], caller_id: str) -> dict:
    """Check the budget and, if allowed, consume one scan.

    Returns {"allowed": bool, "scope": <binding scope when denied>,
             "used": int, "limit": int, "date": day}.
    """
    state = load_state()
    usage = _counters_for(state, tier, key_id, caller_id)
    for scope, used, limit in usage["scope_limits"]:
        if used >= limit:
            return {"allowed": False, "scope": scope, "used": used,
                    "limit": limit, "date": state["date"]}
    if tier == "keyed":
        state.setdefault("keyed", {})[key_id or ""] = \
            int((state.get("keyed") or {}).get(key_id or "", 0)) + 1
        used = state["keyed"][key_id or ""]
        limit = config.KEYED_DAILY_BUDGET
    else:
        state["anon_global"] = int(state.get("anon_global") or 0) + 1
        callers = state.setdefault("anon_callers", {})
        callers[caller_id] = int(callers.get(caller_id, 0)) + 1
        used, limit = state["anon_global"], config.ANON_DAILY_BUDGET
    _save_state(state)
    return {"allowed": True, "scope": None, "used": used, "limit": limit,
            "date": state["date"]}


def refund(tier: str, key_id: Optional[str], caller_id: str) -> None:
    """Give a reserved scan back (the scan itself raised before running)."""
    state = load_state()
    if state.get("date") != _today():
        return
    if tier == "keyed":
        bucket = state.setdefault("keyed", {})
        if key_id in bucket:
            bucket[key_id] = max(0, int(bucket[key_id]) - 1)
    else:
        state["anon_global"] = max(0, int(state.get("anon_global") or 0) - 1)
        callers = state.setdefault("anon_callers", {})
        if caller_id in callers:
            callers[caller_id] = max(0, int(callers[caller_id]) - 1)
    _save_state(state)


def status(tier: str, key_id: Optional[str], caller_id: str) -> dict:
    """Read-only budget snapshot for attaching to a scan result."""
    state = load_state()
    usage = _counters_for(state, tier, key_id, caller_id)
    binding_scope, binding_used, binding_limit = min(
        usage["scope_limits"], key=lambda t: t[2] - t[1]
    )
    return {
        "tier": tier,
        "date": state["date"],
        "used_today": binding_used,
        "daily_limit": binding_limit,
        "remaining_today": max(0, binding_limit - binding_used),
        "binding_scope": binding_scope,
        "resets_at": f"{state['date']}T24:00:00Z (next UTC midnight)",
    }
