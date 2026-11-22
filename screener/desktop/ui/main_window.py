"""Main window: token bar, Equity/Debt tabs, progress and messages."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QProgressBar, QPushButton, QTableView, QTabWidget,
                               QVBoxLayout, QWidget)

from screener.desktop.ui.table_model import COLUMNS, ScreenerProxy, ScreenerTableModel

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
