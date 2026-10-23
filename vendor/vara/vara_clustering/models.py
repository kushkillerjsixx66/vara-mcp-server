"""Stable models for Vara candidate semantic clusters."""
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class Cluster:
    cluster_id: str
    member_ids: List[str]
    centroid: List[float] = field(default_factory=list)
    plane_distribution: Dict[str, int] = field(default_factory=dict)
    coherence: float = 0.0
    method: str = "lexical"
    candidate: bool = True
    lineage: Dict[str, object] = field(default_factory=dict)
    status: str = "coherent_candidate"

    def to_dict(self) -> dict:
        return {"cluster_id": self.cluster_id,"member_ids": list(self.member_ids),"centroid": list(self.centroid),"plane_distribution": dict(self.plane_distribution),"coherence": round(self.coherence,4),"method": self.method,"candidate": self.candidate,"status": self.status,"lineage": dict(self.lineage)}
