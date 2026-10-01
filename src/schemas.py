"""JSON Schema definitions for Vara MCP tools."""
from __future__ import annotations

TOOLS = [
    {
        "name": "vara_run_scan",
        "description": "Execute a full Real Vara scan using the operational dual-track, multi-timescale pipeline. Returns a VaraScanReport.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "active_planes": {"type": "array", "items": {"type": "string", "enum": ["social", "scientific", "tech", "adjacent_possible", "economic", "dark", "geopolitical", "persons", "firecrawl"]}},
                "sweep_depth_hours": {"type": "integer", "minimum": 1, "maximum": 720, "default": 24},
                "scan_label": {"type": "string"},
                "enable_dual_track": {"type": "boolean", "default": True},
                "high_novelty_floor": {"type": "number", "default": 0.15},
                "weak_novelty_floor": {"type": "number", "default": 0.05},
                "enable_multi_timescale": {"type": "boolean", "default": True},
                "use_firecrawl": {"type": "boolean", "default": False},
                "generate_fir": {"type": "boolean", "default": False},
                "lineage": {
                    "type": "array",
                    "description": "Canonical Vara lineage entries. Required for canonical promotion; omitted lineage produces a non-canonical scan.",
                    "items": {
                        "type": "object",
                        "required": ["seq", "operator_id", "role", "altitude"],
                        "properties": {
                            "seq": {},
                            "operator_id": {"type": "string"},
                            "role": {"type": "string"},
                            "altitude": {"type": "string"}
                        }
                    }
                },
            },
            "required": [],
        },
    },
    {
        "name": "vara_list_scans",
        "description": "List historical Vara scan metadata from the local archive.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                "since": {"type": "string"},
                "label_contains": {"type": "string"},
            },
        },
    },
    {
        "name": "vara_get_scan",
        "description": "Retrieve a complete historical VaraScanReport by scan_id (or short prefix).",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "scan_id": {"type": "string"},
                "include_signals": {"type": "boolean", "default": True},
            },
            "required": ["scan_id"],
        },
    },
    {
        "name": "vara_query_signals",
        "description": "Query the committed Vault corpus (and optionally current Veil hold).",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "plane": {"type": "string"},
                "min_novelty": {"type": "number", "minimum": 0, "maximum": 1},
                "entity": {"type": "string"},
                "since": {"type": "string"},
                "until": {"type": "string"},
                "origin": {"type": "string", "enum": ["passed", "veil_promoted", "any"], "default": "any"},
                "canonized_only": {"type": "boolean", "default": False},
                "include_veil_hold": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
        },
    },
    {
        "name": "vara_get_veil_state",
        "description": "Inspect current Veil hold entries and trajectories.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "plane": {"type": "string"},
                "signal_id": {"type": "string"},
                "include_trajectories": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "vara_generate_fir",
        "description": "Generate an Operator-Tier or lightweight Field Intel Report from a scan_id.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "scan_id": {"type": "string"},
                "series": {"type": "string"},
                "baseline": {"type": "string"},
                "format": {"type": "string", "enum": ["operator_tier", "lightweight"], "default": "operator_tier"},
                "next_cycle_hint": {"type": "string"},
            },
            "required": ["scan_id"],
        },
    },
]
