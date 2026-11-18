# AUM Enrichment + Dual-Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the ~632 mapped passive funds (283 NSE ETFs + 349 canonical index funds) with per-scheme AUM and TER scraped from aggregators, filter at ₹10 cr, and produce two rankings per index (AUM-only, and AUM+TER+liquidity).

**Architecture:** A new `ranking/` package layered on top of the existing `data/06_mapped_funds.csv` output. Pure-logic modules (dedup, rank, output) are unit-tested with fixtures; the network-touching aggregator client is isolated behind an injectable interface so enrichment logic is tested with a fake client, and the real client gets a live smoke test. An orchestrator `run_ranking.py` wires it together and writes `data/07_final_shortlist.xlsx` + a resumable cache `data/08_aum_ter.csv`.

**Tech Stack:** Python 3.13, pandas, requests, openpyxl, pytest 9.

## Global Constraints

- AUM threshold: **₹10 cr** (keep schemes with `aum_cr >= 10`).
- Composite weights: **AUM 0.50 / TER 0.30 / liquidity 0.20** (module-level dict `COMPOSITE_WEIGHTS`).
- Missing TER in composite → drop the 0.30 term and renormalize remaining weights.
- Missing liquidity (all index funds) → drop the 0.20 term and renormalize.
- Unresolved AUM (aggregator match failed) → routed to a separate output, never dropped silently, never filtered as "below threshold".
- ETF universe source = `Source == "NSE_ETF"` rows (keyed by `Symbol`, carry `Traded_Value` as liquidity). Index-fund universe source = `Source == "AMFI"` AND `Scheme_Type == "Index Fund"` rows (keyed by ISIN/name, liquidity = NaN). This split prevents double-counting the same ETF across sources.
- Exclude `Matched_Index` in `{"", "COMMODITY (Gold/Silver)", "INTERNATIONAL INDEX"}` from the universe.
- Canonical index fund = group by `(Scheme_Name, AMC)`, prefer `Plan` containing "Direct" then `Option` containing "Growth"; first row if no such match.
- All new code under `ranking/`; tests under `tests/`. Do not modify `fetch_etf_index_data.py`.

---

### Task 0: Project scaffolding + git

**Files:**
- Create: `ranking/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `requirements.txt`
- Create: `.gitignore`

- [ ] **Step 1: Initialize git and scaffolding**

```bash
cd /Users/ajinkyawagh/Desktop/STARTUP/ETF_Indices
git init
mkdir -p ranking tests
touch ranking/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
pandas>=2.0
requests>=2.31
openpyxl>=3.1
pytest>=8.0
```

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: Verify pytest collects nothing yet (no error)**

Run: `python3 -m pytest -q`
Expected: `no tests ran` (exit code 5 is fine), no import errors.

- [ ] **Step 5: Commit**

```bash
git add ranking/ tests/ requirements.txt .gitignore docs/
git commit -m "chore: scaffold ranking package and git repo"
```

---

### Task 1: Build canonical universe (`ranking/dedup.py`)

**Files:**
- Create: `ranking/dedup.py`
- Test: `tests/test_dedup.py`

**Interfaces:**
- Consumes: a DataFrame with the columns of `data/06_mapped_funds.csv`
  (`Scheme_Name, ISIN, Plan, Option, AMC, Scheme_Type, Matched_Index, Source, Symbol, Traded_Value, NAV`).
- Produces: `build_universe(df: pd.DataFrame) -> pd.DataFrame` with exactly these columns:
  `fund_id (str), name (str), kind (str in {"ETF","IndexFund"}), isin (str), symbol (str), amc (str), matched_index (str), liquidity (float), nav (float)`.
  `fund_id` = `symbol` for ETFs, `f"{amc}|{name}"` for index funds. Index-fund `liquidity` is `NaN`, `symbol` is `""`. ETF `isin` is `""`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dedup.py
import numpy as np
import pandas as pd
from ranking.dedup import build_universe

def _mapped_df():
    rows = [
        # index fund: 4 plan/option variants of one scheme -> 1 canonical (Direct+Growth)
        {"Scheme_Name":"NAVI NIFTY50 INDEX FUND","ISIN":"INF1","Plan":"Direct Plan","Option":"IDCW PAYOUT","AMC":"Navi","Scheme_Type":"Index Fund","Matched_Index":"NIFTY 50","Source":"AMFI","Symbol":np.nan,"Traded_Value":np.nan,"NAV":"15.4"},
        {"Scheme_Name":"NAVI NIFTY50 INDEX FUND","ISIN":"INF2","Plan":"Direct Plan","Option":"GROWTH","AMC":"Navi","Scheme_Type":"Index Fund","Matched_Index":"NIFTY 50","Source":"AMFI","Symbol":np.nan,"Traded_Value":np.nan,"NAV":"15.5"},
        {"Scheme_Name":"NAVI NIFTY50 INDEX FUND","ISIN":"INF3","Plan":"Regular Plan","Option":"GROWTH","AMC":"Navi","Scheme_Type":"Index Fund","Matched_Index":"NIFTY 50","Source":"AMFI","Symbol":np.nan,"Traded_Value":np.nan,"NAV":"15.1"},
        {"Scheme_Name":"NAVI NIFTY50 INDEX FUND","ISIN":"INF4","Plan":"Regular Plan","Option":"IDCW PAYOUT","AMC":"Navi","Scheme_Type":"Index Fund","Matched_Index":"NIFTY 50","Source":"AMFI","Symbol":np.nan,"Traded_Value":np.nan,"NAV":"15.0"},
        # ETF from NSE
        {"Scheme_Name":"Nippon Nifty 50 BeES","ISIN":np.nan,"Plan":np.nan,"Option":np.nan,"AMC":np.nan,"Scheme_Type":"ETF (NSE Listed)","Matched_Index":"NIFTY 50","Source":"NSE_ETF","Symbol":"NIFTYBEES","Traded_Value":"6495594512.88","NAV":"161.6"},
        # excluded: commodity
        {"Scheme_Name":"Gold ETF","ISIN":np.nan,"Plan":np.nan,"Option":np.nan,"AMC":np.nan,"Scheme_Type":"ETF (NSE Listed)","Matched_Index":"COMMODITY (Gold/Silver)","Source":"NSE_ETF","Symbol":"GOLDBEES","Traded_Value":"100","NAV":"50"},
        # excluded: unmapped
        {"Scheme_Name":"Mystery Fund","ISIN":"INF9","Plan":"Direct Plan","Option":"GROWTH","AMC":"X","Scheme_Type":"Index Fund","Matched_Index":"","Source":"AMFI","Symbol":np.nan,"Traded_Value":np.nan,"NAV":"10"},
        # excluded: AMFI equity ETF row (ETFs come only from NSE source)
        {"Scheme_Name":"Some ETF via AMFI","ISIN":"INF8","Plan":np.nan,"Option":np.nan,"AMC":"Y","Scheme_Type":"Equity ETF","Matched_Index":"NIFTY 50","Source":"AMFI","Symbol":np.nan,"Traded_Value":np.nan,"NAV":"10"},
    ]
    return pd.DataFrame(rows)

def test_collapses_plan_variants_to_direct_growth():
    u = build_universe(_mapped_df())
    navi = u[u["name"]=="NAVI NIFTY50 INDEX FUND"]
    assert len(navi) == 1
    assert navi.iloc[0]["isin"] == "INF2"            # Direct + Growth picked
    assert navi.iloc[0]["kind"] == "IndexFund"
    assert navi.iloc[0]["fund_id"] == "Navi|NAVI NIFTY50 INDEX FUND"
    assert np.isnan(navi.iloc[0]["liquidity"])

def test_etf_from_nse_with_liquidity():
    u = build_universe(_mapped_df())
    etf = u[u["symbol"]=="NIFTYBEES"]
    assert len(etf) == 1
    assert etf.iloc[0]["kind"] == "ETF"
    assert etf.iloc[0]["fund_id"] == "NIFTYBEES"
    assert abs(etf.iloc[0]["liquidity"] - 6495594512.88) < 1

def test_excludes_commodity_unmapped_and_amfi_etf():
    u = build_universe(_mapped_df())
    names = set(u["name"])
    assert "Gold ETF" not in names
    assert "Mystery Fund" not in names
    assert "Some ETF via AMFI" not in names        # AMFI ETF rows excluded
    # only 2 funds survive: 1 index fund + 1 ETF
    assert len(u) == 2

def test_output_columns_exact():
    u = build_universe(_mapped_df())
    assert list(u.columns) == ["fund_id","name","kind","isin","symbol","amc","matched_index","liquidity","nav"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ranking.dedup'`

- [ ] **Step 3: Write the implementation**

```python
# ranking/dedup.py
"""Build the canonical passive-fund universe from 06_mapped_funds."""
import numpy as np
import pandas as pd

EXCLUDED_INDICES = {"", "COMMODITY (Gold/Silver)", "INTERNATIONAL INDEX"}
OUT_COLUMNS = ["fund_id","name","kind","isin","symbol","amc","matched_index","liquidity","nav"]


def _to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def _pick_canonical(group: pd.DataFrame) -> pd.Series:
    """Prefer Direct plan, then Growth option; fall back to first row."""
    plan = group["Plan"].fillna("")
    direct = group[plan.str.contains("Direct", case=False)]
    use = direct if len(direct) else group
    opt = use["Option"].fillna("")
    growth = use[opt.str.contains("Growth", case=False)]
    return (growth if len(growth) else use).iloc[0]


def build_universe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Matched_Index"] = df["Matched_Index"].fillna("")
    df = df[~df["Matched_Index"].isin(EXCLUDED_INDICES)]

    # --- ETFs: NSE-listed rows only ---
    nse = df[df["Source"] == "NSE_ETF"]
    etf_rows = []
    for _, r in nse.iterrows():
        etf_rows.append({
            "fund_id": str(r["Symbol"]),
            "name": str(r["Scheme_Name"]),
            "kind": "ETF",
            "isin": "",
            "symbol": str(r["Symbol"]),
            "amc": "",
            "matched_index": r["Matched_Index"],
            "liquidity": _to_float(r.get("Traded_Value")),
            "nav": _to_float(r.get("NAV")),
        })

    # --- Index funds: AMFI Index Fund rows, collapsed to one canonical per (name, AMC) ---
    idx = df[(df["Source"] == "AMFI") & (df["Scheme_Type"] == "Index Fund")].copy()
    if_rows = []
    if len(idx):
        for (name, amc), g in idx.groupby(["Scheme_Name", "AMC"], dropna=False):
            r = _pick_canonical(g)
            if_rows.append({
                "fund_id": f"{amc}|{name}",
                "name": str(name),
                "kind": "IndexFund",
                "isin": "" if pd.isna(r.get("ISIN")) else str(r["ISIN"]),
                "symbol": "",
                "amc": str(amc),
                "matched_index": r["Matched_Index"],
                "liquidity": np.nan,
                "nav": _to_float(r.get("NAV")),
            })

    out = pd.DataFrame(etf_rows + if_rows, columns=OUT_COLUMNS)
    return out.reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_dedup.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Smoke against real data**

Run: `python3 -c "import pandas as pd; from ranking.dedup import build_universe; u=build_universe(pd.read_csv('data/06_mapped_funds.csv')); print(len(u), u.kind.value_counts().to_dict())"`
Expected: roughly `632 {'IndexFund': 349, 'ETF': 283}` (exact counts may drift with fresh data).

- [ ] **Step 6: Commit**

```bash
git add ranking/dedup.py tests/test_dedup.py
git commit -m "feat: build canonical passive-fund universe with dedup"
```

---

### Task 2: Aggregator client — pin endpoints + live smoke (`ranking/aggregator.py`)

**Files:**
- Create: `ranking/aggregator.py`
- Test: `tests/test_aggregator_live.py`

**Interfaces:**
- Produces: class `AggregatorClient` with method
  `fetch(kind: str, symbol: str, isin: str, name: str) -> dict | None`.
  Returns `{"aum_cr": float, "ter_pct": float | None, "matched_key": str, "source": str}` on a confident match, else `None`.
  Also standalone helpers used internally: `tickertape_search(text) -> list[dict]`, `groww_search(query) -> list[dict]`.

**Note:** Detail endpoints were not pinned during brainstorming. Step 1 is a discovery spike run against the live APIs; record the working URLs as module constants. The search endpoints are already confirmed working:
`https://api.tickertape.in/search?text=<q>&types=etf,mutualfund` and
`https://groww.in/v1/api/search/v3/query/global/st_query?query=<q>&web=true`.

- [ ] **Step 1: Discovery spike — find the detail/AUM+TER endpoints**

Run these and record which return AUM + expense ratio; write the working URLs into `aggregator.py` constants:

```bash
# Tickertape: search gives sid + marketCap(=AUM for ETF/MF). Try MF detail shapes:
curl -s "https://api.tickertape.in/mutualfunds/detail/<sid>" | head -c 400; echo
curl -s "https://api.tickertape.in/mf/detail/<sid>" | head -c 400; echo
# ETF marketCap is already AUM in cr from search payload — may need no detail call for ETFs.
# Groww: scheme detail for expense ratio / aum:
curl -s "https://groww.in/v1/api/data/mf/web/v3/scheme/<search_id>" | head -c 400; echo
curl -s "https://groww.in/v1/api/stocks_data/v1/accord_points/exchange/NSE/segment/CASH/<symbol>" | head -c 400; echo
```

Record findings as comments + constants (`TT_DETAIL_URL`, `GROWW_DETAIL_URL`) at the top of `aggregator.py`. If a provider's ETF AUM is already present in the search payload (`marketCap`), use that directly and skip its detail call.

- [ ] **Step 2: Write the implementation**

```python
# ranking/aggregator.py
"""Fetch per-scheme AUM (cr) and TER (%) from Tickertape (primary) + Groww (fallback)."""
import time
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
           "Accept": "application/json"}

TT_SEARCH_URL = "https://api.tickertape.in/search"
GROWW_SEARCH_URL = "https://groww.in/v1/api/search/v3/query/global/st_query"
# Detail URLs confirmed in Step 1 discovery spike:
TT_DETAIL_URL = "https://api.tickertape.in/mutualfunds/detail/{sid}"      # update if spike differs
GROWW_DETAIL_URL = "https://groww.in/v1/api/data/mf/web/v3/scheme/{sid}"  # update if spike differs

REQUEST_PAUSE = 0.3
TIMEOUT = 15


def _get(url, params=None, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(0.5 * (attempt + 1))
    return None


def tickertape_search(text):
    data = _get(TT_SEARCH_URL, {"text": text, "types": "etf,mutualfund"})
    if not data or not data.get("success"):
        return []
    return data.get("data", {}).get("stocks", [])


def groww_search(query):
    data = _get(GROWW_SEARCH_URL, {"query": query, "web": "true"})
    if not data or not data.get("data"):
        return []
    return data["data"].get("content", [])


class AggregatorClient:
    """Resolve AUM (cr) + TER (%) for a fund. Returns None when no confident match."""

    def fetch(self, kind, symbol, isin, name):
        query = symbol if (kind == "ETF" and symbol) else name
        if not query:
            return None

        # --- Tickertape primary ---
        hit = self._tickertape(kind, symbol, isin, name, query)
        if hit:
            return hit
        time.sleep(REQUEST_PAUSE)

        # --- Groww fallback ---
        return self._groww(kind, symbol, isin, name, query)

    def _tickertape(self, kind, symbol, isin, name, query):
        results = tickertape_search(query)
        if not results:
            return None
        best = _best_tt_match(results, symbol, name)
        if not best:
            return None
        aum = best.get("marketCap")            # cr, present for etf + mf
        ter = None
        sid = best.get("sid")
        if sid:
            detail = _get(TT_DETAIL_URL.format(sid=sid))
            ter = _extract_tt_ter(detail)       # None if unavailable
            if aum is None:
                aum = _extract_tt_aum(detail)
        if aum is None:
            return None
        return {"aum_cr": float(aum), "ter_pct": ter,
                "matched_key": best.get("ticker") or best.get("sid"), "source": "tickertape"}

    def _groww(self, kind, symbol, isin, name, query):
        results = groww_search(query)
        best = _best_groww_match(results, symbol, isin, name)
        if not best:
            return None
        sid = best.get("search_id")
        detail = _get(GROWW_DETAIL_URL.format(sid=sid)) if sid else None
        aum = _extract_groww_aum(detail)
        ter = _extract_groww_ter(detail)
        if aum is None:
            return None
        return {"aum_cr": float(aum), "ter_pct": ter, "matched_key": sid, "source": "groww"}


# --- matching + extraction helpers (field names finalized in Step 1 spike) ---
def _norm(s):
    return "".join(ch for ch in str(s).upper() if ch.isalnum())

def _best_tt_match(results, symbol, name):
    if symbol:
        for r in results:
            if str(r.get("ticker", "")).upper() == symbol.upper():
                return r
    nn = _norm(name)
    for r in results:
        if _norm(r.get("name")) == nn:
            return r
    return results[0] if results and str(results[0].get("match")) == "EXACT" else None

def _best_groww_match(results, symbol, isin, name):
    for r in results:
        if isin and str(r.get("isin", "")).upper() == isin.upper():
            return r
    if symbol:
        for r in results:
            if str(r.get("nse_scrip_code", "")).upper() == symbol.upper():
                return r
    nn = _norm(name)
    for r in results:
        if _norm(r.get("title")) == nn:
            return r
    return None

def _extract_tt_ter(detail):
    if not detail:
        return None
    d = detail.get("data", detail)
    for k in ("expenseRatio", "expense_ratio", "ter"):
        if isinstance(d, dict) and d.get(k) is not None:
            return float(d[k])
    return None

def _extract_tt_aum(detail):
    if not detail:
        return None
    d = detail.get("data", detail)
    for k in ("aum", "marketCap"):
        if isinstance(d, dict) and d.get(k) is not None:
            return float(d[k])
    return None

def _extract_groww_aum(detail):
    if not detail:
        return None
    d = detail.get("data", detail) if isinstance(detail, dict) else {}
    v = d.get("aum") if isinstance(d, dict) else None
    return float(v) if v is not None else None

def _extract_groww_ter(detail):
    if not detail:
        return None
    d = detail.get("data", detail) if isinstance(detail, dict) else {}
    for k in ("expense_ratio", "expenseRatio"):
        if isinstance(d, dict) and d.get(k) is not None:
            return float(d[k])
    return None
```

> After Step 1, update the `TT_DETAIL_URL`, `GROWW_DETAIL_URL`, and the extraction field names to match what the live APIs actually return. The structure above is the contract; the exact keys are filled from the spike.

- [ ] **Step 3: Write a live smoke test**

```python
# tests/test_aggregator_live.py
import pytest
from ranking.aggregator import AggregatorClient, tickertape_search

pytestmark = pytest.mark.live  # network; run explicitly

def test_tickertape_search_returns_niftybees():
    res = tickertape_search("nippon nifty bees")
    assert any("BEES" in str(r.get("ticker","")).upper() for r in res)

def test_fetch_niftybees_has_plausible_aum():
    hit = AggregatorClient().fetch("ETF", "NIFTYBEES", "", "Nippon India ETF Nifty 50 BeES")
    assert hit is not None
    assert hit["aum_cr"] > 100          # NIFTYBEES AUM is in the thousands of cr
    assert hit["source"] in ("tickertape", "groww")
```

- [ ] **Step 4: Register the `live` marker and run the smoke test**

Add to a new `pytest.ini`:
```ini
[pytest]
markers =
    live: tests that hit real network endpoints
```

Run: `python3 -m pytest tests/test_aggregator_live.py -v -m live`
Expected: PASS. If the AUM assertion fails, revisit the Step 1 constants/field names until a known ETF returns a plausible AUM. Commit `pytest.ini` with this task.

- [ ] **Step 5: Commit**

```bash
git add ranking/aggregator.py tests/test_aggregator_live.py pytest.ini
git commit -m "feat: aggregator client for AUM/TER with live smoke test"
```

---

### Task 3: Enrichment with cache (`ranking/enrich.py`)

**Files:**
- Create: `ranking/enrich.py`
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: universe DataFrame from `build_universe`; an object with
  `.fetch(kind, symbol, isin, name) -> dict | None` (real `AggregatorClient` or a fake).
- Produces: `enrich_universe(df, client, cache_path, refresh=False) -> pd.DataFrame`.
  Adds columns: `aum_cr (float, NaN if unresolved)`, `ter_pct (float, NaN if missing)`,
  `aum_source (str, "" if unresolved)`, `matched_key (str)`, `resolved (bool)`.
  Writes/updates `cache_path` (CSV keyed by `fund_id`) so re-runs skip already-resolved funds.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_enrich.py
import numpy as np
import pandas as pd
from ranking.enrich import enrich_universe

class FakeClient:
    def __init__(self):
        self.calls = []
    def fetch(self, kind, symbol, isin, name):
        self.calls.append(symbol or name)
        if symbol == "NIFTYBEES":
            return {"aum_cr": 5000.0, "ter_pct": 0.04, "matched_key": "NIFTYBEES", "source": "tickertape"}
        if name == "GOOD INDEX FUND":
            return {"aum_cr": 50.0, "ter_pct": None, "matched_key": "gif", "source": "groww"}
        return None  # unresolved

def _universe():
    return pd.DataFrame([
        {"fund_id":"NIFTYBEES","name":"Nippon Nifty 50 BeES","kind":"ETF","isin":"","symbol":"NIFTYBEES","amc":"","matched_index":"NIFTY 50","liquidity":6.5e9,"nav":161.0},
        {"fund_id":"Navi|GOOD INDEX FUND","name":"GOOD INDEX FUND","kind":"IndexFund","isin":"INF2","symbol":"","amc":"Navi","matched_index":"NIFTY 50","liquidity":np.nan,"nav":15.0},
        {"fund_id":"X|UNKNOWN FUND","name":"UNKNOWN FUND","kind":"IndexFund","isin":"INF9","symbol":"","amc":"X","matched_index":"NIFTY 50","liquidity":np.nan,"nav":10.0},
    ])

def test_enriches_resolved_and_marks_unresolved(tmp_path):
    cache = tmp_path/"08.csv"
    out = enrich_universe(_universe(), FakeClient(), cache, refresh=False)
    bees = out[out.fund_id=="NIFTYBEES"].iloc[0]
    assert bees.aum_cr == 5000.0 and bees.ter_pct == 0.04 and bees.resolved == True
    gif = out[out.name=="GOOD INDEX FUND"].iloc[0]
    assert gif.aum_cr == 50.0 and np.isnan(gif.ter_pct) and gif.resolved == True
    unk = out[out.name=="UNKNOWN FUND"].iloc[0]
    assert np.isnan(unk.aum_cr) and unk.resolved == False and unk.aum_source == ""

def test_cache_prevents_refetch(tmp_path):
    cache = tmp_path/"08.csv"
    c1 = FakeClient(); enrich_universe(_universe(), c1, cache)
    c2 = FakeClient(); enrich_universe(_universe(), c2, cache)   # second run
    # resolved funds served from cache; only the unresolved one may be retried
    assert "NIFTYBEES" not in c2.calls
    assert "GOOD INDEX FUND" not in c2.calls

def test_refresh_forces_refetch(tmp_path):
    cache = tmp_path/"08.csv"
    c1 = FakeClient(); enrich_universe(_universe(), c1, cache)
    c2 = FakeClient(); enrich_universe(_universe(), c2, cache, refresh=True)
    assert "NIFTYBEES" in c2.calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_enrich.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ranking.enrich'`

- [ ] **Step 3: Write the implementation**

```python
# ranking/enrich.py
"""Enrich the universe with AUM (cr) + TER (%) via an aggregator client, with a CSV cache."""
import numpy as np
import pandas as pd

CACHE_COLUMNS = ["fund_id", "aum_cr", "ter_pct", "aum_source", "matched_key", "resolved"]


def _load_cache(cache_path):
    try:
        c = pd.read_csv(cache_path)
        return {row["fund_id"]: row for _, row in c.iterrows()}
    except (FileNotFoundError, OSError, pd.errors.EmptyDataError):
        return {}


def enrich_universe(df, client, cache_path, refresh=False):
    df = df.copy().reset_index(drop=True)
    cache = {} if refresh else _load_cache(cache_path)
    records = []

    for _, r in df.iterrows():
        fid = r["fund_id"]
        cached = cache.get(fid)
        if cached is not None and bool(cached.get("resolved")):
            records.append({
                "aum_cr": float(cached["aum_cr"]),
                "ter_pct": float(cached["ter_pct"]) if pd.notna(cached["ter_pct"]) else np.nan,
                "aum_source": str(cached.get("aum_source") or ""),
                "matched_key": str(cached.get("matched_key") or ""),
                "resolved": True,
            })
            continue

        hit = client.fetch(r["kind"], r["symbol"], r["isin"], r["name"])
        if hit:
            ter = hit.get("ter_pct")
            records.append({
                "aum_cr": float(hit["aum_cr"]),
                "ter_pct": float(ter) if ter is not None else np.nan,
                "aum_source": hit.get("source", ""),
                "matched_key": hit.get("matched_key", ""),
                "resolved": True,
            })
        else:
            records.append({"aum_cr": np.nan, "ter_pct": np.nan, "aum_source": "",
                            "matched_key": "", "resolved": False})

    enriched = pd.concat([df, pd.DataFrame(records)], axis=1)
    _write_cache(enriched, cache_path)
    return enriched


def _write_cache(enriched, cache_path):
    out = enriched[["fund_id", "aum_cr", "ter_pct", "aum_source", "matched_key", "resolved"]].copy()
    out.to_csv(cache_path, index=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_enrich.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ranking/enrich.py tests/test_enrich.py
git commit -m "feat: AUM/TER enrichment with resumable CSV cache"
```

---

### Task 4: Filter + dual ranking (`ranking/rank.py`)

**Files:**
- Create: `ranking/rank.py`
- Test: `tests/test_rank.py`

**Interfaces:**
- Consumes: enriched DataFrame (columns from Task 3 plus `matched_index`, `liquidity`).
- Produces:
  - `COMPOSITE_WEIGHTS = {"aum": 0.5, "ter": 0.3, "liq": 0.2}`
  - `AUM_THRESHOLD = 10.0`
  - `split_by_aum(df, threshold=AUM_THRESHOLD) -> (qualifying, unresolved, below)`
  - `rank_by_aum(qualifying) -> df` adds `rank_aum` (int, per `matched_index`, 1 = largest AUM)
  - `rank_composite(qualifying, weights=COMPOSITE_WEIGHTS) -> df` adds `aum_norm, ter_norm, liq_norm, composite_score, rank_composite` (per index)
  - `top_n_per_index(df, n=3, rank_col="rank_aum") -> df`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rank.py
import numpy as np
import pandas as pd
from ranking.rank import (split_by_aum, rank_by_aum, rank_composite,
                          top_n_per_index, COMPOSITE_WEIGHTS)

def _enriched():
    return pd.DataFrame([
        # NIFTY 50: three qualifying ETFs
        {"fund_id":"A","name":"A","matched_index":"NIFTY 50","aum_cr":5000.0,"ter_pct":0.05,"liquidity":900.0,"resolved":True},
        {"fund_id":"B","name":"B","matched_index":"NIFTY 50","aum_cr":1000.0,"ter_pct":0.02,"liquidity":100.0,"resolved":True},
        {"fund_id":"C","name":"C","matched_index":"NIFTY 50","aum_cr":3000.0,"ter_pct":np.nan,"liquidity":500.0,"resolved":True},
        # below threshold
        {"fund_id":"D","name":"D","matched_index":"NIFTY 50","aum_cr":5.0,"ter_pct":0.1,"liquidity":1.0,"resolved":True},
        # unresolved
        {"fund_id":"E","name":"E","matched_index":"NIFTY 50","aum_cr":np.nan,"ter_pct":np.nan,"liquidity":np.nan,"resolved":False},
        # index fund, no liquidity
        {"fund_id":"F","name":"F","matched_index":"NIFTY BANK","aum_cr":200.0,"ter_pct":0.2,"liquidity":np.nan,"resolved":True},
    ])

def test_split_by_aum():
    q, unresolved, below = split_by_aum(_enriched())
    assert set(q.fund_id) == {"A","B","C","F"}
    assert set(unresolved.fund_id) == {"E"}
    assert set(below.fund_id) == {"D"}

def test_split_threshold_boundary_inclusive():
    df = pd.DataFrame([{"fund_id":"X","name":"X","matched_index":"I","aum_cr":10.0,"ter_pct":0.1,"liquidity":1.0,"resolved":True}])
    q, _, below = split_by_aum(df)
    assert set(q.fund_id) == {"X"} and len(below) == 0   # exactly 10 qualifies

def test_rank_by_aum_per_index():
    q, _, _ = split_by_aum(_enriched())
    r = rank_by_aum(q).set_index("fund_id")
    assert r.loc["A","rank_aum"] == 1
    assert r.loc["C","rank_aum"] == 2
    assert r.loc["B","rank_aum"] == 3
    assert r.loc["F","rank_aum"] == 1   # only fund in NIFTY BANK

def test_composite_drops_missing_ter_and_renormalizes():
    q, _, _ = split_by_aum(_enriched())
    r = rank_composite(q).set_index("fund_id")
    # C has no TER -> scored on aum(0.5)+liq(0.2) renormalized to /0.7
    # A: aum_norm=1, liq_norm=1 -> among {A,B,C} aum range [1000,5000], liq [100,900]
    # A should rank 1 in NIFTY 50 (highest aum + highest liq)
    assert r.loc["A","rank_composite"] == 1
    assert 0.0 <= r.loc["C","composite_score"] <= 1.0
    assert not np.isnan(r.loc["C","composite_score"])

def test_composite_single_fund_index_scores_one():
    q, _, _ = split_by_aum(_enriched())
    r = rank_composite(q).set_index("fund_id")
    assert r.loc["F","composite_score"] == 1.0   # alone in its index
    assert r.loc["F","rank_composite"] == 1

def test_top_n_per_index():
    q, _, _ = split_by_aum(_enriched())
    r = rank_by_aum(q)
    top = top_n_per_index(r, n=2, rank_col="rank_aum")
    nifty = top[top.matched_index=="NIFTY 50"]
    assert set(nifty.fund_id) == {"A","C"}   # top 2 by AUM
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_rank.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ranking.rank'`

- [ ] **Step 3: Write the implementation**

```python
# ranking/rank.py
"""Filter at the AUM threshold and produce two per-index rankings."""
import numpy as np
import pandas as pd

AUM_THRESHOLD = 10.0
COMPOSITE_WEIGHTS = {"aum": 0.5, "ter": 0.3, "liq": 0.2}


def split_by_aum(df, threshold=AUM_THRESHOLD):
    df = df.copy()
    resolved = df["resolved"].astype(bool) & df["aum_cr"].notna()
    unresolved = df[~resolved]
    qualifying = df[resolved & (df["aum_cr"] >= threshold)]
    below = df[resolved & (df["aum_cr"] < threshold)]
    return (qualifying.reset_index(drop=True),
            unresolved.reset_index(drop=True),
            below.reset_index(drop=True))


def rank_by_aum(qualifying):
    df = qualifying.copy()
    df["rank_aum"] = (df.groupby("matched_index")["aum_cr"]
                        .rank(method="first", ascending=False).astype(int))
    return df.sort_values(["matched_index", "rank_aum"]).reset_index(drop=True)


def _minmax(series, higher_better=True):
    s = series.astype(float)
    lo, hi = s.min(), s.max()
    if np.isclose(hi, lo):
        return pd.Series(1.0, index=s.index)
    norm = (s - lo) / (hi - lo)
    return norm if higher_better else 1.0 - norm


def _score_group(g, weights):
    g = g.copy()
    g["aum_norm"] = _minmax(g["aum_cr"], higher_better=True)
    # TER: lower better; missing -> NaN norm (term dropped per-row)
    ter_present = g["ter_pct"].notna()
    g["ter_norm"] = np.nan
    if ter_present.any():
        g.loc[ter_present, "ter_norm"] = _minmax(g.loc[ter_present, "ter_pct"], higher_better=False)
    # Liquidity: higher better; missing -> NaN norm (term dropped)
    liq_present = g["liquidity"].notna()
    g["liq_norm"] = np.nan
    if liq_present.any():
        g.loc[liq_present, "liq_norm"] = _minmax(g.loc[liq_present, "liquidity"], higher_better=True)

    def row_score(row):
        terms = [("aum", row["aum_norm"]), ("ter", row["ter_norm"]), ("liq", row["liq_norm"])]
        num = sum(weights[k] * v for k, v in terms if pd.notna(v))
        den = sum(weights[k] for k, v in terms if pd.notna(v))
        return num / den if den > 0 else np.nan

    g["composite_score"] = g.apply(row_score, axis=1)
    g["rank_composite"] = g["composite_score"].rank(method="first", ascending=False).astype(int)
    return g


def rank_composite(qualifying, weights=COMPOSITE_WEIGHTS):
    df = qualifying.copy()
    out = df.groupby("matched_index", group_keys=False).apply(lambda g: _score_group(g, weights))
    return out.sort_values(["matched_index", "rank_composite"]).reset_index(drop=True)


def top_n_per_index(df, n=3, rank_col="rank_aum"):
    return (df[df[rank_col] <= n]
            .sort_values(["matched_index", rank_col])
            .reset_index(drop=True))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rank.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add ranking/rank.py tests/test_rank.py
git commit -m "feat: AUM filter and dual per-index ranking (AUM + composite)"
```

---

### Task 5: Excel output (`ranking/build_output.py`)

**Files:**
- Create: `ranking/build_output.py`
- Test: `tests/test_build_output.py`

**Interfaces:**
- Consumes: `rank_by_aum` output, `rank_composite` output, `unresolved` df, `below` df,
  and optional `df_indices` / `df_benchmarks` (passed through from existing CSVs).
- Produces: `write_shortlist_xlsx(out_path, by_aum, by_composite, top_aum, top_composite, unresolved, below, df_indices=None, df_benchmarks=None, weights=None) -> None`.
  Writes sheets: `Rank by AUM`, `Rank by Composite`, `Top 3 by AUM`, `Top 3 by Composite`, `Unresolved AUM`, `Below 10cr`, `All NSE Indices` (if given), `Benchmark Codes` (if given), `Summary`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_output.py
import pandas as pd
from openpyxl import load_workbook
from ranking.build_output import write_shortlist_xlsx

def _df(**cols):
    return pd.DataFrame(cols)

def test_writes_expected_sheets(tmp_path):
    by_aum = _df(fund_id=["A"], matched_index=["NIFTY 50"], aum_cr=[5000.0], rank_aum=[1])
    by_comp = _df(fund_id=["A"], matched_index=["NIFTY 50"], composite_score=[1.0], rank_composite=[1])
    unresolved = _df(fund_id=["E"], name=["E"], matched_index=["NIFTY 50"])
    below = _df(fund_id=["D"], name=["D"], aum_cr=[5.0])
    out = tmp_path/"07.xlsx"
    write_shortlist_xlsx(out, by_aum, by_comp, by_aum, by_comp, unresolved, below,
                         weights={"aum":0.5,"ter":0.3,"liq":0.2})
    wb = load_workbook(out)
    for s in ["Rank by AUM","Rank by Composite","Top 3 by AUM","Top 3 by Composite",
              "Unresolved AUM","Below 10cr","Summary"]:
        assert s in wb.sheetnames

def test_summary_reports_counts(tmp_path):
    by_aum = _df(fund_id=["A","B"], matched_index=["NIFTY 50","NIFTY 50"], aum_cr=[5000.0,1000.0], rank_aum=[1,2])
    by_comp = by_aum.assign(composite_score=[1.0,0.0], rank_composite=[1,2])
    unresolved = _df(fund_id=["E"], name=["E"], matched_index=["NIFTY 50"])
    below = _df(fund_id=[], name=[], aum_cr=[])
    out = tmp_path/"07.xlsx"
    write_shortlist_xlsx(out, by_aum, by_comp, by_aum, by_comp, unresolved, below)
    wb = load_workbook(out)
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    assert summary["Qualifying funds"] == 2
    assert summary["Unresolved AUM"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_build_output.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ranking.build_output'`

- [ ] **Step 3: Write the implementation**

```python
# ranking/build_output.py
"""Write the final multi-sheet shortlist workbook."""
from datetime import datetime
import pandas as pd


def write_shortlist_xlsx(out_path, by_aum, by_composite, top_aum, top_composite,
                         unresolved, below, df_indices=None, df_benchmarks=None, weights=None):
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        by_aum.to_excel(writer, sheet_name="Rank by AUM", index=False)
        by_composite.to_excel(writer, sheet_name="Rank by Composite", index=False)
        top_aum.to_excel(writer, sheet_name="Top 3 by AUM", index=False)
        top_composite.to_excel(writer, sheet_name="Top 3 by Composite", index=False)
        unresolved.to_excel(writer, sheet_name="Unresolved AUM", index=False)
        below.to_excel(writer, sheet_name="Below 10cr", index=False)
        if df_indices is not None and not df_indices.empty:
            df_indices.to_excel(writer, sheet_name="All NSE Indices", index=False)
        if df_benchmarks is not None and not df_benchmarks.empty:
            df_benchmarks.to_excel(writer, sheet_name="Benchmark Codes", index=False)

        w = weights or {"aum": 0.5, "ter": 0.3, "liq": 0.2}
        stats = {
            "Metric": [
                "Qualifying funds", "Indices with >=1 qualifying fund",
                "Unresolved AUM", "Below 10cr",
                "Composite weights (AUM/TER/liq)", "Generated",
            ],
            "Value": [
                len(by_aum),
                by_aum["matched_index"].nunique() if len(by_aum) else 0,
                len(unresolved), len(below),
                f'{w["aum"]}/{w["ter"]}/{w["liq"]}',
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ],
        }
        pd.DataFrame(stats).to_excel(writer, sheet_name="Summary", index=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_build_output.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add ranking/build_output.py tests/test_build_output.py
git commit -m "feat: multi-sheet shortlist workbook writer"
```

---

### Task 6: Orchestrator (`run_ranking.py`)

**Files:**
- Create: `run_ranking.py`

**Interfaces:**
- Consumes: all `ranking/` modules + existing CSVs in `data/`.
- Produces: an executable script writing `data/07_final_shortlist.xlsx` and `data/08_aum_ter.csv`.
  CLI flags: `--refresh` (ignore cache), `--limit N` (enrich only first N funds, for a quick trial).

- [ ] **Step 1: Write the implementation**

```python
# run_ranking.py
#!/usr/bin/env python3
"""Enrich mapped passive funds with AUM/TER and build the dual-ranked shortlist.

Usage:
  python3 run_ranking.py                # full run (uses cache if present)
  python3 run_ranking.py --refresh      # ignore cache, re-scrape everything
  python3 run_ranking.py --limit 25     # trial run on first 25 funds
"""
import argparse
import logging
from pathlib import Path

import pandas as pd

from ranking.dedup import build_universe
from ranking.enrich import enrich_universe
from ranking.aggregator import AggregatorClient
from ranking.rank import (split_by_aum, rank_by_aum, rank_composite,
                          top_n_per_index, COMPOSITE_WEIGHTS)
from ranking.build_output import write_shortlist_xlsx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DATA = Path(__file__).parent / "data"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    mapped = pd.read_csv(DATA / "06_mapped_funds.csv")
    universe = build_universe(mapped)
    if args.limit:
        universe = universe.head(args.limit)
    log.info("Universe: %d funds (%s)", len(universe), universe.kind.value_counts().to_dict())

    enriched = enrich_universe(universe, AggregatorClient(),
                               DATA / "08_aum_ter.csv", refresh=args.refresh)
    resolved = int(enriched["resolved"].sum())
    log.info("Resolved AUM for %d/%d funds", resolved, len(enriched))

    qualifying, unresolved, below = split_by_aum(enriched)
    by_aum = rank_by_aum(qualifying)
    by_composite = rank_composite(qualifying)
    top_aum = top_n_per_index(by_aum, n=3, rank_col="rank_aum")
    top_composite = top_n_per_index(by_composite, n=3, rank_col="rank_composite")

    df_indices = _try_read(DATA / "01_nse_indices.csv")
    df_benchmarks = _try_read(DATA / "04_benchmark_codes.csv")

    out = DATA / "07_final_shortlist.xlsx"
    write_shortlist_xlsx(out, by_aum, by_composite, top_aum, top_composite,
                         unresolved, below, df_indices, df_benchmarks,
                         weights=COMPOSITE_WEIGHTS)
    log.info("Wrote %s  (qualifying=%d, unresolved=%d, below=%d)",
             out, len(qualifying), len(unresolved), len(below))


def _try_read(path):
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, OSError):
        return None


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Trial run on a small slice (real network)**

Run: `python3 run_ranking.py --limit 15`
Expected: logs "Universe: 15 funds", "Resolved AUM for K/15", and "Wrote .../07_final_shortlist.xlsx". Open the workbook and confirm `Rank by AUM` has rows and `Summary` shows sane counts. If resolved count is 0, revisit Task 2 endpoint constants.

- [ ] **Step 3: Full run**

Run: `python3 run_ranking.py`
Expected: completes over ~632 funds (a few minutes at 0.3s/call), writes the workbook and `data/08_aum_ter.csv`. Note the resolved/unresolved split from the log.

- [ ] **Step 4: Commit (including the generated cache for reproducibility)**

```bash
git add run_ranking.py data/08_aum_ter.csv
git commit -m "feat: orchestrator producing dual-ranked shortlist workbook"
```

---

### Task 7: Full regression run

**Files:** none (verification task)

- [ ] **Step 1: Run the whole unit suite (excluding live)**

Run: `python3 -m pytest -q -m "not live"`
Expected: all dedup/enrich/rank/output tests PASS.

- [ ] **Step 2: Run the live smoke test**

Run: `python3 -m pytest -q -m live`
Expected: PASS (confirms aggregator still reachable).

- [ ] **Step 3: Sanity-check the output coverage**

Run:
```bash
python3 -c "import pandas as pd; x=pd.read_excel('data/07_final_shortlist.xlsx', sheet_name='Summary'); print(x.to_string(index=False))"
```
Expected: `Qualifying funds` is a large fraction of ~632; `Unresolved AUM` is a minority. If unresolved dominates, the aggregator matching in Task 2 needs tuning (log unresolved names and inspect a few in the aggregator search by hand).

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "test: full regression + output coverage check"
```

---

## Self-Review

**Spec coverage:**
- AUM source (Tickertape primary, Groww fallback) → Task 2. ✓
- Universe = ETFs + index funds, de-duplicated → Task 1 (Global Constraints encode the ETF=NSE / IndexFund=AMFI split that resolves the spec's cross-source dup concern). ✓
- ₹10 cr filter, boundary inclusive → Task 4 (`test_split_threshold_boundary_inclusive`). ✓
- Ranking A (AUM) → Task 4 `rank_by_aum`. ✓
- Ranking B (composite 50/30/20, missing-TER renormalize, missing-liq renormalize, single-fund guard) → Task 4 `rank_composite`. ✓
- Unresolved AUM to its own sheet, not dropped → Tasks 4 (`split_by_aum`) + 5 (`Unresolved AUM`). ✓
- Caching / resumable, `--refresh` → Task 3 + Task 6. ✓
- Output workbook sheets → Task 5. ✓
- Open spec tasks (pin detail endpoints, confirm marketCap unit) → Task 2 Step 1 spike. ✓

**Placeholder scan:** The only intentionally-deferred values are the aggregator detail-endpoint URLs and JSON field names in Task 2, which the Step 1 discovery spike pins against the live API before the client is used; the extraction helpers already encode the fallback key candidates. No "TODO/handle edge cases/similar to Task N" placeholders elsewhere.

**Type consistency:** `build_universe` output columns match `enrich_universe` inputs; enriched columns (`aum_cr, ter_pct, aum_source, matched_key, resolved`) match `split_by_aum`/`rank_*`/`build_output` consumers; `rank_col` names (`rank_aum`, `rank_composite`) consistent across Task 4 and Task 6; `COMPOSITE_WEIGHTS` keys (`aum/ter/liq`) consistent across `rank.py`, `build_output.py`, and `run_ranking.py`.
