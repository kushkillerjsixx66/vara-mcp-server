"""Vara MCP Server.

Native MCP Streamable HTTP surface mounted at /api/mcp.
The tool implementations remain in src.tools; this module owns the
protocol boundary and MCP tool registration.
"""

from __future__ import annotations

import contextlib
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import config
from .tools import call_tool


class RunScanArgs(BaseModel):
    keywords: list[str] | None = None
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
    ] | None = None
    sweep_depth_hours: int = Field(default=24, ge=1, le=720)
    scan_label: str | None = None
    enable_dual_track: bool = True
    high_novelty_floor: float = 0.15
    weak_novelty_floor: float = 0.05
    enable_multi_timescale: bool = True
    use_firecrawl: bool = False
    generate_fir: bool = False


class ListScansArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    since: str | None = None
    label_contains: str | None = None


class GetScanArgs(BaseModel):
    scan_id: str
    include_signals: bool = True


class QuerySignalsArgs(BaseModel):
    plane: str | None = None
    min_novelty: float | None = Field(default=None, ge=0, le=1)
    entity: str | None = None
    since: str | None = None
    until: str | None = None
    origin: Literal["passed", "veil_promoted", "any"] = "any"
    canonized_only: bool = False
    include_veil_hold: bool = False
    limit: int = Field(default=50, ge=1, le=200)


class VeilStateArgs(BaseModel):
    plane: str | None = None
    signal_id: str | None = None
    include_trajectories: bool = True


class GenerateFIRArgs(BaseModel):
    scan_id: str
    series: str | None = None
    baseline: str | None = None
    format: Literal["operator_tier", "lightweight"] = "operator_tier"
    next_cycle_hint: str | None = None


mcp = FastMCP(
    "vara-mcp",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


def _call(name: str, args: BaseModel) -> Any:
    return call_tool(name, args.model_dump(exclude_none=True))


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
def vara_run_scan(args: RunScanArgs) -> Any:
    return _call("vara_run_scan", args)


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
def vara_list_scans(args: ListScansArgs = ListScansArgs()) -> Any:
    return _call("vara_list_scans", args)


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
def vara_get_scan(args: GetScanArgs) -> Any:
    return _call("vara_get_scan", args)


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
def vara_query_signals(args: QuerySignalsArgs = QuerySignalsArgs()) -> Any:
    return _call("vara_query_signals", args)


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
def vara_get_veil_state(args: VeilStateArgs = VeilStateArgs()) -> Any:
    return _call("vara_get_veil_state", args)


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
def vara_generate_fir(args: GenerateFIRArgs) -> Any:
    return _call("vara_generate_fir", args)


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
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)

# The native MCP app owns the protocol endpoint. Mounting at /api/mcp while
# configuring streamable_http_path="/" keeps the public URL exactly
# https://.../api/mcp, matching the canonical-vault deployment.
app.mount("/api/mcp", mcp_http_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
