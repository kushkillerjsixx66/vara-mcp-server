from __future__ import annotations

import hashlib
import logging
from typing import List
import numpy as np

from .models import Cluster, ClusterResult
from .lineage import compute_centroid, derive_lineage
from .embeddings import EmbeddingBackend, SentenceTransformerBackend


class ClusteringEngine:
    """Semantic HDBSCAN engine with explicit noise and lineage preservation."""

    def __init__(self, backend=None, logger=None, config=None, vault_client=None, cluster_backend=None):
        self.logger = logger or logging.getLogger("vara.clustering")
        self.config = config
        self.vault_client = vault_client
        self.backend = backend or SentenceTransformerBackend(
            getattr(config, "embedding_model", "all-MiniLM-L6-v2")
        )
        if cluster_backend is not None:
            self.hdbscan = cluster_backend
        else:
            from .backend_hdbscan import HDBSCANBackend
            self.hdbscan = HDBSCANBackend(config, self.logger)

    @staticmethod
    def _signal_id(signal, index):
        sid = signal.get("signal_id") or signal.get("source_id")
        if sid:
            return str(sid)
        blob = f"{signal.get('url','')}|{signal.get('title','')}|{signal.get('content','')}|{index}"
        return "sig:" + hashlib.sha256(blob.encode()).hexdigest()[:16]

    @staticmethod
    def _cluster_id(member_ids):
        key = "|".join(sorted(member_ids))
        return "c:" + hashlib.sha256(key.encode()).hexdigest()[:12]

    def cluster(self, signals: List[dict], embeddings=None) -> ClusterResult:
        if not signals:
            return ClusterResult(clusters=[], noise_signals=[], soft_membership={})

        signal_ids = [self._signal_id(s, i) for i, s in enumerate(signals)]
        texts = [
            (s.get("summary") or s.get("content") or s.get("title") or sid).strip()
            for s, sid in zip(signals, signal_ids)
        ]

        if len(signals) < 2:
            return ClusterResult(clusters=[], noise_signals=signal_ids, soft_membership={})

        vectors = embeddings if embeddings is not None else self.backend.embed_texts_safe(texts)
        if getattr(vectors, "shape", (0, 0))[0] != len(signals):
            return ClusterResult(clusters=[], noise_signals=signal_ids, soft_membership={})

        labels, probabilities, outlier_scores = self.hdbscan.run(vectors)
        if not labels or len(labels) != len(signals):
            return ClusterResult(clusters=[], noise_signals=signal_ids, soft_membership={})

        by_label = {}
        for i, label in enumerate(labels):
            if label != -1:
                by_label.setdefault(label, []).append(i)

        cluster_objs = []
        label_to_id = {}
        for label, idxs in sorted(by_label.items()):
            member_ids = [signal_ids[i] for i in idxs]
            cid = self._cluster_id(member_ids)
            label_to_id[label] = cid
            plane_distribution = {}
            for i in idxs:
                plane = signals[i].get("plane", "unknown")
                plane_distribution[plane] = plane_distribution.get(plane, 0) + 1
            probs = [float(probabilities[i]) for i in idxs]
            outs = [float(outlier_scores[i]) for i in idxs]
            cluster_objs.append(Cluster(
                cluster_id=cid,
                member_ids=member_ids,
                centroid=compute_centroid([vectors[i].tolist() for i in idxs]),
                plane_distribution=plane_distribution,
                metadata={
                    "size": len(member_ids),
                    "hdbscan_label": int(label),
                    "avg_probability": float(np.mean(probs)),
                    "max_outlier_score": float(np.max(outs)),
                },
            ))

        noise_signals = [signal_ids[i] for i, label in enumerate(labels) if label == -1]
        soft_membership = {}
        for i, label in enumerate(labels):
            if label != -1 and label in label_to_id:
                soft_membership[signal_ids[i]] = {
                    label_to_id[label]: float(probabilities[i])
                }

        if self.config and getattr(self.config, "enable_incremental_lineage", False) and self.vault_client:
            prev = self.vault_client.last_clusters() or []
            if prev:
                lineage = derive_lineage(prev, cluster_objs)
                for cluster in cluster_objs:
                    cluster.metadata["lineage"] = lineage["clusters"].get(cluster.cluster_id, {})

        return ClusterResult(
            clusters=cluster_objs,
            noise_signals=noise_signals,
            soft_membership=soft_membership,
        )
