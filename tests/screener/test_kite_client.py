from datetime import date, datetime

import pytest
from kiteconnect import exceptions as kex

from screener.core.kite_client import KiteClient, LiveFeed, Quote, TokenError


class FakeKite:
    def __init__(self, script):
        self.script, self.calls, self.token = list(script), [], None

    def set_access_token(self, t):
        self.token = t

    def profile(self):
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def historical_data(self, token, frm, to, interval):
        self.calls.append((token, frm, to, interval))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def client(script):
    sleeps = []
    c = KiteClient("key", "tok", kite=FakeKite(script), sleep=sleeps.append, clock=lambda: 0.0)
    return c, sleeps


def test_missing_key_or_token_is_token_error():
    with pytest.raises(TokenError):
        KiteClient("", "tok", kite=FakeKite([]))
    with pytest.raises(TokenError):
        KiteClient("key", "  ", kite=FakeKite([]))


def test_validate_maps_token_exception():
    c, _ = client([kex.TokenException("expired")])
    with pytest.raises(TokenError):
        c.validate()
    c2, _ = client([{"user_name": "Test User"}])
    assert c2.validate() == "Test User"


def test_daily_bars_maps_candles_and_throttles():
    candles = [{"date": datetime(2026, 11, 19, 0, 0), "open": 1.0, "close": 2.0},
               {"date": datetime(2026, 11, 20, 0, 0), "open": 2.0, "close": 3.0}]
    c, sleeps = client([candles, candles])
    bars = c.daily_bars(256265, date(2026, 11, 1), date(2026, 11, 20))
    assert [(b.date, b.open, b.close) for b in bars] == [(date(2026, 11, 19), 1.0, 2.0),
                                                         (date(2026, 11, 20), 2.0, 3.0)]
    assert c.kite.calls[0] == (256265, date(2026, 11, 1), date(2026, 11, 20), "day")
    c.daily_bars(256265, date(2026, 11, 1), date(2026, 11, 20))
    assert sleeps and sleeps[0] == pytest.approx(1 / 3)   # clock frozen -> must wait


def test_daily_bars_retries_network_errors_then_succeeds():
    c, sleeps = client([kex.NetworkException("429"), [{"date": date(2026, 11, 20), "open": 1, "close": 2}]])
    assert len(c.daily_bars(1, date(2026, 11, 1), date(2026, 11, 20))) == 1
    assert 1 in sleeps                                       # backoff 2**0


def test_daily_bars_token_error_is_not_retried():
    c, _ = client([kex.TokenException("bad")])
    with pytest.raises(TokenError):
        c.daily_bars(1, date(2026, 11, 1), date(2026, 11, 20))


def test_quote_from_tick():
    q = Quote.from_tick({"instrument_token": 256265, "last_price": 101.5,
                         "ohlc": {"open": 100.0, "close": 99.0},
                         "exchange_timestamp": datetime(2026, 11, 23, 10, 0)})
    assert (q.instrument_token, q.last_price, q.open, q.prev_close) == (256265, 101.5, 100.0, 99.0)


class FakeWS:
    MODE_QUOTE = "quote"

    def __init__(self):
        self.subscribed, self.mode = None, None

    def subscribe(self, tokens):
        self.subscribed = tokens

    def set_mode(self, mode, tokens):
        self.mode = (mode, tokens)


class FakeTicker:
    def __init__(self, api_key, token):
        self.args, self.connected, self.closed = (api_key, token), False, False

    def connect(self, threaded=False):
        self.connected = threaded

    def close(self):
        self.closed = True


def test_live_feed_subscribes_and_forwards_ticks():
    got, status = [], []
    feed = LiveFeed("key", "tok", [256265], on_quotes=got.extend,
                    on_status=lambda s, m: status.append(s), ticker_factory=FakeTicker)
    feed.start()
    kt = feed._kt
    assert kt.connected is True
    ws = FakeWS()
    kt.on_connect(ws, {})
    assert ws.subscribed == [256265] and ws.mode == ("quote", [256265]) and status == ["live"]
    kt.on_ticks(ws, [{"instrument_token": 256265, "last_price": 1.0}, {"instrument_token": 9}])
    assert [q.instrument_token for q in got] == [256265]     # ticks without a price are ignored
    kt.on_error(ws, 403, "TokenException")
    assert status[-1] == "error"
    feed.stop()
    assert kt.closed
