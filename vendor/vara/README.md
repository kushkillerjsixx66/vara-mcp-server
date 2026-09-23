# Vendored Real Vara package

This directory holds the operational Vara runtime used by the MCP server.

Set on Vercel:
```
VARA_PACKAGE_PATH=/var/task/vendor/vara
VARA_DATA_ROOT=/var/task/vendor/vara
```

Contents should include:
- vara_scan.py, vara_harvesters.py, vara_sentinel.py, vara_veil_vault.py
- Supporting harvesters and adaptive modules
- vault_signals.json, veil_hold.json, vara_output/ (historical data)
