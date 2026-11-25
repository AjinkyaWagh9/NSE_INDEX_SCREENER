"""Pure return calculations. No I/O, no Qt."""
import calendar
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

from screener.core.config import MAX_ANCHOR_GAP_DAYS

PERIODS = ("7D", "15D", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y")
_SPEC = {"7D": ("d", 7), "15D": ("d", 15), "1M": ("m", 1), "3M": ("m", 3), "6M": ("m", 6),
         "1Y": ("m", 12), "2Y": ("m", 24), "3Y": ("m", 36), "5Y": ("m", 60)}
_CAGR_YEARS = {"2Y": 2, "3Y": 3, "5Y": 5}


@dataclass(frozen=True)
class Bar:
    date: date
    open: Optional[float]
    close: float


@dataclass
class ReturnSet:
    as_of: Optional[date] = None
    latest: Optional[float] = None
    gap: Optional[float] = None
    day: Optional[float] = None
    periods: dict = field(default_factory=lambda: {p: None for p in PERIODS})
    live: bool = False


def months_back(d: date, months: int) -> date:
    """Same calendar day `months` earlier, clamped to the month's end."""
    y, m0 = divmod(d.year * 12 + (d.month - 1) - months, 12)
    m = m0 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def period_start(anchor: date, period: str) -> date:
    kind, n = _SPEC[period]
    return anchor - timedelta(days=n) if kind == "d" else months_back(anchor, n)


def close_on_or_before(bars: Sequence[Bar], dates: Sequence[date], target: date) -> Optional[float]:
    i = bisect_right(dates, target) - 1
    if i < 0 or (target - dates[i]).days > MAX_ANCHOR_GAP_DAYS:
        return None
    return bars[i].close


def _ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or b in (None, 0) else a / b - 1


def compute_returns(bars: Sequence[Bar], today: date,
                    live_price: Optional[float] = None,
                    live_open: Optional[float] = None,
                    live_prev_close: Optional[float] = None) -> ReturnSet:
    """bars: daily bars sorted by date (may include today's stored close).
    With a live price the anchor is today; otherwise it is the last stored bar."""
    bars = list(bars)
    if live_price is not None:
        anchor, latest, open_, live = today, live_price, live_open, True
        history = [b for b in bars if b.date < today]
    elif bars:
        anchor, latest, open_, live = bars[-1].date, bars[-1].close, bars[-1].open, False
        history = bars[:-1]
    else:
        return ReturnSet()
    prev_close = (live_prev_close if (live and live_prev_close not in (None, 0))
                  else (history[-1].close if history else None))
    out = ReturnSet(as_of=anchor, latest=latest, live=live,
                    gap=_ratio(open_, prev_close), day=_ratio(latest, prev_close))
    dates = [b.date for b in bars]
    for p in PERIODS:
        r = _ratio(latest, close_on_or_before(bars, dates, period_start(anchor, p)))
        if r is not None and p in _CAGR_YEARS:
            r = (1 + r) ** (1 / _CAGR_YEARS[p]) - 1
        out.periods[p] = r
    return out
