# Vendored Vara Runtime

This directory contains a functional MCP-oriented copy of the Real Vara pipeline:

- `vara_scan.py` — orchestrator (VaraConfig, run_vara_scan)
- `vara_sentinel.py` — G1/G2/G3 dual-track gates
- `vara_veil_vault.py` — Veil hold + Vault commit
- `vara_harvesters.py` — RSS/HN harvest (when feedparser available)
- `vara.py` — top-level entry

## Historical data

`vault_signals.json`, `veil_hold.json`, and `vara_output/` are initialized empty.

To load your real historical corpus from Termux:

```bash
cd ~/vara-mcp-server
cp ~/canonical-vault/05_runtime/vault_signals.json vendor/vara/ 2>/dev/null || true
# or from your dual-track data path:
# cp /path/to/vault_signals.json vendor/vara/
# cp -r /path/to/vara_output vendor/vara/
git add vendor/vara/
git commit -m "Add historical Vara signal corpus"
git push
```

## Env vars (Vercel)

```
VARA_PACKAGE_PATH=/var/task/vendor/vara
VARA_DATA_ROOT=/var/task/vendor/vara
```
