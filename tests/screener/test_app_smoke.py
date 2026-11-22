from datetime import date, datetime

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from screener.core.config import IST
from screener.core.db import BarStore
from screener.core.kite_client import Quote
from screener.core.returns import Bar
from screener.core.service import ScreenerService
from screener.desktop.controller import Controller
from screener.desktop.ui.main_window import MainWindow
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
                   nav_fetch=lambda code: [Bar(date(2026, 11, 19), None, 10.0),
                                           Bar(date(2026, 11, 20), None, 10.1)])
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
    from screener.desktop.app import main
    assert main(["--selftest"]) == 0
    assert "selftest ok" in capsys.readouterr().out
