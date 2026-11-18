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
