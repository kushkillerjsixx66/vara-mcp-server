"""Per-request caller context for the MCP endpoint.

The ASGI wrapper in server.py captures two headers from each MCP POST —
the caller's API key (Authorization: Bearer, or X-Vara-Api-Key) and the
client IP (first X-Forwarded-For hop) — and parks them in contextvars.
Tool implementations read them from here; nothing is logged and the key
is never echoed back to the caller.

Outside an HTTP request (direct tool calls, tests, CLI) both values are
None and the caller is treated as anonymous/local.
"""
from __future__ import annotations

import contextvars
from typing import Optional

_api_key: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "vara_api_key", default=None
)
_caller_ip: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "vara_caller_ip", default=None
)


def set_caller(api_key: Optional[str], caller_ip: Optional[str]) -> None:
    _api_key.set(api_key or None)
    _caller_ip.set(caller_ip or None)


def current_api_key() -> Optional[str]:
    return _api_key.get()


def current_caller_ip() -> Optional[str]:
    return _caller_ip.get()
