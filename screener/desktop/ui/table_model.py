"""Qt table model + sort/filter proxy for one screener tab."""
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from screener.core.returns import PERIODS
from screener.core.service import RowData

COLUMNS = ["Category", "Index", "ETFs", "Index Funds", "Gap %", "Day %", *PERIODS]
NUM_START = 4
GAP_COL, DAY_COL = 4, 5
SORT_ROLE = Qt.UserRole + 1
GREEN, RED, GREY = QColor("#22c55e"), QColor("#ef4444"), QColor("#8b949e")
FLASH = QColor("#2a3b52")
FLASH_SECONDS = 0.5


ZERO = 0.00005   # anything that rounds to 0.00% is shown (and coloured) as zero


def fmt_pct(v) -> str:
    if v is None:
        return "—"
    return "0.00%" if abs(v) < ZERO else f"{v * 100:+.2f}%"


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
            old_r = self._rows[n]
            changed = (old_r.result != r.result)
            self._rows[n] = r
            if flash and (changed or old_r.result.as_of is None):
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
            return GREEN if v >= ZERO else RED if v <= -ZERO else None
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

    def _refilter(self, apply) -> None:
        # Qt >= 6.10 replaces invalidateFilter() with begin/endFilterChange().
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            apply()
            self.endFilterChange()
        else:
            apply()
            self.invalidateFilter()

    def set_category(self, category: str) -> None:
        self._refilter(lambda: setattr(self, "_category", "" if category in ("", "All") else category))

    def set_search(self, text: str) -> None:
        self._refilter(lambda: setattr(self, "_text", text.strip().lower()))

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
