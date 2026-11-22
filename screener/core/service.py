"""Qt-free orchestration: history fill-in, AMFI refresh, live quotes -> table rows.
Used unchanged by the desktop app and, later, the web backend."""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional

from screener.core.config import HISTORY_MONTHS, HISTORY_PAD_DAYS, IST, MARKET_CLOSE
from screener.core.db import BarRepository
from screener.core.kite_client import Quote, TokenError
from screener.core.returns import PERIODS, Bar, ReturnSet, compute_returns, months_back
from screener.core.universe import IndexInfo

log = logging.getLogger(__name__)


@dataclass
class RowData:
    info: IndexInfo
    result: ReturnSet
    note: str          # source description shown as a tooltip

    def to_dict(self) -> dict:
        """JSON-ready row for a web API (dates as ISO strings, returns as fractions)."""
        i, r = self.info, self.result
        return {
            "id": i.id, "name": i.display_name, "tab": i.tab, "category": i.category,
            "source": i.source, "etfs": list(i.etfs), "index_funds": list(i.index_funds),
            "as_of": r.as_of.isoformat() if r.as_of else None, "live": r.live,
            "latest": r.latest, "note": self.note,
            "returns": {"gap": r.gap, "day": r.day, **{p: r.periods[p] for p in PERIODS}},
        }


def _quote_date(q: Quote) -> Optional[date]:
    ts = q.timestamp
    if ts is None:
        return None
    return ts.date() if ts.tzinfo is None else ts.astimezone(IST).date()  # Kite sends naive IST


class ScreenerService:
    def __init__(self, universe: list[IndexInfo], store: BarRepository):
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
