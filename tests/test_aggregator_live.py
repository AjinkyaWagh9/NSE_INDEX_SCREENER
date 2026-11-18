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
