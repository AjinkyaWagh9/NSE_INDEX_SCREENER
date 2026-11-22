"""Bridges the Qt UI and ScreenerService: runs network work on a thread pool and
marshals Kite ticker callbacks onto the Qt main thread. Never logs the token.
(A web backend replaces this file; ScreenerService stays the same.)"""
import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from screener.core.amfi_client import fetch_nav_bars
from screener.core.config import app_dir, load_api_key, now_ist, today_ist
from screener.core.kite_client import KiteClient, LiveFeed, TokenError
from screener.core.service import ScreenerService

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
