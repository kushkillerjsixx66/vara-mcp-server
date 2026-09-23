# Deploying Vara MCP

## Vercel (primary)

1. Repo is already structured with `api/index.py` + `vercel.json`.
2. Set env vars in Vercel project:
   - `VARA_PACKAGE_PATH=/var/task/vendor/vara`
   - `VARA_DATA_ROOT=/var/task/vendor/vara`
3. Deploy → copy production URL → register in Grok Connectors.

## Timeout reality

Query tools are safe. `vara_run_scan` can exceed free-tier duration limits.
