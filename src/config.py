"""Configuration for Vara MCP Server."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

def _default_package_path() -> Path:
    explicit = os.environ.get("VARA_PACKAGE_PATH")
    if explicit:
        return Path(explicit).resolve()
    # Vercel / AWS Lambda deployment root, when that is where we are running.
    vercel = Path("/var/task/vendor/vara")
    if vercel.is_dir():
        return vercel.resolve()
    # Anywhere else (local dev, containers, other hosts, graders): the
    # repo-relative vendor tree — this file is <repo>/src/config.py.
    # Without this fallback the server started fine off-Vercel but every
    # scan failed at import time (audit 2026-11-27, finding M1).
    return (Path(__file__).resolve().parent.parent / "vendor" / "vara").resolve()


VARA_PACKAGE_PATH = _default_package_path()


def _default_data_root() -> Path:
    """Prefer a writable location on serverless platforms."""
    explicit = os.environ.get("VARA_DATA_ROOT")
    if explicit:
        return Path(explicit).resolve()
    # Vercel / AWS Lambda: deployment bundle is read-only.
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return Path("/tmp/vara")
    return VARA_PACKAGE_PATH


VARA_DATA_ROOT = _default_data_root()

OUTPUT_DIR = VARA_DATA_ROOT / "vara_output"
VAULT_SIGNALS_PATH = VARA_DATA_ROOT / "vault_signals.json"
VEIL_HOLD_PATH = VARA_DATA_ROOT / "veil_hold.json"
VEIL_TRAJECTORIES_PATH = VARA_DATA_ROOT / "veil_trajectories.json"
DRIFT_LOG_PATH = VARA_DATA_ROOT / "vara_drift_log.json"

HOST = os.environ.get("VARA_MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("VARA_MCP_PORT", "8000"))

DEFAULT_SWEEP_HOURS = 24
DEFAULT_PLANES = ["tech", "scientific", "adjacent_possible", "economic", "geopolitical"]
MAX_SIGNALS_RETURN = 200


# ─── Scan budget (operator ruling 2026-11-27) ────────────────────────────────
# vara_run_scan is the only expensive tool (live harvest); the read tools
# stay unlimited. Two tiers:
#   anonymous — no key. Depth-capped, small shared daily pool. This is the
#               demo surface (directory playgrounds, curious agents).
#   keyed     — a key from VARA_API_KEYS (operator-issued). Full depth up
#               to the pinned FIR configuration, per-key daily allowance.
# Every dial is an environment variable so the operator can retune without
# a code change. VARA_SCAN_BUDGET_ENABLED=0 turns the gate off entirely.

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


SCAN_BUDGET_ENABLED = _env_bool("VARA_SCAN_BUDGET_ENABLED", True)
ANON_MAX_SWEEP_HOURS = _env_int("VARA_ANON_MAX_SWEEP_HOURS", 24)
ANON_MAX_PLANES = _env_int("VARA_ANON_MAX_PLANES", 5)
ANON_DAILY_BUDGET = _env_int("VARA_ANON_DAILY_BUDGET", 10)
ANON_PER_CALLER_DAILY = _env_int("VARA_ANON_PER_CALLER_DAILY", 5)
KEYED_MAX_SWEEP_HOURS = _env_int("VARA_KEYED_MAX_SWEEP_HOURS", 168)
KEYED_MAX_PLANES = _env_int("VARA_KEYED_MAX_PLANES", 8)
KEYED_DAILY_BUDGET = _env_int("VARA_KEYED_DAILY_BUDGET", 5)
BUDGET_CONTACT = os.environ.get("VARA_BUDGET_CONTACT", "lattice.liminaljermo@gmail.com")


def api_keys() -> list[str]:
    """Operator-issued API keys from VARA_API_KEYS (comma-separated).

    Read live so a key rotation in the deployment environment takes effect
    without a code change. Keys are credentials: they are never logged,
    stored, or returned — budget state records only a truncated hash.
    """
    raw = os.environ.get("VARA_API_KEYS") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]

# Seed filenames that may need to be copied from the package into the
# writable data root on first use (cold start / empty /tmp).
_SEED_FILES = (
    "vault_signals.json",
    "veil_hold.json",
    "veil_trajectories.json",
    "vara_drift_log.json",
)


def ensure_writable_data_root() -> None:
    """Create data root and seed missing state files from the package tree.

    Safe to call repeatedly. Does not overwrite existing writable files, so
    live Veil/Vault state in /tmp is preserved across warm invocations.
    """
    VARA_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if VARA_DATA_ROOT == VARA_PACKAGE_PATH:
        return  # local/dev: package tree is already the data root

    for name in _SEED_FILES:
        dest = VARA_DATA_ROOT / name
        src = VARA_PACKAGE_PATH / name
        if not dest.exists() and src.is_file():
            try:
                shutil.copy2(src, dest)
            except OSError:
                pass

    seed_out = VARA_PACKAGE_PATH / "vara_output"
    if seed_out.is_dir():
        for src in seed_out.glob("scan_*.json"):
            dest = OUTPUT_DIR / src.name
            if not dest.exists():
                try:
                    shutil.copy2(src, dest)
                except OSError:
                    pass
