# Vara MCP — Architecture Notes

## Source of truth

- **Runtime implementation**: local dual-track derivative (vendored under `vendor/vara/`).
- **Contracts & naming**: chatgpt branch of canonical-vault.

## Tools

| Tool | Primary capability |
|------|--------------------|
| `vara_run_scan` | Live dual-track scan → VaraScanReport (+ optional FIR) |
| `vara_list_scans` | Inventory of `vara_output/scan_*.json` |
| `vara_get_scan` | Full historical report by id/prefix |
| `vara_query_signals` | Filtered read of `vault_signals.json` (+ optional Veil hold) |
| `vara_get_veil_state` | Current hold + trajectories |
| `vara_generate_fir` | Operator-Tier markdown from a scan |

## Data paths (configurable)

```
VARA_PACKAGE_PATH  → directory containing vara_scan.py, harvesters, etc.
VARA_DATA_ROOT     → directory containing vault_signals.json, veil_hold.json, vara_output/
```

Defaults point at `vendor/vara` so historical signals remain accessible.
