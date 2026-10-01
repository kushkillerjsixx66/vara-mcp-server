"""Regression tests for the native MCP transport boundary."""

import asyncio

from src.server import app, mcp


def test_native_mcp_registers_all_tools():
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "vara_run_scan",
        "vara_list_scans",
        "vara_get_scan",
        "vara_query_signals",
        "vara_get_veil_state",
        "vara_generate_fir",
    }


def test_run_scan_is_not_read_only():
    tools = asyncio.run(mcp.list_tools())
    run_scan = next(tool for tool in tools if tool.name == "vara_run_scan")

    assert run_scan.annotations is not None
    assert run_scan.annotations.read_only_hint is False
    assert run_scan.annotations.destructive_hint is False
    assert run_scan.annotations.idempotent_hint is False
    assert run_scan.annotations.open_world_hint is True


def test_read_tools_are_read_only():
    tools = asyncio.run(mcp.list_tools())

    for name in {
        "vara_list_scans",
        "vara_get_scan",
        "vara_query_signals",
        "vara_get_veil_state",
        "vara_generate_fir",
    }:
        tool = next(item for item in tools if item.name == name)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False


def test_native_mcp_endpoint_is_mounted():
    routes = {getattr(route, "path", None) for route in app.routes}
    assert "/api/mcp" in routes
