"""Domain-keyword completeness — FIR-025 instrument fix (2026-11-06),
transplanted onto live main.

A plane with no DOMAIN_KEYWORDS entry is density-scored on the caller
keywords alone while other planes carry up to 159 extra terms; one
global novelty threshold then prunes it wholesale (adjacent_possible
shipped in exactly that state on live main). These tests pin the
invariant: every supported plane carries a real domain list, and a
plane's own vocabulary actually moves its density score.

Live-main adaptations: the density function is named
``_keyword_relevance`` here (same formula as the snapshot's
``_keyword_density``), and the scientific sample text below uses live's
own scientific vocabulary — live's scientific list (added by 98d130c)
is fitted to broad science topics, not the snapshot's arXiv paper
register. The invariant pinned is presence and effect, not the terms.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "vendor" / "vara"))

from vara_harvesters import DOMAIN_KEYWORDS, _PLANE_HARVESTERS, _keyword_relevance

ACTIVE_PLANES = [
    "tech", "scientific", "social", "economic",
    "geopolitical", "dark", "adjacent_possible",
]


def test_every_active_plane_has_a_domain_list():
    for plane in ACTIVE_PLANES:
        assert plane in _PLANE_HARVESTERS, f"{plane} has no harvester"
        kws = DOMAIN_KEYWORDS.get(plane)
        assert kws, f"{plane} has NO DOMAIN_KEYWORDS entry — it will be pruned by vocabulary imbalance"
        assert len(kws) >= 10, f"{plane} domain list too thin to score fairly: {len(kws)} terms"


def test_scientific_domain_terms_score_scientific_text():
    # Sample text is written in live's scientific vocabulary (machine
    # learning, protein design, genomics, quantum, materials science,
    # fusion, energy storage) — see the module docstring.
    text = ("A machine learning study of protein design for genomics, "
            "applying quantum methods to materials science and fusion "
            "energy storage.")
    caller = ["nonexistent-caller-term"]
    without_domain = _keyword_relevance(text, caller)
    with_domain = _keyword_relevance(text, caller + DOMAIN_KEYWORDS["scientific"])
    assert without_domain == 0.0
    assert with_domain > 0.0


def test_adjacent_possible_domain_terms_score_frontier_text():
    text = ("A Bayesian forecasting exercise on recursive self-improvement "
            "and takeoff dynamics, with implications for AI governance "
            "and longtermism.")
    caller = ["nonexistent-caller-term"]
    without_domain = _keyword_relevance(text, caller)
    with_domain = _keyword_relevance(text, caller + DOMAIN_KEYWORDS["adjacent_possible"])
    assert without_domain == 0.0
    assert with_domain > 0.0
