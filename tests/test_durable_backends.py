"""Defect B — durable storage verification.

Local/filesystem fallback round-trip (scan archive AND Veil hold state),
backend selection, and Vercel Blob request shaping against a fake Blob API
(no real store, no credentials).
"""
from __future__ import annotations

import json

import pytest

from src import durable


@pytest.fixture()
def local_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("VARA_DURABLE_BACKEND", "local")
    monkeypatch.setenv("VARA_LOCAL_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return tmp_path


def test_local_fallback_round_trip_scan_and_state(local_backend, monkeypatch):
    # Data root (hot cache) is separate from the archive root.
    from src import config

    monkeypatch.setattr(config, "VARA_DATA_ROOT", local_backend / "data", raising=False)
    monkeypatch.setattr(config, "OUTPUT_DIR", local_backend / "data" / "vara_output", raising=False)
    monkeypatch.setattr(config, "VEIL_HOLD_PATH", local_backend / "data" / "veil_hold.json", raising=False)
    monkeypatch.setattr(config, "VAULT_SIGNALS_PATH", local_backend / "data" / "vault_signals.json", raising=False)
    monkeypatch.setattr(config, "VEIL_TRAJECTORIES_PATH", local_backend / "data" / "veil_trajectories.json", raising=False)
    monkeypatch.setattr(config, "DRIFT_LOG_PATH", local_backend / "data" / "vara_drift_log.json", raising=False)
    config.ensure_writable_data_root()

    assert durable.backend_name() == "local"
    assert durable.enabled() is True

    report = {
        "scan_id": "abcd1234-0000-0000-0000-000000000000",
        "scan_label": "roundtrip",
        "timestamp": "2026-10-10T12:00:00",
        "signals": [{"signal_id": "s1"}],
        "all_signals": [{"signal_id": "s1"}, {"signal_id": "s2", "disposition": "pruned"}],
    }
    status = durable.persist_scan_report(report)
    assert status["persisted"] is True
    assert status["backend"] == "local"
    assert status["index_updated"] is True

    # Veil hold state is mirrored too, not just the scan archive.
    (local_backend / "data" / "veil_hold.json").write_text(json.dumps({"s9": {"status": "HELD"}}))
    state_status = durable.persist_state_files()
    assert state_status["files"]["veil_hold.json"] == "ok"

    # Reads come back from the archive, not the hot cache.
    fetched = durable.fetch_durable_scan("abcd1234")
    assert fetched is not None and fetched["scan_label"] == "roundtrip"
    listed = durable.list_durable_scans()
    assert listed and listed[0]["scan_id"] == report["scan_id"]
    assert listed[0]["all_signal_count"] == 2

    # Hydration restores state + scan files into a fresh data root.
    (local_backend / "data" / "veil_hold.json").unlink()
    result = durable.hydrate_from_durable()
    assert result["hydrated_state"] >= 1
    assert (local_backend / "data" / "veil_hold.json").exists()


def test_backend_selection(monkeypatch):
    monkeypatch.delenv("VARA_DURABLE_BACKEND", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "blob-token")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    assert durable.backend_name() == "blob"  # Blob preferred when both present

    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN")
    assert durable.backend_name() == "github"

    monkeypatch.delenv("GITHUB_TOKEN")
    assert durable.backend_name() == "local"  # off-serverless fallback

    monkeypatch.setenv("VERCEL", "1")
    assert durable.backend_name() == "none"  # serverless without credentials: honest none
    assert durable.enabled() is False

    monkeypatch.setenv("VARA_DURABLE_BACKEND", "blob")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "blob-token")
    assert durable.backend_name() == "blob" and durable.enabled() is True


def test_blob_backend_round_trip_against_fake_api(monkeypatch):
    monkeypatch.setenv("VARA_DURABLE_BACKEND", "blob")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test-token")

    store: dict[str, str] = {}
    calls: list[tuple[str, str]] = []

    def fake_http(method, url, *, headers=None, params=None, json_body=None, content=None, timeout=60.0):
        calls.append((method, url))
        assert (headers or {}).get("Authorization") == "Bearer test-token"
        if method == "PUT":
            path = url.split("blob.vercel-storage.com/", 1)[1]
            store[path] = content.decode("utf-8")
            return 200, json.dumps({"url": f"https://store.example/{path}", "pathname": path}).encode()
        if method == "GET" and url.endswith("blob.vercel-storage.com/"):
            prefix = (params or {}).get("prefix", "")
            blobs = [
                {"pathname": p, "url": f"https://store.example/{p}",
                 "downloadUrl": f"https://store.example/{p}?download=1"}
                for p in store if p.startswith(prefix)
            ]
            return 200, json.dumps({"blobs": blobs, "hasMore": False}).encode()
        if method == "GET" and url.startswith("https://store.example/"):
            path = url.split("store.example/", 1)[1].split("?")[0]
            if path in store:
                return 200, store[path].encode()
            return 404, b""
        return 500, b""

    monkeypatch.setattr(durable, "_http_request", fake_http)

    report = {"scan_id": "beef5678-0000-0000-0000-000000000000", "scan_label": "blobtest",
              "timestamp": "2026-10-10T12:00:00", "signals": []}
    status = durable.persist_scan_report(report)
    assert status["persisted"] is True and status["backend"] == "blob"
    assert any(p.startswith("data/archive/scans/") for p in store)
    assert "data/archive/index.json" in store

    fetched = durable.fetch_durable_scan("beef5678")
    assert fetched is not None and fetched["scan_label"] == "blobtest"
