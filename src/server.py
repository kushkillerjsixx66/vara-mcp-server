"""Vara MCP Server using the official MCP Streamable HTTP transport."""

from __future__ import annotations

import contextlib
from typing import Annotated, Any, Literal

from pydantic import Field

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.types import ASGIApp, Receive, Scope, Send

try:
    from . import config
    from . import request_context
    from . import tools as _tools_data
    from .tools import call_tool
except ImportError:
    # Direct execution (python src/server.py) has no package context for the
    # relative imports above. Put the project root on the path and import as
    # the src package instead, so the file runs the same way it is imported
    # by the Vercel entry (api/index.py) and by python -m src.server.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src import config
    from src import request_context
    from src import tools as _tools_data
    from src.tools import call_tool


# DNS-rebinding protection is kept enabled. The public Vercel hostname must be
# explicitly allowed; an empty allowed_hosts list rejects every external Host.
# Host validation is the rebinding defense and stays narrow. Origins are a
# separate question: this server is unauthenticated and carries no ambient
# credentials (no cookies, no sessions to ride), so Origin checks protect
# nothing here — but leaving allowed_origins empty made the SDK reject EVERY
# browser-context client (web playgrounds, inspectors) with 403 while the
# CORS layer advertised "*". The list below names the real browser surfaces
# (Glama's playground/gateway, this deployment's own origin, local dev and
# inspector origins) and is deliberately extensible: add an origin when a
# new browser client appears. Native MCP clients send no Origin and were
# never affected.
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
    allowed_origins=[
        "https://glama.ai",
        "https://www.glama.ai",
        "https://vara-mcp-server.vercel.app",
        "http://localhost:*",
        "https://localhost:*",
        "http://127.0.0.1:*",
        "https://127.0.0.1:*",
    ],
)

mcp = FastMCP(
    "vara-mcp",
    instructions=(
        "Vara is a weak-signal scanner for AI agents. It searches public "
        "sources across topic areas called planes (social, scientific, tech, "
        "economic, geopolitical, adjacent_possible, dark, persons) for early, "
        "low-volume signals — papers, posts, releases, and reports that may "
        "matter before they are widely noticed. Every signal comes with "
        "provenance: its source, when it was retrieved, and a novelty score.\n\n"
        "How to use it: call vara_run_scan with keywords (optionally "
        "target_entities, specific planes, or a wider sweep_depth_hours) to "
        "run a live scan; it returns a report with a scan_id. Follow up with "
        "vara_get_scan to re-read a report, vara_query_signals to search "
        "signals across scans, and vara_generate_fir to turn a scan into a "
        "readable Field Intel Report. Signals too weak to pass when first "
        "seen are not thrown away — they are held in the Veil, a watch list "
        "tracked over time; vara_get_veil_state shows what is being held. "
        "Held signals are unverified by definition.\n\n"
        "Practical notes: vara_run_scan performs live network work and can "
        "take a while; all other tools are fast reads. Scan history lives in "
        "an archive local to the running server instance, so older scans may "
        "be unavailable — keep the scan_id and any report you need. No "
        "account or API key is required: anonymous scans run in a capped "
        "demo tier (24h sweep, up to 5 planes, a shared daily budget), and "
        "an operator-issued API key (Authorization: Bearer, or "
        "X-Vara-Api-Key) unlocks full-depth scans. Read tools are never "
        "budget-limited."
    ),
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
        "Run a live scan of public sources for weak signals on a topic. "
        "Searches the selected planes (source categories) over the last "
        "sweep_depth_hours for the given keywords and target entities, scores "
        "what it finds for novelty, and returns a scan report whose signals "
        "each carry their source and retrieval time, plus a scan_id for "
        "follow-up calls. The only tool that changes state; it makes live "
        "network requests and can take a while. Scans are budget-tiered: "
        "anonymous callers are capped at a 24h sweep and 5 planes with a "
        "shared daily budget; an operator-issued API key unlocks full depth."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)
def vara_run_scan(
    keywords: Annotated[list[str], Field(max_length=100)] | None = None,
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
    sweep_depth_hours: Annotated[int, Field(ge=1, le=720)] = 24,
    scan_label: Annotated[str, Field(max_length=200)] | None = None,
    enable_dual_track: bool = True,
    high_novelty_floor: Annotated[float, Field(ge=0.0, le=1.0)] = 0.15,
    weak_novelty_floor: Annotated[float, Field(ge=0.0, le=1.0)] = 0.05,
    enable_multi_timescale: bool = True,
    use_firecrawl: bool = False,
    generate_fir: bool = False,
    extra_rss_feeds: Annotated[list[str], Field(max_length=50)] | None = None,
    extra_substacks: Annotated[list[str], Field(max_length=50)] | None = None,
    target_entities: Annotated[list[str], Field(max_length=50)] | None = None,
) -> Any:
    arguments = {
        "keywords": keywords,
        "target_entities": target_entities,
        "active_planes": active_planes,
        "sweep_depth_hours": sweep_depth_hours,
        "scan_label": scan_label,
        "enable_dual_track": enable_dual_track,
        "high_novelty_floor": high_novelty_floor,
        "weak_novelty_floor": weak_novelty_floor,
        "enable_multi_timescale": enable_multi_timescale,
        "use_firecrawl": use_firecrawl,
        "generate_fir": generate_fir,
        # Caller-supplied feeds: SSRF-guarded at the tool boundary and at
        # the vendor fetch site (private/link-local destinations rejected,
        # optional VARA_FEED_HOST_ALLOWLIST enforced). See src/ssrf_guard.py.
        "extra_rss_feeds": extra_rss_feeds,
        "extra_substacks": extra_substacks,
    }
    return _call("vara_run_scan", {k: v for k, v in arguments.items() if v is not None})


@mcp.tool(
    title="List Vara scans",
    description=(
        "List previous scans, newest first (metadata only). History is kept "
        "in an archive local to the running server instance, so older scans "
        "may no longer be listed."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def vara_list_scans(
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    since: str | None = None,
    label_contains: str | None = None,
) -> Any:
    arguments = {"limit": limit, "since": since, "label_contains": label_contains}
    return _call("vara_list_scans", {k: v for k, v in arguments.items() if v is not None})


@mcp.tool(
    title="Get Vara scan",
    description=(
        "Get the complete report of a previous scan by its scan_id (a unique "
        "prefix works too), including the signals it found."
    ),
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
    description=(
        "Search the signals collected by past scans. Filter by plane (source "
        "category), minimum novelty score, entity, or date range. Set "
        "include_veil_hold to also search signals that were held back as too "
        "weak (see vara_get_veil_state)."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def vara_query_signals(
    plane: str | None = None,
    min_novelty: Annotated[float, Field(ge=0.0, le=1.0)] | None = None,
    entity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    origin: Literal["passed", "veil_promoted", "any"] = "any",
    canonized_only: bool = False,
    include_veil_hold: bool = False,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
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
    description=(
        "Show the Veil: signals Vara judged too weak to pass when first seen, "
        "kept on a watch list and re-checked over time. Trajectories show "
        "whether a held signal is strengthening or fading. Held signals are "
        "unverified — being in the Veil is not a result."
    ),
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
    description=(
        "Turn a scan into a Field Intel Report: a readable intelligence "
        "brief built from the scan's signals, with provenance attached. "
        "format 'operator_tier' is the full report (keyed callers); "
        "'free' is the FFIR — a Free Field Intel Report, observed signals "
        "only, which is what anonymous callers receive; 'lightweight' is "
        "a short brief."
    ),
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
    format: Literal["operator_tier", "lightweight", "free"] = "operator_tier",
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


def _signal_address(sig: dict, position: int) -> str:
    """Addressable identity for a signal within its scan.

    Modern signals carry signal_id/source_id. Legacy scans (e.g. the Sep 2
    seed) carry neither — those signals are addressed positionally as
    "idx:{n}" so every signal in every scan stays reachable as a resource.
    """
    return sig.get("signal_id") or sig.get("source_id") or f"idx:{position}"


def _signal_index_entry(scan_id: str, sig: dict, position: int = 0) -> dict:
    sid = sig.get("signal_id") or sig.get("source_id")
    return {
        "signal_id": sid,
        "source_id": sig.get("source_id"),
        "plane": sig.get("plane"),
        "title": sig.get("title"),
        "url": sig.get("url"),
        "novelty_score": sig.get("novelty_score"),
        "track": sig.get("track"),
        "uri": f"vara://scan/{scan_id}/signal/{_signal_address(sig, position)}",
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
    out["signals_index"] = [
        _signal_index_entry(str(data.get("scan_id") or scan_id), s, i)
        for i, s in enumerate(signals)
    ]
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
    signals = data.get("signals") or []
    if signal_id.startswith("idx:"):
        try:
            pos = int(signal_id[4:])
        except ValueError:
            pos = -1
        if 0 <= pos < len(signals):
            return _json.dumps(
                {
                    "scan_id": data.get("scan_id"),
                    "scan_timestamp": data.get("timestamp"),
                    "config_hash": data.get("config_hash"),
                    "identity": "positional — this signal carries no signal_id/source_id (legacy scan)",
                    "signal": signals[pos],
                },
                default=str,
            )
        return _json.dumps(
            {"error": f"No signal at position {signal_id} in scan '{data.get('scan_id') or scan_id}'"},
            default=str,
        )
    for sig in signals:
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
    if signals and all("content_hash" not in s for s in signals):
        gaps.append("per-signal content_hash is not recorded in scan reports")
    return _json.dumps(
        {
            "scan_id": data.get("scan_id"),
            "scan_label": data.get("scan_label"),
            "retrieved_at": data.get("timestamp"),
            "config_hash": data.get("config_hash"),
            "keywords": data.get("keywords"),
            "active_planes": data.get("active_planes"),
            "canonical_conformance": data.get("canonical_conformance"),
            "signal_lineage": data.get("signal_lineage"),
            "all_signals": data.get("all_signals"),
            "signals": [
                {
                    "signal_id": s.get("signal_id") or s.get("source_id"),
                    "source_id": s.get("source_id"),
                    "source": s.get("source") or s.get("source_id"),
                    "url": s.get("url"),
                    "feed_tier": s.get("feed_tier"),
                    "entity_first_seen": s.get("entity_first_seen"),
                    "track": s.get("track"),
                    "retrieved_at": s.get("retrieved_at"),
                    "disposition": s.get("disposition"),
                    "content_hash": s.get("content_hash"),
                    "uri": f"vara://scan/{data.get('scan_id')}/signal/{_signal_address(s, i)}",
                }
                for i, s in enumerate(signals)
            ],
            "lineage_gaps": gaps,
        },
        default=str,
    )


@mcp.resource(
    "vara://veil/state",
    name="vara-veil-state",
    description=(
        "The Veil watch list: signals held back as too weak when first seen, "
        "with their trajectories over time. See the vara_get_veil_state tool."
    ),
    mime_type="application/json",
)
def veil_state_resource() -> str:
    return _json.dumps(_tools_data.vara_get_veil_state({}), default=str)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from . import durable as _durable
    from . import ssrf_guard as _ssrf

    return {
        "status": "ok",
        "service": "vara-mcp",
        "mcp_base": "/api/mcp",
        "durable": {"backend": _durable.backend_name(), "enabled": _durable.enabled()},
        "ssrf_guard": {"module": "src.ssrf_guard", "feed_allowlist_configured": bool(_ssrf.feed_host_allowlist())},
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

    CPU-burn guard (2026-10-29): this server is stateless (stateless_http,
    json_response) and has no server-initiated messages to stream, but the
    SDK's GET handler still opens an SSE stream that never closes — on
    Vercel each such GET ran to the 300s function cap and burned Fluid
    Active CPU (directory crawlers probing the endpoint made it a daily
    bleed). The MCP spec permits a server that offers no standalone SSE
    stream to answer GET with 405; do exactly that, immediately, and the
    same for DELETE (no sessions exist to terminate). POST is untouched.
    """

    _BLOCKED_METHODS = ("GET", "DELETE")
    _BLOCKED_BODY = (
        b'{"jsonrpc":"2.0","error":{"code":-32000,"message":'
        b'"Method Not Allowed: stateless MCP server, POST only"},"id":null}'
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") == "POST" \
                and scope.get("path") in ("/api/mcp", "/api/mcp/"):
            # Park the caller's API key + client IP in contextvars for the
            # scan-budget gate (src/budget.py). Values are used only for
            # tier resolution and hashed counting — never logged or echoed.
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers") or []
            }
            api_key = headers.get("x-vara-api-key")
            auth = headers.get("authorization") or ""
            if not api_key and auth.lower().startswith("bearer "):
                api_key = auth[7:].strip()
            forwarded = headers.get("x-forwarded-for") or ""
            caller_ip = forwarded.split(",")[0].strip() or None
            if caller_ip is None and scope.get("client"):
                caller_ip = scope["client"][0]
            request_context.set_caller(api_key, caller_ip)
        if scope["type"] == "http" and scope.get("path") in ("/api/mcp", "/api/mcp/"):
            if scope.get("method") in self._BLOCKED_METHODS:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 405,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"allow", b"POST"),
                            (
                                b"content-length",
                                str(len(self._BLOCKED_BODY)).encode(),
                            ),
                        ],
                    }
                )
                await send(
                    {"type": "http.response.body", "body": self._BLOCKED_BODY}
                )
                return
            if scope.get("path") == "/api/mcp":
                scope = dict(scope)
                scope["path"] = "/api/mcp/"
                if "raw_path" in scope:
                    scope["raw_path"] = b"/api/mcp/"
        await self.app(scope, receive, send)


app = FastAPI(
    title="Vara MCP Server",
    description=(
        "Vara MCP Server — governed weak-signal scanning for AI agents: "
        "live scans of public sources, per-signal provenance, Field Intel Reports."
    ),
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
