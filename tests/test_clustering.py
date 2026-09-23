from types import SimpleNamespace

from vendor.vara.clustering.engine import ClusteringEngine
from vendor.vara.clustering.lineage import derive_lineage
from vendor.vara.clustering.models import Cluster


class FakeEmbedder:
    def embed_texts_safe(self, texts):
        import numpy as np
        return np.array([[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]], dtype="float32")


class FakeClusterBackend:
    def run(self, vectors):
        return [0, 0, -1], [0.95, 0.8, 0.0], [0.01, 0.2, 1.0]


def config():
    return SimpleNamespace(embedding_model="test", enable_incremental_lineage=False)


def test_engine_preserves_noise_and_soft_membership():
    signals = [
        {"signal_id": "a", "plane": "tech", "content": "one"},
        {"signal_id": "b", "plane": "scientific", "content": "two"},
        {"signal_id": "c", "plane": "economic", "content": "three"},
    ]
    engine = ClusteringEngine(backend=FakeEmbedder(), config=config(), cluster_backend=FakeClusterBackend())
    result = engine.cluster(signals)
    assert result.noise_signals == ["c"]
    assert len(result.clusters) == 1
    assert result.clusters[0].member_ids == ["a", "b"]
    assert result.clusters[0].plane_distribution == {"tech": 1, "scientific": 1}
    assert result.soft_membership["a"]
    assert result.soft_membership["b"]
    assert "c" not in result.soft_membership


def test_cluster_identity_is_deterministic():
    engine = ClusteringEngine(backend=FakeEmbedder(), config=config(), cluster_backend=FakeClusterBackend())
    assert engine._cluster_id(["a", "b"]) == engine._cluster_id(["b", "a"])


def test_lineage_represents_split():
    previous = [Cluster(cluster_id="old", member_ids=["a", "b", "c", "d"], centroid=[], plane_distribution={})]
    current = [
        Cluster(cluster_id="left", member_ids=["a", "b"], centroid=[], plane_distribution={}),
        Cluster(cluster_id="right", member_ids=["c", "d"], centroid=[], plane_distribution={}),
    ]
    lineage = derive_lineage(previous, current)
    assert lineage["clusters"]["left"]["status"] == "split"
    assert lineage["clusters"]["right"]["status"] == "split"
