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
from vara_veil_vault import run_veil

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
    # True entity targeting: when non-empty, only signals naming at least
    # one of these entities (word-boundary match over title + content)
    # proceed past enrichment; the rest are counted in the report's
    # entity_filter stats, never silently dropped.
    target_entities: list = field(default_factory=list)
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
    embedding_backend: str = "lightweight"
    embedding_dimensions: int = 256
    enable_incremental_lineage: bool = True

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "keywords": sorted(self.keywords),
                "target_entities": sorted(self.target_entities),
                "sweep_depth_hours": self.sweep_depth_hours,
                "active_planes": sorted(self.active_planes),
                "scan_label": self.scan_label,
                "enable_dual_track": self.enable_dual_track,
                "high_novelty_floor": self.high_novelty_floor,
                "weak_novelty_floor": self.weak_novelty_floor,
                "clustering_min_cluster_size": self.clustering_min_cluster_size,
                "clustering_min_samples": self.clustering_min_samples,
                "clustering_metric": self.clustering_metric,
                "cluster_selection_epsilon": self.cluster_selection_epsilon,
                "embedding_model": self.embedding_model,
                "embedding_backend": self.embedding_backend,
                "embedding_dimensions": self.embedding_dimensions,
                "enable_incremental_lineage": self.enable_incremental_lineage,
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
    entity_filter: Optional[dict] = None
    weak_signals: Optional[list] = None
    # Defect C: the FULL harvested set with per-signal provenance +
    # disposition — including blocked/pruned/deferred/veil-held signals,
    # which are absent from `signals` (output only). Marked, not dropped.
    all_signals: Optional[list] = None


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
            # Defect C: guarantee provenance fields at intake for any
            # harvester that did not stamp them itself.
            intake_ts = datetime.datetime.utcnow().isoformat()
            for sig in plane_sigs:
                if isinstance(sig, dict):
                    sig.setdefault("retrieved_at", intake_ts)
                    if not sig.get("source"):
                        sig["source"] = sig.get("source_id") or sig.get("url") or ""
                    if not sig.get("content_hash"):
                        sig["content_hash"] = hashlib.sha256(
                            str(sig.get("content") or "").encode()
                        ).hexdigest()
                    # PORT FIX (PR #14, Codex P1): canonical harvesters emit
                    # relevance_score; the dual-track splitter and Sentinel
                    # consume novelty_score. Map at the boundary so no
                    # harvested signal is silently evaluated as zero
                    # novelty. (Vendor-line novelty was relevance-derived.)
                    if "novelty_score" not in sig and sig.get("relevance_score") is not None:
                        sig["novelty_score"] = sig["relevance_score"]
                    # PORT FIX (PR #14, Codex P2): signal identity must be
                    # a function of the persisted record. The Veil
                    # migration reconstructs legacy IDs via
                    # _compute_signal_id over STORED (truncated) content,
                    # while harvesters compute it over full content — so
                    # re-base any sig:-identity here, over the stored form.
                    _sid = sig.get("signal_id")
                    if isinstance(_sid, str) and _sid.startswith("sig:"):
                        try:
                            from vara_harvesters import _compute_signal_id

                            sig["signal_id"] = _compute_signal_id(
                                sig.get("plane", ""),
                                sig.get("title", ""),
                                sig.get("content", ""),
                            )
                        except Exception:
                            pass
            all_signals.extend(plane_sigs)
            logger.info("Intake plane=%s signals=%d", plane, len(plane_sigs))
        except Exception as e:
            logger.error("Intake plane=%s failed: %s", plane, e)
    return all_signals, errors


def _load_drift_log() -> list:
    if not os.path.exists(DRIFT_LOG_PATH):
        return []
    try:
        with open(DRIFT_LOG_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []


def _save_drift_log(log: list) -> None:
    # Keep last 500 entries
    trimmed = log[-500:]
    with open(DRIFT_LOG_PATH, "w") as f:
        json.dump(trimmed, f, indent=2)


def stage_drift(
    signals:    list,
    config:     VaraConfig,
    scan_id:    str,
) -> tuple:
    """
    Compare raw_velocity against prior scan history.
    Tags signals with velocity_score and detects spikes.

    Returns (enriched_signals: list[dict], drift_entries: list[dict]).
    """
    drift_log    = _load_drift_log()
    drift_entries = []
    enriched     = []

    # Build plane->velocity history from prior log
    plane_history = {}
    for entry in drift_log[-100:]:
        p  = entry.get("plane", "")
        rv = entry.get("raw_velocity", 0.0)
        plane_history.setdefault(p, []).append(rv)

    for sig in signals:
        plane = sig.get("plane", "")
        rv    = sig.get("raw_velocity", 0.0)
        hist  = plane_history.get(plane, [])

        if hist:
            import statistics as _stats
            mean_rv = _stats.mean(hist)
            std_rv  = _stats.pstdev(hist) or 0.01
            z_score = (rv - mean_rv) / std_rv
            spike   = z_score >= config.velocity_spike_threshold
        else:
            z_score = 0.0
            spike   = False

        sig["velocity_score"] = round(max(0.0, min(1.0, rv + (z_score * 0.05))), 4)
        sig["velocity_spike"] = spike
        enriched.append(sig)

        entry = {
            "scan_id":      scan_id,
            "plane":        plane,
            "source_id":    sig.get("source_id", ""),
            "raw_velocity": rv,
            "z_score":      round(z_score, 4),
            "spike":        spike,
            "timestamp":    datetime.datetime.utcnow().isoformat(),
        }
        drift_entries.append(entry)

    _save_drift_log(drift_log + drift_entries)
    return enriched, drift_entries


# ─── STAGE: CLUSTER ──────────────────────────────────────────────────────────


def stage_enrich_entities(signals: list) -> list:
    try:
        from entity_watchlist import enrich_signal_with_entities
        return [enrich_signal_with_entities(s) if isinstance(s, dict) else s for s in signals]
    except Exception:
        return signals


def stage_entity_filter(signals: list, entities: list) -> tuple:
    """True entity targeting.

    Keep only signals whose title + content name at least one target
    entity (word-boundary match via entity_watchlist.match_entities);
    stamp each kept signal with its `matched_entities`. Returns
    (kept, stats) — the dropped count is recorded in stats, so the
    filter is provenance, not silent loss.
    """
    from entity_watchlist import match_entities

    kept = []
    per_entity: dict = {}
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        text = f"{sig.get('title', '')} {sig.get('content', '')}"
        matched = match_entities(text, entities)
        if matched:
            sig["matched_entities"] = matched
            for name in matched:
                per_entity[name] = per_entity.get(name, 0) + 1
            kept.append(sig)
    stats = {
        "targets": list(entities),
        "pre_filter": len(signals),
        "kept": len(kept),
        "dropped": len(signals) - len(kept),
        "per_entity": per_entity,
    }
    return kept, stats


def stage_dual_track(signals: list, config: VaraConfig) -> tuple:
    """Split into high-novelty and weak-signal tracks.

    Returns (high, weak, below_floor). Below-floor signals used to be
    dropped here entirely; they are now returned so the report can carry
    them with a pruned disposition (Defect C).
    """
    high, weak, below = [], [], []
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
            below.append(sig)
    return high, weak, below


def stage_cluster(signals: list, config: VaraConfig) -> tuple:
    """Cluster via the canonical vara_clustering contract.

    PORT (Fork 2, 2026-10-23): the canonical clustering interface is
    ``vara_clustering.engine.cluster_signals(signals, scan_id)``; per
    operator ruling the backend behind that contract remains the
    HDBSCAN semantic engine (vendored ``clustering`` package). The
    adapter returns canonical Cluster records (with lineage) and this
    stage stamps membership back onto the signal dicts. Noise is
    preserved, never silently discarded.
    """
    if not signals:
        return [], []
    try:
        from vara_clustering.engine import cluster_signals

        backend_config = {
            "min_cluster_size": max(2, int(config.clustering_min_cluster_size)),
            "min_samples": max(1, int(config.clustering_min_samples)),
            "metric": config.clustering_metric,
            "cluster_selection_epsilon": float(config.cluster_selection_epsilon),
            "embedding_model": config.embedding_model,
            "embedding_backend": getattr(config, "embedding_backend", "lightweight"),
            "embedding_dimensions": getattr(config, "embedding_dimensions", 256),
            "enable_incremental_lineage": bool(config.enable_incremental_lineage),
        }
        _clustered, clusters = cluster_signals(
            signals,
            scan_id=getattr(config, "scan_id", "") or "",
            backend_config=backend_config,
        )
        member_of = {}
        coherence_of = {}
        for c in clusters:
            coherence_of[c["cluster_id"]] = c.get("coherence", 0.0)
            for mid in c.get("member_ids", []):
                member_of[mid] = c["cluster_id"]
        for signal in signals:
            sid = signal.get("signal_id")
            if sid and sid in member_of:
                signal["cluster_id"] = member_of[sid]
                # Canonical coherence = mean membership probability.
                signal["cluster_probability"] = coherence_of.get(member_of[sid], 0.0)
                signal["cluster_state"] = "clustered"
            else:
                signal["cluster_id"] = None
                signal["cluster_probability"] = 0.0
                signal["cluster_state"] = "noise"
        return signals, clusters
    except Exception as exc:
        logger.error("Canonical clustering unavailable: %s", exc)
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

    config.scan_id = scan_id
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

    drift_entries = []
    try:
        normalized, drift_entries = stage_drift(normalized, config, scan_id)
    except Exception as exc:  # port guard: drift persistence is CWD-relative
        logger.warning("stage_drift unavailable: %s", exc)
    normalized = stage_enrich_entities(normalized)

    entity_filter_stats = None
    if config.target_entities:
        pre_filter_count = len(normalized)
        normalized, entity_filter_stats = stage_entity_filter(
            normalized, config.target_entities
        )
        if not normalized:
            return VaraScanReport(
                scan_id=scan_id, scan_label=config.scan_label, timestamp=timestamp,
                config_hash=config.config_hash, keywords=config.keywords,
                active_planes=config.active_planes, signals=[], clusters=[],
                drift_log=drift_entries, null_result=True,
                routing={
                    "harvested": pre_filter_count,
                    "vault_bound": 0,
                    "veil_held": 0,
                    "veil_promoted": 0,
                    "states": {},
                    "entity_filter": entity_filter_stats,
                },
                entity_filter=entity_filter_stats,
                all_signals=[],
            )

    below_floor: list = []
    sentinel_reports: list = []
    if config.enable_dual_track:
        high, weak, below_floor = stage_dual_track(normalized, config)
        clustered_high, clusters_high = stage_cluster(high, config)
        clustered_weak, clusters_weak = stage_cluster(weak, config)
        clusters = clusters_high + clusters_weak
        sentinel_high = run_sentinel(clustered_high, scan_id, weak_track=False)
        sentinel_weak = run_sentinel(clustered_weak, scan_id, weak_track=True)
        sentinel_reports = [sentinel_high, sentinel_weak]
        handoff_high = sentinel_to_vault_handoff(sentinel_high)
        handoff_weak = sentinel_to_vault_handoff(sentinel_weak)
        passed = handoff_high["passed_signals"] + handoff_weak["passed_signals"]
        deferred = handoff_high["deferred_signals"] + handoff_weak["deferred_signals"]
        veil_report = run_veil(deferred, scan_id)
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
        sentinel_reports = [sentinel_report]
        handoff = sentinel_to_vault_handoff(sentinel_report)
        veil_report = run_veil(handoff["deferred_signals"], scan_id)
        output_signals = handoff["passed_signals"] + list(getattr(veil_report, "promoted_signals", []) or [])
        sentinel_summary = {
            "sentinel_id": sentinel_report.sentinel_id,
            "passed": sentinel_report.passed, "blocked": sentinel_report.blocked,
            "deferred": sentinel_report.deferred, "pruned": sentinel_report.pruned,
        }
        weak_out = []

    # Defect C: record every harvested signal's disposition on the signal
    # itself. The same dict objects flow through every stage, so object
    # identity is the join key. Precedence: promoted > passed > veil_held
    # (deferred, still held) > blocked > pruned > below-floor pruned.
    promoted_ids = {id(s) for s in (getattr(veil_report, "promoted_signals", []) or [])}
    passed_ids = {id(s) for r in sentinel_reports for s in r.passed_signals}
    deferred_ids = {id(s) for r in sentinel_reports for s in r.deferred_signals}
    blocked_ids = {id(s) for r in sentinel_reports for s in r.blocked_signals}
    pruned_ids = {id(s) for r in sentinel_reports for s in r.pruned_signals}
    all_harvested = clustered + below_floor
    for sig in all_harvested:
        if not isinstance(sig, dict):
            continue
        if id(sig) in promoted_ids:
            sig["disposition"] = "promoted"
        elif id(sig) in passed_ids:
            sig["disposition"] = "vault_bound"
        elif id(sig) in deferred_ids:
            sig["disposition"] = "veil_held"
        elif id(sig) in blocked_ids:
            sig["disposition"] = "blocked"
        elif id(sig) in pruned_ids:
            sig["disposition"] = "pruned"
        elif sig.get("track") == "below_floor":
            sig["disposition"] = "pruned"
        else:
            sig.setdefault("disposition", "harvested")
    disposition_counts: dict = {}
    for sig in all_harvested:
        if isinstance(sig, dict):
            d = sig.get("disposition", "harvested")
            disposition_counts[d] = disposition_counts.get(d, 0) + 1

    report = VaraScanReport(
        scan_id=scan_id,
        scan_label=config.scan_label,
        timestamp=timestamp,
        config_hash=config.config_hash,
        keywords=config.keywords,
        active_planes=config.active_planes,
        signals=output_signals,
        clusters=clusters,
        drift_log=drift_entries,
        null_result=len(clustered) == 0,
        sentinel=sentinel_summary,
        routing={
            "harvested": len(all_harvested),
            "vault_bound": len(output_signals),
            "veil_held": len(getattr(veil_report, "held_entries", []) or []),
            "veil_promoted": getattr(veil_report, "promoted", 0),
            "states": disposition_counts,
            **({"entity_filter": entity_filter_stats} if entity_filter_stats else {}),
        },
        entity_filter=entity_filter_stats,
        weak_signals=weak_out if config.enable_dual_track else None,
        all_signals=all_harvested,
    )

    out_path = os.path.join(OUTPUT_DIR, f"scan_{scan_id[:8]}.json")
    with open(out_path, "w") as f:
        json.dump(asdict(report), f, indent=2, default=str)

    logger.info(
        "Scan complete: id=%s harvested=%d output=%d",
        scan_id[:8], len(normalized), len(output_signals),
    )
    return report
