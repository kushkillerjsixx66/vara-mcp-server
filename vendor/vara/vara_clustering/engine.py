"""HDBSCAN-backed engine behind the canonical vara_clustering interface.

Operator ruling (2026-10-23): the canonical Vara modules run the server,
with the vendored HDBSCAN semantic backend kept as the clustering engine.
This module is that adapter — it is NOT canonical code. It implements the
canonical `cluster_signals(signals, scan_id)` contract (canonical
models.Cluster dicts, canonical lineage attached to every cluster) on
top of the vendored `clustering` package (ClusteringEngine + HDBSCAN
backend + lightweight embeddings).

Degradation contract: if the HDBSCAN backend is unavailable or fails,
all signals are returned unclustered (cluster_id None) with an empty
cluster list and the failure is logged — the same all-noise shape an
unclustered scan produces, never an exception into the scan pipeline.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import List, Mapping, Tuple

from .lineage import build_lineage
from .models import Cluster

logger = logging.getLogger(__name__)


def _backend_config(overrides: dict = None):
    bc = overrides or {}
    # Adapter translation: the vendored embedding backend returns
    # L2-normalized vectors, on which euclidean distance is a monotone
    # transform of cosine distance — while current hdbscan builds
    # reject metric="cosine" outright. The declared config metric
    # stays "cosine"; the backend receives the equivalent.
    backend_metric = bc.get("metric", "cosine")
    if backend_metric == "cosine":
        backend_metric = "euclidean"

    class Cfg:
        min_cluster_size = int(bc.get("min_cluster_size", 2))
        min_samples = int(bc.get("min_samples", 1))
        metric = backend_metric
        cluster_selection_epsilon = float(bc.get("cluster_selection_epsilon", 0.0))
        embedding_model = bc.get("embedding_model") or None
        embedding_backend = bc.get("embedding_backend", "lightweight")
        embedding_dimensions = int(bc.get("embedding_dimensions", 256))
        enable_incremental_lineage = bool(bc.get("enable_incremental_lineage", False))

    return Cfg()


def cluster_signals(
    signals: List[Mapping],
    scan_id: str = "",
    similarity_threshold: float = 0.34,
    min_cluster_size: int = 2,
    coherence_threshold: float = 0.30,
    backend_config: dict = None,
) -> Tuple[List[dict], List[dict]]:
    """Cluster signals with the HDBSCAN backend; canonical-shaped output.

    `similarity_threshold` is accepted for signature parity with the
    canonical lexical engine; the density-based backend does not use it.
    `min_cluster_size` is likewise set on the backend config default (2).
    """
    if not signals:
        return [], []

    enriched = [dict(s) for s in signals]

    try:
        from clustering import ClusteringEngine

        engine = ClusteringEngine(config=_backend_config(backend_config), logger=logger)
        result = engine.cluster([dict(s) for s in signals])
    except Exception as exc:  # backend unavailable: degrade to all-noise
        logger.error("HDBSCAN backend unavailable, returning unclustered: %s", exc)
        for s in enriched:
            s["cluster_id"] = None
        return enriched, []

    by_id = {}
    for idx, s in enumerate(enriched):
        sid = s.get("signal_id") or engine._signal_id(s, idx)
        s["signal_id"] = sid
        by_id[sid] = s

    clusters: List[dict] = []
    for cluster in result.clusters:
        members = [by_id[mid] for mid in cluster.member_ids if mid in by_id]
        if not members:
            continue
        coherence = float(cluster.metadata.get("avg_probability", 0.0))
        status = (
            "coherent_candidate"
            if coherence >= coherence_threshold
            else "fragmented_candidate"
        )
        planes = Counter(str(m.get("plane", "unknown")) for m in members)
        lineage = build_lineage(scan_id, members)
        # Port adaptation: canonical member_count counts observation_ids,
        # which server-harvested signals do not carry; fall back to the
        # signal count so lineage is never reported as zero-member.
        if not lineage.get("member_count"):
            lineage["member_count"] = len(lineage.get("signal_ids", []))
        canonical = Cluster(
            cluster_id=cluster.cluster_id,
            member_ids=list(cluster.member_ids),
            centroid=list(cluster.centroid),
            plane_distribution=dict(planes),
            coherence=coherence,
            method="hdbscan_semantic",
            candidate=True,
            lineage=lineage,
            status=status,
        ).to_dict()
        clusters.append(canonical)
        for m in members:
            m["cluster_id"] = cluster.cluster_id
            membership = result.soft_membership.get(m["signal_id"], {})
            m["cluster_probability"] = float(
                membership.get(cluster.cluster_id, coherence)
            )
            m["cluster_coherence"] = round(coherence, 4)
            m["cluster_method"] = "hdbscan_semantic"
            m["cluster_status"] = status

    clustered_ids = {mid for c in result.clusters for mid in c.member_ids}
    for s in enriched:
        if s["signal_id"] not in clustered_ids:
            s["cluster_id"] = None

    return enriched, sorted(clusters, key=lambda c: c["cluster_id"])
