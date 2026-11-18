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
