# Vara MCP Server

<a href="https://lounge.ai/@liminaljermo"><img src="https://lounge.ai/api/badge/liminaljermo" alt="Jeremy Sebastian on Lounge" height="28"></a>

Vara is a **weak-signal scanner** that any MCP-compatible AI client can call. It searches public sources — papers, posts, releases, feeds — for early, low-volume signals on topics you choose, scores them for novelty, and returns every signal with its provenance: where it came from, when it was retrieved, and how it was judged. Signals too weak to trust yet are not discarded; they are held in a watch list (the Veil) and re-checked as they develop. Vara can also turn a scan into a **Field Intel Report**: a readable brief with its evidence attached.

## Use it

Vara is hosted — there is nothing to install, and no account or API key is needed. Point any MCP client at:

```
https://vara-mcp-server.vercel.app/api/mcp
```

Claude Code:

```
claude mcp add --transport http vara-mcp-server https://vara-mcp-server.vercel.app/api/mcp
```

The working flow:

1. **Scan** — `vara_run_scan` with keywords for your topic (optionally `target_entities`, specific `active_planes`, or a wider `sweep_depth_hours`). It searches live sources and returns a report with a `scan_id`.
2. **Read** — `vara_get_scan` re-reads a report; `vara_query_signals` searches the signals from past scans by category, novelty, entity, or date.
3. **Report** — `vara_generate_fir` turns a scan into a Field Intel Report.
4. **Watch** — signals too weak to pass are held in the Veil instead of discarded. `vara_get_veil_state` shows the watch list and whether held signals are strengthening or fading.

Two honest limits: a scan does live network work and can take a while (on this free-tier host it can occasionally time out — retrying is safe), and scan history is archived on the running instance, so older scans may not always be reachable. Keep the `scan_id` of anything you care about.

## The Lattice

This server is part of **the Lattice** — a governance-first cognitive architecture for AI ("cognitive constitution"): layered gates (coherence · attention budget · reversibility), mandatory per-signal lineage, and refusal on insufficient evidence treated as a governed success.

- **Live demo:** https://huggingface.co/spaces/Jeremysixx66/lattice-demo
- **Paper (SSRN, July 2026):** https://doi.org/10.2139/ssrn.7141439
- **Writing:** https://liminaljermo.substack.com
- **Spec bundle (Zenodo):** https://doi.org/10.5281/zenodo.23242183
- **Archive and source map (are.na):** https://www.are.na/jeremy-sebastian
- **ORCID:** https://orcid.org/0009-0000-0609-822X

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
| `vara_run_scan` | Run a live scan for weak signals on a topic; returns a report + `scan_id` |
| `vara_list_scans` | List previous scans (instance-local archive) |
| `vara_get_scan` | Full report of a past scan by `scan_id` |
| `vara_query_signals` | Search signals across scans, with filters |
| `vara_get_veil_state` | The Veil watch list: held, too-weak signals and their trajectories |
| `vara_generate_fir` | Turn a scan into a readable Field Intel Report |

See `docs/ARCHITECTURE.md` and `docs/DEPLOY.md` for full detail.

[![M8ven Score](https://m8ven.ai/badge/mcp/kushkillerjsixx66/vara-mcp-server)](https://m8ven.ai/mcp/kushkillerjsixx66/vara-mcp-server)

[![M8ven Score](https://m8ven.ai/badge/mcp/kushkillerjsixx66-vara-mcp-server-18llln?v=3fb7042ea6c08d5fe5705537a872e398)](https://m8ven.ai/mcp/kushkillerjsixx66-vara-mcp-server-18llln)
