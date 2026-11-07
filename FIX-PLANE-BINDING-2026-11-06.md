# Fix: Plane Binding Collapse + Instrument Provenance — 2026-11-06

**Scope:** extracted code copy at `~/workspace/mcp-upgrade/repos/vara-mcp-server/`
(not a git repo). Implementation + tests only. **Nothing deployed, pushed, or
run against the live server.** System of origin: Lattice (vault line), Vara MCP.

**Finding addressed (FIR-025, verified):** a 7-plane scan harvested all planes,
but the vault-bound set collapsed — corrected run: bound 135, **all tech**; the
other six planes (scientific, social, economic, geopolitical, dark,
adjacent_possible) bound zero and were uniformly pruned. Separately (Fault 3),
the scan payload carried no per-plane flow counts and no record of the
effective keyword vocabulary in force, so the collapse was invisible in the
payload and cross-cycle comparisons could not pin the instrument.

---

## 1. Traced mechanism (file/line evidence)

The full path harvest → novelty → track split → Sentinel gates → vault_bound:

1. **Scoring — `vendor/vara/vara_harvesters.py`**
   - `_harvest_rss_plane`, line 297: `plane_kw = DOMAIN_KEYWORDS.get(plane, kw_set)`
     and line 310: `novelty = _keyword_density(full_text, kw_set + plane_kw)`,
     where `kw_set` is the caller's keywords (falling back to DEFAULT_KEYWORDS).
   - `DOMAIN_KEYWORDS`, line 105: `"tech": DEFAULT_KEYWORDS` — tech's domain
     list **is** the full 108-term default vocabulary. Measured sizes
     (counted from the file at fix time): DEFAULT_KEYWORDS **108**; economic
     **22**; geopolitical **24**; social **12**; dark **12**. **scientific and
     adjacent_possible have no DOMAIN_KEYWORDS entry at all** — they fall back
     to the caller set, so their "plane vocabulary" is whatever the caller
     happened to pass (FIR-025: a 56-term, tech-flavoured method list).
   - `_keyword_density`, lines 213–226: novelty = distinct-term hits /
     (0.15 × vocabulary size), capped at 1.0. The score is an **absolute**
     density over whatever vocabulary the plane was scored against; nothing
     in the score is plane-relative.

2. **Track split — `vendor/vara/vara_scan.py`, `stage_dual_track` (line 170)**
   - VaraConfig floors (lines 43–44): `high_novelty_floor = 0.15`,
     `weak_novelty_floor = 0.05` — **single global absolute thresholds**.
   - Lines 182–190: novelty ≥ 0.15 → high track; ≥ 0.05 → weak track;
     otherwise track `below_floor`.
   - Below-floor signals never reach clustering or the Sentinel. At
     disposition stamping (lines 460–462) they are stamped `pruned`.

3. **Sentinel gates — `vendor/vara/vara_sentinel.py`**
   - Lines 18–21: `G1_NOVELTY_THRESHOLD = 0.15`, `G1_WEAK_NOVELTY_FLOOR = 0.05`,
     `G2_ATTENTION_BUDGET = 100`, `G2_WEAK_BUDGET = 50` — again global.
   - `gate_g1` re-applies the same absolute novelty thresholds per track;
     `gate_g2` PRUNEs at budget and DEFERs to the Veil at 90% of budget.

4. **Binding — `vendor/vara/vara_scan.py`**
   - Line 415: output (vault-bound) = Sentinel `passed` + Veil `promoted`.
   - Lines 448–462: disposition stamping — passed → `vault_bound`,
     below-floor / Sentinel-pruned → `pruned` (surfaced in the record by
     `src/lineage.py`, which maps routing states to dispositions).

**Why non-tech planes prune as entire planes:** novelty is an absolute
density, but the vocabularies it is computed against differ ~9× in size and
in kind (tech's 108 terms are the harvester's native vocabulary; two planes
have none). A plane whose text matches its thin vocabulary sparsely produces
a score distribution centred far below a tech item's. Every downstream gate
then applies one global absolute threshold to those incomparable scores, so
a systematic per-plane score offset becomes a systematic per-plane prune:
below-floor at the track split, or weak-track volume crowded out at G2.
FIR-025's payload (bound 135/135 tech, six planes at 0, uniformly pruned) is
exactly this signature. The instrument compounded it: `routing` in the
report carried only global counts, so the collapse did not appear in the
payload at all.

## 2. The fix — per-plane bind floor (chosen approach)

**Approach chosen: per-plane bind floor guarantee**, over within-plane
percentile normalization. Rationale: the Sentinel gates are stateless
per-signal functions (`gate_g1` sees one signal), so percentile
normalization would require rewriting the meaning of `novelty_score`
everywhere it is consumed (Sentinel, `vara_query_signals` min-novelty
filter, FIR rendering, entity first-seen boost). The existing code shape
already carries floors as VaraConfig fields and already routes
weak-but-coherent signals through a softened track — a bounded,
operator-set floor guarantee is the smallest principled change that fits.
It triggers **only** for a plane that harvested coherent signals but placed
**zero** in either track, so any scan whose planes place normally —
including tech-only scans and every pre-existing test — behaves exactly as
before.

**Changes:**

- `vendor/vara/vara_scan.py`
  - `VaraConfig.plane_bind_floor: int = 5` (line 49), included in
    `compute_hash` (line 73). `0` disables the guarantee. Exposed to MCP
    callers via the config passthrough in `src/tools.py` (line 93).
  - `stage_dual_track` (rescue block, lines ~193–235): after the absolute
    split, for each plane with signals but no tracked signal, take its
    top-`plane_bind_floor` **coherent** signals (novelty > 0 and non-empty
    title or content), sorted by novelty descending; move them from
    below-floor to the weak track and stamp `plane_bind_floor: True`.
  - `VaraScanReport.instrument` field (line 111) + `_build_instrument`
    (line 288), assembled at line 476 and attached at line 499 (§3 below).
- `vendor/vara/vara_sentinel.py`
  - `gate_g1` (line 70): a `plane_bind_floor`-stamped signal PASSes G1.
    The empty-content BLOCK still fires first — the guarantee never binds
    an incoherent signal.
  - `gate_g2` (line 84): a stamped signal PASSes G2 (no PRUNE, no DEFER).
    The guarantee is bounded by construction (≤ floor × active planes),
    so it cannot itself exhaust the attention budget; letting other
    planes' volume prune it would void the guarantee.
- `src/tools.py` — `plane_bind_floor` added to the VaraConfig passthrough
  keys so scan callers can set/disable it per scan.

Behaviour preserved: absolute floors, thresholds, budgets, track semantics,
dispositions, and all existing payload fields are unchanged. A stamped
signal still flows through clustering, Sentinel (all three gates logged),
and disposition stamping like any other weak-track signal; it is visible
per-signal in the payload as `plane_bind_floor: true`.

## 3. New payload fields (Fault 3 — additive only)

`run_vara_scan` results now carry a top-level **`instrument`** object
(flows through `asdict(report)` in `src/tools.py` unchanged):

```json
"instrument": {
  "planes": {
    "<plane>": {
      "harvested": 0,        // signals the plane produced
      "kept": 0,             // entered a track (high/weak; not below-floor)
      "bound": 0,            // disposition vault_bound or promoted
      "pruned": 0,
      "blocked": 0,
      "veil_held": 0,
      "plane_bind_floor": 0  // of the kept, how many the floor admitted
    }
  },
  "vocabulary": {
    "caller_keywords": 0,                 // len(config.keywords)
    "default_keywords": 108,
    "domain_keywords": {"<plane>": 0},    // per active plane; 0 = no entry
    "per_plane_effective": {"<plane>": 0},// |caller ∪ plane domain| per plane
    "effective_vocabulary_size": 0,       // union across active planes
    "effective_vocabulary_hash": "<sha256 hex>"
  }
}
```

The hash is the SHA-256 of the sorted, lowercased union of every term in
force across the scan's active planes (caller set — with the harvester's
own DEFAULT_KEYWORDS fallback when the caller list is empty — unioned with
each plane's domain list), newline-joined. A later cycle compares hashes
before comparing results: same hash, comparable instrument.

## 4. Tests

Runner: the workspace venv matching this repo's own test provenance
(CPython 3.12.3, pytest 9.1.1), `python -m pytest tests/ -q`.

- **Before:** 54 passed, **1 failed** — `tests/test_native_mcp.py::
  test_native_mcp_endpoint_is_mounted` (AttributeError:
  `'_NormalizeMcpPath' object has no attribute 'routes'`). Pre-existing,
  in the API mounting layer, unrelated to the scan pipeline.
- **After:** **59 passed, 1 failed** — the same single pre-existing
  failure. No regressions.

New file `tests/test_plane_binding_floor.py` (5 tests, canned-harvest
monkeypatch style matching `test_vendor_pipeline_lineage.py`, no network):

1. `test_nontech_plane_binds_via_floor` — tech (0.50/0.60) + economic (0.20)
   place normally; all four social signals sit below the weak floor
   (0.01–0.04) yet **bind** via the floor, stamped, with disposition
   `vault_bound`; instrument counts assert social harvested/kept/bound = 4
   and tech/economic carry no floor admissions.
2. `test_instrument_reports_effective_vocabulary` — caller/default/domain
   counts match the live `vara_harvesters` tables; tech's effective set
   exceeds social's; hash is 64-hex.
3. `test_floor_only_rescues_unplaced_planes` — a plane with a weak-track
   placement gets **no** rescue (its below-floor signal stays below);
   an unplaced plane's signals are rescued and stamped.
4. `test_floor_cap_and_coherence_gate` — floor caps at N=3 by novelty;
   the highest-novelty but empty (title+content) signal is **not** rescued.
5. `test_floor_disabled_binds_nothing_below_floor` — `plane_bind_floor=0`
   restores the FIR-025 behaviour exactly (social harvested 4, bound 0,
   pruned 4), proving the guarantee — not some side effect — does the work.

## 5. Residual risks / not verified

- **Trigger is zero-track, not zero-bound.** A plane that places some
  weak-track signals but still binds zero (e.g. all deferred at G2 and
  held by the Veil) is **not** rescued by this version — binding is only
  known after the Veil runs, too late to rescue within the same pass
  without restructuring the pipeline. The new per-plane `instrument`
  counts make that case visible in the payload for the first time; if
  FIR-026 shows it, the floor trigger can be revisited with evidence.
- **Non-dual-track path unchanged.** With `enable_dual_track=False`,
  signals go straight to the high-track Sentinel (G1 at 0.15) and the
  floor does not apply. The FIR pipeline runs dual-track; noted for
  completeness.
- **G2 accounting:** stamped signals still increment the weak-track G2
  counter in `run_sentinel` (they consume attention, they just can't be
  pruned/deferred by it). With the default floor of 5 and 9 planes, the
  worst case is 45 guaranteed weak-track admissions against a weak budget
  of 50 — bounded, but an operator scanning many planes with a large
  floor should treat floor × planes as committed budget.
- **Scientific / adjacent_possible vocabulary gap is reported, not
  repaired.** These planes still have no DOMAIN_KEYWORDS; the payload now
  shows `domain_keywords: 0` and their effective set = the caller set.
  Authoring domain vocabularies for them is an operator content decision,
  out of scope for this fix.
- **Not verified against the live server** (by instruction): no deploy, no
  live scan. The fix is verified only in this copy's test suite. The
  payload change is additive, but downstream consumers that validate the
  report against a strict schema (none found in this repo's tests) should
  be checked at deploy time. FIR-026's W26 watch (entity_filter return +
  plane binding) remains the live verification.
- The pre-existing `test_native_mcp_endpoint_is_mounted` failure predates
  this change and is untouched by it.

---

## Addendum — 2026-11-06 (later): domain keyword lists authored

At the operator's ruling ("fix the keyword problem"), `DOMAIN_KEYWORDS` in
`vendor/vara/vara_harvesters.py` gained the two missing entries, fitted to
each plane's actual RSS feeds:

- `scientific` (24 terms): arXiv cs.AI/cs.LG/cs.CL/cs.CR/econ paper
  register — preprint, transformer, attention mechanism, diffusion model,
  reinforcement learning, neural network, zero-shot, few-shot, ablation,
  benchmark dataset, differential privacy, cryptography, causal inference,
  econometrics, theorem, convergence, generalization, robustness,
  embedding, tokenizer, autoregressive, probabilistic, language model,
  statistical significance.
- `adjacent_possible` (22 terms): LessWrong / EA Forum / Shtetl-Optimized
  frontier-discourse register — AGI, superintelligence, forecasting,
  prediction market, effective altruism, rationality, Bayesian, decision
  theory, scaling laws, recursive self-improvement, longtermism,
  biosecurity, AI governance, red-teaming, takeoff, frontier model,
  compute governance, intelligence explosion, epistemics, world model,
  agent foundations, crucial consideration.

New tests in `tests/test_domain_keywords.py` (3): every active plane has
a harvester AND a domain list of >= 10 terms; scientific domain terms
move a scientific text's density from 0; adjacent_possible terms do the
same for frontier-discourse text. Suite after addendum: **62 passed,
1 failed** — the same pre-existing unrelated failure
(`test_native_mcp_endpoint_is_mounted`). The `instrument` payload block
now reports domain_keywords 24 / 22 for these planes instead of 0.

Still not deployed; rides with the same production redeploy decision.

---

## Transplant onto live main — 2026-11-06 (later)

The fix above was implemented in an extracted snapshot. Live `main` of
`vara-mcp-server` had since moved ahead of that snapshot — HEAD
`1cf9e428ebe` (the Fluid-CPU fail-fast fix), notably `98d130c` "true
entity targeting", which added a strict post-harvest entity-filter
stage the snapshot pipeline does not have. Copying the fixed files over
live would have regressed live features, so the fix was **transplanted
hunk by hunk** onto the live clone
(`~/workspace/mcp-upgrade/repos/vara-mcp-server-live/`), branch
`fix/plane-binding-instrument`, as uncommitted working-tree edits.
Nothing pushed, nothing deployed.

### What differed per file, and how each hunk was adapted

- **`vendor/vara/vara_harvesters.py`** — live's keyword tables were
  rewritten by `98d130c` and do NOT match the snapshot's pre-fix dict:
  DEFAULT_KEYWORDS is 159 terms on live (108 in the snapshot);
  economic 25, geopolitical 24, social 11, dark 13 (snapshot: 22/24/12/12).
  Critically, live **already has a `scientific` entry** (16 terms,
  broad-science register, added by `98d130c`). The snapshot's 24-term
  arXiv-register scientific list was therefore NOT transplanted —
  overwriting it would have regressed a newer deliberate live change,
  and the fix's invariant (every plane carries a real domain list) is
  already satisfied for scientific on live. Only the missing
  **`adjacent_possible` list (22 terms) was added, verbatim** from the
  snapshot, with a comment recording this reasoning. (Live also names
  the density function `_keyword_relevance`, where the snapshot has
  `_keyword_density` — identical formula — and routes its output to
  `relevance_score`, mapped to `novelty_score` at intake by the PR #14
  port fix. Neither needed changes.)
- **`vendor/vara/vara_sentinel.py`** — the touched regions of live's
  file are identical to the snapshot's pre-fix file, so both hunks
  (the `plane_bind_floor` PASS in `gate_g1` after the empty-content
  BLOCK, and the PASS at the top of `gate_g2`) applied **verbatim,
  no adaptation**.
- **`vendor/vara/vara_scan.py`** — the most diverged file. Live adds:
  the `target_entities` config field + hash entry, `stage_drift`,
  `stage_entity_filter`, the canonical clustering adapter, the PR #14
  port fixes, and an `entity_filter` report field. Adaptations:
  (1) `plane_bind_floor: int = 5` placed after `weak_novelty_floor`
  and added to `compute_hash` alongside live's entries;
  (2) the rescue block inserted at the same point in `stage_dual_track`
  (live's split loop is otherwise identical to the snapshot's), with
  the comment's vocabulary figures updated to live's (159-term
  default; 11–25 domain terms per other plane);
  (3) `VaraScanReport.instrument` added next to live's `entity_filter`
  field; (4) `_build_instrument` gained two optional parameters
  (`entity_filter_stats`, `pre_filter_plane_counts`) for the stage
  mapping below, and its `kept` test is `track in ("high", "weak")`
  rather than the snapshot's `track != "below_floor"` — on live an
  untracked signal in the stamped set means entity-dropped, not kept,
  so the snapshot's formulation would have inverted the count;
  (5) the instrument is also attached on the entity-filter
  early-return path (a path that does not exist in the snapshot),
  built from an empty stamped set plus the pre-filter counts, so a
  fully-filtered scan still reports its instrument;
  (6) `run_vara_scan` captures per-plane pre-filter counts immediately
  before `stage_entity_filter` runs. Live's drift stage, clustering
  adapter, disposition stamping, and port fixes are untouched.
- **`src/tools.py`** — live's file carries the entity-targeting block
  (watchlist keyword fallback, per-entity feed generation + SSRF
  validation) and the drift-path retargeting; the only transplant is
  `"plane_bind_floor"` added to live's existing config-passthrough
  tuple. Nothing else touched.
- **Tests** — both files copied from the snapshot.
  `test_plane_binding_floor.py` needed only its header figures updated
  to live's vocabulary sizes; its code is unchanged (the canned-harvest
  monkeypatch pattern targets `vara_scan.harvest_plane` /
  `stage_cluster`, which live exposes identically).
  `test_domain_keywords.py` was adapted: `_keyword_density` →
  `_keyword_relevance` (live's name, same formula), and the scientific
  sample text rewritten in live's scientific vocabulary (live's list
  is broad-science, not the snapshot's arXiv register — the pinned
  invariant is presence and effect, not the specific terms). The
  adjacent_possible test is unchanged, since that list transplanted
  verbatim.

### Entity-filter stage mapping (instrument counts)

Live's pipeline order is: harvest → drift → enrich →
**entity filter** → dual-track split → cluster → Sentinel → Veil.
Signals the entity stage drops never enter the disposition-stamped
set (`all_signals`), so the instrument's per-plane counts map as:

- `harvested` — signals in the post-filter, disposition-stamped set
  (the set the track split and everything downstream actually saw);
- `entity_dropped` — present only when the stage ran: pre-filter
  per-plane count − `harvested`. True intake per plane =
  `harvested + entity_dropped`;
- `kept` — of the post-filter set, signals that entered a track
  (high or weak, floor admissions included);
- `bound` / `pruned` / `blocked` / `veil_held` / `plane_bind_floor` —
  as in the snapshot, from dispositions and the floor stamp;
- the stage's own global stats (`targets`, `pre_filter`, `kept`,
  `dropped`, `per_entity`) are echoed verbatim at
  `instrument.entity_filter`, mirroring the report-level
  `entity_filter` field.

Verified by an ad-hoc interplay check (not committed): a 2-plane
canned scan with `target_entities=["Dell"]` — each plane lost exactly
one signal to the filter (`entity_dropped: 1`, `harvested: 1`), and
the social plane's surviving signal (novelty 0.02, below the weak
floor) was floor-rescued, stamped, and bound. The floor and the
entity filter compose; neither stage hides the other's effect.

### Final test result (live tree)

Runner: `/tmp/vara-test-venv` (CPython 3.12, pytest, repo
`requirements.txt`), `python -m pytest tests/ -q`, in the live clone.

- **Baseline (live main, before transplant): 47 passed, 0 failed** —
  including `test_native_mcp_endpoint_is_mounted`, which passes on
  live (it failed only in the extracted snapshot, in its API mounting
  layer).
- **After transplant: 55 passed, 0 failed** — the original 47 plus
  the 5 plane-binding tests and 3 domain-keyword tests. No
  regressions; the previously-failing-on-snapshot test still passes.

### Residuals

Carried over from the original report: the floor triggers on
zero-track, not zero-bound; the non-dual-track path is unchanged;
floor-admitted signals still consume G2 weak-track count. New on
live: `instrument.planes.<plane>.harvested` is a **post-entity-filter**
count whenever `target_entities` is set — consumers comparing
instrument blocks across cycles must add `entity_dropped` for intake
totals (when the stage did not run, the field is absent and
`harvested` is the full intake, as in the snapshot semantics).
