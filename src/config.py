"""Configuration for Vara MCP Server."""
from __future__ import annotations
import os
from pathlib import Path

VARA_PACKAGE_PATH = Path(
    os.environ.get("VARA_PACKAGE_PATH", "/var/task/vendor/vara")
).resolve()

VARA_DATA_ROOT = Path(
    os.environ.get("VARA_DATA_ROOT", str(VARA_PACKAGE_PATH))
).resolve()

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
