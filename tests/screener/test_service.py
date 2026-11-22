from datetime import date, datetime, timedelta

import pytest

from screener.core.config import IST
from screener.core.db import BarStore
from screener.core.kite_client import Quote, TokenError
from screener.core.returns import Bar, months_back
from screener.core.service import ScreenerService
from tests.screener.helpers import make_info

TODAY = date(2026, 11, 23)


class FakeClient:
    def __init__(self, fail_tokens=(), token_error=False):
        self.calls, self.fail, self.token_error = [], set(fail_tokens), token_error

    def daily_bars(self, token, start, end):
        self.calls.append((token, start, end))
        if self.token_error:
            raise TokenError("expired")
        if token in self.fail:
            raise RuntimeError("boom")
        return [Bar(end, 100.0, 100.0)]


@pytest.fixture
def svc(tmp_path):
    universe = [make_info("NIFTY 50", token=1), make_info("NIFTY BANK", token=2),
                make_info("NIFTY SDL APR 2027", tab="debt", category="Target Maturity",
                          source="amfi", code=555)]
    return ScreenerService(universe, BarStore(tmp_path / "t.db"))


def test_first_backfill_pulls_five_years(svc):
    c = FakeClient()
    progress = []
    assert svc.backfill_kite(c, TODAY, progress=lambda d, t: progress.append((d, t))) == []
    start = months_back(TODAY, 60) - timedelta(days=7)
    assert c.calls == [(1, start, TODAY - timedelta(days=1)), (2, start, TODAY - timedelta(days=1))]
    assert progress[-1] == (2, 2)


def test_next_backfill_restarts_from_last_stored_day(svc):
    svc.store.upsert_bars("NIFTY 50", [Bar(date(2026, 11, 18), None, 1.0)], "kite")
    svc.store.upsert_bars("NIFTY BANK", [Bar(TODAY, None, 1.0)], "kite")   # self-captured close today
    c = FakeClient()
    svc.backfill_kite(c, TODAY)
    assert c.calls == [(1, date(2026, 11, 18), date(2026, 11, 22))]        # BANK: nothing to fetch yet


def test_backfill_isolates_failures_but_propagates_token_errors(svc):
    assert svc.backfill_kite(FakeClient(fail_tokens={1}), TODAY) == ["NIFTY 50"]
    with pytest.raises(TokenError):
        svc.backfill_kite(FakeClient(token_error=True), TODAY)


def test_refresh_amfi_and_note(svc):
    svc.refresh_amfi(lambda code: [Bar(date(2026, 11, 20), None, 10.0), Bar(date(2026, 11, 21), None, 10.1)])
    row = svc.row("NIFTY SDL APR 2027", TODAY)
    assert row.result.day == pytest.approx(0.01)
    assert row.result.gap is None
    assert row.note.startswith("NAV of Proxy Fund") and "21 Nov 2026" in row.note


def test_live_quote_drives_row_only_when_from_today(svc):
    svc.store.upsert_bars("NIFTY 50", [Bar(date(2026, 11, 20), 99.0, 100.0)], "kite")
    stale = Quote(1, 105.0, 104.0, 100.0, datetime(2026, 11, 20, 15, 29))
    assert svc.apply_quotes([stale]) == {"NIFTY 50"}
    assert not svc.row("NIFTY 50", TODAY).result.live
    fresh = Quote(1, 102.0, 101.0, 100.0, datetime(2026, 11, 23, 10, 0))
    svc.apply_quotes([fresh, Quote(999, 1.0, None, None, None)])            # unknown token ignored
    r = svc.row("NIFTY 50", TODAY).result
    assert r.live and r.day == pytest.approx(0.02) and r.gap == pytest.approx(0.01)


def test_capture_closes_only_after_market_close(svc):
    svc.apply_quotes([Quote(1, 102.0, 101.0, 100.0, datetime(2026, 11, 23, 15, 29))])
    assert svc.capture_closes(datetime(2026, 11, 23, 15, 0, tzinfo=IST)) == 0
    assert svc.capture_closes(datetime(2026, 11, 23, 15, 45, tzinfo=IST)) == 1
    assert svc.store.bars("NIFTY 50") == [Bar(TODAY, 101.0, 102.0)]


def test_row_to_dict_is_json_ready(svc):
    import json
    svc.store.upsert_bars("NIFTY 50", [Bar(date(2026, 11, 19), 99.0, 100.0),
                                       Bar(date(2026, 11, 20), 100.0, 101.0)], "kite")
    d = svc.row("NIFTY 50", TODAY).to_dict()
    json.dumps(d)                                            # must not raise
    assert d["id"] == "NIFTY 50" and d["as_of"] == "2026-11-20" and d["live"] is False
    assert d["returns"]["day"] == pytest.approx(0.01) and d["returns"]["5Y"] is None
    assert d["etfs"] == ["A ETF"] and d["source"] == "kite"


def test_rows_cover_universe_and_kite_tokens(svc):
    assert [r.info.id for r in svc.rows(TODAY)] == ["NIFTY 50", "NIFTY BANK", "NIFTY SDL APR 2027"]
    assert svc.kite_tokens() == [1, 2]
    assert svc.row("NIFTY BANK", TODAY).result.as_of is None
