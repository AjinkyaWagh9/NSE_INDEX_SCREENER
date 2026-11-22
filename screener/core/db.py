"""Daily-bar storage. BarRepository is the interface the service depends on;
BarStore is the SQLite implementation used by the desktop app. A web app can supply
its own BarRepository (e.g. PostgreSQL) without touching the rest of core."""
import sqlite3
import threading
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Protocol

from screener.core.returns import Bar


class BarRepository(Protocol):
    def upsert_bars(self, index_id: str, bars: Iterable[Bar], source: str) -> int: ...
    def bars(self, index_id: str) -> list[Bar]: ...
    def last_date(self, index_id: str) -> Optional[date]: ...
    def close(self) -> None: ...


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
