"""Durable archive backend for Vara MCP on serverless.

Local /tmp is a hot cache only. This module dual-writes scan reports and
key state files to a GitHub branch so results survive instance recycling.

Enable by setting:
  GITHUB_TOKEN          — repo contents:write on the archive repo
  VARA_GITHUB_REPO      — default kushkillerjsixx66/vara-mcp-server
  VARA_GITHUB_BRANCH    — default vara-archive (not main — avoids redeploys)
  VARA_DURABLE_BACKEND  — "github" (default when token present) or "none"
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import httpx

from . import config

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_ARCHIVE_PREFIX = "data/archive"


def _backend() -> str:
    explicit = (os.environ.get("VARA_DURABLE_BACKEND") or "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        return "github"
    return "none"


def enabled() -> bool:
    return _backend() == "github" and bool(_token())


def _token() -> str:
    return (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or ""
    ).strip()


def _repo() -> str:
    return (
        os.environ.get("VARA_GITHUB_REPO")
        or "kushkillerjsixx66/vara-mcp-server"
    ).strip()


def _branch() -> str:
    return (os.environ.get("VARA_GITHUB_BRANCH") or "vara-archive").strip()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _contents_url(path: str) -> str:
    return f"{_GITHUB_API}/repos/{_repo()}/contents/{path}"


def _get_file(path: str) -> Optional[dict[str, Any]]:
    """Return GitHub contents API payload or None if missing."""
    try:
        r = httpx.get(
            _contents_url(path),
            headers=_headers(),
            params={"ref": _branch()},
            timeout=30.0,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("durable get_file %s failed: %s", path, e)
        return None


def _put_file(path: str, content: str, message: str) -> bool:
    """Create or update a text file on the archive branch."""
    existing = _get_file(path)
    payload: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": _branch(),
    }
    if existing and existing.get("sha"):
        payload["sha"] = existing["sha"]
    try:
        r = httpx.put(
            _contents_url(path),
            headers=_headers(),
            json=payload,
            timeout=60.0,
        )
        # 201 created, 200 updated; 409 conflict — retry once with fresh sha
        if r.status_code == 409:
            existing = _get_file(path)
            if existing and existing.get("sha"):
                payload["sha"] = existing["sha"]
                r = httpx.put(
                    _contents_url(path),
                    headers=_headers(),
                    json=payload,
                    timeout=60.0,
                )
        if r.status_code not in (200, 201):
            logger.warning(
                "durable put_file %s -> %s %s",
                path,
                r.status_code,
                r.text[:300],
            )
            return False
        return True
    except Exception as e:
        logger.warning("durable put_file %s failed: %s", path, e)
        return False


def _decode_content(payload: dict[str, Any]) -> str:
    raw = payload.get("content") or ""
    # GitHub may wrap base64 with newlines
    return base64.b64decode("".join(raw.split())).decode("utf-8")


def _scan_path(filename: str) -> str:
    return f"{_ARCHIVE_PREFIX}/scans/{filename}"


def _index_path() -> str:
    return f"{_ARCHIVE_PREFIX}/index.json"


def _state_path(name: str) -> str:
    return f"{_ARCHIVE_PREFIX}/state/{name}"


def load_index() -> list[dict[str, Any]]:
    if not enabled():
        return []
    payload = _get_file(_index_path())
    if not payload:
        return []
    try:
        data = json.loads(_decode_content(payload))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_index(entries: list[dict[str, Any]]) -> bool:
    if not enabled():
        return False
    body = json.dumps(entries, indent=2, default=str)
    return _put_file(_index_path(), body, "chore(archive): update scan index")


def persist_scan_report(report: dict[str, Any], local_path: Optional[Path] = None) -> dict[str, Any]:
    """Write scan JSON + index entry to durable store.

    Returns status dict for inclusion in the tool response.
    """
    status: dict[str, Any] = {"backend": _backend(), "persisted": False}
    if not enabled():
        status["reason"] = "durable backend not configured (set GITHUB_TOKEN)"
        return status

    scan_id = str(report.get("scan_id") or "unknown")
    short = scan_id.replace("-", "")[:8]
    filename = f"scan_{short}.json"
    if local_path and local_path.name.startswith("scan_"):
        filename = local_path.name

    body = json.dumps(report, indent=2, default=str)
    ok = _put_file(
        _scan_path(filename),
        body,
        f"archive: scan {short} ({report.get('scan_label') or ''})".strip(),
    )
    status["scan_file"] = filename
    status["branch"] = _branch()
    status["repo"] = _repo()

    if not ok:
        status["reason"] = "failed to write scan file"
        return status

    meta = {
        "scan_id": report.get("scan_id"),
        "scan_label": report.get("scan_label"),
        "timestamp": report.get("timestamp"),
        "config_hash": report.get("config_hash"),
        "active_planes": report.get("active_planes"),
        "signal_count": len(report.get("signals") or []),
        "null_result": report.get("null_result"),
        "file": filename,
    }
    index = [e for e in load_index() if e.get("scan_id") != meta["scan_id"]]
    index.insert(0, meta)
    # Cap index growth
    index = index[:500]
    index_ok = save_index(index)
    status["persisted"] = True
    status["index_updated"] = index_ok
    return status


def persist_state_files() -> dict[str, Any]:
    """Mirror Veil/Vault state files from local data root to durable store."""
    status: dict[str, Any] = {"backend": _backend(), "files": {}}
    if not enabled():
        status["reason"] = "durable backend not configured"
        return status

    mapping = {
        "vault_signals.json": config.VAULT_SIGNALS_PATH,
        "veil_hold.json": config.VEIL_HOLD_PATH,
        "veil_trajectories.json": config.VEIL_TRAJECTORIES_PATH,
        "vara_drift_log.json": config.DRIFT_LOG_PATH,
    }
    for name, path in mapping.items():
        if not path.is_file():
            status["files"][name] = "missing_local"
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            status["files"][name] = f"read_error:{e}"
            continue
        ok = _put_file(
            _state_path(name),
            text,
            f"archive: state {name}",
        )
        status["files"][name] = "ok" if ok else "failed"
    return status


def hydrate_from_durable() -> dict[str, Any]:
    """Pull durable index entries and missing scan/state files into /tmp."""
    result: dict[str, Any] = {"backend": _backend(), "hydrated_scans": 0, "hydrated_state": 0}
    if not enabled():
        return result

    config.ensure_writable_data_root()

    # State files
    for name in (
        "vault_signals.json",
        "veil_hold.json",
        "veil_trajectories.json",
        "vara_drift_log.json",
    ):
        dest = config.VARA_DATA_ROOT / name
        if dest.exists():
            continue
        payload = _get_file(_state_path(name))
        if not payload:
            continue
        try:
            dest.write_text(_decode_content(payload), encoding="utf-8")
            result["hydrated_state"] += 1
        except OSError:
            pass

    # Scan files from index
    for entry in load_index():
        filename = entry.get("file") or ""
        if not filename:
            continue
        dest = config.OUTPUT_DIR / filename
        if dest.exists():
            continue
        payload = _get_file(_scan_path(filename))
        if not payload:
            continue
        try:
            dest.write_text(_decode_content(payload), encoding="utf-8")
            result["hydrated_scans"] += 1
        except OSError:
            pass

    return result


def list_durable_scans(limit: int = 20) -> list[dict[str, Any]]:
    """Return index entries (most recent first), limited."""
    return load_index()[:limit]


def fetch_durable_scan(scan_id: str) -> Optional[dict[str, Any]]:
    """Load a full scan report by id or prefix from durable store."""
    if not enabled() or not scan_id:
        return None
    sid = scan_id.strip()
    for entry in load_index():
        eid = str(entry.get("scan_id") or "")
        fname = str(entry.get("file") or "")
        if eid == sid or eid.startswith(sid) or fname.startswith(f"scan_{sid[:8]}"):
            payload = _get_file(_scan_path(fname))
            if not payload:
                continue
            try:
                return json.loads(_decode_content(payload))
            except Exception:
                return None
    # Fallback: try direct filename guess
    short = sid.replace("-", "")[:8]
    payload = _get_file(_scan_path(f"scan_{short}.json"))
    if payload:
        try:
            return json.loads(_decode_content(payload))
        except Exception:
            return None
    return None
