import json
from pathlib import Path

from ranking.trendlyne import (rows_to_records, build_etf_map, fetch_etf_rows,
                               load_etf_source)

FIXTURE = Path(__file__).parent / "fixtures" / "trendlyne_etf_page.json"


def _fixture_rows():
    return json.load(open(FIXTURE))["body"]["tableData"]


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _fake_getter_factory(pages):
    """Return a getter that serves `pages` (list of body dicts) by pageNumber."""
    def getter(url, params=None, headers=None, timeout=None):
        return FakeResp({"body": pages[params["pageNumber"] - 1]})
    return getter


def test_rows_to_records_converts_aum_to_crore_and_reads_ter():
    recs = rows_to_records(_fixture_rows())
    gold = next(r for r in recs if r["symbol"] == "GOLDADD")
    # raw AUM 2.78e10 rupees -> ~2785.6 crore
    assert abs(gold["aum_cr"] - 2785.6) < 1.0
    assert gold["ter_pct"] == 0.45
    assert gold["isin"] == "INF740KA1ZP2"
    assert gold["name"] == "DSP Gold ETF"


def test_build_etf_map_keys_by_symbol_and_isin():
    m = build_etf_map(rows_to_records(_fixture_rows()))
    assert "GOLDADD" in m
    assert "INF740KA1ZP2" in m          # also keyed by ISIN
    assert m["GOLDADD"] is m["INF740KA1ZP2"]


def test_fetch_etf_rows_paginates_until_isNextPage_false():
    page1 = {"tableData": [["A", "SYMA"] + [0] * 25], "isNextPage": True}
    page2 = {"tableData": [["B", "SYMB"] + [0] * 25], "isNextPage": False}
    rows = fetch_etf_rows(getter=_fake_getter_factory([page1, page2]))
    assert len(rows) == 2
    assert rows[0][1] == "SYMA" and rows[1][1] == "SYMB"


def test_rows_to_records_skips_short_rows_and_null_aum():
    good = ["Full ETF", "FULLSYM", "x", 0, 0, "INF1", 0, 0, 0, 0, 0, 0, 0,
            1e9, 0, 0, 0, 100, "High", 0.3, None]   # 21 cols, AUM present
    short = ["Truncated", "SHORTSYM", "x"]            # fewer than 21 cols -> skipped
    null_aum = ["No AUM", "NOAUM", "x", 0, 0, "INF2", 0, 0, 0, 0, 0, 0, 0,
                None, 0, 0, 0, 0, "Low", 0.5, None]  # AUM None -> aum_cr None
    recs = rows_to_records([good, short, null_aum])
    syms = {r["symbol"]: r for r in recs}
    assert "SHORTSYM" not in syms                     # short row dropped
    assert syms["FULLSYM"]["aum_cr"] == 100.0         # 1e9 / 1e7
    assert syms["NOAUM"]["aum_cr"] is None            # not coerced to 0


def test_fetch_etf_rows_degrades_on_network_error():
    import requests as _rq

    def boom(*a, **k):
        raise _rq.RequestException("down")

    assert fetch_etf_rows(getter=boom) == []          # returns [], does not raise


def test_load_etf_source_uses_cache_without_network(tmp_path):
    cache = tmp_path / "tl.csv"
    page = {"body": {"tableData": _fixture_rows(), "isNextPage": False}}
    calls = []

    def getter(url, params=None, headers=None, timeout=None):
        calls.append(params)
        return FakeResp(page)

    m1 = load_etf_source(cache, getter=getter)      # first run fetches
    assert "GOLDADD" in m1 and len(calls) == 1

    def boom(*a, **k):
        raise AssertionError("network should not be called on cache hit")

    m2 = load_etf_source(cache, getter=boom)        # second run from cache
    assert "GOLDADD" in m2
    assert abs(m2["GOLDADD"]["aum_cr"] - m1["GOLDADD"]["aum_cr"]) < 0.01
