from datetime import date, timedelta

import pytest

from screener.core.returns import Bar, compute_returns, months_back


def daily(start, n, f):
    return [Bar(start + timedelta(days=i), f(i), f(i)) for i in range(n)]


def test_months_back_clamps_to_month_end():
    assert months_back(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert months_back(date(2024, 3, 31), 1) == date(2024, 2, 29)
    assert months_back(date(2026, 1, 15), 60) == date(2021, 1, 15)


def test_day_and_gap_from_live_quote():
    bars = [Bar(date(2026, 11, 20), 100.0, 100.0)]
    r = compute_returns(bars, date(2026, 11, 23), live_price=103.0, live_open=101.0)
    assert r.live and r.as_of == date(2026, 11, 23)
    assert r.day == pytest.approx(0.03)
    assert r.gap == pytest.approx(0.01)


def test_without_live_uses_last_stored_session():
    bars = [Bar(date(2026, 11, 19), 99.0, 100.0), Bar(date(2026, 11, 20), 101.0, 102.0)]
    r = compute_returns(bars, date(2026, 11, 22))
    assert not r.live and r.as_of == date(2026, 11, 20)
    assert r.day == pytest.approx(0.02)
    assert r.gap == pytest.approx(0.01)


def test_period_uses_last_trading_day_on_or_before_target():
    # 7D target is 2026-11-13; nearest stored close on or before it is 2026-11-12
    bars = [Bar(date(2026, 11, 12), None, 100.0), Bar(date(2026, 11, 19), None, 105.0)]
    r = compute_returns(bars, date(2026, 11, 20), live_price=110.0)
    assert r.periods["7D"] == pytest.approx(0.10)


def test_gap_longer_than_seven_days_is_blank():
    bars = [Bar(date(2026, 10, 1), None, 100.0), Bar(date(2026, 11, 19), None, 105.0)]
    r = compute_returns(bars, date(2026, 11, 20), live_price=110.0)
    assert r.periods["7D"] is None


def test_young_index_has_blank_long_periods():
    bars = daily(date(2025, 1, 1), 700, lambda i: 100.0 + i)
    r = compute_returns(bars, date(2026, 12, 1), live_price=900.0)
    assert r.periods["1Y"] is not None
    assert r.periods["3Y"] is None and r.periods["5Y"] is None


def test_multi_year_periods_are_cagr():
    bars = [Bar(date(2021, 11, 20), None, 100.0), Bar(date(2024, 11, 20), None, 120.0),
            Bar(date(2026, 11, 19), None, 150.0)]
    r = compute_returns(bars, date(2026, 11, 20), live_price=161.051)
    assert r.periods["5Y"] == pytest.approx(0.10, abs=1e-6)       # 1.1 ** 5 = 1.61051
    assert r.periods["2Y"] == pytest.approx((161.051 / 120) ** 0.5 - 1)


def test_one_year_is_plain_return():
    bars = [Bar(date(2025, 11, 20), None, 100.0), Bar(date(2026, 11, 19), None, 108.0)]
    r = compute_returns(bars, date(2026, 11, 20), live_price=110.0)
    assert r.periods["1Y"] == pytest.approx(0.10)


def test_no_data_gives_blank_set():
    r = compute_returns([], date(2026, 11, 20))
    assert r.as_of is None and r.day is None
    assert all(v is None for v in r.periods.values())


def test_api_secret_prefers_env(monkeypatch):
    from screener.core.config import load_api_secret
    monkeypatch.setenv("KITE_API_SECRET", " s3cret ")
    assert load_api_secret() == "s3cret"
