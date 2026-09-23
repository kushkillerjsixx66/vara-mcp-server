"""
vara_scan.py — Vara Scan Pipeline Orchestrator (MCP vendor copy)
Dual-track aware; imports sentinel + veil/vault.
"""
from __future__ import annotations

import hashlib
import json
import datetime
import uuid
import os
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, List

from vara_sentinel import run_sentinel, sentinel_to_vault_handoff
from vara_veil_vault import route_signals

logger = logging.getLogger("vara.scan")

DRIFT_LOG_PATH = "vara_drift_log.json"
OUTPUT_DIR = "vara_output"

VALID_PLANES = {
    "social", "scientific", "tech", "adjacent_possible",
    "economic", "dark", "geopolitical", "persons", "firecrawl",
}


@dataclass
class VaraConfig:
    keywords: list
    sweep_depth_hours: int
    active_planes: list
    scan_label: str
    velocity_spike_threshold: float = 3.5
    fringe_to_main_ratio: float = 0.40
    output_formats: list = field(default_factory=lambda: ["markdown", "json"])
    extra_rss_feeds: list = field(default_factory=list)
    extra_substacks: list = field(default_factory=list)
    use_firecrawl: bool = False
    enable_dual_track: bool = True
    high_novelty_floor: float = 0.15
    weak_novelty_floor: float = 0.05
    enable_multi_timescale: bool = True
    timescale_windows: list = field(default_factory=lambda: [6, 24, 72, 168])
    config_hash: str = ""

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "keywords": sorted(self.keywords),
                "sweep_depth_hours": self.sweep_depth_hours,
                "active_planes": sorted(self.active_planes),
                "scan_label": self.scan_label,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class VaraScanReport:
    scan_id: str
    scan_label: str
    timestamp: str
    config_hash: str
    keywords: list
    active_planes: list
    signals: list
    clusters: list
    drift_log: list
    null_result: bool
    error: Optional[str] = None
    sentinel: Optional[dict] = None
    routing: Optional[dict] = None


def harvest_plane(plane: str, keywords: list, sweep_hours: int, **kwargs) -> list:
    """Minimal harvester — tries real module, else returns empty (safe)."""
    try:
        from vara_harvesters import harvest_plane as _hp
        return _hp(plane=plane, keywords=keywords, sweep_hours=sweep_hours, **kwargs)
    except Exception as e:
        logger.warning("harvest_plane %s failed or unavailable: %s", plane, e)
        return []


def stage_intake(config: VaraConfig) -> tuple:
    errors = []
    if not config.keywords:
        errors.append("keywords empty")
    if config.sweep_depth_hours <= 0:
        errors.append("sweep_depth_hours must be > 0")
    if not config.active_planes:
        errors.append("active_planes empty")
    if errors:
        return [], errors
    all_signals = []
    for plane in config.active_planes:
        try:
            plane_sigs = harvest_plane(
                plane=plane,
                keywords=config.keywords,
                sweep_hours=config.sweep_depth_hours,
                extra_rss_feeds=config.extra_rss_feeds,
                extra_substacks=config.extra_substacks,
            )
            all_signals.extend(plane_sigs)
        except Exception as e:
            logger.error("Intake plane=%s failed: %s", plane, e)
    return all_signals, errors


def stage_cluster(signals: list) -> tuple:
    from collections import defaultdict
    buckets = defaultdict(list)
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        plane = sig.get("plane", "unknown")
        novelty = float(sig.get("novelty_score", 0.0))
        band = round(novelty * 4) / 4
        key = f"{plane}:{band:.2f}"
        cid = "c:" + hashlib.sha256(key.encode()).hexdigest()[:8]
        sig["cluster_id"] = cid
        buckets[cid].append(sig)
    enriched = [s for bucket in buckets.values() for s in bucket]
    clusters = [
        {
            "cluster_id": cid,
            "plane": members[0].get("plane", ""),
            "member_count": len(members),
            "avg_novelty": round(sum(m.get("novelty_score", 0) for m in members) / len(members), 4),
        }
        for cid, members in buckets.items()
    ]
    return enriched, clusters


def run_vara_scan(config: VaraConfig) -> VaraScanReport:
    scan_id = str(uuid.uuid4())
    timestamp = datetime.datetime.utcnow().isoformat()
    config.config_hash = config.compute_hash()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    raw_signals, intake_errors = stage_intake(config)
    if intake_errors:
        return VaraScanReport(
            scan_id=scan_id, scan_label=config.scan_label, timestamp=timestamp,
            config_hash=config.config_hash, keywords=config.keywords,
            active_planes=config.active_planes, signals=[], clusters=[],
            drift_log=[], null_result=True, error="; ".join(intake_errors),
        )

    if not raw_signals:
        # Normalize to dicts if HarvestedSignal objects
        return VaraScanReport(
            scan_id=scan_id, scan_label=config.scan_label, timestamp=timestamp,
            config_hash=config.config_hash, keywords=config.keywords,
            active_planes=config.active_planes, signals=[], clusters=[],
            drift_log=[], null_result=True,
        )

    # Normalize signals to dicts
    normalized = []
    for s in raw_signals:
        if hasattr(s, "__dataclass_fields__"):
            normalized.append(asdict(s))
        elif isinstance(s, dict):
            normalized.append(s)
        else:
            normalized.append({"content": str(s), "novelty_score": 0.1, "plane": "tech"})

    clustered, clusters = stage_cluster(normalized)
    sentinel_report = run_sentinel(clustered, scan_id)
    handoff = sentinel_to_vault_handoff(sentinel_report)
    vault_report, veil_report = route_signals(
        passed_signals=handoff["passed_signals"],
        deferred_signals=handoff["deferred_signals"],
        scan_id=scan_id,
    )
    output_signals = handoff["passed_signals"] + list(getattr(veil_report, "promoted_signals", []) or [])

    report = VaraScanReport(
        scan_id=scan_id,
        scan_label=config.scan_label,
        timestamp=timestamp,
        config_hash=config.config_hash,
        keywords=config.keywords,
        active_planes=config.active_planes,
        signals=output_signals,
        clusters=clusters,
        drift_log=[],
        null_result=len(clustered) == 0,
        sentinel={
            "sentinel_id": sentinel_report.sentinel_id,
            "total_input": sentinel_report.total_input,
            "passed": sentinel_report.passed,
            "blocked": sentinel_report.blocked,
            "deferred": sentinel_report.deferred,
            "pruned": sentinel_report.pruned,
        },
        routing={
            "harvested": len(clustered),
            "vault_bound": len(output_signals),
            "veil_held": len(getattr(veil_report, "held_entries", []) or []),
            "veil_promoted": getattr(veil_report, "promoted", 0),
        },
    )

    out_path = os.path.join(OUTPUT_DIR, f"scan_{scan_id[:8]}.json")
    with open(out_path, "w") as f:
        json.dump(asdict(report), f, indent=2, default=str)

    return report
