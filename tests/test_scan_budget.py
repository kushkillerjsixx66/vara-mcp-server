"""Scan-budget tests (operator ruling 2026-11-27).

Anonymous tier: 24h sweep / 5 planes / 10 scans per day global / 5 per
caller. Keyed tier: 168h / 8 planes / 5 per day per key. Reads are never
gated. Budget state stores truncated hashes only — never raw keys or IPs.
"""
import hashlib
import json
import sys
import types

import pytest

from src import budget, config, durable, request_context, tools


@pytest.fixture()
def budget_env(tmp_path, monkeypatch):
    """Isolate budget + durable state into a tmp tree with small dials."""
    monkeypatch.setattr(config, "VARA_DATA_ROOT", tmp_path)
    monkeypatch.setenv("VARA_LOCAL_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("VARA_DURABLE_BACKEND", "local")
    monkeypatch.setattr(config, "SCAN_BUDGET_ENABLED", True)
    monkeypatch.setattr(config, "ANON_DAILY_BUDGET", 10)
    monkeypatch.setattr(config, "ANON_PER_CALLER_DAILY", 5)
    monkeypatch.setattr(config, "KEYED_DAILY_BUDGET", 5)
    request_context.set_caller(None, None)
    yield tmp_path
    request_context.set_caller(None, None)


# ─── Tier resolution ─────────────────────────────────────────────────────────

def test_resolve_tier_anonymous_without_key(budget_env):
    assert budget.resolve_tier(None)["tier"] == "anonymous"
    assert budget.resolve_tier("")["tier"] == "anonymous"


def test_resolve_tier_keyed_with_valid_key(budget_env, monkeypatch):
    monkeypatch.setenv("VARA_API_KEYS", "alpha-key, beta-key")
    resolved = budget.resolve_tier("beta-key")
    assert resolved["tier"] == "keyed"
    assert resolved["key_id"] == hashlib.sha256(b"beta-key").hexdigest()[:12]


def test_resolve_tier_wrong_key_falls_back_to_anonymous(budget_env, monkeypatch):
    monkeypatch.setenv("VARA_API_KEYS", "alpha-key")
    assert budget.resolve_tier("not-a-key")["tier"] == "anonymous"


# ─── Caps ────────────────────────────────────────────────────────────────────

def test_apply_caps_anonymous(budget_env):
    sweep, planes, notices = budget.apply_caps(
        "anonymous", 168, ["a", "b", "c", "d", "e", "f", "g"]
    )
    assert sweep == 24
    assert planes == ["a", "b", "c", "d", "e"]
    assert any("24" in n for n in notices)
    assert any("f" in n and "g" in n for n in notices)


def test_apply_caps_keyed_full_depth(budget_env):
    planes = ["a", "b", "c", "d", "e", "f", "g", "h"]
    sweep, out_planes, notices = budget.apply_caps("keyed", 168, planes)
    assert sweep == 168
    assert out_planes == planes
    assert notices == []
    sweep2, _, notices2 = budget.apply_caps("keyed", 720, planes)
    assert sweep2 == 168
    assert notices2


def test_apply_caps_under_limit_is_silent(budget_env):
    sweep, planes, notices = budget.apply_caps("anonymous", 12, ["tech"])
    assert (sweep, planes, notices) == (12, ["tech"], [])


# ─── Reservation / exhaustion ────────────────────────────────────────────────

def test_global_budget_exhaustion(budget_env, monkeypatch):
    monkeypatch.setattr(config, "ANON_DAILY_BUDGET", 2)
    monkeypatch.setattr(config, "ANON_PER_CALLER_DAILY", 10)
    assert budget.reserve("anonymous", None, "caller-a")["allowed"]
    assert budget.reserve("anonymous", None, "caller-b")["allowed"]
    denied = budget.reserve("anonymous", None, "caller-c")
    assert not denied["allowed"]
    assert denied["scope"] == "global"


def test_per_caller_cap_binds_before_global(budget_env, monkeypatch):
    monkeypatch.setattr(config, "ANON_PER_CALLER_DAILY", 1)
    assert budget.reserve("anonymous", None, "caller-a")["allowed"]
    denied = budget.reserve("anonymous", None, "caller-a")
    assert not denied["allowed"]
    assert denied["scope"] == "caller"
    assert budget.reserve("anonymous", None, "caller-b")["allowed"]


def test_keyed_budget_is_per_key(budget_env, monkeypatch):
    monkeypatch.setattr(config, "KEYED_DAILY_BUDGET", 1)
    assert budget.reserve("keyed", "key-a", "caller-a")["allowed"]
    assert not budget.reserve("keyed", "key-a", "caller-a")["allowed"]
    assert budget.reserve("keyed", "key-b", "caller-a")["allowed"]


def test_refund_returns_the_scan(budget_env, monkeypatch):
    monkeypatch.setattr(config, "ANON_DAILY_BUDGET", 1)
    monkeypatch.setattr(config, "ANON_PER_CALLER_DAILY", 1)
    assert budget.reserve("anonymous", None, "caller-a")["allowed"]
    budget.refund("anonymous", None, "caller-a")
    assert budget.reserve("anonymous", None, "caller-a")["allowed"]


def test_day_rollover_resets_counters(budget_env):
    state = budget.load_state()
    state["anon_global"] = 999
    budget._save_state(state)
    # Rewrite both copies as yesterday's: load_state must ignore them.
    import datetime
    yesterday = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    stale = {**state, "date": yesterday}
    (budget_env / "scan_budget.json").write_text(json.dumps(stale))
    durable.save_budget_state(stale)
    fresh = budget.load_state()
    assert fresh["anon_global"] == 0
    assert fresh["date"] != yesterday


def test_state_stores_hashes_only(budget_env, monkeypatch):
    monkeypatch.setenv("VARA_API_KEYS", "super-secret-key")
    resolved = budget.resolve_tier("super-secret-key")
    caller = budget.caller_id_for("203.0.113.7")
    budget.reserve("keyed", resolved["key_id"], caller)
    budget.reserve("anonymous", None, caller)
    text = (budget_env / "scan_budget.json").read_text()
    assert "super-secret-key" not in text
    assert "203.0.113.7" not in text
    assert resolved["key_id"] in text
    assert caller in text


# ─── Tool-level gate ─────────────────────────────────────────────────────────

class _FakeConfig:
    last_kwargs = None

    def __init__(self, **kwargs):
        _FakeConfig.last_kwargs = kwargs


@pytest.fixture()
def fake_vendor(tmp_path, monkeypatch):
    """Stub the vendor Vara package so vara_run_scan runs without network."""
    ran = {"count": 0}

    def fake_run(cfg):
        ran["count"] += 1
        return {
            "scan_id": "12345678-0000-0000-0000-000000000000",
            "scan_label": "test",
            "timestamp": "2026-11-27T00:00:00",
            "config_hash": "deadbeef",
            "active_planes": ["tech"],
            "signals": [],
            "null_result": False,
        }

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
    # Point every config path the tool touches at the tmp tree.
    monkeypatch.setattr(config, "VARA_PACKAGE_PATH", tmp_path)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "vara_output")
    monkeypatch.setattr(config, "VAULT_SIGNALS_PATH", tmp_path / "vault_signals.json")
    monkeypatch.setattr(config, "VEIL_HOLD_PATH", tmp_path / "veil_hold.json")
    monkeypatch.setattr(config, "VEIL_TRAJECTORIES_PATH", tmp_path / "veil_traj.json")
    monkeypatch.setattr(config, "DRIFT_LOG_PATH", tmp_path / "vara_drift_log.json")
    return ran


def test_tool_gate_clamps_anonymous_and_stamps_result(budget_env, fake_vendor):
    result = tools.vara_run_scan({"keywords": ["x"], "sweep_depth_hours": 100})
    assert _FakeConfig.last_kwargs["sweep_depth_hours"] == 24
    assert result["scan_budget"]["tier"] == "anonymous"
    assert result["scan_budget"]["used_today"] == 1
    assert any("capped" in n for n in result["scan_budget"]["notices"])
    assert fake_vendor["count"] == 1


def test_tool_gate_exhaustion_returns_payload_without_scanning(budget_env, fake_vendor, monkeypatch):
    monkeypatch.setattr(config, "ANON_DAILY_BUDGET", 1)
    monkeypatch.setattr(config, "ANON_PER_CALLER_DAILY", 1)
    first = tools.vara_run_scan({"keywords": ["x"]})
    assert "error" not in first or not first["error"]
    second = tools.vara_run_scan({"keywords": ["x"]})
    assert "budget exhausted" in second["error"]
    assert config.KEY_PURCHASE_URL in second["error"]
    assert second["scan_budget"]["exhausted"] is True
    assert "veil_state" in second
    assert fake_vendor["count"] == 1  # the vendor scan never ran twice


def test_tool_gate_keyed_unlocks_full_depth(budget_env, fake_vendor, monkeypatch):
    monkeypatch.setenv("VARA_API_KEYS", "operator-key")
    request_context.set_caller("operator-key", "198.51.100.9")
    result = tools.vara_run_scan({"keywords": ["x"], "sweep_depth_hours": 168})
    assert _FakeConfig.last_kwargs["sweep_depth_hours"] == 168
    assert result["scan_budget"]["tier"] == "keyed"


def test_tool_gate_disabled_passes_through(budget_env, fake_vendor, monkeypatch):
    monkeypatch.setattr(config, "SCAN_BUDGET_ENABLED", False)
    result = tools.vara_run_scan({"keywords": ["x"], "sweep_depth_hours": 100})
    assert _FakeConfig.last_kwargs["sweep_depth_hours"] == 100
    assert "scan_budget" not in result
