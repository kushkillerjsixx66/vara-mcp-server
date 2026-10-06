"""Configuration for Vara MCP Server."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

VARA_PACKAGE_PATH = Path(
    os.environ.get("VARA_PACKAGE_PATH", "/var/task/vendor/vara")
).resolve()


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
