from datetime import date

from PySide6.QtCore import Qt

from screener.core.returns import ReturnSet
from screener.core.service import RowData
from screener.desktop.ui.table_model import COLUMNS, ScreenerProxy, ScreenerTableModel, fmt_pct
from tests.screener.helpers import make_info


def row(id, one_year, category="Broad Market", etfs=("A ETF",), live=True, source="kite"):
    r = ReturnSet(as_of=date(2026, 11, 23), latest=1.0, gap=0.01, day=0.02, live=live)
    r.periods["1Y"] = one_year
    return RowData(make_info(id, category=category, etfs=etfs, source=source,
                             code=1 if source == "amfi" else None), r, "note")


def build(qapp, rows):
    m = ScreenerTableModel()
    m.set_rows(rows)
    p = ScreenerProxy()
    p.setSourceModel(m)
    return m, p


def names(p):
    return [p.index(i, 1).data() for i in range(p.rowCount())]


def test_formatting():
    assert fmt_pct(0.0123) == "+1.23%" and fmt_pct(-0.5) == "-50.00%" and fmt_pct(None) == "—"
    assert fmt_pct(-0.00004) == "0.00%" and fmt_pct(0.00004) == "0.00%"   # no red "-0.00%"


def test_sort_desc_and_asc_keep_blanks_last(qapp):
    m, p = build(qapp, [row("NIFTY A", 0.10), row("NIFTY B", None), row("NIFTY C", -0.05)])
    col = COLUMNS.index("1Y")
    p.sort(col, Qt.DescendingOrder)
    assert names(p) == ["Nifty A", "Nifty C", "Nifty B"]
    p.sort(col, Qt.AscendingOrder)
    assert names(p) == ["Nifty C", "Nifty A", "Nifty B"]


def test_category_and_search_filters(qapp):
    m, p = build(qapp, [row("NIFTY BANK", 0.1, category="Sector", etfs=("Bank BeES",)),
                        row("NIFTY 50", 0.1)])
    p.set_category("Sector")
    assert names(p) == ["Nifty Bank"]
    p.set_category("All")
    p.set_search("bees")                               # matches fund names, case-insensitive
    assert names(p) == ["Nifty Bank"]
    p.set_search("")
    assert p.rowCount() == 2


def test_colours_grey_gap_and_nav_marker(qapp):
    m, _ = build(qapp, [row("NIFTY A", -0.1, live=False), row("NIFTY SDL", 0.05, source="amfi")])
    one_year = COLUMNS.index("1Y")
    assert m.index(0, one_year).data(Qt.ForegroundRole).name() == "#c62828"
    assert m.index(0, COLUMNS.index("Gap %")).data(Qt.ForegroundRole).name() == "#8a8a8a"
    assert m.index(1, 1).data() == "Nifty Sdl · NAV"


def test_update_rows_changes_values_and_flashes(qapp):
    m, _ = build(qapp, [row("NIFTY A", 0.1)])
    m.update_rows([row("NIFTY A", 0.2), row("NOT IN MODEL", 0.3)])
    assert m.index(0, COLUMNS.index("1Y")).data() == "+20.00%"
    assert m.index(0, COLUMNS.index("Day %")).data(Qt.BackgroundRole) is not None
