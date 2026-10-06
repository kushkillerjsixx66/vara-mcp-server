# Vara durable archive

This branch holds scan reports and mirrored Veil/Vault state written by the
MCP server on Vercel. It is **not** the production deploy branch.

```
data/archive/
  index.json          # scan metadata, newest first
  scans/scan_*.json   # full scan reports
  state/              # vault_signals, veil_hold, trajectories, drift log
```

Written automatically when `GITHUB_TOKEN` is set on the deployment.
