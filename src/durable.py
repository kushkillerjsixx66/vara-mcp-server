"""Durable archive backend for Vara MCP on serverless (Defect B).

Local /tmp is a hot cache only — on Vercel it dies with the instance, which
is how the inaugural scan's server-side record evaporated on 2026-10-06.
This module dual-writes scan reports and key state files (scan archive AND
Veil hold state) to a durable store so results survive instance recycling.

Backends (``VARA_DURABLE_BACKEND``):

  blob    Vercel Blob (preferred; smallest change from the path-based code —
          scan JSON and veil JSON stored as blobs). Requires
          ``BLOB_READ_WRITE_TOKEN`` in the Vercel project environment.
  github  Legacy backend: GitHub contents API on an archive branch.
          Requires ``GITHUB_TOKEN`` (contents:write).
  local   Filesystem archive under ``VARA_LOCAL_ARCHIVE_ROOT`` (default
          ``<data root>/durable_archive``). Used automatically for
          non-serverless runs with no durable credentials configured, so
          local development and tests exercise the full durable interface
          without Blob/GitHub credentials. NOT durable on Vercel.
  none    No durable store. On serverless (VERCEL set) with no credentials
          configured this is the honest default: ``enabled()`` is False and
          callers report that records will not survive instance recycling.

Selection when ``VARA_DURABLE_BACKEND`` is unset: blob if a Blob token is
present, else github if a GitHub token is present, else local off-serverless
/ none on serverless.

Upstream error bodies are never logged (Defect A rule 5) — failures log a
status code or exception class only.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from . import config

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_BLOB_API = "https://blob.vercel-storage.com"
_ARCHIVE_PREFIX = "data/archive"


def _on_serverless() -> bool:
    return bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _blob_token() -> str:
    return (os.environ.get("BLOB_READ_WRITE_TOKEN") or "").strip()


def _github_token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()


def _backend() -> str:
    explicit = (os.environ.get("VARA_DURABLE_BACKEND") or "").strip().lower()
    if explicit in ("blob", "github", "local", "filesystem", "none"):
        return "local" if explicit == "filesystem" else explicit
    if explicit:
        return "none"
    if _blob_token():
        return "blob"
    if _github_token():
        return "github"
    return "none" if _on_serverless() else "local"


def backend_name() -> str:
    return _backend()


def enabled() -> bool:
    backend = _backend()
    if backend == "blob":
        return bool(_blob_token())
    if backend == "github":
        return bool(_github_token())
    if backend == "local":
        return True
    return False


def _local_root() -> Path:
    explicit = os.environ.get("VARA_LOCAL_ARCHIVE_ROOT")
    if explicit:
        return Path(explicit)
    return config.VARA_DATA_ROOT / "durable_archive"


def _http_request(method, url, *, headers=None, params=None, json_body=None, content=None, timeout=60.0):
    try:
        import httpx
        r = httpx.request(method, url, headers=headers or {}, params=params,
                          json=json_body, content=content, timeout=timeout)
        return r.status_code, r.content
    except ImportError:
        pass
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    data = content
    hdrs = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _repo() -> str:
    return (os.environ.get("VARA_GITHUB_REPO") or "kushkillerjsixx66/vara-mcp-server").strip()


def _branch() -> str:
    return (os.environ.get("VARA_GITHUB_BRANCH") or "vara-archive").strip()


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {_github_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _contents_url(path: str) -> str:
    return f"{_GITHUB_API}/repos/{_repo()}/contents/{path}"


def _github_get_file(path: str):
    try:
        status, body = _http_request("GET", _contents_url(path), headers=_github_headers(),
                                     params={"ref": _branch()}, timeout=30.0)
        if status == 404:
            return None
        if status != 200:
            logger.warning("durable github get %s -> status %s", path, status)
            return None
        return json.loads(body.decode("utf-8"))
    except Exception as e:
        logger.warning("durable github get %s failed: %s", path, type(e).__name__)
        return None


def _github_put_file(path: str, content: str, message: str) -> bool:
    existing = _github_get_file(path)
    payload: dict = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": _branch(),
    }
    if existing and existing.get("sha"):
        payload["sha"] = existing["sha"]
    try:
        status, _ = _http_request("PUT", _contents_url(path), headers=_github_headers(),
                                  json_body=payload, timeout=60.0)
        if status == 409:
            existing = _github_get_file(path)
            if existing and existing.get("sha"):
                payload["sha"] = existing["sha"]
                status, _ = _http_request("PUT", _contents_url(path), headers=_github_headers(),
                                          json_body=payload, timeout=60.0)
        if status not in (200, 201):
            logger.warning("durable github put %s -> status %s", path, status)
            return False
        return True
    except Exception as e:
        logger.warning("durable github put %s failed: %s", path, type(e).__name__)
        return False


def _github_get_text(path: str):
    payload = _github_get_file(path)
    if not payload:
        return None
    raw = payload.get("content") or ""
    try:
        return base64.b64decode("".join(raw.split())).decode("utf-8")
    except Exception:
        return None


def _blob_headers() -> dict:
    return {"Authorization": f"Bearer {_blob_token()}"}


def _blob_put_text(path: str, content: str) -> bool:
    headers = {
        **_blob_headers(),
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "1",
        "Content-Type": "application/json",
    }
    access = (os.environ.get("VARA_BLOB_ACCESS") or "").strip().lower()
    if access in ("public", "private"):
        headers["x-vercel-blob-access"] = access
    try:
        status, _ = _http_request("PUT", f"{_BLOB_API}/{path}", headers=headers,
                                  content=content.encode("utf-8"), timeout=60.0)
        if status not in (200, 201):
            logger.warning("durable blob put %s -> status %s", path, status)
            return False
        return True
    except Exception as e:
        logger.warning("durable blob put %s failed: %s", path, type(e).__name__)
        return False


def _blob_get_text(path: str):
    try:
        status, body = _http_request("GET", _BLOB_API + "/", headers=_blob_headers(),
                                     params={"prefix": path, "limit": "100"}, timeout=30.0)
        if status != 200:
            logger.warning("durable blob list %s -> status %s", path, status)
            return None
        listing = json.loads(body.decode("utf-8"))
        match = None
        for blob in listing.get("blobs") or []:
            if blob.get("pathname") == path:
                match = blob
                break
        if not match:
            return None
        download = match.get("downloadUrl") or match.get("url")
        if not download:
            return None
        status, body = _http_request("GET", download, headers=_blob_headers(), timeout=30.0)
        if status != 200:
            logger.warning("durable blob get %s -> status %s", path, status)
            return None
        return body.decode("utf-8")
    except Exception as e:
        logger.warning("durable blob get %s failed: %s", path, type(e).__name__)
        return None


def _local_put_text(path: str, content: str) -> bool:
    try:
        dest = _local_root() / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return True
    except OSError as e:
        logger.warning("durable local put %s failed: %s", path, type(e).__name__)
        return False


def _local_get_text(path: str):
    try:
        src = _local_root() / path
        if not src.is_file():
            return None
        return src.read_text(encoding="utf-8")
    except OSError:
        return None


def _store_put_text(path: str, content: str, message: str = "") -> bool:
    backend = _backend()
    if backend == "blob":
        return _blob_put_text(path, content)
    if backend == "github":
        return _github_put_file(path, content, message or f"archive: {path}")
    if backend == "local":
        return _local_put_text(path, content)
    return False


def _store_get_text(path: str):
    backend = _backend()
    if backend == "blob":
        return _blob_get_text(path)
    if backend == "github":
        return _github_get_text(path)
    if backend == "local":
        return _local_get_text(path)
    return None


def _scan_path(filename: str) -> str:
    return f"{_ARCHIVE_PREFIX}/scans/{filename}"


def _index_path() -> str:
    return f"{_ARCHIVE_PREFIX}/index.json"


def _state_path(name: str) -> str:
    return f"{_ARCHIVE_PREFIX}/state/{name}"


def load_index() -> list:
    if not enabled():
        return []
    text = _store_get_text(_index_path())
    if not text:
        return []
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_index(entries: list) -> bool:
    if not enabled():
        return False
    body = json.dumps(entries, indent=2, default=str)
    return _store_put_text(_index_path(), body, "chore(archive): update scan index")


def persist_scan_report(report: dict, local_path: Optional[Path] = None) -> dict:
    status: dict = {"backend": _backend(), "persisted": False}
    if not enabled():
        status["reason"] = ("durable backend not configured "
                            "(set BLOB_READ_WRITE_TOKEN for Vercel Blob, or GITHUB_TOKEN)")
        return status
    scan_id = str(report.get("scan_id") or "unknown")
    short = scan_id.replace("-", "")[:8]
    filename = f"scan_{short}.json"
    if local_path and local_path.name.startswith("scan_"):
        filename = local_path.name
    body = json.dumps(report, indent=2, default=str)
    ok = _store_put_text(_scan_path(filename), body,
                         f"archive: scan {short} ({report.get('scan_label') or ''})".strip())
    status["scan_file"] = filename
    status["pathname"] = _scan_path(filename)
    if _backend() == "github":
        status["branch"] = _branch()
        status["repo"] = _repo()
    if _backend() == "local":
        status["archive_root"] = str(_local_root())
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
        "all_signal_count": len(report.get("all_signals") or report.get("signals") or []),
        "null_result": report.get("null_result"),
        "file": filename,
    }
    index = [e for e in load_index() if e.get("scan_id") != meta["scan_id"]]
    index.insert(0, meta)
    index = index[:500]
    index_ok = save_index(index)
    status["persisted"] = True
    status["index_updated"] = index_ok
    return status


def persist_state_files() -> dict:
    status: dict = {"backend": _backend(), "files": {}}
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
            status["files"][name] = f"read_error:{type(e).__name__}"
            continue
        ok = _store_put_text(_state_path(name), text, f"archive: state {name}")
        status["files"][name] = "ok" if ok else "failed"
    return status


def hydrate_from_durable() -> dict:
    result: dict = {"backend": _backend(), "hydrated_scans": 0, "hydrated_state": 0}
    if not enabled():
        return result
    config.ensure_writable_data_root()
    for name in ("vault_signals.json", "veil_hold.json", "veil_trajectories.json", "vara_drift_log.json"):
        dest = config.VARA_DATA_ROOT / name
        if dest.exists():
            continue
        text = _store_get_text(_state_path(name))
        if text is None:
            continue
        try:
            dest.write_text(text, encoding="utf-8")
            result["hydrated_state"] += 1
        except OSError:
            pass
    for entry in load_index():
        filename = entry.get("file") or ""
        if not filename:
            continue
        dest = config.OUTPUT_DIR / filename
        if dest.exists():
            continue
        text = _store_get_text(_scan_path(filename))
        if text is None:
            continue
        try:
            dest.write_text(text, encoding="utf-8")
            result["hydrated_scans"] += 1
        except OSError:
            pass
    return result


def list_durable_scans(limit: int = 20) -> list:
    return load_index()[:limit]


def fetch_durable_scan(scan_id: str):
    if not enabled() or not scan_id:
        return None
    sid = scan_id.strip()
    for entry in load_index():
        eid = str(entry.get("scan_id") or "")
        fname = str(entry.get("file") or "")
        if eid == sid or eid.startswith(sid) or fname.startswith(f"scan_{sid[:8]}"):
            text = _store_get_text(_scan_path(fname))
            if text is None:
                continue
            try:
                return json.loads(text)
            except Exception:
                return None
    short = sid.replace("-", "")[:8]
    text = _store_get_text(_scan_path(f"scan_{short}.json"))
    if text is not None:
        try:
            return json.loads(text)
        except Exception:
            return None
    return None
