"""Vara MCP Server using the official MCP Streamable HTTP transport."""

from __future__ import annotations

import contextlib
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from . import config
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
    }


mcp_http_app = mcp.streamable_http_app()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield


app = FastAPI(
    title="Vara MCP Server",
    description="Machine-callable Real Vara sensory architecture",
    version="1.1.0",
    lifespan=lifespan,
    redirect_slashes=False,  # POST /api/mcp must be answered directly (no 307)
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)

# Native Streamable HTTP endpoint.
# Dual-mount so both /api/mcp and /api/mcp/ answer POSTs with no redirect.
# (Starlette path matching treats the two prefixes differently relative to
# streamable_http_path="/".)
app.mount("/api/mcp/", mcp_http_app)
app.mount("/api/mcp", mcp_http_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
