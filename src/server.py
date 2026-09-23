"""
Vara MCP Server — Streamable HTTP entry point.

Compatible with Grok custom connectors and other MCP clients that speak
Streamable HTTP / SSE.

Run:
    python -m src.server
or:
    uvicorn src.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from .schemas import TOOLS
from .tools import call_tool
from . import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vara.mcp")

app = FastAPI(
    title="Vara MCP Server",
    description="Machine-callable Real Vara sensory architecture",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "vara-mcp",
        "package_path": str(config.VARA_PACKAGE_PATH),
        "data_root": str(config.VARA_DATA_ROOT),
        "tools": [t["name"] for t in TOOLS],
    }


@app.get("/mcp/tools")
@app.post("/mcp/tools/list")
async def list_tools():
    """Return the tool catalogue."""
    return {"tools": TOOLS}


@app.post("/mcp/tools/call")
async def tools_call(request: Request):
    """
    Call a tool.
    Body: { "name": "vara_run_scan", "arguments": { ... } }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    name = body.get("name") or body.get("tool")
    arguments = body.get("arguments") or body.get("args") or {}

    if not name:
        return JSONResponse({"error": "missing tool name"}, status_code=400)

    logger.info("tool call: %s args_keys=%s", name, list(arguments.keys()))
    result = call_tool(name, arguments)
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}], "isError": "error" in result}


@app.post("/mcp")
async def mcp_jsonrpc(request: Request):
    """
    Lightweight JSON-RPC style endpoint for broader MCP compatibility.
    Supports tools/list and tools/call.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        result = call_tool(name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "isError": "error" in result,
            },
        }

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "vara-mcp", "version": "1.0.0"},
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    import uvicorn
    logger.info("Starting Vara MCP on %s:%s", config.HOST, config.PORT)
    logger.info("VARA_PACKAGE_PATH=%s", config.VARA_PACKAGE_PATH)
    logger.info("VARA_DATA_ROOT=%s", config.VARA_DATA_ROOT)
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
