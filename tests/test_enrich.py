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

def test_cache_merge_preserves_fund_ids_not_in_smaller_run(tmp_path):
    cache = tmp_path/"08.csv"
    full = _universe()
    c1 = FakeClient()
    enrich_universe(full, c1, cache, refresh=False)

    # second run with a SMALLER universe (only the first row)
    smaller = full.head(1)
    c2 = FakeClient()
    enrich_universe(smaller, c2, cache, refresh=False)

    on_disk = pd.read_csv(cache)
    fund_ids = set(on_disk["fund_id"])
    # fund_ids resolved/seen in the first (full) run must still be present
    assert "NIFTYBEES" in fund_ids
    assert "Navi|GOOD INDEX FUND" in fund_ids
    assert "X|UNKNOWN FUND" in fund_ids

class EmptySourceClient:
    """Resolves a fund but with empty-string aum_source/matched_key, to exercise
    the CSV round-trip (empty string -> NaN on read -> must not become "nan")."""
    def __init__(self):
        self.calls = []
    def fetch(self, kind, symbol, isin, name):
        self.calls.append(symbol or name)
        return {"aum_cr": 10.0, "ter_pct": 0.1, "matched_key": "", "source": ""}

def _single_fund_universe():
    return pd.DataFrame([
        {"fund_id":"EMPTYSRC","name":"Empty Source Fund","kind":"ETF","isin":"","symbol":"EMPTYSRC","amc":"","matched_index":"NIFTY 50","liquidity":1.0e9,"nav":100.0},
    ])

def test_empty_string_aum_source_roundtrips_as_empty(tmp_path):
    cache = tmp_path/"08.csv"
    c1 = EmptySourceClient()
    enrich_universe(_single_fund_universe(), c1, cache, refresh=False)

    # second run: served from cache (resolved=True), where aum_source/matched_key
    # were persisted as "" and round-tripped through CSV as NaN on read.
    c2 = EmptySourceClient()
    out = enrich_universe(_single_fund_universe(), c2, cache, refresh=False)
    assert "EMPTYSRC" not in c2.calls  # confirms it was served from cache
    row = out[out.fund_id == "EMPTYSRC"].iloc[0]
    assert row.aum_source == ""
    assert row.matched_key == ""
