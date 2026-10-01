from src.schemas import TOOLS


EXPECTED_ANNOTATIONS = {
    "vara_run_scan": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "vara_list_scans": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "vara_get_scan": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "vara_query_signals": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "vara_get_veil_state": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "vara_generate_fir": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}


def test_all_mcp_tools_have_complete_behavioral_annotations():
    tools_by_name = {tool["name"]: tool for tool in TOOLS}

    assert set(tools_by_name) == set(EXPECTED_ANNOTATIONS)

    for name, expected in EXPECTED_ANNOTATIONS.items():
        annotations = tools_by_name[name]["annotations"]
        assert annotations == expected
        assert all(isinstance(value, bool) for value in annotations.values())


def test_all_mcp_tools_have_input_schemas():
    for tool in TOOLS:
        assert isinstance(tool["inputSchema"], dict)
        assert tool["inputSchema"]["type"] == "object"


def test_run_scan_exposes_canonical_lineage_input():
    schema = next(tool["inputSchema"] for tool in TOOLS if tool["name"] == "vara_run_scan")
    lineage = schema["properties"]["lineage"]

    assert lineage["type"] == "array"
    assert lineage["items"]["required"] == ["seq", "operator_id", "role", "altitude"]
