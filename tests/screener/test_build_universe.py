import json

import pandas as pd
import pytest

from screener.core.universe import load_universe
from screener.tools.build_universe import (UniverseError, build_records, debt_category,
                                           kite_index_table, resolve_kite)

KITE_CSV = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
    "256265,1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE\n"
    "263433,1002,NIFTY SMLCAP 250,NIFTY SMLCAP 250,0,,0,0,0,EQ,INDICES,NSE\n"
    "300001,1003,NIFTY GS 10YR,NIFTY GS 10YR,0,,0,0,0,EQ,INDICES,NSE\n"
    "999999,1004,NIFTYBEES,NIFTYBEES,0,,0,0,1,EQ,NSE,NSE\n"
)


def frame(rows):
    cols = ["matched_index", "Index", "Category", "Fund", "Type", "aum_cr",
            "rank_aum", "rank_composite", "fund_id", "_cat", "_top"]
    return pd.DataFrame(rows, columns=cols)


def test_kite_table_keeps_nse_indices_only():
    k = kite_index_table(KITE_CSV)
    assert set(k.tradingsymbol) == {"NIFTY 50", "NIFTY SMLCAP 250", "NIFTY GS 10YR"}


def test_resolve_by_name_and_alias():
    k = kite_index_table(KITE_CSV)
    assert resolve_kite("NIFTY 50", "Nifty 50", "equity", k) == ("NIFTY 50", 256265)
    assert resolve_kite("NIFTY SMALLCAP 250", "Nifty Smallcap 250", "equity", k) == ("NIFTY SMLCAP 250", 263433)
    assert resolve_kite("NIFTY 10 YR BENCHMARK G-SEC", "Nifty 10 Yr Benchmark G-Sec", "debt", k) == ("NIFTY GS 10YR", 300001)
    assert resolve_kite("NIFTY SDL APR 2027", "Nifty SDL Apr 2027", "debt", k) == (None, None)


def test_debt_categories():
    assert debt_category("NIFTY BHARAT BOND INDEX - APRIL 2030") == "Bharat Bond"
    assert debt_category("NIFTY 1D RATE") == "Liquid / Overnight"
    assert debt_category("NIFTY MIDCAP 150 + 8-13 YR G-SEC (HYBRID)") == "Hybrid"
    assert debt_category("NIFTY 8-13 YR G-SEC") == "G-Sec Benchmark"
    assert debt_category("NIFTY SDL APR 2027") == "Target Maturity"


def test_build_records_names_sources_and_proxy():
    df = frame([
        ["NIFTY 50", "Nifty 50", "Broad Market", "Big ETF", "ETF", 900.0, 1, 1, "BIG", 0, -900],
        ["NIFTY 50", "Nifty 50", "Broad Market", "Small ETF", "ETF", 50.0, 3, 3, "SML", 0, -900],
        ["NIFTY 50", "Nifty 50", "Broad Market", "Some Index Fund", "Index Fund", 300.0, 2, 2, "IF1", 0, -900],
        ["NIFTY SDL APR 2027", "Nifty SDL Apr 2027", "Debt", "SDL Fund", "Index Fund", 80.0, 1, 1, "SDL", 4, -80],
    ])
    fund_rets = pd.DataFrame({"fund_id": ["SDL"], "scheme_code": [12345.0],
                              "first_nav_date": ["2022-01-01"], "returns_note": [None]})
    recs = build_records(df, fund_rets, kite_index_table(KITE_CSV))
    eq, debt = recs
    assert eq["source"] == "kite" and eq["kite_instrument_token"] == 256265
    assert eq["etfs"] == ["Big ETF", "Small ETF"] and eq["index_funds"] == ["Some Index Fund"]
    assert debt["tab"] == "debt" and debt["category"] == "Target Maturity"
    assert debt["source"] == "amfi" and debt["nav_scheme_code"] == 12345
    assert debt["nav_fund_name"] == "SDL Fund"


def test_equity_without_kite_symbol_fails_loudly():
    df = frame([["NIFTY MYSTERY", "Nifty Mystery", "Thematic", "F", "ETF", 10.0, 1, 1, "F", 2, -10]])
    with pytest.raises(UniverseError, match="NIFTY MYSTERY"):
        build_records(df, pd.DataFrame(columns=["fund_id", "scheme_code", "first_nav_date", "returns_note"]),
                      kite_index_table(KITE_CSV))


def test_load_universe_roundtrip(tmp_path):
    rec = {"id": "NIFTY 50", "display_name": "Nifty 50", "tab": "equity", "category": "Broad Market",
           "source": "kite", "kite_symbol": "NIFTY 50", "kite_instrument_token": 256265,
           "nav_scheme_code": None, "nav_fund_name": None, "etfs": ["A"], "index_funds": []}
    p = tmp_path / "u.json"
    p.write_text(json.dumps([rec]))
    (info,) = load_universe(p)
    assert info.etfs == ("A",) and info.index_funds == () and info.kite_instrument_token == 256265
