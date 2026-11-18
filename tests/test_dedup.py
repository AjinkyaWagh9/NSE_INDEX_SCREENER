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


def test_index_provider_classification():
    from ranking.dedup import index_provider
    assert index_provider("NIFTY 50") == "NSE"
    assert index_provider("S&P BSE SENSEX") == "BSE"
    assert index_provider("BSE INDIA DEFENCE") == "BSE"
    assert index_provider("NASDAQ 100") == "International"
    assert index_provider("MSCI INDEX") == "International"
    assert index_provider("S&P 500") == "International"
    assert index_provider("CRISIL 10 YEAR GILT") == "CRISIL"


def test_exclude_providers_drops_intl_and_crisil():
    rows = [
        {"Scheme_Name":"X Nifty 50 ETF","ISIN":None,"Plan":None,"Option":None,"AMC":None,"Scheme_Type":"ETF (NSE Listed)","Matched_Index":"NIFTY 50","Source":"NSE_ETF","Symbol":"XN50","Traded_Value":"1","NAV":"1"},
        {"Scheme_Name":"Y Sensex ETF","ISIN":None,"Plan":None,"Option":None,"AMC":None,"Scheme_Type":"ETF (NSE Listed)","Matched_Index":"S&P BSE SENSEX","Source":"NSE_ETF","Symbol":"YSX","Traded_Value":"1","NAV":"1"},
        {"Scheme_Name":"Z Nasdaq ETF","ISIN":None,"Plan":None,"Option":None,"AMC":None,"Scheme_Type":"ETF (NSE Listed)","Matched_Index":"NASDAQ 100","Source":"NSE_ETF","Symbol":"ZNQ","Traded_Value":"1","NAV":"1"},
        {"Scheme_Name":"W Gilt ETF","ISIN":None,"Plan":None,"Option":None,"AMC":None,"Scheme_Type":"ETF (NSE Listed)","Matched_Index":"CRISIL 10 YEAR GILT","Source":"NSE_ETF","Symbol":"WGL","Traded_Value":"1","NAV":"1"},
    ]
    u = build_universe(pd.DataFrame(rows), exclude_providers={"International", "CRISIL"})
    kept = set(u["matched_index"])
    assert kept == {"NIFTY 50", "S&P BSE SENSEX"}   # intl + CRISIL dropped
