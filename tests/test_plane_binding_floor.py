"""Plane bind floor + instrument provenance (2026-11-06 fix).

FIR-025 finding: novelty is an absolute keyword density scored against
plane vocabularies of very unequal size (on live main, tech's domain
list is the 159-term DEFAULT_KEYWORDS; the other planes carry 11–25
domain terms each, and adjacent_possible had none at all until the
2026-11-06 fix), while the dual-track floors and Sentinel G1/G2
thresholds are single global values. Whole planes whose score
distribution sits lower were pruned — bound 135, all tech, six planes
at zero.

These tests run the real vendor run_vara_scan with a canned harvest
(same pattern as test_vendor_pipeline_lineage.py): a non-tech plane
whose signals all fall below the weak floor must still bind its top
coherent signals via the plane bind floor, planes that place normally
must be untouched, and the report must carry per-plane counts plus the
effective vocabulary in force.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = str(ROOT / "vendor" / "vara")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

import vara_scan  # noqa: E402
import vara_harvesters  # noqa: E402


def _sig(source_id, plane, novelty, title="A title", content="some content"):
    return {
        "source_id": source_id, "plane": plane, "title": title,
        "content": content, "url": f"https://a.example/{source_id}",
        "novelty_score": novelty, "raw_velocity": 0.5, "feed_tier": "main",
    }


def _multi_plane_signals():
    return {
        "tech": [
            _sig("src:tech1", "tech", 0.50),
            _sig("src:tech2", "tech", 0.60),
        ],
        # Every social signal sits below the weak floor (0.05): without
        # the fix this plane binds zero and is pruned as a whole.
        "social": [
            _sig("src:soc1", "social", 0.04),
            _sig("src:soc2", "social", 0.03),
            _sig("src:soc3", "social", 0.02),
            _sig("src:soc4", "social", 0.01),
        ],
        "economic": [
            _sig("src:econ1", "economic", 0.20),
        ],
    }


def _run_scan(tmp_path, monkeypatch, planes_signals, active_planes, **cfg_over):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vara_scan, "OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(
        vara_scan, "harvest_plane",
        lambda plane, keywords, sweep_hours, **kw: [
            dict(s) for s in planes_signals.get(plane, [])
        ],
    )
    monkeypatch.setattr(vara_scan, "stage_cluster", lambda signals, config: (signals, []))
    cfg = vara_scan.VaraConfig(
        keywords=["AI", "agentic", "compute"], sweep_depth_hours=24,
        active_planes=active_planes, scan_label="plane-floor-test",
        **cfg_over,
    )
    return vara_scan.run_vara_scan(cfg)


def test_nontech_plane_binds_via_floor(tmp_path, monkeypatch):
    report = _run_scan(
        tmp_path, monkeypatch, _multi_plane_signals(),
        ["tech", "social", "economic"],
    )
    by_id = {s["source_id"]: s for s in report.all_signals}

    # The whole social plane bound through the floor guarantee.
    social_out = [s for s in report.signals if s["plane"] == "social"]
    assert len(social_out) == 4
    for sid in ("src:soc1", "src:soc2", "src:soc3", "src:soc4"):
        assert by_id[sid]["disposition"] == "vault_bound"
        assert by_id[sid]["plane_bind_floor"] is True

    # Planes that place normally are untouched by the floor.
    assert by_id["src:tech1"]["disposition"] == "vault_bound"
    assert by_id["src:econ1"]["disposition"] == "vault_bound"
    assert "plane_bind_floor" not in by_id["src:tech1"]
    assert "plane_bind_floor" not in by_id["src:econ1"]

    # Instrument: per-plane flow counts make the rescue visible.
    planes = report.instrument["planes"]
    assert planes["social"] == {
        "harvested": 4, "kept": 4, "bound": 4,
        "pruned": 0, "blocked": 0, "veil_held": 0, "plane_bind_floor": 4,
    }
    assert planes["tech"]["harvested"] == 2
    assert planes["tech"]["bound"] == 2
    assert planes["tech"]["plane_bind_floor"] == 0
    assert planes["economic"]["bound"] == 1


def test_instrument_reports_effective_vocabulary(tmp_path, monkeypatch):
    report = _run_scan(
        tmp_path, monkeypatch, _multi_plane_signals(),
        ["tech", "social", "economic"],
    )
    vocab = report.instrument["vocabulary"]
    assert vocab["caller_keywords"] == 3
    assert vocab["default_keywords"] == len(vara_harvesters.DEFAULT_KEYWORDS)
    assert vocab["domain_keywords"]["tech"] == len(vara_harvesters.DEFAULT_KEYWORDS)
    assert vocab["domain_keywords"]["social"] == len(
        vara_harvesters.DOMAIN_KEYWORDS["social"]
    )
    assert vocab["domain_keywords"]["economic"] == len(
        vara_harvesters.DOMAIN_KEYWORDS["economic"]
    )
    # The vocabulary asymmetry behind the bug is visible in the payload:
    # tech's effective set dwarfs social's.
    assert vocab["per_plane_effective"]["tech"] > vocab["per_plane_effective"]["social"]
    digest = vocab["effective_vocabulary_hash"]
    assert isinstance(digest, str) and len(digest) == 64
    int(digest, 16)  # hex


def test_floor_only_rescues_unplaced_planes():
    signals = [
        _sig("src:t-weak", "tech", 0.10),
        _sig("src:t-below", "tech", 0.01),
        _sig("src:s-a", "social", 0.03),
        _sig("src:s-b", "social", 0.02),
    ]
    cfg = vara_scan.VaraConfig(
        keywords=["model"], sweep_depth_hours=24,
        active_planes=["tech", "social"], scan_label="floor-scope",
    )
    high, weak, below = vara_scan.stage_dual_track([dict(s) for s in signals], cfg)
    weak_ids = {s["source_id"] for s in weak}
    below_ids = {s["source_id"] for s in below}
    # tech placed a weak-track signal, so its below-floor signal is NOT
    # rescued; social placed nothing, so both its signals are.
    assert below_ids == {"src:t-below"}
    assert weak_ids == {"src:t-weak", "src:s-a", "src:s-b"}
    by_id = {s["source_id"]: s for s in weak}
    assert by_id["src:s-a"]["plane_bind_floor"] is True
    assert "plane_bind_floor" not in by_id["src:t-weak"]


def test_floor_cap_and_coherence_gate():
    signals = [_sig(f"src:s{i}", "social", 0.005 * i) for i in range(1, 8)]
    # Highest-novelty social signal is incoherent (empty title + content):
    # the floor must skip it, not bind it.
    signals.append(_sig("src:empty", "social", 0.045, title="", content=""))
    cfg = vara_scan.VaraConfig(
        keywords=["model"], sweep_depth_hours=24,
        active_planes=["social"], scan_label="floor-cap",
        plane_bind_floor=3,
    )
    high, weak, below = vara_scan.stage_dual_track([dict(s) for s in signals], cfg)
    rescued = [s for s in weak if s.get("plane_bind_floor")]
    assert len(rescued) == 3
    assert {s["source_id"] for s in rescued} == {"src:s7", "src:s6", "src:s5"}
    assert "src:empty" in {s["source_id"] for s in below}


def test_floor_disabled_binds_nothing_below_floor(tmp_path, monkeypatch):
    report = _run_scan(
        tmp_path, monkeypatch, _multi_plane_signals(),
        ["tech", "social", "economic"], plane_bind_floor=0,
    )
    planes = report.instrument["planes"]
    assert planes["social"]["harvested"] == 4
    assert planes["social"]["bound"] == 0
    assert planes["social"]["pruned"] == 4
    assert [s for s in report.signals if s["plane"] == "social"] == []
