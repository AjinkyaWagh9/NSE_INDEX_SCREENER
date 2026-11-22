"""Entry point:  python3 -m screener.desktop.app   (or the packaged NSEScreener executable).
--selftest loads the bundled universe and core modules without opening a window."""
import argparse
import logging
import sys
import tempfile
from pathlib import Path


def _selftest() -> int:
    import screener.desktop.controller  # noqa: F401 - proves Qt + kiteconnect are bundled
    from screener.core.config import app_dir, load_api_key, load_api_secret, today_ist
    from screener.core.db import BarStore
    from screener.core.service import ScreenerService
    from screener.core.universe import load_universe

    universe = load_universe()
    with tempfile.TemporaryDirectory() as d:
        store = BarStore(Path(d) / "selftest.db")
        rows = ScreenerService(universe, store).rows(today_ist())
        store.close()
    equity = sum(i.tab == "equity" for i in universe)
    msg = (f"selftest ok: {len(universe)} indices ({equity} equity, {len(universe) - equity} debt), "
           f"{len(rows)} rows, API key {'set' if load_api_key() else 'MISSING'}, "
           f"API secret {'set' if load_api_secret() else 'not set (in-app login disabled)'}")
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

    from screener.core.config import app_dir
    from screener.core.db import BarStore
    from screener.core.service import ScreenerService
    from screener.core.universe import load_universe
    from screener.desktop.controller import Controller
    from screener.desktop.ui.main_window import MainWindow

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
