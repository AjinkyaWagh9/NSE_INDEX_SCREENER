# Live Index Screener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PySide6 desktop app with Equity and Debt tabs that shows Gap %, Day %, 7D … 5Y returns for every shortlisted NSE index, live from Zerodha Kite during market hours, backed by a local SQLite store of daily closes.

**Architecture:** A pure returns engine and a SQLite bar store sit at the core. Thin clients fetch Kite daily history and live ticks, and AMFI NAVs for the debt indices. A Qt-free `ScreenerService` turns stored bars plus live quotes into table rows. A Qt `Controller` runs network work on a thread pool and marshals ticker callbacks to the UI thread. The UI is one window with two `QTableView`s over a sortable, filterable proxy model.

**Tech Stack:** Python 3.13, PySide6 ≥ 6.6, kiteconnect ≥ 5.0 (official Zerodha SDK), SQLite (stdlib), pandas + requests (AMFI reuse and universe build), pytest, PyInstaller ≥ 6.

**Spec:** `docs/superpowers/specs/2026-11-22-live-index-screener-design.md`

## Global Constraints

- All dates and times are IST, a fixed UTC+05:30 (India has no DST); never use the computer's local time zone.
- Read-only: never call any Kite order, GTT or funds API.
- The Kite **API secret is not used**. The API key lives in git-ignored `screener/secrets_local.py`.
- The access token is held in memory only. It is never written to disk and never logged.
- Return conventions: Gap/Day/7D/15D/1M/3M/6M/1Y are plain returns; 2Y, 3Y and 5Y are CAGR.
- A past date that isn't a trading day uses the last close on or before it. No close within 7 days before the target, or a series starting after the target, gives a blank value (shown "—").
- Equity values are Kite **price** indices (excluding dividends). Debt rows not on Kite use the proxy fund's AMFI NAV.
- Automated tests never touch the network (the probe script in Task 9 is the only live check).
- Run everything from the repo root: `/Users/ajinkyawagh/Desktop/STARTUP/ETF_Indices`.

## File Structure

```
screener/
  __init__.py                 package marker
  config.py                   IST helpers, constants, paths, API-key loader
  secrets_local.example.py    template for the git-ignored secrets_local.py
  returns.py                  Bar, ReturnSet, compute_returns (pure)
  db.py                       BarStore (SQLite daily bars)
  universe.py                 IndexInfo + load_universe()
  build_universe.py           dev-time generator for universe.json
  universe.json               generated, committed, bundled
  amfi_client.py              fetch_nav_bars() (reuses ranking.returns)
  kite_client.py              KiteClient (history), LiveFeed (ticker), Quote, TokenError
  service.py                  ScreenerService + RowData (Qt-free orchestration)
  controller.py               Qt Controller (threads, signals)
  ui/__init__.py
  ui/table_model.py           ScreenerTableModel, ScreenerProxy
  ui/main_window.py           TabView, MainWindow
  app.py                      entry point (+ --selftest)
  probe_kite.py               manual live check with the user's token
  NSEScreener.spec            PyInstaller spec
  BUILD.md                    build + first-run instructions
tests/screener/
  __init__.py, conftest.py, helpers.py
  test_engine.py, test_db.py, test_build_universe.py, test_amfi_client.py,
  test_kite_client.py, test_service.py, test_table_model.py, test_app_smoke.py
```

---

### Task 1: Package scaffold, config and returns engine

**Files:**
- Create: `screener/__init__.py`, `screener/config.py`, `screener/secrets_local.example.py`, `screener/returns.py`
- Create: `tests/screener/__init__.py`, `tests/screener/conftest.py`, `tests/screener/test_engine.py`
- Modify: `.gitignore`, `requirements.txt`

**Interfaces:**
- Produces:
  - `screener.config`: `IST`, `MARKET_OPEN`, `MARKET_CLOSE`, `HISTORY_MONTHS=60`, `HISTORY_PAD_DAYS=7`, `MAX_ANCHOR_GAP_DAYS=7`, `HIST_MIN_INTERVAL_S=1/3`, `now_ist() -> datetime`, `today_ist() -> date`, `app_dir() -> Path`, `resource_path(name: str) -> Path`, `load_api_key() -> str`
  - `screener.returns`: `PERIODS: tuple[str,...]`, `Bar(date, open: float|None, close: float)` (frozen dataclass), `ReturnSet(as_of, latest, gap, day, periods: dict[str, float|None], live: bool)`, `months_back(d: date, months: int) -> date`, `compute_returns(bars, today, live_price=None, live_open=None) -> ReturnSet`

- [ ] **Step 1: Add ignore rules and dependencies**

Append to `.gitignore`:

```
build/
dist/
screener/secrets_local.py
screener/screener.db
screener/screener.log
screener/selftest.txt
screener/nav_cache/
```

Replace `requirements.txt` with:

```
pandas>=2.0
requests>=2.31
openpyxl>=3.1
pytest>=8.0
PySide6>=6.6
kiteconnect>=5.0
pyinstaller>=6.0
```

- [ ] **Step 2: Create the package files**

`screener/__init__.py`:

```python
"""Live NSE index screener (PySide6 + Zerodha Kite Connect)."""
```

`screener/config.py`:

```python
"""App-wide constants, IST time helpers and file locations."""
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30), "IST")  # India has no DST
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
HISTORY_MONTHS = 60          # 5 years of daily history
HISTORY_PAD_DAYS = 7         # so the 5Y anchor has a close on or before it
MAX_ANCHOR_GAP_DAYS = 7      # a past close older than this before the target -> blank
HIST_MIN_INTERVAL_S = 1 / 3  # Kite historical API allows ~3 requests/second
PACKAGE_DIR = Path(__file__).resolve().parent


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def app_dir() -> Path:
    """Folder for screener.db, screener.log and nav_cache: next to the executable
    when frozen by PyInstaller, otherwise the package folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PACKAGE_DIR


def resource_path(name: str) -> Path:
    """Read-only files bundled with the app (e.g. universe.json)."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "screener" / name if base else PACKAGE_DIR / name


def load_api_key() -> str:
    """Kite API key from the git-ignored screener/secrets_local.py ('' if missing)."""
    try:
        from screener.secrets_local import KITE_API_KEY
    except ImportError:
        return ""
    return KITE_API_KEY.strip()
```

`screener/secrets_local.example.py`:

```python
# Copy this file to secrets_local.py (git-ignored) and put your Kite Connect API key in it.
# The API secret is NOT needed: the app takes a ready-made daily access token.
KITE_API_KEY = "your_api_key_here"
```

`tests/screener/__init__.py`: empty file.

`tests/screener/conftest.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # Qt tests run headless

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
```

- [ ] **Step 3: Write the failing engine tests**

`tests/screener/test_engine.py`:

```python
from datetime import date, timedelta

import pytest

from screener.returns import Bar, compute_returns, months_back


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
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python3 -m pytest tests/screener/test_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screener.returns'`

- [ ] **Step 5: Implement the engine**

`screener/returns.py`:

```python
"""Pure return calculations. No I/O, no Qt."""
import calendar
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

from screener.config import MAX_ANCHOR_GAP_DAYS

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
                    live_open: Optional[float] = None) -> ReturnSet:
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
    prev_close = history[-1].close if history else None
    out = ReturnSet(as_of=anchor, latest=latest, live=live,
                    gap=_ratio(open_, prev_close), day=_ratio(latest, prev_close))
    dates = [b.date for b in bars]
    for p in PERIODS:
        r = _ratio(latest, close_on_or_before(bars, dates, period_start(anchor, p)))
        if r is not None and p in _CAGR_YEARS:
            r = (1 + r) ** (1 / _CAGR_YEARS[p]) - 1
        out.periods[p] = r
    return out
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/screener/test_engine.py -q`
Expected: `9 passed`

- [ ] **Step 7: Commit**

```bash
git add .gitignore requirements.txt screener/__init__.py screener/config.py screener/secrets_local.example.py screener/returns.py tests/screener/__init__.py tests/screener/conftest.py tests/screener/test_engine.py
git commit -m "feat(screener): package scaffold, IST config and pure returns engine"
```

---

### Task 2: SQLite bar store

**Files:**
- Create: `screener/db.py`, `tests/screener/test_db.py`

**Interfaces:**
- Consumes: `screener.returns.Bar`
- Produces: `screener.db.BarStore(path: Path)` with `upsert_bars(index_id: str, bars: Iterable[Bar], source: str) -> int`, `bars(index_id: str) -> list[Bar]` (ascending), `last_date(index_id: str) -> date | None`, `close() -> None`. Safe to call from several threads.

- [ ] **Step 1: Write the failing tests**

`tests/screener/test_db.py`:

```python
from datetime import date

from screener.db import BarStore
from screener.returns import Bar


def test_upsert_and_read_sorted(tmp_path):
    s = BarStore(tmp_path / "t.db")
    s.upsert_bars("NIFTY 50", [Bar(date(2026, 11, 20), 1.0, 2.0), Bar(date(2026, 11, 19), None, 1.5)], "kite")
    assert [b.date for b in s.bars("NIFTY 50")] == [date(2026, 11, 19), date(2026, 11, 20)]
    assert s.bars("NIFTY 50")[0].open is None


def test_upsert_overwrites_same_day(tmp_path):
    s = BarStore(tmp_path / "t.db")
    s.upsert_bars("X", [Bar(date(2026, 11, 20), 1.0, 2.0)], "kite")
    s.upsert_bars("X", [Bar(date(2026, 11, 20), 1.0, 3.0)], "kite")
    assert s.bars("X") == [Bar(date(2026, 11, 20), 1.0, 3.0)]


def test_last_date_and_persistence(tmp_path):
    p = tmp_path / "t.db"
    s = BarStore(p)
    assert s.last_date("X") is None
    s.upsert_bars("X", [Bar(date(2026, 11, 18), None, 1.0), Bar(date(2026, 11, 20), None, 1.0)], "amfi")
    s.close()
    s2 = BarStore(p)
    assert s2.last_date("X") == date(2026, 11, 20)
    assert s2.bars("other") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/screener/test_db.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screener.db'`

- [ ] **Step 3: Implement the store**

`screener/db.py`:

```python
"""SQLite store of daily bars: one row per index per trading day."""
import sqlite3
import threading
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from screener.returns import Bar

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_bar (
  index_id   TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  open       REAL,
  close      REAL NOT NULL,
  source     TEXT NOT NULL,
  PRIMARY KEY (index_id, trade_date)
)"""


class BarStore:
    def __init__(self, path: Path):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute(_SCHEMA)

    def upsert_bars(self, index_id: str, bars: Iterable[Bar], source: str) -> int:
        rows = [(index_id, b.date.isoformat(), b.open, b.close, source) for b in bars]
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO daily_bar VALUES (?,?,?,?,?) "
                "ON CONFLICT(index_id, trade_date) DO UPDATE SET "
                "open=excluded.open, close=excluded.close, source=excluded.source", rows)
        return len(rows)

    def bars(self, index_id: str) -> list[Bar]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT trade_date, open, close FROM daily_bar WHERE index_id=? ORDER BY trade_date",
                (index_id,))
            rows = cur.fetchall()
        return [Bar(date.fromisoformat(d), o, c) for d, o, c in rows]

    def last_date(self, index_id: str) -> Optional[date]:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(trade_date) FROM daily_bar WHERE index_id=?", (index_id,)).fetchone()
        return date.fromisoformat(row[0]) if row and row[0] else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/screener/test_db.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add screener/db.py tests/screener/test_db.py
git commit -m "feat(screener): SQLite daily bar store"
```

---

### Task 3: Universe model, generator and universe.json

**Files:**
- Create: `screener/universe.py`, `screener/build_universe.py`, `screener/universe.json` (generated)
- Create: `tests/screener/helpers.py`, `tests/screener/test_build_universe.py`

**Interfaces:**
- Consumes: `build_presentation.load() -> (df, sheets)` (columns used: `matched_index, Index, Category, Fund, Type, aum_cr, rank_aum, rank_composite, fund_id, _cat, _top`), `build_presentation._proxy_fund(ix, df, fund_rets) -> (fund_name, scheme_code) | None`, `build_presentation.RETURNS` (path of `data/10_fund_returns.csv`)
- Produces:
  - `screener.universe.IndexInfo` (frozen dataclass): `id, display_name, tab ("equity"|"debt"), category, source ("kite"|"amfi"|"none"), kite_symbol, kite_instrument_token, nav_scheme_code, nav_fund_name, etfs: tuple[str,...], index_funds: tuple[str,...]`
  - `screener.universe.load_universe(path: Path | None = None) -> list[IndexInfo]`
  - `screener.build_universe`: `KITE_ALIASES`, `norm(s)`, `kite_index_table(csv_text) -> DataFrame`, `resolve_kite(index_id, display_name, tab, kite) -> (symbol|None, token|None)`, `debt_category(index_id) -> str`, `build_records(df, fund_rets, kite) -> list[dict]`, `UniverseError`
  - `tests/screener/helpers.py`: `make_info(...) -> IndexInfo` used by later tests

Note: `nav_fund_name` extends spec §4.1 so the UI tooltip can name the proxy fund.

- [ ] **Step 1: Create the universe model and test helper**

`screener/universe.py`:

```python
"""The fixed list of indices the screener shows (generated by build_universe.py)."""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from screener.config import resource_path


@dataclass(frozen=True)
class IndexInfo:
    id: str
    display_name: str
    tab: str                       # "equity" | "debt"
    category: str
    source: str                    # "kite" | "amfi" | "none"
    kite_symbol: Optional[str]
    kite_instrument_token: Optional[int]
    nav_scheme_code: Optional[int]
    nav_fund_name: Optional[str]
    etfs: tuple
    index_funds: tuple


def load_universe(path: Optional[Path] = None) -> list[IndexInfo]:
    data = json.loads((path or resource_path("universe.json")).read_text(encoding="utf-8"))
    return [IndexInfo(**{**r, "etfs": tuple(r["etfs"]), "index_funds": tuple(r["index_funds"])})
            for r in data]
```

`tests/screener/helpers.py`:

```python
from screener.universe import IndexInfo


def make_info(id="NIFTY 50", tab="equity", category="Broad Market", source="kite", token=1,
              code=None, etfs=("A ETF",), funds=("A Index Fund",)):
    return IndexInfo(id=id, display_name=id.title(), tab=tab, category=category, source=source,
                     kite_symbol=id if source == "kite" else None,
                     kite_instrument_token=token if source == "kite" else None,
                     nav_scheme_code=code, nav_fund_name="Proxy Fund" if source == "amfi" else None,
                     etfs=tuple(etfs), index_funds=tuple(funds))
```

- [ ] **Step 2: Write the failing generator tests**

`tests/screener/test_build_universe.py`:

```python
import json

import pandas as pd
import pytest

from screener.build_universe import (UniverseError, build_records, debt_category,
                                     kite_index_table, resolve_kite)
from screener.universe import load_universe

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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest tests/screener/test_build_universe.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screener.build_universe'`

- [ ] **Step 4: Implement the generator**

`screener/build_universe.py`:

```python
#!/usr/bin/env python3
"""Generate screener/universe.json from this project's shortlist + Kite's instrument list.

Run from the repo root after run_ranking.py and compute_returns.py:
    python3 -m screener.build_universe            # downloads Kite's public instrument list
    python3 -m screener.build_universe --instruments path/to/instruments.csv
"""
import argparse
import io
import json
import re
from pathlib import Path

import pandas as pd
import requests

import build_presentation as bp

KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"
OUT = Path(__file__).resolve().parent / "universe.json"

# Our canonical index id -> Kite tradingsymbol, where names differ after normalisation.
KITE_ALIASES = {
    "NIFTY SMALLCAP 250": "NIFTY SMLCAP 250",
    "NIFTY SMALLCAP 100": "NIFTY SMLCAP 100",
    "NIFTY SMALLCAP 50": "NIFTY SMLCAP 50",
    "NIFTY LARGEMIDCAP 250": "NIFTY LARGEMID250",
    "NIFTY TOTAL MARKET": "NIFTY TOTAL MKT",
    "NIFTY MIDSMALLCAP 400": "NIFTY MIDSML 400",
    "NIFTY MIDSMALLCAP400 50:50": "NIFTY MIDSMALL 50 50",
    "NIFTY PRIVATE BANK": "NIFTY PVT BANK",
    "NIFTY OIL & GAS": "NIFTY OIL AND GAS",
    "NIFTY MIDSMALL HEALTHCARE": "NIFTY MIDSML HLTH",
    "NIFTY FINANCIAL SERVICES EX-BANK": "NIFTY FINSEREXBNK",
    "NIFTY500 HEALTHCARE": "NIFTY500 HEALTH",
    "NIFTY INFRASTRUCTURE": "NIFTY INFRA",
    "NIFTY INDIA MANUFACTURING": "NIFTY INDIA MFG",
    "NIFTY INDIA CONSUMPTION": "NIFTY CONSUMPTION",
    "NIFTY INDIA DIGITAL": "NIFTY IND DIGITAL",
    "NIFTY INDIA RAILWAYS PSU": "NIFTY RAILWAYS PSU",
    "NIFTY INDIA INTERNET": "NIFTY INTERNET",
    "NIFTY INDIA INFRASTRUCTURE & LOGISTICS": "NIFTY INFRALOG",
    "NIFTY200 MOMENTUM 30": "NIFTY200MOMENTM30",
    "NIFTY100 LOW VOLATILITY 30": "NIFTY100 LOWVOL30",
    "NIFTY50 EQUAL WEIGHT": "NIFTY50 EQL WGT",
    "NIFTY MIDCAP150 MOMENTUM 50": "NIFTYM150MOMNTM50",
    "NIFTY ALPHA LOW-VOLATILITY 30": "NIFTY ALPHALOWVOL",
    "NIFTY500 MULTICAP 50:25:25": "NIFTY500 MULTICAP",
    "NIFTY200 QUALITY 30": "NIFTY200 QUALTY30",
    "NIFTY100 EQUAL WEIGHT": "NIFTY100 EQL WGT",
    "NIFTY MIDCAP150 QUALITY 50": "NIFTY M150 QLTY50",
    "NIFTY500 FLEXICAP QUALITY 30": "NIFTY500 FLEXICAP",
    "NIFTY500 MULTICAP INDIA MANUFACTURING 50:30:20": "NIFTY MULTI MFG",
    "NIFTY100 QUALITY 30": "NIFTY100 QUALTY30",
    "NIFTY100 ESG SECTOR LEADERS": "NIFTY100ESGSECLDR",
    "NIFTY500 QUALITY 50": "NIFTY500 QLTY50",
    "NIFTY DIVIDEND OPPORTUNITIES 50": "NIFTY DIV OPPS 50",
    "NIFTY500 MULTICAP INFRASTRUCTURE 50:30:20": "NIFTY MULTI INFRA",
    "NIFTY TOTAL MARKET MOMENTUM QUALITY 50": "NIFTY TMMQ 50",
    "NIFTY500 LOW VOLATILITY 50": "NIFTY500 LOWVOL50",
    "NIFTY GROWTH SECTORS 15": "NIFTY GROWSECT 15",
    # debt indices that Kite carries
    "NIFTY 10 YR BENCHMARK G-SEC": "NIFTY GS 10YR",
    "NIFTY 8-13 YR G-SEC": "NIFTY GS 8 13YR",
    "NIFTY BHARAT BOND INDEX - APRIL 2030": "BHARATBOND-APR30",
    "NIFTY BHARAT BOND INDEX - APRIL 2031": "BHARATBOND-APR31",
    "NIFTY BHARAT BOND INDEX - APRIL 2032": "BHARATBOND-APR32",
    "NIFTY BHARAT BOND INDEX - APRIL 2033": "BHARATBOND-APR33",
}


class UniverseError(Exception):
    """An index could not be resolved; fix KITE_ALIASES rather than drop it silently."""


def norm(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper().replace("NIFTY", ""))


def kite_index_table(csv_text: str) -> pd.DataFrame:
    k = pd.read_csv(io.StringIO(csv_text), low_memory=False)
    k = k[(k["segment"] == "INDICES") & (k["exchange"] == "NSE")]
    return k[["instrument_token", "tradingsymbol", "name"]].reset_index(drop=True)


def resolve_kite(index_id: str, display_name: str, tab: str, kite: pd.DataFrame):
    """(tradingsymbol, instrument_token) or (None, None). Debt only via KITE_ALIASES."""
    by_sym = dict(zip(kite["tradingsymbol"], kite["instrument_token"]))
    sym = KITE_ALIASES.get(index_id)
    if sym is None and tab == "equity":
        lookup = {norm(n): s for n, s in zip(kite["name"], kite["tradingsymbol"])}
        lookup.update({norm(s): s for s in kite["tradingsymbol"]})
        sym = lookup.get(norm(display_name))
    if sym is None or sym not in by_sym:
        return None, None
    return sym, int(by_sym[sym])


def debt_category(index_id: str) -> str:
    u = index_id.upper()
    if "BHARAT BOND" in u:
        return "Bharat Bond"
    if "1D RATE" in u or "LIQUID" in u:
        return "Liquid / Overnight"
    if "HYBRID" in u:
        return "Hybrid"
    if "BENCHMARK" in u or "8-13 YR" in u:
        return "G-Sec Benchmark"
    return "Target Maturity"


def _top_names(sub: pd.DataFrame, kind: str, n: int = 3) -> list:
    return list(sub[sub["Type"] == kind].sort_values("aum_cr", ascending=False)["Fund"].head(n))


def build_records(df: pd.DataFrame, fund_rets: pd.DataFrame, kite: pd.DataFrame) -> list:
    recs, unresolved = [], []
    for ix in df.sort_values(["_cat", "_top", "matched_index"])["matched_index"].unique():
        sub = df[df["matched_index"] == ix]
        first = sub.iloc[0]
        tab = "debt" if first["Category"] == "Debt" else "equity"
        sym, tok = resolve_kite(ix, first["Index"], tab, kite)
        fund = code = None
        if sym:
            source = "kite"
        elif tab == "debt" and (proxy := bp._proxy_fund(ix, df, fund_rets)):
            source, (fund, code) = "amfi", proxy
        else:
            source = "none"
            if tab == "equity":
                unresolved.append(ix)
        recs.append({
            "id": ix,
            "display_name": first["Index"],
            "tab": tab,
            "category": debt_category(ix) if tab == "debt" else first["Category"],
            "source": source,
            "kite_symbol": sym,
            "kite_instrument_token": tok,
            "nav_scheme_code": int(code) if code is not None else None,
            "nav_fund_name": fund,
            "etfs": _top_names(sub, "ETF"),
            "index_funds": _top_names(sub, "Index Fund"),
        })
    if unresolved:
        raise UniverseError(f"No Kite symbol for equity indices: {unresolved} - add them to KITE_ALIASES")
    return recs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instruments", help="local copy of Kite's instruments CSV (default: download)")
    args = ap.parse_args()
    if args.instruments:
        text = Path(args.instruments).read_text(encoding="utf-8")
    else:
        resp = requests.get(KITE_INSTRUMENTS_URL, timeout=60)
        resp.raise_for_status()
        text = resp.text
    df, _ = bp.load()
    recs = build_records(df, pd.read_csv(bp.RETURNS), kite_index_table(text))
    OUT.write_text(json.dumps(recs, indent=1, ensure_ascii=False), encoding="utf-8")
    count = lambda tab, src: sum(r["tab"] == tab and r["source"] == src for r in recs)
    print(f"Wrote {OUT}: equity kite={count('equity', 'kite')} | debt kite={count('debt', 'kite')} "
          f"amfi={count('debt', 'amfi')} none={count('debt', 'none')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/screener/test_build_universe.py -q`
Expected: `6 passed`

- [ ] **Step 6: Generate the real universe.json**

Run: `python3 -m screener.build_universe`
Expected output: `Wrote …/screener/universe.json: equity kite=89 | debt kite=6 amfi=35 none=0`

If it raises `UniverseError`, add the listed index ids to `KITE_ALIASES`, using the exact tradingsymbol from Kite's list, and re-run.

- [ ] **Step 7: Commit**

```bash
git add screener/universe.py screener/build_universe.py screener/universe.json tests/screener/helpers.py tests/screener/test_build_universe.py
git commit -m "feat(screener): index universe model, generator and universe.json"
```

---

### Task 4: AMFI NAV client

**Files:**
- Create: `screener/amfi_client.py`, `tests/screener/test_amfi_client.py`

**Interfaces:**
- Consumes: `ranking.returns.fetch_nav_history(code, cache_dir, max_age_days=1, session=None) -> pd.Series` (date-indexed, ascending, split-adjusted; already in the repo)
- Produces: `screener.amfi_client.fetch_nav_bars(scheme_code: int, cache_dir: Path, max_age_days: float = 0.5, session=None) -> list[Bar]` (ascending, `open=None`)

- [ ] **Step 1: Write the failing test**

`tests/screener/test_amfi_client.py`:

```python
from datetime import date

from screener.amfi_client import fetch_nav_bars


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def get(self, url, timeout=30):
        self.calls += 1
        return FakeResp(self.payload)


def test_bars_ascending_and_zero_navs_skipped(tmp_path):
    payload = {"data": [{"date": "20-11-2026", "nav": "11.0"},
                        {"date": "19-11-2026", "nav": "0"},
                        {"date": "18-11-2026", "nav": "10.0"}]}
    sess = FakeSession(payload)
    bars = fetch_nav_bars(12345, tmp_path, session=sess)
    assert [(b.date, b.close, b.open) for b in bars] == [(date(2026, 11, 18), 10.0, None),
                                                         (date(2026, 11, 20), 11.0, None)]
    fetch_nav_bars(12345, tmp_path, session=sess)      # second call served from the cache
    assert sess.calls == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/screener/test_amfi_client.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screener.amfi_client'`

- [ ] **Step 3: Implement the client**

`screener/amfi_client.py`:

```python
"""Debt-row NAV history from AMFI (via mfapi.in), reusing the pipeline's cached fetcher."""
from pathlib import Path

from ranking.returns import fetch_nav_history
from screener.returns import Bar


def fetch_nav_bars(scheme_code: int, cache_dir: Path, max_age_days: float = 0.5,
                   session=None) -> list[Bar]:
    nav = fetch_nav_history(int(scheme_code), cache_dir, max_age_days=max_age_days, session=session)
    return [Bar(ts.date(), None, float(v)) for ts, v in nav.items()]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/screener/test_amfi_client.py -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add screener/amfi_client.py tests/screener/test_amfi_client.py
git commit -m "feat(screener): AMFI NAV client for debt rows"
```

---

### Task 5: Kite client (history + live feed)

**Files:**
- Create: `screener/kite_client.py`, `tests/screener/test_kite_client.py`

**Interfaces:**
- Consumes: `screener.returns.Bar`, `screener.config.HIST_MIN_INTERVAL_S`, `kiteconnect.KiteConnect`, `kiteconnect.KiteTicker`, `kiteconnect.exceptions`
- Produces:
  - `TokenError(Exception)`
  - `Quote(instrument_token: int, last_price: float, open: float|None, prev_close: float|None, timestamp: datetime|None)` with `Quote.from_tick(tick: dict) -> Quote`
  - `KiteClient(api_key, access_token, kite=None, sleep=time.sleep, clock=time.monotonic)`: `validate() -> str` (user name; raises `TokenError`), `daily_bars(instrument_token: int, from_date: date, to_date: date) -> list[Bar]`
  - `LiveFeed(api_key, access_token, tokens, on_quotes, on_status, ticker_factory=KiteTicker)`: `start()`, `stop()`. Callbacks: `on_quotes(list[Quote])`, `on_status(state: str, message: str)` with state in `live|reconnecting|error|closed|disconnected`. Callbacks run on the ticker thread.

- [ ] **Step 1: Write the failing tests**

`tests/screener/test_kite_client.py`:

```python
from datetime import date, datetime

import pytest
from kiteconnect import exceptions as kex

from screener.kite_client import KiteClient, LiveFeed, Quote, TokenError


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/screener/test_kite_client.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screener.kite_client'`

- [ ] **Step 3: Implement the client**

`screener/kite_client.py`:

```python
"""Thin wrapper over the official kiteconnect SDK: token check, daily history, live feed.
Read-only by design: no order APIs are used."""
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable, Optional

from kiteconnect import KiteConnect, KiteTicker
from kiteconnect import exceptions as kex

from screener.config import HIST_MIN_INTERVAL_S
from screener.returns import Bar

log = logging.getLogger(__name__)


class TokenError(Exception):
    """API key or access token missing, invalid or expired."""


@dataclass(frozen=True)
class Quote:
    instrument_token: int
    last_price: float
    open: Optional[float]
    prev_close: Optional[float]
    timestamp: Optional[datetime]

    @classmethod
    def from_tick(cls, t: dict) -> "Quote":
        ohlc = t.get("ohlc") or {}
        return cls(int(t["instrument_token"]), float(t["last_price"]), ohlc.get("open"),
                   ohlc.get("close"), t.get("exchange_timestamp") or t.get("timestamp"))


def _to_date(d) -> date:
    return d.date() if isinstance(d, datetime) else d


class KiteClient:
    RETRIES = 3

    def __init__(self, api_key: str, access_token: str, kite=None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        if not api_key:
            raise TokenError("No Kite API key configured (screener/secrets_local.py)")
        if not access_token or not access_token.strip():
            raise TokenError("Paste today's access token")
        self.kite = kite or KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token.strip())
        self._sleep, self._clock, self._last_call = sleep, clock, None

    def validate(self) -> str:
        try:
            return self.kite.profile().get("user_name", "")
        except kex.TokenException as e:
            raise TokenError(str(e)) from e

    def _throttle(self) -> None:
        if self._last_call is not None:
            wait = HIST_MIN_INTERVAL_S - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def daily_bars(self, instrument_token: int, from_date: date, to_date: date) -> list[Bar]:
        for attempt in range(self.RETRIES):
            self._throttle()
            try:
                candles = self.kite.historical_data(instrument_token, from_date, to_date, "day")
                break
            except kex.TokenException as e:
                raise TokenError(str(e)) from e
            except (kex.NetworkException, kex.DataException, kex.GeneralException) as e:
                if attempt == self.RETRIES - 1:
                    raise
                log.warning("historical_data %s failed (%s); retrying", instrument_token, e)
                self._sleep(2 ** attempt)
        return [Bar(_to_date(c["date"]), c.get("open"), float(c["close"])) for c in candles]


class LiveFeed:
    """Streams quote-mode ticks on KiteTicker's background thread. Callbacks run on that
    thread, so the UI layer must marshal them to the Qt main thread."""

    def __init__(self, api_key: str, access_token: str, tokens: Iterable[int],
                 on_quotes: Callable[[list], None], on_status: Callable[[str, str], None],
                 ticker_factory=KiteTicker):
        self._tokens = list(tokens)
        self._on_quotes, self._on_status = on_quotes, on_status
        self._kt = kt = ticker_factory(api_key, access_token.strip())
        kt.on_connect = self._handle_connect
        kt.on_ticks = lambda ws, ticks: self._on_quotes(
            [Quote.from_tick(t) for t in ticks if "last_price" in t])
        kt.on_close = lambda ws, code, reason: self._on_status("closed", f"{code} {reason or ''}".strip())
        kt.on_error = lambda ws, code, reason: self._on_status("error", f"{code} {reason or ''}".strip())
        kt.on_reconnect = lambda ws, attempts: self._on_status("reconnecting", f"attempt {attempts}")
        kt.on_noreconnect = lambda ws: self._on_status("disconnected", "gave up reconnecting")

    def _handle_connect(self, ws, response) -> None:
        ws.subscribe(self._tokens)
        ws.set_mode(ws.MODE_QUOTE, self._tokens)
        self._on_status("live", "")

    def start(self) -> None:
        self._kt.connect(threaded=True)

    def stop(self) -> None:
        self._kt.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/screener/test_kite_client.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add screener/kite_client.py tests/screener/test_kite_client.py
git commit -m "feat(screener): Kite client for daily history and live quote feed"
```

---

### Task 6: Screener service (Qt-free orchestration)

**Files:**
- Create: `screener/service.py`, `tests/screener/test_service.py`

**Interfaces:**
- Consumes: `BarStore`, `IndexInfo`, `compute_returns`, `months_back`, `Bar`, `ReturnSet`, `Quote`, `TokenError`, config constants
- Produces:
  - `RowData(info: IndexInfo, result: ReturnSet, note: str)`
  - `ScreenerService(universe: list[IndexInfo], store: BarStore)` with:
    - `kite_tokens() -> list[int]`
    - `backfill_kite(client, today: date, progress=lambda done, total: None) -> list[str]` (failed ids; `TokenError` propagates)
    - `refresh_amfi(fetch: Callable[[int], list[Bar]]) -> list[str]`
    - `apply_quotes(quotes: Iterable[Quote]) -> set[str]` (changed index ids)
    - `capture_closes(now: datetime) -> int`
    - `row(index_id: str, today: date) -> RowData`, `rows(today: date) -> list[RowData]`

- [ ] **Step 1: Write the failing tests**

`tests/screener/test_service.py`:

```python
from datetime import date, datetime, timedelta

import pytest

from screener.config import IST
from screener.db import BarStore
from screener.kite_client import Quote, TokenError
from screener.returns import Bar, months_back
from screener.service import ScreenerService
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


def test_rows_cover_universe_and_kite_tokens(svc):
    assert [r.info.id for r in svc.rows(TODAY)] == ["NIFTY 50", "NIFTY BANK", "NIFTY SDL APR 2027"]
    assert svc.kite_tokens() == [1, 2]
    assert svc.row("NIFTY BANK", TODAY).result.as_of is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/screener/test_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screener.service'`

- [ ] **Step 3: Implement the service**

`screener/service.py`:

```python
"""Qt-free orchestration: history fill-in, AMFI refresh, live quotes -> table rows."""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional

from screener.config import HISTORY_MONTHS, HISTORY_PAD_DAYS, IST, MARKET_CLOSE
from screener.db import BarStore
from screener.kite_client import Quote, TokenError
from screener.returns import Bar, ReturnSet, compute_returns, months_back
from screener.universe import IndexInfo

log = logging.getLogger(__name__)


@dataclass
class RowData:
    info: IndexInfo
    result: ReturnSet
    note: str          # source description shown as a tooltip


def _quote_date(q: Quote) -> Optional[date]:
    ts = q.timestamp
    if ts is None:
        return None
    return ts.date() if ts.tzinfo is None else ts.astimezone(IST).date()  # Kite sends naive IST


class ScreenerService:
    def __init__(self, universe: list[IndexInfo], store: BarStore):
        self.universe = universe
        self.store = store
        self._by_id = {i.id: i for i in universe}
        self._by_token = {i.kite_instrument_token: i.id for i in universe
                          if i.source == "kite" and i.kite_instrument_token}
        self._bars: dict[str, list[Bar]] = {}
        self._quotes: dict[str, Quote] = {}

    # ---------- history ----------
    def kite_tokens(self) -> list[int]:
        return list(self._by_token)

    def backfill_kite(self, client, today: date,
                      progress: Callable[[int, int], None] = lambda done, total: None) -> list[str]:
        todo = [i for i in self.universe if i.source == "kite"]
        first_start = months_back(today, HISTORY_MONTHS) - timedelta(days=HISTORY_PAD_DAYS)
        end = today - timedelta(days=1)
        failed = []
        for n, info in enumerate(todo, 1):
            # Re-fetch the last stored day so a self-captured close is replaced by Kite's official one.
            start = self.store.last_date(info.id) or first_start
            if start <= end:
                try:
                    bars = client.daily_bars(info.kite_instrument_token, start, end)
                    self.store.upsert_bars(info.id, bars, "kite")
                    self._bars.pop(info.id, None)
                except TokenError:
                    raise
                except Exception:  # noqa: BLE001 - one index must not stop the others
                    log.exception("history fill-in failed for %s", info.id)
                    failed.append(info.id)
            progress(n, len(todo))
        return failed

    def refresh_amfi(self, fetch: Callable[[int], list[Bar]]) -> list[str]:
        failed = []
        for info in self.universe:
            if info.source != "amfi":
                continue
            try:
                self.store.upsert_bars(info.id, fetch(info.nav_scheme_code), "amfi")
                self._bars.pop(info.id, None)
            except Exception:  # noqa: BLE001
                log.exception("AMFI refresh failed for %s", info.id)
                failed.append(info.id)
        return failed

    # ---------- live ----------
    def apply_quotes(self, quotes: Iterable[Quote]) -> set[str]:
        changed = set()
        for q in quotes:
            ix = self._by_token.get(q.instrument_token)
            if ix:
                self._quotes[ix] = q
                changed.add(ix)
        return changed

    def capture_closes(self, now: datetime) -> int:
        """After 15:30 IST, store today's close from each index's last quote."""
        now = now.astimezone(IST)
        if now.time() < MARKET_CLOSE:
            return 0
        today, n = now.date(), 0
        for ix, q in self._quotes.items():
            if _quote_date(q) == today:
                self.store.upsert_bars(ix, [Bar(today, q.open, q.last_price)], "kite")
                self._bars.pop(ix, None)
                n += 1
        return n

    # ---------- rows ----------
    def row(self, index_id: str, today: date) -> RowData:
        info = self._by_id[index_id]
        bars = self._bars.get(index_id)
        if bars is None:
            bars = self._bars[index_id] = self.store.bars(index_id)
        q = self._quotes.get(index_id)
        live = q is not None and _quote_date(q) == today
        res = compute_returns(bars, today, q.last_price if live else None, q.open if live else None)
        return RowData(info, res, self._note(info, res))

    def rows(self, today: date) -> list[RowData]:
        return [self.row(i.id, today) for i in self.universe]

    @staticmethod
    def _note(info: IndexInfo, res: ReturnSet) -> str:
        when = res.as_of.strftime("%d %b %Y") if res.as_of else "no data yet"
        if info.source == "amfi":
            return f"NAV of {info.nav_fund_name} · {when}"
        if info.source == "none":
            return "No data source for this index"
        return "Live (Kite)" if res.live else f"Last close · {when}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/screener/test_service.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add screener/service.py tests/screener/test_service.py
git commit -m "feat(screener): Qt-free service for backfill, NAVs, live quotes and rows"
```

---

### Task 7: Table model and sort/filter proxy

**Files:**
- Create: `screener/ui/__init__.py`, `screener/ui/table_model.py`, `tests/screener/test_table_model.py`

**Interfaces:**
- Consumes: `RowData`, `PERIODS`
- Produces:
  - `COLUMNS: list[str]` = `["Category","Index","ETFs","Index Funds","Gap %","Day %", *PERIODS]`, `SORT_ROLE`, `fmt_pct(v) -> str`
  - `ScreenerTableModel(parent=None)`: `set_rows(rows: list[RowData])`, `update_rows(rows: list[RowData], flash=True)` (ignores ids not in the model), `expire_flash()`
  - `ScreenerProxy(parent=None)`: `set_category(text: str)` ("All" clears), `set_search(text: str)`; blanks sort last in both directions

- [ ] **Step 1: Write the failing tests**

`tests/screener/test_table_model.py`:

```python
from datetime import date

from PySide6.QtCore import Qt

from screener.returns import ReturnSet
from screener.service import RowData
from screener.ui.table_model import COLUMNS, ScreenerProxy, ScreenerTableModel, fmt_pct
from tests.screener.helpers import make_info


def row(id, one_year, category="Broad Market", etfs=("A ETF",), live=True, source="kite"):
    r = ReturnSet(as_of=date(2026, 11, 23), latest=1.0, gap=0.01, day=0.02, live=live)
    r.periods["1Y"] = one_year
    return RowData(make_info(id, category=category, etfs=etfs, source=source,
                             code=1 if source == "amfi" else None), r, "note")


def build(qapp, rows):
    m = ScreenerTableModel()
    m.set_rows(rows)
    p = ScreenerProxy()
    p.setSourceModel(m)
    return m, p


def names(p):
    return [p.index(i, 1).data() for i in range(p.rowCount())]


def test_formatting():
    assert fmt_pct(0.0123) == "+1.23%" and fmt_pct(-0.5) == "-50.00%" and fmt_pct(None) == "—"


def test_sort_desc_and_asc_keep_blanks_last(qapp):
    m, p = build(qapp, [row("NIFTY A", 0.10), row("NIFTY B", None), row("NIFTY C", -0.05)])
    col = COLUMNS.index("1Y")
    p.sort(col, Qt.DescendingOrder)
    assert names(p) == ["Nifty A", "Nifty C", "Nifty B"]
    p.sort(col, Qt.AscendingOrder)
    assert names(p) == ["Nifty C", "Nifty A", "Nifty B"]


def test_category_and_search_filters(qapp):
    m, p = build(qapp, [row("NIFTY BANK", 0.1, category="Sector", etfs=("Bank BeES",)),
                        row("NIFTY 50", 0.1)])
    p.set_category("Sector")
    assert names(p) == ["Nifty Bank"]
    p.set_category("All")
    p.set_search("bees")                               # matches fund names, case-insensitive
    assert names(p) == ["Nifty Bank"]
    p.set_search("")
    assert p.rowCount() == 2


def test_colours_grey_gap_and_nav_marker(qapp):
    m, _ = build(qapp, [row("NIFTY A", -0.1, live=False), row("NIFTY SDL", 0.05, source="amfi")])
    one_year = COLUMNS.index("1Y")
    assert m.index(0, one_year).data(Qt.ForegroundRole).name() == "#c62828"
    assert m.index(0, COLUMNS.index("Gap %")).data(Qt.ForegroundRole).name() == "#8a8a8a"
    assert m.index(1, 1).data() == "Nifty Sdl · NAV"


def test_update_rows_changes_values_and_flashes(qapp):
    m, _ = build(qapp, [row("NIFTY A", 0.1)])
    m.update_rows([row("NIFTY A", 0.2), row("NOT IN MODEL", 0.3)])
    assert m.index(0, COLUMNS.index("1Y")).data() == "+20.00%"
    assert m.index(0, COLUMNS.index("Day %")).data(Qt.BackgroundRole) is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/screener/test_table_model.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screener.ui'`

- [ ] **Step 3: Implement the model and proxy**

`screener/ui/__init__.py`: empty file.

`screener/ui/table_model.py`:

```python
"""Qt table model + sort/filter proxy for one screener tab."""
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from screener.returns import PERIODS
from screener.service import RowData

COLUMNS = ["Category", "Index", "ETFs", "Index Funds", "Gap %", "Day %", *PERIODS]
NUM_START = 4
GAP_COL, DAY_COL = 4, 5
SORT_ROLE = Qt.UserRole + 1
GREEN, RED, GREY = QColor("#1a7f37"), QColor("#c62828"), QColor("#8a8a8a")
FLASH = QColor("#fff3bf")
FLASH_SECONDS = 1.5


def fmt_pct(v) -> str:
    return "—" if v is None else f"{v * 100:+.2f}%"


class ScreenerTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[RowData] = []
        self._pos: dict[str, int] = {}
        self._flash: dict[str, float] = {}

    # ----- structure -----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    # ----- updates -----
    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._pos = {r.info.id: n for n, r in enumerate(self._rows)}
        self._flash.clear()
        self.endResetModel()

    def update_rows(self, rows, flash: bool = True) -> None:
        for r in rows:
            n = self._pos.get(r.info.id)
            if n is None:
                continue
            self._rows[n] = r
            if flash:
                self._flash[r.info.id] = time.monotonic()
            self.dataChanged.emit(self.index(n, 0), self.index(n, len(COLUMNS) - 1))

    def expire_flash(self) -> None:
        now = time.monotonic()
        for ix, t in list(self._flash.items()):
            if now - t > FLASH_SECONDS:
                del self._flash[ix]
                n = self._pos[ix]
                self.dataChanged.emit(self.index(n, GAP_COL), self.index(n, DAY_COL))

    # ----- data -----
    @staticmethod
    def _value(row: RowData, col: int):
        res = row.result
        if col == GAP_COL:
            return res.gap
        if col == DAY_COL:
            return res.day
        return res.periods[COLUMNS[col]]

    @staticmethod
    def _text(row: RowData, col: int) -> str:
        info = row.info
        if col == 0:
            return info.category
        if col == 1:
            return f"{info.display_name} · NAV" if info.source == "amfi" else info.display_name
        funds = info.etfs if col == 2 else info.index_funds
        return "\n".join(funds) or "—"

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = self._rows[index.row()], index.column()
        if col < NUM_START:
            if role in (Qt.DisplayRole, SORT_ROLE):
                return self._text(row, col)
            if role == Qt.ToolTipRole and col == 1:
                return row.note
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignLeft | Qt.AlignTop)
            return None
        v = self._value(row, col)
        if role == Qt.DisplayRole:
            return fmt_pct(v)
        if role == SORT_ROLE:
            return v
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignTop)
        if role == Qt.ForegroundRole:
            if v is None or (col == GAP_COL and not row.result.live):
                return GREY
            return GREEN if v > 0 else RED if v < 0 else None
        if role == Qt.BackgroundRole and col in (GAP_COL, DAY_COL) and row.info.id in self._flash:
            return FLASH
        if role == Qt.ToolTipRole:
            return self._tooltip(row, col, v)
        return None

    @staticmethod
    def _tooltip(row: RowData, col: int, v) -> str:
        if v is not None:
            return row.note
        if col == GAP_COL and row.info.source == "amfi":
            return "NAVs have no opening value"
        if row.result.as_of is None:
            return "No data stored yet - connect to load history"
        if col > DAY_COL:
            return f"Not enough history for {COLUMNS[col]}"
        return "Not available"


class ScreenerProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self._category = ""
        self._text = ""

    def set_category(self, category: str) -> None:
        self._category = "" if category in ("", "All") else category
        self.invalidateFilter()

    def set_search(self, text: str) -> None:
        self._text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, src_row, src_parent):
        m = self.sourceModel()
        cell = lambda c: m.index(src_row, c, src_parent).data()
        if self._category and cell(0) != self._category:
            return False
        if self._text:
            return self._text in " ".join(str(cell(c)) for c in (1, 2, 3)).lower()
        return True

    def lessThan(self, left, right):
        a, b = left.data(SORT_ROLE), right.data(SORT_ROLE)
        if a is None or b is None:
            if a is None and b is None:
                return False
            # Blanks always last: Qt reverses lessThan for descending order.
            left_blank = a is None
            return left_blank if self.sortOrder() == Qt.DescendingOrder else not left_blank
        return a < b
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/screener/test_table_model.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add screener/ui/__init__.py screener/ui/table_model.py tests/screener/test_table_model.py
git commit -m "feat(screener): sortable, filterable table model with blanks-last sorting"
```

---

### Task 8: Controller, main window and app entry

**Files:**
- Create: `screener/controller.py`, `screener/ui/main_window.py`, `screener/app.py`, `tests/screener/test_app_smoke.py`

**Interfaces:**
- Consumes: `ScreenerService`, `KiteClient`, `LiveFeed`, `TokenError`, `fetch_nav_bars`, `ScreenerTableModel`, `ScreenerProxy`, `COLUMNS`, config helpers
- Produces:
  - `Controller(service, api_key=None, feed_factory=LiveFeed, client_factory=KiteClient, nav_fetch=None, pool=None)` with signals `status(str state, str msg)` (state ∈ `live|offline|busy|error`), `progress(int done, int total)` (0,0 hides), `rows_reset(list)`, `rows_updated(list)`, `updated_at(str)`, `message(str)`; methods `start()`, `connect_kite(token: str)`, `refresh_history()`, `shutdown()`
  - `MainWindow(controller, universe)` with attributes `token`, `connect_btn`, `refresh_btn`, `status_lbl`, `updated_lbl`, `equity: TabView`, `debt: TabView`; `TabView.model`, `TabView.proxy`, `TabView.table`
  - `screener.app.main(argv=None) -> int` (supports `--selftest`)

- [ ] **Step 1: Write the failing smoke test**

`tests/screener/test_app_smoke.py`:

```python
from datetime import datetime

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from screener.config import IST
from screener.controller import Controller
from screener.db import BarStore
from screener.kite_client import Quote
from screener.returns import Bar
from screener.service import ScreenerService
from screener.ui.main_window import MainWindow
from tests.screener.helpers import make_info


class FakeClient:
    def __init__(self, api_key, token):
        self.token = token

    def validate(self):
        return "Tester"

    def daily_bars(self, token, start, end):
        return [Bar(end, 100.0, 100.0)]


class FakeFeed:
    instances = []

    def __init__(self, api_key, token, tokens, on_quotes, on_status):
        self.args = (api_key, token, list(tokens))
        self.on_quotes, self.on_status = on_quotes, on_status
        self.stopped = False
        FakeFeed.instances.append(self)

    def start(self):
        now = datetime.now(IST).replace(tzinfo=None)   # Kite sends naive IST timestamps
        self.on_status("live", "")
        self.on_quotes([Quote(1, 103.0, 101.0, 100.0, now)])

    def stop(self):
        self.stopped = True


def settle(pool):
    pool.waitForDone(5000)
    for _ in range(5):
        QApplication.processEvents()


def test_window_offline_then_live(qapp, tmp_path):
    universe = [make_info("NIFTY 50", token=1),
                make_info("NIFTY SDL APR 2027", tab="debt", category="Target Maturity", source="amfi", code=7)]
    store = BarStore(tmp_path / "t.db")
    pool = QThreadPool()
    c = Controller(ScreenerService(universe, store), api_key="key", feed_factory=FakeFeed,
                   client_factory=FakeClient, pool=pool,
                   nav_fetch=lambda code: [Bar(datetime(2026, 11, 19).date(), None, 10.0),
                                           Bar(datetime(2026, 11, 20).date(), None, 10.1)])
    w = MainWindow(c, universe)
    c.start()
    settle(pool)
    assert w.equity.model.rowCount() == 1 and w.debt.model.rowCount() == 1
    assert "🟡" in w.status_lbl.text()
    assert w.debt.proxy.index(0, 5).data() == "+1.00%"          # Day % from NAVs

    w.token.setText("secret-token")
    w.connect_btn.click()
    assert w.token.text() == ""                                  # token not kept in the box
    settle(pool)
    assert FakeFeed.instances[-1].args == ("key", "secret-token", [1])
    assert "🟢" in w.status_lbl.text()
    assert w.equity.proxy.index(0, 5).data() == "+3.00%"        # live Day % vs stored 100
    assert w.equity.proxy.index(0, 4).data() == "+1.00%"        # Gap %
    assert w.updated_lbl.text().startswith("Last updated")

    w.connect_btn.click()                                        # second connect is refused
    assert "restart" in w.status_lbl.text().lower()
    c.shutdown()
    assert FakeFeed.instances[-1].stopped
    store.close()


def test_selftest_runs_without_window(capsys):
    from screener.app import main
    assert main(["--selftest"]) == 0
    assert "selftest ok" in capsys.readouterr().out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/screener/test_app_smoke.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screener.controller'`

- [ ] **Step 3: Implement the controller**

`screener/controller.py`:

```python
"""Bridges the Qt UI and ScreenerService: runs network work on a thread pool and
marshals Kite ticker callbacks onto the Qt main thread. Never logs the token."""
import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from screener.amfi_client import fetch_nav_bars
from screener.config import app_dir, load_api_key, now_ist, today_ist
from screener.kite_client import KiteClient, LiveFeed, TokenError
from screener.service import ScreenerService

log = logging.getLogger(__name__)


class _JobSignals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn, signals: _JobSignals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            result = self.fn()
        except Exception as e:  # noqa: BLE001 - reported to the UI
            log.exception("background job failed")
            self.signals.failed.emit(e)
            return
        self.signals.done.emit(result)


class Controller(QObject):
    status = Signal(str, str)
    progress = Signal(int, int)
    rows_reset = Signal(list)
    rows_updated = Signal(list)
    updated_at = Signal(str)
    message = Signal(str)
    _quotes_in = Signal(list)       # ticker thread -> main thread
    _status_in = Signal(str, str)

    def __init__(self, service: ScreenerService, api_key=None, feed_factory=LiveFeed,
                 client_factory=KiteClient, nav_fetch=None, pool=None):
        super().__init__()
        self.service = service
        self.api_key = load_api_key() if api_key is None else api_key
        self._feed_factory, self._client_factory = feed_factory, client_factory
        self._nav_fetch = nav_fetch or (lambda code: fetch_nav_bars(code, app_dir() / "nav_cache"))
        self._pool = pool or QThreadPool.globalInstance()
        self._feed = None
        self._client = None
        self._jobs: set = set()
        self._quotes_in.connect(self._on_quotes)
        self._status_in.connect(self._on_feed_status)
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._minute_tick)
        self._timer.start()

    # ----- helpers -----
    def _run(self, fn, on_done, on_error=None) -> None:
        sig = _JobSignals()
        self._jobs.add(sig)
        sig.done.connect(on_done)
        sig.failed.connect(on_error or self._on_job_error)
        sig.done.connect(lambda *_: self._jobs.discard(sig))
        sig.failed.connect(lambda *_: self._jobs.discard(sig))
        self._pool.start(_Job(fn, sig))

    def _emit_rows(self) -> None:
        self.rows_reset.emit(self.service.rows(today_ist()))
        self.updated_at.emit(now_ist().strftime("%H:%M:%S"))

    # ----- public -----
    def start(self) -> None:
        self._emit_rows()
        self.status.emit("offline", "Not connected - showing last stored closes")
        self.refresh_history()

    def refresh_history(self) -> None:
        client = self._client

        def work():
            failed = self.service.refresh_amfi(self._nav_fetch)
            if client is not None:
                failed += self.service.backfill_kite(client, today_ist(), progress=self.progress.emit)
            return failed

        self._run(work, self._after_history)

    def connect_kite(self, token: str) -> None:
        if self._feed is not None:
            self.status.emit("error", "Already connected - restart the app to use a new token")
            return
        try:
            client = self._client_factory(self.api_key, token)
        except TokenError as e:
            self.status.emit("error", str(e))
            return
        self.status.emit("busy", "Checking token and loading history…")

        def work():
            client.validate()
            return self.service.backfill_kite(client, today_ist(), progress=self.progress.emit)

        self._run(work, lambda failed: self._go_live(client, token, failed))

    def shutdown(self) -> None:
        self._timer.stop()
        if self._feed is not None:
            self._feed.stop()

    # ----- slots -----
    def _after_history(self, failed) -> None:
        self.progress.emit(0, 0)
        self._emit_rows()
        if failed:
            self.message.emit(f"Could not update {len(failed)} indices - see screener.log")

    def _go_live(self, client, token: str, failed) -> None:
        self._client = client
        self._after_history(failed)
        self._feed = self._feed_factory(self.api_key, token, self.service.kite_tokens(),
                                        on_quotes=self._quotes_in.emit, on_status=self._status_in.emit)
        self._feed.start()

    def _on_quotes(self, quotes) -> None:
        changed = self.service.apply_quotes(quotes)
        today = today_ist()
        self.rows_updated.emit([self.service.row(ix, today) for ix in changed])
        self.updated_at.emit(now_ist().strftime("%H:%M:%S"))

    def _on_feed_status(self, state: str, msg: str) -> None:
        if state == "live":
            self.status.emit("live", "Live")
        elif state == "reconnecting":
            self.status.emit("busy", f"Reconnecting… {msg}")
        elif state == "error" and "403" in msg:
            self.status.emit("error", "Token expired - restart the app and paste today's token")
        else:
            self.status.emit("offline", f"Live feed {state}. Showing last data. {msg}".strip())

    def _on_job_error(self, exc) -> None:
        self.progress.emit(0, 0)
        if isinstance(exc, TokenError):
            self.status.emit("error", "Token invalid or expired - paste today's token")
        else:
            self.status.emit("error", f"{type(exc).__name__}: {exc}")

    def _minute_tick(self) -> None:
        if self.service.capture_closes(now_ist()):
            log.info("stored today's closes")
```

- [ ] **Step 4: Implement the main window**

`screener/ui/main_window.py`:

```python
"""Main window: token bar, Equity/Debt tabs, progress and messages."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QProgressBar, QPushButton, QTableView, QTabWidget,
                               QVBoxLayout, QWidget)

from screener.ui.table_model import COLUMNS, ScreenerProxy, ScreenerTableModel

EQUITY_FOOTER = ("Price index returns from Kite (excluding dividends). 1Y and shorter are plain "
                 "returns; 2Y, 3Y and 5Y are annualised (CAGR). Hover a cell to see its source.")
DEBT_FOOTER = ("Rows marked '· NAV' use the tracking fund's NAV (previous business day) and have "
               "no Gap %. Bharat Bond, 10 Yr and 8-13 Yr G-Sec rows are live from Kite.")
STATUS_ICON = {"live": "🟢", "offline": "🟡", "busy": "🟡", "error": "🔴"}
COL_WIDTHS = [120, 230, 260, 260] + [72] * (len(COLUMNS) - 4)


class TabView(QWidget):
    def __init__(self, categories, footer: str, parent=None):
        super().__init__(parent)
        self.model = ScreenerTableModel(self)
        self.proxy = ScreenerProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setDynamicSortFilter(True)

        self.category = QComboBox()
        self.category.addItems(["All", *categories])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search index or fund…")
        self.search.setClearButtonEnabled(True)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._on_header)
        for c, w in enumerate(COL_WIDTHS):
            self.table.setColumnWidth(c, w)
        self._sort_col, self._sort_order = COLUMNS.index("1Y"), Qt.DescendingOrder
        self._apply_sort()

        self.category.currentTextChanged.connect(self.proxy.set_category)
        self.search.textChanged.connect(self.proxy.set_search)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Category"))
        bar.addWidget(self.category)
        bar.addWidget(self.search, 1)
        footer_lbl = QLabel(footer)
        footer_lbl.setWordWrap(True)
        footer_lbl.setStyleSheet("color:#666")
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.table, 1)
        layout.addWidget(footer_lbl)

    def _on_header(self, col: int) -> None:
        # First click on a column sorts descending; clicking again toggles.
        if col == self._sort_col:
            self._sort_order = (Qt.AscendingOrder if self._sort_order == Qt.DescendingOrder
                                else Qt.DescendingOrder)
        else:
            self._sort_col, self._sort_order = col, Qt.DescendingOrder
        self._apply_sort()

    def _apply_sort(self) -> None:
        self.proxy.sort(self._sort_col, self._sort_order)
        self.table.horizontalHeader().setSortIndicator(self._sort_col, self._sort_order)

    def set_rows(self, rows) -> None:
        self.model.set_rows(rows)
        self.table.resizeRowsToContents()


class MainWindow(QMainWindow):
    def __init__(self, controller, universe):
        super().__init__()
        self.c = controller
        self.setWindowTitle("NSE Index Screener")

        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Paste today's Kite access token")
        self.token.setMinimumWidth(320)
        self.connect_btn = QPushButton("Connect")
        self.refresh_btn = QPushButton("Refresh history")
        self.status_lbl = QLabel()
        self.updated_lbl = QLabel("Last updated —")

        top = QHBoxLayout()
        top.addWidget(QLabel("Access token"))
        top.addWidget(self.token)
        top.addWidget(self.connect_btn)
        top.addSpacing(16)
        top.addWidget(self.status_lbl, 1)
        top.addWidget(self.updated_lbl)
        top.addWidget(self.refresh_btn)

        def cats(tab):
            return list(dict.fromkeys(i.category for i in universe if i.tab == tab))

        self.equity = TabView(cats("equity"), EQUITY_FOOTER)
        self.debt = TabView(cats("debt"), DEBT_FOOTER)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.equity, "Equity")
        self.tabs.addTab(self.debt, "Debt")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.progress = QProgressBar()
        self.progress.setFormat("Loading history %v/%m")
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)

        self.connect_btn.clicked.connect(self._on_connect)
        self.token.returnPressed.connect(self._on_connect)
        self.refresh_btn.clicked.connect(controller.refresh_history)
        controller.status.connect(self._on_status)
        controller.progress.connect(self._on_progress)
        controller.rows_reset.connect(self._on_rows_reset)
        controller.rows_updated.connect(self._on_rows_updated)
        controller.updated_at.connect(lambda t: self.updated_lbl.setText(f"Last updated {t}"))
        controller.message.connect(lambda m: self.statusBar().showMessage(m, 15000))

        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(500)
        self._flash_timer.timeout.connect(self._expire_flash)
        self._flash_timer.start()
        self._on_status("offline", "Not connected")

    def _on_connect(self) -> None:
        token = self.token.text()
        self.token.clear()          # don't keep the token on screen
        self.c.connect_kite(token)

    def _on_status(self, state: str, msg: str) -> None:
        self.status_lbl.setText(f"{STATUS_ICON.get(state, '🟡')} {msg}")

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setVisible(total > 0)
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)

    def _on_rows_reset(self, rows) -> None:
        self.equity.set_rows([r for r in rows if r.info.tab == "equity"])
        self.debt.set_rows([r for r in rows if r.info.tab == "debt"])

    def _on_rows_updated(self, rows) -> None:
        self.equity.model.update_rows(rows)
        self.debt.model.update_rows(rows)

    def _expire_flash(self) -> None:
        self.equity.model.expire_flash()
        self.debt.model.expire_flash()
```

- [ ] **Step 5: Implement the entry point**

`screener/app.py`:

```python
"""Entry point:  python3 -m screener.app   (or the packaged NSEScreener executable).
--selftest loads the bundled universe and core modules without opening a window."""
import argparse
import logging
import sys
import tempfile
from pathlib import Path


def _selftest() -> int:
    import screener.controller  # noqa: F401 - proves Qt + kiteconnect are bundled
    from screener.config import app_dir, load_api_key, today_ist
    from screener.db import BarStore
    from screener.service import ScreenerService
    from screener.universe import load_universe

    universe = load_universe()
    with tempfile.TemporaryDirectory() as d:
        store = BarStore(Path(d) / "selftest.db")
        rows = ScreenerService(universe, store).rows(today_ist())
        store.close()
    equity = sum(i.tab == "equity" for i in universe)
    msg = (f"selftest ok: {len(universe)} indices ({equity} equity, {len(universe) - equity} debt), "
           f"{len(rows)} rows, API key {'set' if load_api_key() else 'MISSING'}")
    print(msg)
    try:
        (app_dir() / "selftest.txt").write_text(msg + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NSE Index Screener")
    ap.add_argument("--selftest", action="store_true", help="check the bundle and exit")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()

    from PySide6.QtWidgets import QApplication

    from screener.config import app_dir
    from screener.controller import Controller
    from screener.db import BarStore
    from screener.service import ScreenerService
    from screener.ui.main_window import MainWindow
    from screener.universe import load_universe

    logging.basicConfig(filename=str(app_dir() / "screener.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv[:1])
    universe = load_universe()
    store = BarStore(app_dir() / "screener.db")
    controller = Controller(ScreenerService(universe, store))
    window = MainWindow(controller, universe)
    window.resize(1500, 850)
    window.show()
    controller.start()
    code = app.exec()
    controller.shutdown()
    store.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run the smoke tests to verify they pass**

Run: `python3 -m pytest tests/screener/test_app_smoke.py -q`
Expected: `2 passed`

- [ ] **Step 7: Run the whole screener suite**

Run: `python3 -m pytest tests/screener -q`
Expected: `40 passed`

- [ ] **Step 8: Launch the app manually (no token)**

Run: `python3 -m screener.app`
Expected: the window opens with the Equity tab (89 rows) and the Debt tab (41 rows) and a 🟡 status. Debt rows fill in after a few seconds from AMFI; equity rows stay "—" until you connect. Close the window.

- [ ] **Step 9: Commit**

```bash
git add screener/controller.py screener/ui/main_window.py screener/app.py tests/screener/test_app_smoke.py
git commit -m "feat(screener): Qt controller, main window and app entry point"
```

---

### Task 9: Live probe script (run with the user's token)

**Files:**
- Create: `screener/probe_kite.py`

**Interfaces:**
- Consumes: `KiteClient`, `TokenError`, `compute_returns`, `months_back`, `load_universe`, `ranking.index_dashboard.load_index_returns(folder, match_index) -> (DataFrame indexed by canonical id with r1m/r3m columns, as_of: date)`, `fetch_etf_index_data.match_index`
- Produces: `python3 -m screener.probe_kite` (interactive; the token is read with `getpass`, so it's never echoed or stored)

- [ ] **Step 1: Write the probe**

`screener/probe_kite.py`:

```python
"""One-off check of your Kite access. Run from the repo root:
    python3 -m screener.probe_kite
It asks for today's access token (not echoed), confirms historical-data access, reports how far
back daily history goes for every Kite index, and compares 1M/3M with NSE's latest Index Dashboard
(TRI, so small differences of a few tenths of a percent are expected)."""
import getpass
from datetime import timedelta

from screener.config import HISTORY_MONTHS, HISTORY_PAD_DAYS, load_api_key, today_ist
from screener.kite_client import KiteClient, TokenError
from screener.returns import compute_returns, months_back
from screener.universe import load_universe


def _dashboard():
    try:
        from fetch_etf_index_data import match_index
        from ranking.index_dashboard import load_index_returns
        return load_index_returns("data/index_dashboards", match_index)
    except Exception as e:  # noqa: BLE001
        print(f"(No NSE dashboard comparison: {e})")
        return None, None


def main() -> int:
    token = getpass.getpass("Kite access token: ")
    try:
        client = KiteClient(load_api_key(), token)
        print("Connected as", client.validate())
    except TokenError as e:
        print("Token problem:", e)
        return 1
    dash, dash_asof = _dashboard()
    today = today_ist()
    start = months_back(today, HISTORY_MONTHS) - timedelta(days=HISTORY_PAD_DAYS)
    short = []
    for info in (i for i in load_universe() if i.source == "kite"):
        try:
            bars = client.daily_bars(info.kite_instrument_token, start, today - timedelta(days=1))
        except Exception as e:  # noqa: BLE001
            print(f"{info.display_name:48} ERROR {e}")
            continue
        first = bars[0].date if bars else None
        line = f"{info.display_name:48} {len(bars):5d} days from {first}"
        if first is None or first > start + timedelta(days=14):
            short.append(info.display_name)
        if dash is not None and info.id in dash.index and bars:
            r = compute_returns([b for b in bars if b.date <= dash_asof], dash_asof)
            d = dash.loc[info.id]
            for p, col in (("1M", "r1m"), ("3M", "r3m")):
                if r.periods[p] is not None and d[col] == d[col]:
                    line += f" | {p} Kite {r.periods[p] * 100:+.2f}% vs NSE {d[col] * 100:+.2f}%"
        print(line)
    print(f"\n{len(short)} indices have less than 5 years of history "
          "(their 3Y/5Y will show '—' until enough data exists):")
    for name in short:
        print("  -", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Check it imports cleanly**

Run: `python3 -c "import screener.probe_kite; print('ok')"`
Expected: `ok`

- [ ] **Step 3: User runs the probe with a live token** (manual; done by the user, not an agent)

Prerequisite: create `screener/secrets_local.py` from the example with the real API key.
Run: `python3 -m screener.probe_kite` and paste today's access token at the prompt.
Expected: "Connected as …", one line per index (95 in all) with day counts, 1M/3M within ~0.5% of NSE for most indices, and a list of indices with short history. Any `ERROR` lines or a permission error mean historical data isn't enabled on the Kite plan.

- [ ] **Step 4: Commit**

```bash
git add screener/probe_kite.py
git commit -m "feat(screener): live probe script for Kite access and history depth"
```

---

### Task 10: Packaging and build instructions

**Files:**
- Create: `screener/NSEScreener.spec`, `screener/BUILD.md`

**Interfaces:**
- Consumes: `screener/app.py` (`--selftest`), `screener/universe.json`, `screener/secrets_local.py` (must exist at build time)
- Produces: `dist/NSEScreener` (macOS) / `dist/NSEScreener.exe` (Windows)

- [ ] **Step 1: Write the PyInstaller spec**

`screener/NSEScreener.spec`:

```python
# PyInstaller spec. Build from the repo root:  pyinstaller screener/NSEScreener.spec
# Requires screener/secrets_local.py to exist (its API key is bundled into the executable).
from pathlib import Path

root = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller

a = Analysis(
    [str(root / "screener" / "app.py")],
    pathex=[str(root)],
    datas=[(str(root / "screener" / "universe.json"), "screener")],
    hiddenimports=["screener.secrets_local", "autobahn.twisted.websocket", "twisted.internet.reactor"],
    excludes=["matplotlib", "tkinter", "IPython"],
)
pyz = PYZ(a.pure)
# Passing binaries + datas straight to EXE (no COLLECT step) produces a one-file build.
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="NSEScreener",
          console=False, upx=False)
```

- [ ] **Step 2: Write the build guide**

`screener/BUILD.md`:

````markdown
# Building NSE Index Screener

PyInstaller builds for the OS it runs on: build the Windows `.exe` on a Windows PC and the
macOS app on a Mac.

## One-time setup (either OS)

1. Install Python 3.12 or 3.13 and Git, then clone this repository.
2. From the repo root:
   ```
   pip install -r requirements.txt
   ```
3. Copy `screener/secrets_local.example.py` to `screener/secrets_local.py` and put your Kite
   Connect API key in it. **Anyone who has the built executable can extract this key.**
   The API secret is not needed.

## Build

```
python -m pytest tests/screener -q
pyinstaller --noconfirm screener/NSEScreener.spec
dist/NSEScreener --selftest          # Windows: dist\NSEScreener.exe --selftest
```

The self-test prints (and writes to `selftest.txt` next to the executable)
`selftest ok: 130 indices (89 equity, 41 debt), 130 rows, API key set`.

## Using the app

1. Put `NSEScreener(.exe)` in its own folder. It creates `screener.db`, `screener.log`
   and `nav_cache/` next to itself.
2. Open it, paste today's Kite access token, click **Connect**.
   The first connection downloads ~5 years of history (about a minute). Later ones only fetch
   missing days.
3. The token is kept in memory only. Tokens expire daily (around 6 am), so restart the app
   and paste the new token each morning.

## Updating the index list

After re-running the ranking pipeline (`run_ranking.py`, `compute_returns.py`):
```
python -m screener.build_universe
```
then rebuild. Indices added this way start with empty history and fill in on the next Connect.
````

- [ ] **Step 3: Build and self-test on the Mac**

Run (requires `screener/secrets_local.py`; for a dry build, copy the example to it first):
```bash
test -f screener/secrets_local.py || cp screener/secrets_local.example.py screener/secrets_local.py
pyinstaller --noconfirm screener/NSEScreener.spec
dist/NSEScreener --selftest
```
Expected last line: `selftest ok: 130 indices (89 equity, 41 debt), 130 rows, API key set`

If PyInstaller reports a missing module at runtime, add it to `hiddenimports` in the spec and rebuild.

- [ ] **Step 4: Commit**

```bash
git add screener/NSEScreener.spec screener/BUILD.md
git commit -m "build(screener): PyInstaller spec and build/usage guide"
```

---

## Spec coverage

| Spec section | Task |
|---|---|
| §3 UI (token bar, status, last updated, Refresh history, tabs, sort, filter, search, colours, flash, footers, tooltips, NAV marker) | 7, 8 |
| §4 components, §4.1 universe.json + aliases + fail-loud, §4.2 schema | 1–6, 3, 2 |
| §5 data flow (start offline, connect, backfill + resume, live, end-of-day capture, AMFI refresh) | 6, 8 |
| §6 returns definitions and rules, IST | 1, 6 |
| §7 error handling (token, reconnect, retries, isolation, AMFI stale, logging) | 5, 6, 8 |
| §8 secrets and token | 1, 8, 10 |
| §9 testing incl. probe | every task, 9 |
| §10 packaging | 10 |
