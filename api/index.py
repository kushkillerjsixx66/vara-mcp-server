"""
Vercel serverless entry for Vara MCP Server.

Primary MCP surface: /api/mcp  (canonical-vault style)
Health probe:        /health

All routes are handled by the FastAPI app defined in src/server.py.
Live scans (vara_run_scan) may hit platform timeouts on free/hobby plans
because they perform network I/O across multiple feeds. Query tools are safe.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on the path so "src" is importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.server import app  # noqa: E402

# Vercel Python runtime looks for a module-level "app" (ASGI) or "handler"
handler = app
