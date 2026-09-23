from __future__ import annotations

import numpy as np


class HDBSCANBackend:
    """HDBSCAN backend for normalized semantic embeddings."""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        try:
            import hdbscan
        except ImportError as exc:
            raise ImportError("pip install hdbscan") from exc

        self.clusterer = hdbscan.HDBSCAN(
            min_cluster_size=config.min_cluster_size,
            min_samples=config.min_samples,
            metric=config.metric,
            cluster_selection_epsilon=config.cluster_selection_epsilon,
            prediction_data=True,
        )

    def run(self, vectors):
        if not vectors:
            return [], [], []
        try:
            vectors = np.asarray(vectors, dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[0] == 0:
                return [], [], []
            self.clusterer.fit(vectors)
            return (
                self.clusterer.labels_.tolist(),
                self.clusterer.probabilities_.tolist(),
                self.clusterer.outlier_scores_.tolist(),
            )
        except Exception as exc:
            self.logger.error("HDBSCAN failure: %s", exc)
            return [], [], []
