"""
vara_scan.py — Vara Scan Pipeline Orchestrator (MCP vendor)
Dual-track (high + weak), entity first-seen enrichment, Sentinel + Veil/Vault.
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
    # Semantic clustering contract
    clustering_min_cluster_size: int = 2
    clustering_min_samples: int = 1
    clustering_metric: str = "cosine"
    cluster_selection_epsilon: float = 0.0
    embedding_model: str = "all-MiniLM-L6-v2"
    enable_incremental_lineage: bool = True

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "keywords": sorted(self.keywords),
                "sweep_depth_hours": self.sweep_depth_hours,
                "active_planes": sorted(self.active_planes),
                "scan_label": self.scan_label,
                "enable_dual_track": self.enable_dual_track,
                "high_novelty_floor": self.high_novelty_floor,
                "weak_novelty_floor": self.weak_novelty_floor,
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
    weak_signals: Optional[list] = None


def harvest_plane(plane: str, keywords: list, sweep_hours: int, **kwargs) -> list:
    try:
        from vara_harvesters import harvest_plane as _hp
        return _hp(plane=plane, keywords=keywords, sweep_hours=sweep_hours, **kwargs)
    except Exception as e:
        logger.warning("harvest_plane %s failed: %s", plane, e)
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
            logger.info("Intake plane=%s signals=%d", plane, len(plane_sigs))
        except Exception as e:
            logger.error("Intake plane=%s failed: %s", plane, e)
    return all_signals, errors


def stage_enrich_entities(signals: list) -> list:
    try:
        from entity_watchlist import enrich_signal_with_entities
        return [enrich_signal_with_entities(s) if isinstance(s, dict) else s for s in signals]
    except Exception:
        return signals


def stage_dual_track(signals: list, config: VaraConfig) -> tuple:
    """Split into high-novelty and weak-signal tracks."""
    high, weak = [], []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        nov = float(sig.get("novelty_score", 0))
        if nov >= config.high_novelty_floor:
            sig["track"] = "high"
            high.append(sig)
        elif nov >= config.weak_novelty_floor:
            sig["track"] = "weak"
            weak.append(sig)
        else:
            sig["track"] = "below_floor"
    return high, weak


def stage_cluster(signals: list, config: VaraConfig) -> tuple:
    """Semantic HDBSCAN clustering. Noise is preserved, never silently discarded."""
    if not signals:
        return [], []

    try:
        from clustering import ClusteringEngine

        class ClusterConfig:
            min_cluster_size = max(2, int(config.clustering_min_cluster_size))
            min_samples = max(1, int(config.clustering_min_samples))
            metric = config.clustering_metric
            cluster_selection_epsilon = float(config.cluster_selection_epsilon)
            embedding_model = config.embedding_model
            enable_incremental_lineage = bool(config.enable_incremental_lineage)

        engine = ClusteringEngine(config=ClusterConfig(), logger=logger)
        result = engine.cluster(signals)

        by_id = {s.get("signal_id"): s for s in signals}
        for signal in signals:
            sid = signal.get("signal_id")
            if not sid:
                sid = engine._signal_id(signal, signals.index(signal))
                signal["signal_id"] = sid
            membership = result.soft_membership.get(sid, {})
            if membership:
                cid, probability = next(iter(membership.items()))
                signal["cluster_id"] = cid
                signal["cluster_probability"] = probability
                signal["cluster_state"] = "clustered"
            else:
                signal["cluster_id"] = None
                signal["cluster_probability"] = 0.0
                signal["cluster_state"] = "noise"

        clusters = [c.model_dump() for c in result.clusters]
        for noise_id in result.noise_signals:
            if noise_id in by_id:
                by_id[noise_id]["cluster_state"] = "noise"
        return signals, clusters
    except Exception as exc:
        logger.error("Semantic clustering unavailable: %s", exc)
        # Preserve observations as explicit noise rather than reverting to fake clusters.
        for signal in signals:
            signal["cluster_id"] = None
            signal["cluster_probability"] = 0.0
            signal["cluster_state"] = "noise"
        return signals, []


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
        return VaraScanReport(
            scan_id=scan_id, scan_label=config.scan_label, timestamp=timestamp,
            config_hash=config.config_hash, keywords=config.keywords,
            active_planes=config.active_planes, signals=[], clusters=[],
            drift_log=[], null_result=True,
        )

    normalized = []
    for s in raw_signals:
        if hasattr(s, "__dataclass_fields__"):
            normalized.append(asdict(s))
        elif isinstance(s, dict):
            normalized.append(s)
        else:
            normalized.append({"content": str(s), "novelty_score": 0.1, "plane": "tech"})

    normalized = stage_enrich_entities(normalized)

    if config.enable_dual_track:
        high, weak = stage_dual_track(normalized, config)
        clustered_high, clusters_high = stage_cluster(high, config)
        clustered_weak, clusters_weak = stage_cluster(weak, config)
        clusters = clusters_high + clusters_weak
        sentinel_high = run_sentinel(clustered_high, scan_id, weak_track=False)
        sentinel_weak = run_sentinel(clustered_weak, scan_id, weak_track=True)
        handoff_high = sentinel_to_vault_handoff(sentinel_high)
        handoff_weak = sentinel_to_vault_handoff(sentinel_weak)
        passed = handoff_high["passed_signals"] + handoff_weak["passed_signals"]
        deferred = handoff_high["deferred_signals"] + handoff_weak["deferred_signals"]
        vault_report, veil_report = route_signals(passed, deferred, scan_id)
        output_signals = passed + list(getattr(veil_report, "promoted_signals", []) or [])
        sentinel_summary = {
            "high": {"passed": sentinel_high.passed, "blocked": sentinel_high.blocked,
                      "deferred": sentinel_high.deferred, "pruned": sentinel_high.pruned},
            "weak": {"passed": sentinel_weak.passed, "blocked": sentinel_weak.blocked,
                      "deferred": sentinel_weak.deferred, "pruned": sentinel_weak.pruned},
        }
        weak_out = clustered_weak
        clustered = clustered_high + clustered_weak
    else:
        clustered, clusters = stage_cluster(normalized, config)
        sentinel_report = run_sentinel(clustered, scan_id)
        handoff = sentinel_to_vault_handoff(sentinel_report)
        vault_report, veil_report = route_signals(
            handoff["passed_signals"], handoff["deferred_signals"], scan_id)
        output_signals = handoff["passed_signals"] + list(getattr(veil_report, "promoted_signals", []) or [])
        sentinel_summary = {
            "sentinel_id": sentinel_report.sentinel_id,
            "passed": sentinel_report.passed, "blocked": sentinel_report.blocked,
            "deferred": sentinel_report.deferred, "pruned": sentinel_report.pruned,
        }
        weak_out = []

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
        sentinel=sentinel_summary,
        routing={
            "harvested": len(clustered),
            "vault_bound": len(output_signals),
            "veil_held": len(getattr(veil_report, "held_entries", []) or []),
            "veil_promoted": getattr(veil_report, "promoted", 0),
        },
        weak_signals=weak_out if config.enable_dual_track else None,
    )

    out_path = os.path.join(OUTPUT_DIR, f"scan_{scan_id[:8]}.json")
    with open(out_path, "w") as f:
        json.dump(asdict(report), f, indent=2, default=str)

    logger.info(
        "Scan complete: id=%s harvested=%d output=%d",
        scan_id[:8], len(normalized), len(output_signals),
    )
    return report
