"""
Tool implementations for Vara MCP Server.
Imports the operational Vara package and the local signal stores.
"""

from __future__ import annotations

import json
import sys
import datetime
from pathlib import Path
from typing import Any, Optional

from . import config

# Make the operational Vara package importable
if str(config.VARA_PACKAGE_PATH) not in sys.path:
    sys.path.insert(0, str(config.VARA_PACKAGE_PATH))


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default if default is not None else []


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ─── TOOL: vara_run_scan ─────────────────────────────────────────────────────

def vara_run_scan(arguments: dict) -> dict:
    """Execute a full Real Vara scan."""
    try:
        from vara_scan import run_vara_scan, VaraConfig
    except ImportError as e:
        return {
            "error": f"Cannot import operational Vara package from {config.VARA_PACKAGE_PATH}: {e}",
            "hint": "Set VARA_PACKAGE_PATH to the directory containing vara_scan.py",
        }

    keywords = arguments.get("keywords") or ["AI", "agentic", "compute"]
    planes = arguments.get("active_planes") or list(config.DEFAULT_PLANES)
    sweep = int(arguments.get("sweep_depth_hours") or config.DEFAULT_SWEEP_HOURS)
    label = arguments.get("scan_label") or f"mcp_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M')}"

    cfg_kwargs = {
        "keywords": keywords,
        "sweep_depth_hours": sweep,
        "active_planes": planes,
        "scan_label": label,
    }
    for key in (
        "enable_dual_track", "high_novelty_floor", "weak_novelty_floor",
        "enable_multi_timescale", "use_firecrawl",
    ):
        if key in arguments:
            cfg_kwargs[key] = arguments[key]

    try:
        cfg = VaraConfig(**cfg_kwargs)
    except TypeError:
        cfg = VaraConfig(
            keywords=keywords,
            sweep_depth_hours=sweep,
            active_planes=planes,
            scan_label=label,
        )

    import vara_scan as vs
    original_output = getattr(vs, "OUTPUT_DIR", "vara_output")
    vs.OUTPUT_DIR = str(config.OUTPUT_DIR)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        report = run_vara_scan(cfg)
    finally:
        vs.OUTPUT_DIR = original_output

    if hasattr(report, "__dataclass_fields__"):
        from dataclasses import asdict
        result = asdict(report)
    elif isinstance(report, dict):
        result = report
    else:
        result = {"raw": str(report)}

    if arguments.get("generate_fir"):
        result["field_intel_report"] = _render_fir_from_report(result, arguments)

    return result


# ─── TOOL: vara_list_scans ───────────────────────────────────────────────────

def vara_list_scans(arguments: dict) -> dict:
    limit = int(arguments.get("limit") or 20)
    since = arguments.get("since")
    label_contains = (arguments.get("label_contains") or "").lower()

    scans = []
    if not config.OUTPUT_DIR.exists():
        return {"scans": [], "count": 0, "note": f"No output dir at {config.OUTPUT_DIR}"}

    for path in sorted(config.OUTPUT_DIR.glob("scan_*.json"), reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        meta = {
            "scan_id": data.get("scan_id"),
            "scan_label": data.get("scan_label"),
            "timestamp": data.get("timestamp"),
            "config_hash": data.get("config_hash"),
            "active_planes": data.get("active_planes"),
            "signal_count": len(data.get("signals") or []),
            "null_result": data.get("null_result"),
            "file": path.name,
        }
        if since and (meta["timestamp"] or "") < since:
            continue
        if label_contains and label_contains not in (meta["scan_label"] or "").lower():
            continue
        scans.append(meta)
        if len(scans) >= limit:
            break

    return {"scans": scans, "count": len(scans)}


# ─── TOOL: vara_get_scan ─────────────────────────────────────────────────────

def vara_get_scan(arguments: dict) -> dict:
    scan_id = (arguments.get("scan_id") or "").strip()
    if not scan_id:
        return {"error": "scan_id is required"}

    include_signals = arguments.get("include_signals", True)
    prefix = scan_id[:8]

    candidates = list(config.OUTPUT_DIR.glob(f"scan_{prefix}*.json")) if config.OUTPUT_DIR.exists() else []
    if not candidates and config.OUTPUT_DIR.exists():
        for path in config.OUTPUT_DIR.glob("scan_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("scan_id", "").startswith(scan_id) or data.get("scan_id") == scan_id:
                    candidates = [path]
                    break
            except Exception:
                continue

    if not candidates:
        return {"error": f"No scan found matching '{scan_id}'", "searched": str(config.OUTPUT_DIR)}

    with open(candidates[0], "r", encoding="utf-8") as f:
        data = json.load(f)

    if not include_signals:
        data = {k: v for k, v in data.items() if k != "signals"}
        data["signals_omitted"] = True

    return data


# ─── TOOL: vara_query_signals ────────────────────────────────────────────────

def vara_query_signals(arguments: dict) -> dict:
    vault = _load_json(config.VAULT_SIGNALS_PATH, [])
    results = []

    plane = arguments.get("plane")
    min_nov = arguments.get("min_novelty")
    entity = (arguments.get("entity") or "").lower()
    since = arguments.get("since")
    until = arguments.get("until")
    origin = arguments.get("origin") or "any"
    canonized_only = bool(arguments.get("canonized_only"))
    limit = int(arguments.get("limit") or 50)

    for entry in vault:
        sig = entry.get("signal") or {}
        if plane and sig.get("plane") != plane:
            continue
        if min_nov is not None and float(sig.get("novelty_score") or 0) < float(min_nov):
            continue
        if entity:
            blob = f"{sig.get('title','')} {sig.get('content','')} {entry.get('source_id','')}".lower()
            if entity not in blob:
                continue
        committed = entry.get("committed_at") or ""
        if since and committed < since:
            continue
        if until and committed > until:
            continue
        if origin != "any" and entry.get("origin") != origin:
            continue
        if canonized_only and not entry.get("canonized"):
            continue
        results.append(entry)
        if len(results) >= limit:
            break

    out = {"count": len(results), "signals": results}

    if arguments.get("include_veil_hold"):
        hold = _load_json(config.VEIL_HOLD_PATH, {})
        out["veil_hold_count"] = len(hold) if isinstance(hold, dict) else 0
        out["veil_hold_sample"] = list(hold.values())[:10] if isinstance(hold, dict) else []

    return out


# ─── TOOL: vara_get_veil_state ───────────────────────────────────────────────

def vara_get_veil_state(arguments: dict) -> dict:
    hold = _load_json(config.VEIL_HOLD_PATH, {})
    trajectories = _load_json(config.VEIL_TRAJECTORIES_PATH, {})

    plane = arguments.get("plane")
    signal_id = arguments.get("signal_id")

    entries = list(hold.values()) if isinstance(hold, dict) else []
    if plane:
        entries = [e for e in entries if (e.get("signal") or {}).get("plane") == plane]
    if signal_id:
        entries = [e for e in entries if e.get("signal_id") == signal_id or e.get("source_id") == signal_id]

    result = {
        "held_count": len(entries),
        "held_entries": entries[:100],
    }
    if arguments.get("include_trajectories", True):
        result["trajectories"] = trajectories
    return result


# ─── TOOL: vara_generate_fir ─────────────────────────────────────────────────

def _render_fir_from_report(report: dict, arguments: dict) -> str:
    """Minimal Operator-Tier FIR renderer."""
    series = arguments.get("series") or "FIR-XXX"
    baseline = arguments.get("baseline") or "prior"
    ts = report.get("timestamp") or datetime.datetime.utcnow().isoformat()
    planes = ", ".join(report.get("active_planes") or [])
    signals = report.get("signals") or []
    null = report.get("null_result", False)

    lines = [
        f"FIELD INTEL REPORT  ·  SERIES {series}  ·  VARA:SCAN INTELLIGENCE LAYER",
        "",
        f"FIELD INTEL REPORT {series}",
        f"VARA:SCAN CYCLE {report.get('scan_id','')[:8]}  |  Issued: {ts}",
        "",
        "Classification: Operator-Tier Intelligence Brief",
        f"Baseline: {baseline}",
        "",
        "SECTION 01 — EXECUTIVE SUMMARY",
        f"  Scan label: {report.get('scan_label')}",
        f"  Active planes: {planes}",
        f"  Signals returned: {len(signals)}  |  Null result: {null}",
        f"  Config hash: {report.get('config_hash')}",
        "",
        "SECTION 02 — TARGET NODE DELTA REGISTRY",
        "  (Populate from high-novelty / entity signals in full implementation)",
        "",
        "SECTION 05 — EMERGENT SIGNALS",
    ]
    for i, s in enumerate(signals[:12], 1):
        title = (s.get("title") or s.get("content") or "")[:120]
        plane = s.get("plane", "?")
        nov = s.get("novelty_score", 0)
        lines.append(f"  {i}. [{plane}] nov={nov:.3f}  {title}")

    lines += [
        "",
        "SECTION 08 — SIGNAL CONTINUITY — CARRY-FORWARD TO NEXT CYCLE",
        "  Review Veil hold and weak-signal trajectories before next cycle.",
        "",
        f"VARA:SCAN {report.get('scan_id','')[:8]} · COMPILED BY OPERATOR INTELLIGENCE LAYER",
    ]
    return "\n".join(lines)


def vara_generate_fir(arguments: dict) -> dict:
    scan_id = arguments.get("scan_id")
    if not scan_id:
        return {"error": "scan_id is required for FIR generation in this version"}

    report = vara_get_scan({"scan_id": scan_id, "include_signals": True})
    if "error" in report:
        return report

    markdown = _render_fir_from_report(report, arguments)
    return {
        "format": arguments.get("format") or "operator_tier",
        "scan_id": report.get("scan_id"),
        "markdown": markdown,
    }


# ─── Dispatcher ──────────────────────────────────────────────────────────────

TOOL_HANDLERS = {
    "vara_run_scan": vara_run_scan,
    "vara_list_scans": vara_list_scans,
    "vara_get_scan": vara_get_scan,
    "vara_query_signals": vara_query_signals,
    "vara_get_veil_state": vara_get_veil_state,
    "vara_generate_fir": vara_generate_fir,
}


def call_tool(name: str, arguments: dict) -> Any:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    try:
        return handler(arguments or {})
    except Exception as e:
        return {"error": str(e), "tool": name}
