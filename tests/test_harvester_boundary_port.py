"""Regression guards for the PR #14 review fixes (Codex P1 + P2 + P2).

The canonical harvesters and the vendored consumers meet at stage_intake.
These tests pin the three boundary invariants the port must hold:

1. relevance_score is mapped to novelty_score when novelty is absent
   (otherwise every harvested signal classifies as zero novelty).
2. sig:-identities are re-based onto the stored (truncated) content —
   the same basis the Veil migration uses for legacy holds — so
   recurrence can match across the upgrade.
3. stage_drift resolves DRIFT_LOG_PATH from the module global at call
   time, which is what lets src/tools.py retarget it to the writable
   data root on serverless deployments.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = str(ROOT / "vendor" / "vara")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

import vara_scan  # noqa: E402
from vara_harvesters import _compute_signal_id  # noqa: E402

FULL = "signal body " * 80  # 960 chars; stored form truncates to 500


def _cfg():
    return vara_scan.VaraConfig(
        keywords=["signal"], sweep_depth_hours=24,
        active_planes=["tech"], scan_label="boundary-test",
    )


def _canonical_shaped_signal():
    # Exactly what canonical harvest_plane serializes: identity computed
    # over FULL content, content stored truncated, relevance only.
    return {
        "signal_id": _compute_signal_id("tech", "Title", FULL),
        "plane": "tech",
        "title": "Title",
        "content": FULL[:500],
        "url": "https://example.com/1",
        "relevance_score": 0.42,
        "raw_velocity": 0.5,
    }


def test_intake_maps_relevance_to_novelty(monkeypatch):
    monkeypatch.setattr(
        vara_scan, "harvest_plane",
        lambda plane, keywords, sweep_hours, **kw: [_canonical_shaped_signal()],
    )
    signals, errors = vara_scan.stage_intake(_cfg())
    assert errors == []
    assert signals[0]["novelty_score"] == 0.42


def test_intake_preserves_existing_novelty(monkeypatch):
    sig = _canonical_shaped_signal()
    sig["novelty_score"] = 0.9
    monkeypatch.setattr(
        vara_scan, "harvest_plane",
        lambda plane, keywords, sweep_hours, **kw: [sig],
    )
    signals, _ = vara_scan.stage_intake(_cfg())
    assert signals[0]["novelty_score"] == 0.9


def test_intake_rebases_identity_on_stored_content(monkeypatch):
    canned = _canonical_shaped_signal()
    full_basis_id = canned["signal_id"]
    monkeypatch.setattr(
        vara_scan, "harvest_plane",
        lambda plane, keywords, sweep_hours, **kw: [canned],
    )
    signals, _ = vara_scan.stage_intake(_cfg())
    stored_basis_id = _compute_signal_id("tech", "Title", FULL[:500])
    assert stored_basis_id != full_basis_id  # the defect is real for this input
    assert signals[0]["signal_id"] == stored_basis_id


def test_stage_drift_uses_module_level_path(tmp_path, monkeypatch):
    drift_file = tmp_path / "vara_drift_log.json"
    monkeypatch.setattr(vara_scan, "DRIFT_LOG_PATH", str(drift_file))
    sig = {"plane": "tech", "raw_velocity": 9.9, "signal_id": "sig:x"}
    enriched, entries = vara_scan.stage_drift([sig], _cfg(), "scan-1")
    assert drift_file.exists()  # save resolved through the module global
    assert isinstance(entries, list)
