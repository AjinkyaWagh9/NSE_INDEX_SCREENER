"""Thin wrapper over the official kiteconnect SDK: token check, daily history, live feed.
Read-only by design: no order APIs are used."""
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable, Optional

from kiteconnect import KiteConnect, KiteTicker
from kiteconnect import exceptions as kex

from screener.core.config import HIST_MIN_INTERVAL_S
from screener.core.returns import Bar

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


# ---------- daily login (option B): request token -> access token ----------
_REQUEST_TOKEN = re.compile(r"request_token=([A-Za-z0-9]+)")


def login_url(api_key: str) -> str:
    """Zerodha's login page for this app; after login it redirects with ?request_token=..."""
    return KiteConnect(api_key=api_key).login_url()


def extract_request_token(text: str) -> Optional[str]:
    """Pull the request token out of the redirected address (None if it isn't there)."""
    m = _REQUEST_TOKEN.search(text or "")
    return m.group(1) if m else None


def exchange_request_token(api_key: str, api_secret: str, redirect_text: str, kite=None) -> str:
    """Swap the request token from Zerodha's redirect for today's access token."""
    if not api_secret:
        raise TokenError("No Kite API secret configured (screener/secrets_local.py)")
    request_token = extract_request_token(redirect_text)
    if not request_token:
        raise TokenError("No request_token found - paste the whole address you landed on after login")
    kite = kite or KiteConnect(api_key=api_key)
    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
    except kex.TokenException as e:
        raise TokenError(f"Login expired or already used - log in again ({e})") from e
    return session["access_token"]


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
            raise TokenError(f"Token invalid or expired - log in again or paste today's token ({e})") from e

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
    thread, so the UI layer must marshal them to its own thread."""

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
