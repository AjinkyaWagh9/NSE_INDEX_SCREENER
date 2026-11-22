from datetime import date

import numpy as np
import pandas as pd

from ranking.returns import adjust_for_splits, period_returns


def _nav(start, values):
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def test_one_year_absolute_and_multi_year_cagr():
    idx = pd.to_datetime(["2021-10-31", "2023-10-31", "2024-10-31", "2025-10-31", "2026-10-31"])
    nav = pd.Series([100, 120, 130, 150, 165], index=idx, dtype=float)
    r = period_returns(nav, date(2026, 10, 31))
    assert abs(r[1] - 0.10) < 1e-9
    assert abs(r[2] - ((165 / 130) ** 0.5 - 1)) < 1e-9
    assert abs(r[5] - ((165 / 100) ** 0.2 - 1)) < 1e-9


def test_young_fund_gets_nan():
    nav = _nav("2025-06-01", np.linspace(10, 12, 600))
    r = period_returns(nav, date(2026, 10, 31))
    assert not np.isnan(r[1]) and np.isnan(r[2]) and np.isnan(r[5])


def test_split_is_not_a_crash():
    nav = _nav("2026-01-01", [100, 101, 10.2, 10.3])  # 1:10 split on day 3
    adj = adjust_for_splits(nav)
    # split day itself is treated as flat; other days keep their real moves
    assert abs(adj.iloc[-1] / adj.iloc[0] - 1.01 * 10.3 / 10.2) < 1e-9


def test_month_returns_short_absolute_long_cagr():
    from ranking.returns import month_returns
    idx = pd.to_datetime(["2024-10-31", "2026-04-30", "2026-07-31", "2026-10-31"])
    nav = pd.Series([100, 110, 115, 121], index=idx, dtype=float)
    r = month_returns(nav, date(2026, 10, 31), months=(3, 6, 24, 60))
    assert abs(r[3] - (121 / 115 - 1)) < 1e-9
    assert abs(r[6] - (121 / 110 - 1)) < 1e-9
    assert abs(r[24] - 0.10) < 1e-9          # 1.21 over 2y -> 10% CAGR
    assert np.isnan(r[60])
