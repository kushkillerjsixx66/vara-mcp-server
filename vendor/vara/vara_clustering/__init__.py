"""Canonical vara_clustering interface, HDBSCAN-backed (adapter).

models.py and lineage.py are the canonical modules verbatim
(canonical-vault 05_runtime/vara_clustering @ e120d98). engine.py is the
operator-ruled adapter (2026-10-23) that runs the vendored HDBSCAN
backend behind the canonical cluster_signals contract.
"""
from .engine import cluster_signals

__all__ = ["cluster_signals"]
