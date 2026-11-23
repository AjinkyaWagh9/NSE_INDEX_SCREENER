"""Main window: token bar, category tabs, progress and messages."""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QProgressBar, QPushButton, QTableView, QTabWidget,
                               QVBoxLayout, QWidget)

from screener.desktop.ui.table_model import COLUMNS, ScreenerProxy, ScreenerTableModel

EQUITY_FOOTER = ("Price index returns from Kite (excluding dividends). 1Y and shorter are plain "
                 "returns; 2Y, 3Y and 5Y are annualised (CAGR). Hover a cell to see its source.")
DEBT_FOOTER = ("Rows marked '· NAV' use the tracking fund's NAV (previous business day) and have "
               "no Gap %. Bharat Bond, 10 Yr and 8-13 Yr G-Sec rows are live from Kite.")
STATUS_ICON = {"live": "🟢", "offline": "🟡", "busy": "🟡", "error": "🔴"}
COL_WIDTHS = [140, 280, 0, 0] + [85] * (len(COLUMNS) - 4)
CATEGORIES = ["Broad Market", "Sector", "Thematic", "Strategy / Factor"]

APP_STYLE = """
QMainWindow, QWidget {
    background-color: #1e222d;
    color: #e2e8f0;
    font-size: 15px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

QLineEdit {
    background-color: #282d3b;
    border: 1px solid #3b4254;
    border-radius: 6px;
    padding: 7px 12px;
    color: #f8fafc;
    font-size: 15px;
}
QLineEdit:focus {
    border: 1px solid #38bdf8;
}

QComboBox {
    background-color: #282d3b;
    border: 1px solid #3b4254;
    border-radius: 6px;
    padding: 6px 14px;
    color: #f8fafc;
    font-size: 15px;
}
QComboBox QAbstractItemView {
    background-color: #282d3b;
    border: 1px solid #3b4254;
    selection-background-color: #384259;
    color: #f8fafc;
}

QPushButton {
    background-color: #282d3b;
    border: 1px solid #3d4659;
    border-radius: 6px;
    padding: 7px 16px;
    color: #f8fafc;
    font-size: 15px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #363e4f;
    border-color: #4f5b74;
}
QPushButton:pressed {
    background-color: #1e222d;
}

QTabWidget::pane {
    border: 1px solid #2a2f3d;
    background-color: #1e222d;
    border-radius: 6px;
}
QTabBar::tab {
    background-color: #252a37;
    color: #94a3b8;
    padding: 10px 22px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: 15px;
    font-weight: 600;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background-color: #1e222d;
    color: #38bdf8;
    border-bottom: 2px solid #38bdf8;
}
QTabBar::tab:hover:!selected {
    background-color: #2f3545;
    color: #e2e8f0;
}

QTableView {
    background-color: #161820;
    alternate-background-color: #1c202a;
    border: 1px solid #2a2f3d;
    border-radius: 6px;
    gridline-color: #252a36;
    color: #e2e8f0;
    font-size: 15px;
    selection-background-color: #2c3e5e;
    selection-color: #ffffff;
}
QHeaderView::section {
    background-color: #212530;
    color: #94a3b8;
    font-size: 14px;
    font-weight: 600;
    padding: 10px 8px;
    border: none;
    border-right: 1px solid #2a2f3d;
    border-bottom: 1px solid #2a2f3d;
}
QHeaderView::section:hover {
    background-color: #282d3b;
    color: #f1f5f9;
}

QScrollBar:vertical {
    border: none;
    background-color: #161820;
    width: 10px;
}
QScrollBar::handle:vertical {
    background-color: #333a4c;
    min-height: 25px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background-color: #475169;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background-color: #161820;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background-color: #333a4c;
    min-width: 25px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #475169;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QStatusBar {
    background-color: #1e222d;
    color: #94a3b8;
    border-top: 1px solid #2a2f3d;
    font-size: 13px;
}
"""


def open_in_browser(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


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
        self.search.setPlaceholderText("Search index…")
        self.search.setClearButtonEnabled(True)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._on_header)
        for c, w in enumerate(COL_WIDTHS):
            self.table.setColumnWidth(c, w)
        for col_name in ("ETFs", "Index Funds"):
            if col_name in COLUMNS:
                self.table.setColumnHidden(COLUMNS.index(col_name), True)

        self._sort_col, self._sort_order = COLUMNS.index("1Y"), Qt.DescendingOrder
        self._apply_sort()

        self.category.currentTextChanged.connect(self.proxy.set_category)
        self.search.textChanged.connect(self.proxy.set_search)

        bar = QHBoxLayout()
        search_lbl = QLabel("Search:")
        search_lbl.setStyleSheet("color: #94a3b8; font-size: 15px; font-weight: 500;")
        bar.addWidget(search_lbl)
        bar.addWidget(self.search, 1)

        footer_lbl = QLabel(footer)
        footer_lbl.setWordWrap(True)
        footer_lbl.setStyleSheet("color:#8b949e; font-size: 13px; padding-top: 4px;")
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
        self.setStyleSheet(APP_STYLE)

        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Paste the address after login (or an access token)")
        self.token.setMinimumWidth(360)
        self.login_btn = QPushButton("Login with Zerodha")
        self.connect_btn = QPushButton("Connect")
        self.refresh_btn = QPushButton("Refresh history")
        self.status_lbl = QLabel()
        self.updated_lbl = QLabel("Last updated —")

        top = QHBoxLayout()
        top.addWidget(self.login_btn)
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
        self.cat_views = {cat: TabView([cat], EQUITY_FOOTER) for cat in CATEGORIES}

        self.tabs = QTabWidget()
        self.tabs.addTab(self.equity, "All")
        for cat in CATEGORIES:
            self.tabs.addTab(self.cat_views[cat], cat)
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

        self.login_btn.clicked.connect(self._on_login)
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

    def _on_login(self) -> None:
        url = self.c.zerodha_login_url()
        if not url:
            self._on_status("error", "No Kite API key configured (screener/secrets_local.py)")
            return
        open_in_browser(url)
        self._on_status("busy", "Log in on Zerodha's page, then paste the address you land on here")
        self.token.setFocus()

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
        for cat, view in self.cat_views.items():
            view.set_rows([r for r in rows if r.info.category == cat])
        self.debt.set_rows([r for r in rows if r.info.tab == "debt"])

    def _on_rows_updated(self, rows) -> None:
        self.equity.model.update_rows(rows)
        for view in self.cat_views.values():
            view.model.update_rows(rows)
        self.debt.model.update_rows(rows)

    def _expire_flash(self) -> None:
        self.equity.model.expire_flash()
        for view in self.cat_views.values():
            view.model.expire_flash()
        self.debt.model.expire_flash()
