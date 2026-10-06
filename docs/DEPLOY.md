# Deploying Vara MCP

## Vercel (primary)

1. Repo is already structured with `api/index.py` + `vercel.json`.
2. Set environment variables in the Vercel project:
   - `VARA_PACKAGE_PATH=/var/task/vendor/vara`  (read-only code + seed assets)
   - `VARA_DATA_ROOT=/tmp/vara`  (writable **hot cache** per instance)
   - `GITHUB_TOKEN` — fine-grained or classic token with `contents:write` on this repo
   - Optional:
     - `VARA_GITHUB_REPO=kushkillerjsixx66/vara-mcp-server`
     - `VARA_GITHUB_BRANCH=vara-archive` (default; **not** `main` — avoids redeploy loops)
     - `VARA_DURABLE_BACKEND=github` (default when token is present)
3. Deploy → copy production URL → register in Grok Connectors as:
   `https://<your-vercel-domain>/api/mcp`

### Why two storage layers?

| Layer | Path | Lifetime |
|-------|------|----------|
| Package seed | `/var/task/vendor/vara` | Immutable deployment bundle |
| Hot cache | `/tmp/vara` | Single serverless instance only |
| **Durable archive** | GitHub branch `vara-archive` under `data/archive/` | Survives instance cycles |

Without `GITHUB_TOKEN`, scans still run and write to `/tmp`, but the archive evaporates when the instance is recycled — the failure mode observed after the inaugural scan.

Create the archive branch once (empty is fine):
```bash
git fetch origin main && git checkout -b vara-archive origin/main
git push -u origin vara-archive
```
Do **not** point the Vercel production branch at `vara-archive`.

## Timeout reality

Query tools are safe. `vara_run_scan` can exceed free-tier duration limits
because it performs multi-feed network I/O. Prefer Pro + Fluid for live scans,
or run scans on a long-running host and use this endpoint for read access.
