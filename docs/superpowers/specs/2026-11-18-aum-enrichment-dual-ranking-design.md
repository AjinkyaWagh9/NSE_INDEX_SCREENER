# Design: AUM Enrichment + Dual-Ranking for ETF/Index-Fund Shortlist

**Date:** 2026-11-18
**Status:** Approved (brainstorming)
**Author:** Claude + user

## Problem

The existing pipeline (`fetch_etf_index_data.py`) downloads NSE indices, NSE ETFs,
the AMFI scheme catalog, and benchmark codes, and maps ~2,046 passive products to
97 indices. But it has **no per-scheme AUM data**. The current "ranking" substitutes
`Traded_Value` (an ETF-only liquidity proxy), and the ≥₹10 cr AUM filter described in
`Context.md` is not implemented.

### Key feasibility finding (why this design is shaped as it is)

Per-scheme AUM is **not** available as a clean free download from AMFI:

- `portal.amfiindia.com/rssNAV.aspx?fwise=y` works but is **AMC-level only** (57 fund
  houses, one total AAUM each).
- AMFI's quarterly disclosure is **AMC × scheme-category** level, not per individual
  scheme.

Therefore per-scheme AUM must come from a **third-party aggregator**. Probes confirmed:

- **Tickertape** (`api.tickertape.in/search?text=...&types=mutualfund`) returns
  `marketCap` ≈ AUM inline (e.g. BANKBEES = ₹5,314 cr), plus `sid`, `slug`, ISIN-able.
- **Groww** (`groww.in/v1/api/search/v3/query/global/st_query?query=...`) returns ISIN,
  `entity_type` (ETF/…), `search_id`, exchange scrip codes.

Exact **detail** endpoint paths (for TER/expense ratio) were not pinned during
brainstorming and are the first implementation task.

## Decisions (locked)

| Decision | Choice |
|---|---|
| AUM source | Scrape aggregator — **Tickertape primary, Groww fallback** |
| Universe | **ETFs + index funds** (all passive products) |
| Rankings | **Two separate**: (A) AUM-only, (B) AUM + TER + liquidity |
| Composite weights | **AUM 0.50 / TER 0.30 / liquidity 0.20** (config constant) |
| Missing TER in Ranking B | Rank on **AUM + liquidity only**, renormalize those weights |
| Missing AUM | Move scheme to a separate **"Unresolved AUM"** sheet (not dropped) |
| Filter | Drop schemes with **AUM < ₹10 cr** |
| Shortlist | **Top 3 per index**, both rankings |

## Architecture

Existing Steps 1–6 of `fetch_etf_index_data.py` are **unchanged**. A new enrichment +
ranking layer is added on top of `data/06_mapped_funds.csv`. Implemented as new,
independently testable modules (not inlined into the existing monolith step functions).

### Component 1 — Scheme de-duplication
`06_mapped_funds.csv` has 2,372 rows that are **plan/option variants**
(Direct/Regular × Growth/IDCW) of far fewer real schemes.

- Collapse to **one canonical scheme per fund**, preferring **Direct Plan + Growth**.
- Canonical identity derived from a normalized scheme name (plan/option tokens stripped)
  or a stable base code; carry ISIN and NSE symbol as join keys.
- Expected: ~2,000 rows → ~800–1,000 real lookups.
- **What it does:** input mapped-funds DataFrame → output one-row-per-scheme DataFrame
  with join keys. **Depends on:** nothing external. Testable with fixture rows.

### Component 2 — AUM/TER enrichment module
For each canonical scheme, fetch **AUM (₹ cr)** and **TER (%)**.

- **Matching key priority:** ISIN → NSE symbol (ETFs) → normalized name.
- **Primary: Tickertape**; **fallback: Groww** when Tickertape has no confident match.
- Record `aum_source`, `matched_key`, and `match_confidence` per scheme so coverage is
  auditable.
- **Liquidity:** reuse `Traded_Value` already pulled from NSE (ETFs only; index funds N/A).
- **Caching:** write/read `data/08_aum_ter.csv`. Re-runs fetch only cache misses.
- **Politeness:** rate-limit (~0.3 s/call), retry with backoff, timeout per call.
- **What it does:** canonical schemes → schemes + {aum_cr, ter_pct, liquidity, source,
  confidence}. **Depends on:** Tickertape/Groww HTTP, local cache. Network mocked in tests.

### Component 3 — Filter
- Schemes with resolved `aum_cr >= 10` proceed.
- Schemes with **unresolved AUM** (no confident match) → "Unresolved AUM" output,
  excluded from ranking but visible.
- Schemes with resolved `aum_cr < 10` are dropped from the shortlist.

### Component 4 — Dual ranking (per index)
For each mapped index, over its qualifying funds:

- **Ranking A — AUM only:** sort by `aum_cr` desc.
- **Ranking B — composite:** min-max normalize **within the index**:
  - `aum_norm` (higher better), `ter_norm` (lower better), `liq_norm` (higher better).
  - `score = 0.5*aum_norm + 0.3*ter_norm + 0.2*liq_norm`.
  - **Missing TER:** drop the 0.3 term, renormalize remaining weights to sum 1.
  - **Missing liquidity** (index funds): drop the 0.2 term, renormalize.
  - Single-fund index: normalized value defined as 1.0 (avoid divide-by-zero).
- Weights are a module-level config dict for easy tuning.
- **What it does:** filtered funds → per-index ranked tables (A and B). **Depends on:**
  only the enriched DataFrame. Pure/deterministic → unit-testable.

### Component 5 — Output (`data/07_final_shortlist.xlsx`, reworked)
Sheets:
1. **Rank by AUM** — all qualifying funds, per index, AUM-sorted.
2. **Rank by Composite** — same funds, composite-sorted, component scores shown.
3. **Top 3 per Index** — shortlist, both rankings side by side.
4. **Unresolved AUM** — schemes whose AUM couldn't be sourced.
5. Retained: **All NSE Indices**, **Benchmark Codes**.
6. **Summary** — counts, coverage %, run timestamp, weights used.

## Data flow

```
06_mapped_funds.csv
  → [dedup] canonical schemes
  → [enrich: Tickertape→Groww, cached to 08_aum_ter.csv] + liquidity (NSE Traded_Value)
  → [filter: AUM>=10cr | unresolved | dropped]
  → [rank A: AUM] + [rank B: composite 50/30/20]
  → 07_final_shortlist.xlsx (6 sheets)
```

## Error handling

- Aggregator HTTP failure on a scheme → mark unresolved, continue (never abort the run).
- Cache is authoritative for already-resolved schemes; a `--refresh` flag forces re-fetch.
- Ambiguous match (multiple candidates) → pick ISIN-exact if present, else highest
  name-similarity above a threshold; below threshold → unresolved (don't guess).
- Normalization guards: single-fund / all-equal-metric groups → norm = 1.0.

## Testing

- **Dedup:** fixture of plan/option variants collapses to expected canonical set.
- **Matching:** ISIN-exact, symbol, and name-fuzzy cases each resolve to the right record;
  below-threshold name → unresolved.
- **Ranking B math:** known inputs → known composite scores; missing-TER and missing-liq
  renormalization; single-fund edge case.
- **Filter:** boundary at exactly 10 cr (≥10 passes).
- **Enrichment:** network mocked; cache hit path does zero HTTP.

## Out of scope (YAGNI)

- Tracking error / tracking difference (hard to source; excluded by decision).
- Per-AMC factsheet parsing.
- Historical AUM trends; only latest snapshot.
- International/commodity funds remain mapped but outside the index-ranking sheets.

## Open implementation tasks (not blockers)

1. Pin Tickertape and Groww **detail** endpoint paths for AUM + TER.
2. Confirm Tickertape `marketCap` unit (cr) across ETFs vs open-ended funds.
3. Decide name-similarity threshold empirically against a sample.
