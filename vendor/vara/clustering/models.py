from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Dict, List, Any


class Cluster(BaseModel):
    cluster_id: str
    member_ids: List[str]
    centroid: List[float]
    plane_distribution: Dict[str, int]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ClusterResult(BaseModel):
    clusters: List[Cluster]
    noise_signals: List[str]
    soft_membership: Dict[str, Dict[str, float]]
