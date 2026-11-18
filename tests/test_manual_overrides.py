from ranking.manual_overrides import load_manual_etf_overrides
from ranking.aggregator import AggregatorClient


def test_load_skips_rows_without_aum(tmp_path):
    p = tmp_path / "ov.csv"
    p.write_text(
        "symbol,aum_cr,ter_pct,name,note\n"
        "SBINIFTY50,203017.02,0.04,SBI Nifty 50 ETF,x\n"
        "NEWLAUNCH,,0.29,New Fund,no aum\n"      # no AUM -> skipped
        "pharmaietf,6.48,,ICICI Pharma ETF,y\n"  # lowercase symbol, blank TER
    )
    m = load_manual_etf_overrides(p)
    assert set(m) == {"SBINIFTY50", "PHARMAIETF"}        # NEWLAUNCH dropped, symbol uppercased
    assert m["SBINIFTY50"]["aum_cr"] == 203017.02
    assert m["SBINIFTY50"]["ter_pct"] == 0.04
    assert m["PHARMAIETF"]["ter_pct"] is None             # blank TER -> None


def test_missing_file_returns_empty(tmp_path):
    assert load_manual_etf_overrides(tmp_path / "nope.csv") == {}


def test_manual_source_wins_over_trendlyne_and_tickertape():
    manual = {"SBINIFTY50": {"aum_cr": 203017.02, "ter_pct": 0.04, "name": "SBI Nifty 50 ETF"}}
    # etf_source (Trendlyne) has a different value; manual must win and never hit network.
    etf = {"SBINIFTY50": {"aum_cr": 999.0, "ter_pct": 0.9, "symbol": "SBINIFTY50"}}
    c = AggregatorClient(etf_source=etf, manual_source=manual)
    hit = c.fetch("ETF", "SBINIFTY50", "", "Nifty 50")
    assert hit["source"] == "manual"
    assert hit["aum_cr"] == 203017.02 and hit["ter_pct"] == 0.04


def test_non_override_etf_still_uses_etf_source():
    etf = {"OTHERETF": {"aum_cr": 500.0, "ter_pct": 0.1, "symbol": "OTHERETF"}}
    c = AggregatorClient(etf_source=etf, manual_source={})
    hit = c.fetch("ETF", "OTHERETF", "", "x")
    assert hit["source"] == "trendlyne" and hit["aum_cr"] == 500.0
