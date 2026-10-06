# Deploying Vara MCP

## Vercel (primary)

1. Repo is already structured with `api/index.py` + `vercel.json`.
2. Set environment variables in the Vercel project:
   - `VARA_PACKAGE_PATH=/var/task/vendor/vara`  (read-only code + seed assets)
   - `VARA_DATA_ROOT=/tmp/vara`  (**writable** state: Veil hold, Vault mutations, scan output)
3. Deploy → copy production URL → register in Grok Connectors as:
   `https://<your-vercel-domain>/api/mcp`

On Vercel the deployment bundle under `/var/task` is read-only. Pointing
`VARA_DATA_ROOT` at the same path causes `Errno 30` when a scan tries to
persist Veil state. `/tmp/vara` is ephemeral per instance but is the correct
serverless write target; seed files are copied from the package on first use.

## Timeout reality

Query tools are safe. `vara_run_scan` can exceed free-tier duration limits
because it performs multi-feed network I/O. Prefer Pro + Fluid for live scans,
or run scans on a long-running host and use this endpoint for read access.
