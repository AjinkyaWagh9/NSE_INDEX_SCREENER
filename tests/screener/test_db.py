from datetime import date

from screener.core.db import BarStore
from screener.core.returns import Bar


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
