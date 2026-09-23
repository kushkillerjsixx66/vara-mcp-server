# Vara MCP Server

Machine-callable surface for the **Real Vara** sensory architecture (dual-track, multi-timescale, Sentinel-gated, Veil/Vault-mediated).

This package wraps the operational Vara pipeline so it can be registered as a custom MCP connector in Grok (or any MCP-compatible client). It exposes both **live scanning** and **access to previously gathered signals**, enabling continuous Field Intel Report production.

## Goals

- Make the real Vara scan architecture callable (`vara_run_scan`)
- Provide read access to historical scans and the Vault / Veil corpus
- Preserve governance contracts (G1/G2/G3, consecutive recurrence, observation-aware Vault)
- Emit Operator-Tier Field Intel Reports as first-class outputs
- Remain deployable to public HTTPS endpoints (required by Grok custom connectors)

## Directory Layout

```
vara-mcp-server/
├── README.md
├── requirements.txt
├── vercel.json             # Vercel routing + function limits
├── api/
│   └── index.py            # Vercel Python entry (exposes FastAPI app)
├── src/
│   ├── __init__.py
│   ├── server.py           # FastAPI / MCP surface (/api/mcp)
│   ├── tools.py            # Tool implementations
│   ├── schemas.py          # JSON Schema definitions
│   └── config.py           # Paths & defaults
├── schemas/
│   └── tools.json
├── docs/
│   ├── ARCHITECTURE.md
│   └── DEPLOY.md
├── vendor/vara/            # Operational Vara package + historical data
└── data/
    └── README.md
```

## Deploy on Vercel

1. This repo is already structured for Vercel (`api/index.py` + `vercel.json`).
2. Set environment variables in the Vercel project:
   - `VARA_PACKAGE_PATH` = `/var/task/vendor/vara`
   - `VARA_DATA_ROOT`   = `/var/task/vendor/vara`
3. Deploy. Copy the production HTTPS URL.
4. In **Grok → Connectors → New → Custom** paste:

   ```
   https://<your-vercel-domain>/api/mcp
   ```

   (canonical-vault style path)

### Vercel realities

| Tool | Vercel suitability |
|------|--------------------|
| `vara_list_scans` | Excellent |
| `vara_get_scan` | Excellent |
| `vara_query_signals` | Excellent |
| `vara_get_veil_state` | Excellent |
| `vara_generate_fir` | Excellent |
| `vara_run_scan` | Risky on free/hobby (network-heavy). Better on Pro + Fluid or a long-running host. |

## Tools

| Tool | Description |
|------|-------------|
| `vara_run_scan` | Full dual-track / multi-timescale Real Vara scan |
| `vara_list_scans` | Historical scan inventory |
| `vara_get_scan` | Full past report by ID |
| `vara_query_signals` | Filtered Vault (+ optional Veil) query |
| `vara_get_veil_state` | Current hold + trajectories |
| `vara_generate_fir` | Operator-Tier Field Intel Report markdown |

See `docs/ARCHITECTURE.md` and `docs/DEPLOY.md` for full detail.
