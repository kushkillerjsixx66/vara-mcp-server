"""FFIR — Free Field Intel Report tests (operator ruling 2026-11-27).

The free tier's report shape: observed signals only, top 8, no
interpretation layer, and the boundary stated on the face of the report.
Anonymous callers always receive the FFIR from vara_generate_fir;
keyed callers receive the format they asked for.
"""
import json
import sys
import types

import pytest

from src import config, request_context, tools

SCAN_ID = "12345678-abcd-4abc-8abc-1234567890ab"


def _scan_doc(n_signals=20):
    return {
        "scan_id": SCAN_ID,
        "scan_label": "ffir-test",
        "timestamp": "2026-11-27T00:00:00",
        "config_hash": "deadbeef",
        "active_planes": ["tech", "scientific"],
        "signals": [
            {
                "title": f"Signal number {i}",
                "plane": "tech",
                "novelty_score": 0.5,
                "content": f"Body {i}",
            }
            for i in range(n_signals)
        ],
        "null_result": False,
        "error": None,
    }


@pytest.fixture()
def archive_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VARA_DATA_ROOT", tmp_path)
    monkeypatch.setattr(config, "VARA_PACKAGE_PATH", tmp_path)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "vara_output")
    monkeypatch.setattr(config, "VAULT_SIGNALS_PATH", tmp_path / "vault_signals.json")
    monkeypatch.setattr(config, "VEIL_HOLD_PATH", tmp_path / "veil_hold.json")
    monkeypatch.setattr(config, "VEIL_TRAJECTORIES_PATH", tmp_path / "veil_traj.json")
    monkeypatch.setattr(config, "DRIFT_LOG_PATH", tmp_path / "vara_drift_log.json")
    monkeypatch.setenv("VARA_LOCAL_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("VARA_DURABLE_BACKEND", "local")
    out = tmp_path / "vara_output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "scan_12345678.json").write_text(json.dumps(_scan_doc()))
    request_context.set_caller(None, None)
    yield tmp_path
    request_context.set_caller(None, None)


def test_anonymous_default_gets_ffir_with_notice(archive_env):
    out = tools.vara_generate_fir({"scan_id": SCAN_ID})
    assert out["format"] == "free"
    assert out["markdown"].startswith("FREE FIELD INTEL REPORT")
    assert "format_notice" in out


def test_anonymous_explicit_operator_tier_still_ffir(archive_env):
    out = tools.vara_generate_fir({"scan_id": SCAN_ID, "format": "operator_tier"})
    assert out["format"] == "free"
    assert "format_notice" in out


def test_anonymous_explicit_free_no_notice(archive_env):
    out = tools.vara_generate_fir({"scan_id": SCAN_ID, "format": "free"})
    assert out["format"] == "free"
    assert "format_notice" not in out


def test_ffir_is_bounded_and_observed_only(archive_env):
    out = tools.vara_generate_fir({"scan_id": SCAN_ID, "format": "free"})
    md = out["markdown"]
    assert "Signal number 7" in md          # 8th signal (0-based 7) present
    assert "Signal number 8" not in md      # 9th is beyond the bound
    assert "and 12 more signals" in md
    assert "WHAT THE FULL REPORT ADDS" in md


def test_ffir_carries_the_key_purchase_link(archive_env):
    out = tools.vara_generate_fir({"scan_id": SCAN_ID, "format": "free"})
    assert config.KEY_PURCHASE_URL in out["markdown"]
    assert config.KEY_PURCHASE_URL.startswith("https://buy.stripe.com/")


def test_keyed_gets_operator_tier(archive_env, monkeypatch):
    monkeypatch.setenv("VARA_API_KEYS", "operator-key")
    request_context.set_caller("operator-key", None)
    out = tools.vara_generate_fir({"scan_id": SCAN_ID, "format": "operator_tier"})
    assert out["format"] == "operator_tier"
    assert "FREE FIELD INTEL REPORT" not in out["markdown"]
    assert "format_notice" not in out


# ─── run_scan embeds the tier's report shape ─────────────────────────────────

class _FakeConfig:
    last_kwargs = None

    def __init__(self, **kwargs):
        _FakeConfig.last_kwargs = kwargs


@pytest.fixture()
def fake_vendor(tmp_path, monkeypatch):
    def fake_run(cfg):
        return {**_scan_doc(3), "scan_id": SCAN_ID}

    vs = types.ModuleType("vara_scan")
    vs.VaraConfig = _FakeConfig
    vs.run_vara_scan = fake_run
    vs.OUTPUT_DIR = str(tmp_path)
    vs.DRIFT_LOG_PATH = str(tmp_path / "drift.json")
    vvv = types.ModuleType("vara_veil_vault")
    vvv.VAULT_PATH = str(tmp_path / "vault.json")
    vvv.VEIL_HOLD_PATH = str(tmp_path / "veil.json")
    ew = types.ModuleType("entity_watchlist")
    ew.WATCHLIST_PATH = str(tmp_path / "watch.json")
    ew.DEFAULT_SCAN_KEYWORDS = ["AI"]
    ew.entity_feed_urls = lambda entities: []
    monkeypatch.setitem(sys.modules, "vara_scan", vs)
    monkeypatch.setitem(sys.modules, "vara_veil_vault", vvv)
    monkeypatch.setitem(sys.modules, "entity_watchlist", ew)
    monkeypatch.setattr(tools.lineage_mod, "enrich_report", lambda r: r)
    monkeypatch.setattr(tools, "govern_operational_report", lambda r, lineage=None: r)
    monkeypatch.setattr(config, "SCAN_BUDGET_ENABLED", True)
    return tmp_path


def test_run_scan_anonymous_embeds_ffir(archive_env, fake_vendor):
    result = tools.vara_run_scan({"keywords": ["x"], "generate_fir": True})
    assert result["field_intel_report"].startswith("FREE FIELD INTEL REPORT")


def test_run_scan_keyed_embeds_full_fir(archive_env, fake_vendor, monkeypatch):
    monkeypatch.setenv("VARA_API_KEYS", "operator-key")
    request_context.set_caller("operator-key", None)
    result = tools.vara_run_scan({"keywords": ["x"], "generate_fir": True})
    assert result["field_intel_report"].startswith("FIELD INTEL REPORT")
    assert not result["field_intel_report"].startswith("FREE FIELD INTEL REPORT")
