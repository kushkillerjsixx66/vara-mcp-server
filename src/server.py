"""Vara MCP Server using the official MCP Streamable HTTP transport."""

from __future__ import annotations

import contextlib
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.types import ASGIApp, Receive, Scope, Send

from . import config
from . import tools as _tools_data
from .tools import call_tool


# DNS-rebinding protection is kept enabled. The public Vercel hostname must be
# explicitly allowed; an empty allowed_hosts list rejects every external Host.
_TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "vara-mcp-server.vercel.app",
        "vara-mcp-server.vercel.app:*",
    ],
)

mcp = FastMCP(
    "vara-mcp",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=_TRANSPORT_SECURITY,
)


def _call(name: str, arguments: dict[str, Any]) -> Any:
    return call_tool(name, arguments)


@mcp.tool(
    title="Run Vara scan",
    description=(
        "Execute a full Real Vara scan using the operational dual-track, "
        "multi-timescale pipeline. This tool changes Vara runtime state."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)
def vara_run_scan(
    keywords: list[str] | None = None,
    active_planes: list[
        Literal[
            "social",
            "scientific",
            "tech",
            "adjacent_possible",
            "economic",
            "dark",
            "geopolitical",
            "persons",
            "firecrawl",
        ]
    ]
    | None = None,
    sweep_depth_hours: int = 24,
    scan_label: str | None = None,
    enable_dual_track: bool = True,
    high_novelty_floor: float = 0.15,
    weak_novelty_floor: float = 0.05,
    enable_multi_timescale: bool = True,
    use_firecrawl: bool = False,
    generate_fir: bool = False,
) -> Any:
    arguments = {
        "keywords": keywords,
        "active_planes": active_planes,
        "sweep_depth_hours": sweep_depth_hours,
        "scan_label": scan_label,
        "enable_dual_track": enable_dual_track,
        "high_novelty_floor": high_novelty_floor,
        "weak_novelty_floor": weak_novelty_floor,
        "enable_multi_timescale": enable_multi_timescale,
        "use_firecrawl": use_firecrawl,
        "generate_fir": generate_fir,
    }
    return _call("vara_run_scan", {k: v for k, v in arguments.items() if v is not None})


@mcp.tool(
    title="List Vara scans",
    description="List historical Vara scan metadata from the local archive.",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def vara_list_scans(
    limit: int = 20,
    since: str | None = None,
    label_contains: str | None = None,
) -> Any:
    arguments = {"limit": limit, "since": since, "label_contains": label_contains}
    return _call("vara_list_scans", {k: v for k, v in arguments.items() if v is not None})


@mcp.tool(
    title="Get Vara scan",
    description="Retrieve a complete historical VaraScanReport by scan_id or short prefix.",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def vara_get_scan(
    scan_id: str,
    include_signals: bool = True,
) -> Any:
    return _call(
        "vara_get_scan",
        {"scan_id": scan_id, "include_signals": include_signals},
    )


@mcp.tool(
    title="Query Vara signals",
    description="Query the committed Vault corpus and optionally the current Veil hold.",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def vara_query_signals(
    plane: str | None = None,
    min_novelty: float | None = None,
    entity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    origin: Literal["passed", "veil_promoted", "any"] = "any",
    canonized_only: bool = False,
    include_veil_hold: bool = False,
    limit: int = 50,
) -> Any:
    arguments = {
        "plane": plane,
        "min_novelty": min_novelty,
        "entity": entity,
        "since": since,
        "until": until,
        "origin": origin,
        "canonized_only": canonized_only,
        "include_veil_hold": include_veil_hold,
        "limit": limit,
    }
    return _call("vara_query_signals", {k: v for k, v in arguments.items() if v is not None})


@mcp.tool(
    title="Get Veil state",
    description="Inspect current Veil hold entries and trajectories.",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def vara_get_veil_state(
    plane: str | None = None,
    signal_id: str | None = None,
    include_trajectories: bool = True,
) -> Any:
    arguments = {
        "plane": plane,
        "signal_id": signal_id,
        "include_trajectories": include_trajectories,
    }
    return _call("vara_get_veil_state", {k: v for k, v in arguments.items() if v is not None})


@mcp.tool(
    title="Generate FIR",
    description="Generate an Operator-Tier or lightweight Field Intel Report from a scan_id.",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def vara_generate_fir(
    scan_id: str,
    series: str | None = None,
    baseline: str | None = None,
    format: Literal["operator_tier", "lightweight"] = "operator_tier",
    next_cycle_hint: str | None = None,
) -> Any:
    arguments = {
        "scan_id": scan_id,
        "series": series,
        "baseline": baseline,
        "format": format,
        "next_cycle_hint": next_cycle_hint,
    }
    return _call("vara_generate_fir", {k: v for k, v in arguments.items() if v is not None})


# ─── Resources (MCP upgrade Phase 1, 2026-10-07) ─────────────────────────────
# Until now this server advertised `resources` capability but exposed zero
# resources: every read was a tool call returning an unbounded blob (a full
# scan report = manifest + every signal body in one response). Resources make
# scans addressable at signal granularity — the URI is the provenance:
#
#   vara://scans                            index of archived scans (manifests)
#   vara://scan/{scan_id}                   one scan: metadata + signal INDEX
#                                           (bodies are NOT inlined)
#   vara://scan/{scan_id}/signal/{signal_id}  one signal, full body
#   vara://scan/{scan_id}/lineage           provenance view of a scan, with
#                                           lineage gaps stated as nulls
#   vara://veil/state                       current Veil hold
#
# All handlers reuse the same data functions as the tools (src/tools.py), so
# resource reads and tool reads cannot diverge.

import json as _json


def _signal_index_entry(scan_id: str, sig: dict) -> dict:
    sid = sig.get("signal_id") or sig.get("source_id")
    return {
        "signal_id": sid,
        "source_id": sig.get("source_id"),
        "plane": sig.get("plane"),
        "title": sig.get("title"),
        "url": sig.get("url"),
        "novelty_score": sig.get("novelty_score"),
        "track": sig.get("track"),
        "uri": f"vara://scan/{scan_id}/signal/{sid}" if sid else None,
    }


@mcp.resource(
    "vara://scans",
    name="vara-scans",
    description="Index of archived Vara scans (metadata only, newest first).",
    mime_type="application/json",
)
def scans_resource() -> str:
    return _json.dumps(_tools_data.vara_list_scans({"limit": 50}), default=str)


@mcp.resource(
    "vara://scan/{scan_id}",
    name="vara-scan",
    description=(
        "One Vara scan report with its signals replaced by an index of "
        "per-signal resource URIs. Read vara://scan/{id}/signal/{signal_id} "
        "for a signal body."
    ),
    mime_type="application/json",
)
def scan_resource(scan_id: str) -> str:
    # NOTE: scan reports carry a top-level "error" field that is null on
    # success — failure is a non-empty error string, never key presence.
    data = _tools_data.vara_get_scan({"scan_id": scan_id, "include_signals": True})
    if data.get("error"):
        return _json.dumps({"error": data["error"]}, default=str)
    signals = data.get("signals") or []
    out = {k: v for k, v in data.items() if k != "signals"}
    out["signal_count"] = len(signals)
    out["signals_index"] = [_signal_index_entry(str(data.get("scan_id") or scan_id), s) for s in signals]
    out["lineage_uri"] = f"vara://scan/{data.get('scan_id') or scan_id}/lineage"
    return _json.dumps(out, default=str)


@mcp.resource(
    "vara://scan/{scan_id}/signal/{signal_id}",
    name="vara-scan-signal",
    description="One signal from a Vara scan, full body, with its scan provenance.",
    mime_type="application/json",
)
def scan_signal_resource(scan_id: str, signal_id: str) -> str:
    data = _tools_data.vara_get_scan({"scan_id": scan_id, "include_signals": True})
    if data.get("error"):
        return _json.dumps({"error": data["error"]}, default=str)
    for sig in data.get("signals") or []:
        if signal_id in (sig.get("signal_id"), sig.get("source_id")):
            return _json.dumps(
                {
                    "scan_id": data.get("scan_id"),
                    "scan_timestamp": data.get("timestamp"),
                    "config_hash": data.get("config_hash"),
                    "signal": sig,
                },
                default=str,
            )
    return _json.dumps(
        {"error": f"No signal '{signal_id}' in scan '{data.get('scan_id') or scan_id}'"},
        default=str,
    )


@mcp.resource(
    "vara://scan/{scan_id}/lineage",
    name="vara-scan-lineage",
    description=(
        "Provenance view of a scan: scan-level provenance plus per-signal "
        "source fields. Fields the scan pipeline does not record are "
        "returned as explicit nulls and named in lineage_gaps — never filled."
    ),
    mime_type="application/json",
)
def scan_lineage_resource(scan_id: str) -> str:
    data = _tools_data.vara_get_scan({"scan_id": scan_id, "include_signals": True})
    if data.get("error"):
        return _json.dumps({"error": data["error"]}, default=str)
    signals = data.get("signals") or []
    gaps = []
    if signals and all("retrieved_at" not in s for s in signals):
        gaps.append("per-signal retrieved_at is not recorded by the scan pipeline")
    if signals and all("disposition" not in s for s in signals):
        gaps.append("per-signal disposition is not recorded in scan reports")
    return _json.dumps(
        {
            "scan_id": data.get("scan_id"),
            "scan_label": data.get("scan_label"),
            "retrieved_at": data.get("timestamp"),
            "config_hash": data.get("config_hash"),
            "keywords": data.get("keywords"),
            "active_planes": data.get("active_planes"),
            "canonical_conformance": data.get("canonical_conformance"),
            "signals": [
                {
                    "signal_id": s.get("signal_id") or s.get("source_id"),
                    "source_id": s.get("source_id"),
                    "url": s.get("url"),
                    "feed_tier": s.get("feed_tier"),
                    "entity_first_seen": s.get("entity_first_seen"),
                    "track": s.get("track"),
                    "retrieved_at": s.get("retrieved_at"),
                    "disposition": s.get("disposition"),
                    "uri": f"vara://scan/{data.get('scan_id')}/signal/{s.get('signal_id') or s.get('source_id')}",
                }
                for s in signals
            ],
            "lineage_gaps": gaps,
        },
        default=str,
    )


@mcp.resource(
    "vara://veil/state",
    name="vara-veil-state",
    description="Current Veil hold: held entries and trajectories.",
    mime_type="application/json",
)
def veil_state_resource() -> str:
    return _json.dumps(_tools_data.vara_get_veil_state({}), default=str)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return {
        "status": "ok",
        "service": "vara-mcp",
        "mcp_base": "/api/mcp",
        "package_path": str(config.VARA_PACKAGE_PATH),
        "data_root": str(config.VARA_DATA_ROOT),
        "tools": [
            "vara_run_scan",
            "vara_list_scans",
            "vara_get_scan",
            "vara_query_signals",
            "vara_get_veil_state",
            "vara_generate_fir",
        ],
        "resources": [
            "vara://scans",
            "vara://scan/{scan_id}",
            "vara://scan/{scan_id}/signal/{signal_id}",
            "vara://scan/{scan_id}/lineage",
            "vara://veil/state",
        ],
    }


mcp_http_app = mcp.streamable_http_app()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield


class _NormalizeMcpPath:
    """Rewrite /api/mcp → /api/mcp/ internally so the mounted app matches.

    No client-visible redirect; the original POST body is preserved.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/api/mcp":
            scope = dict(scope)
            scope["path"] = "/api/mcp/"
            if "raw_path" in scope:
                scope["raw_path"] = b"/api/mcp/"
        await self.app(scope, receive, send)


app = FastAPI(
    title="Vara MCP Server",
    description="Machine-callable Real Vara sensory architecture",
    version="1.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)

# Mount at the slash form that the Streamable HTTP app matches as path "/".
app.mount("/api/mcp/", mcp_http_app)

# Outermost ASGI wrapper: present exact /api/mcp as /api/mcp/ to the router.
app = _NormalizeMcpPath(app)  # type: ignore[assignment]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
