from __future__ import annotations

import numpy as np
from typing import Dict, List


def compute_centroid(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    arr = np.asarray(vectors, dtype=np.float32)
    centroid = arr.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm
    return centroid.tolist()


def jaccard(a: List[str], b: List[str]) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def derive_lineage(prev_clusters, new_clusters):
    """Derive many-to-many cluster lineage, including split/merge evidence."""
    edges = []
    parents_for_new: Dict[str, list] = {}
    children_for_old: Dict[str, list] = {}

    for new_c in new_clusters:
        for prev_c in prev_clusters:
            score = jaccard(prev_c.member_ids, new_c.member_ids)
            if score > 0:
                edge = {
                    "parent": prev_c.cluster_id,
                    "child": new_c.cluster_id,
                    "similarity": score,
                }
                edges.append(edge)
                parents_for_new.setdefault(new_c.cluster_id, []).append(edge)
                children_for_old.setdefault(prev_c.cluster_id, []).append(edge)

    lineage = {}
    for new_c in new_clusters:
        incoming = sorted(
            parents_for_new.get(new_c.cluster_id, []),
            key=lambda e: e["similarity"], reverse=True,
        )
        if not incoming:
            status = "new"
        elif len(incoming) > 1:
            status = "merge"
        else:
            parent = incoming[0]["parent"]
            sibling_count = len(children_for_old.get(parent, []))
            status = "split" if sibling_count > 1 else (
                "continued" if incoming[0]["similarity"] >= 0.2 else "new"
            )
        lineage[new_c.cluster_id] = {
            "parents": incoming,
            "status": status,
        }

    return {"clusters": lineage, "edges": edges}
