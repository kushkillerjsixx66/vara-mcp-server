"""Cluster lineage helpers."""
import hashlib
from typing import Iterable, Mapping
def cluster_id(member_ids: Iterable[str]) -> str:
    payload="|".join(sorted(str(x) for x in member_ids)).encode()
    return "cl:" + hashlib.sha256(payload).hexdigest()[:16]
def build_lineage(scan_id: str, members: Iterable[Mapping]) -> dict:
    observations=sorted({str(m.get("observation_id","")) for m in members if m.get("observation_id")})
    signals=sorted({str(m.get("signal_id","")) for m in members if m.get("signal_id")})
    return {"scan_id":scan_id,"observation_ids":observations,"signal_ids":signals,"member_count":len(observations)}
