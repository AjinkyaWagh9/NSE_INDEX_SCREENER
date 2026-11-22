#!/usr/bin/env python3
"""Build a clean, presentation-ready workbook from data/07_final_shortlist.xlsx.

Output: data/ETF_Index_Shortlist.xlsx with 4 sheets:
  Overview        - what this is, method, headline numbers, data caveats
  At a Glance     - one row per index: largest fund vs best-value fund
  Top 3 by AUM    - top 3 funds per index ranked by size
  Top 3 Best Value- top 3 funds per index ranked by composite score
Run after run_ranking.py.
"""
import re
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from fetch_etf_index_data import match_index
from ranking.index_dashboard import load_index_returns
from ranking.returns import fetch_nav_history, month_returns
from ranking.rank import AUM_THRESHOLD, COMPOSITE_WEIGHTS, TER_MAX_PLAUSIBLE

DATA = Path(__file__).parent / "data"
SRC = DATA / "07_final_shortlist.xlsx"
RETURNS = DATA / "10_fund_returns.csv"
DASHBOARDS = DATA / "index_dashboards"
RET_COLS = [("ret_1y", "1Y Return"), ("ret_2y", "2Y CAGR"), ("ret_3y", "3Y CAGR"), ("ret_5y", "5Y CAGR")]
OUT = DATA / "ETF_Index_Shortlist.xlsx"

FONT = "Arial"
NAVY = "1F3864"
BAND = "EEF2F8"
GOLD = "FFF4CC"
GRID = Side(style="thin", color="D0D7E2")

# ---------- classification & display helpers ----------

DEBT = ("G-SEC", "SDL", "BOND", "1D RATE", "LIQUID", "AAA")
FACTOR = ("MOMENTUM", "QUALITY", "VALUE", "LOW VOL", "LOW-VOL", "ALPHA", "EQUAL WEIGHT",
          "DIVIDEND", "ENHANCED", "SHARIAH", "ESG", "HYBRID", "MULTICAP", "FLEXICAP",
          "GROWTH SECTORS", "HIGH BETA", "50:50", "SECTOR LEADERS")
BROAD = {"NIFTY 50", "NIFTY NEXT 50", "NIFTY 100", "NIFTY 200", "NIFTY 500", "NIFTY NEXT 100",
         "NIFTY MIDCAP 50", "NIFTY MIDCAP 100", "NIFTY MIDCAP 150", "NIFTY MIDCAP SELECT",
         "NIFTY SMALLCAP 50", "NIFTY SMALLCAP 100", "NIFTY SMALLCAP 250", "NIFTY SMALLCAP 500",
         "NIFTY MIDSMALLCAP 400", "NIFTY LARGEMIDCAP 250", "NIFTY TOTAL MARKET",
         "NIFTY MICROCAP 250"}
SECTOR = ("BANK", "NIFTY IT", "PHARMA", "AUTO", "FMCG", "METAL", "REALTY", "FINANCIAL",
          "HEALTHCARE", "HOSPITALS", "OIL & GAS", "ENERGY", "CHEMICALS", "MEDIA", "INSURANCE",
          "CAPITAL MARKETS", "POWER", "CEMENT", "COMMODITIES")
CATEGORY_ORDER = ["Broad Market", "Sector", "Thematic", "Strategy / Factor", "Debt"]


def category(ix: str) -> str:
    u = ix.upper()
    if "EV & NEW AGE" in u:
        return "Thematic"
    if "IT & TELECOM" in u:
        return "Sector"
    if any(k in u for k in DEBT):
        return "Debt"
    if u in BROAD:
        return "Broad Market"
    if any(k in u for k in FACTOR):
        return "Strategy / Factor"
    if any(k in u for k in SECTOR):
        return "Sector"
    return "Thematic"


KEEP_UPPER = {"ETF", "NSE", "SDL", "IT", "PSU", "AAA", "UTI", "SBI", "HDFC", "ICICI",
              "DSP", "LIC", "MF", "HSBC", "ELSS", "IDCW", "FMCG", "EV", "MNC", "CPSE", "PSE",
              "REITS", "IPO", "ESG", "BNP", "CASE", "MQ", "TER", "ONE", "G-SEC", "1D"}


def tidy_name(n: str) -> str:
    """Title-case fund names that arrive in ALL CAPS, keeping acronyms."""
    n = re.sub(r"\s+", " ", str(n)).strip().rstrip("-").strip()
    if n != n.upper():
        return n
    words = []
    for w in n.split(" "):
        words.append(w if w in KEEP_UPPER or any(c.isdigit() for c in w) else w.capitalize())
    return " ".join(words)


INDEX_UPPER = {"IT", "PSU", "FMCG", "EV", "MNC", "CPSE", "PSE", "IPO", "G-SEC", "SDL",
               "AAA", "ESG", "1D", "YR", "MQ", "(HYBRID)"}


def display_index(ix: str) -> str:
    ix = ix.replace(" (Target Maturity)", "").replace(" INDEX", "")
    out = []
    for w in ix.split(" "):
        if w in ("G-SEC",):
            out.append("G-Sec")
        elif w == "(HYBRID)":
            out.append("(Hybrid)")
        elif w in INDEX_UPPER:
            out.append(w)
        elif any(c.isdigit() for c in w):
            # NIFTY500 -> Nifty500, MIDCAP150 -> Midcap150, 50:25:25 unchanged
            out.append(re.sub(r"[A-Z]+", lambda m: m.group(0).capitalize(), w))
        elif w == "REITS":
            out.append("REITs")
        elif w in ("&", "-", "+"):
            out.append(w)
        else:
            out.append(w.capitalize() if "-" not in w else "-".join(p.capitalize() for p in w.split("-")))
    return " ".join(out).replace("Ex-Bank", "ex-Bank")


# ---------- load ----------

def load():
    x = pd.read_excel(SRC, sheet_name=None)
    by_aum, by_comp = x["Rank by AUM"], x["Rank by Composite"]
    comp_rank = by_comp.set_index(["matched_index", "fund_id"])[["rank_composite", "composite_score"]]
    df = by_aum.join(comp_rank, on=["matched_index", "fund_id"])
    df["Category"] = df["matched_index"].map(category)
    df["Index"] = df["matched_index"].map(display_index)
    df["Fund"] = df["name"].map(tidy_name)
    df["Type"] = df["kind"].map({"ETF": "ETF", "IndexFund": "Index Fund"})
    df["TER"] = df["ter_pct"] / 100.0
    df["ter_suspect"] = df["ter_pct"] > TER_MAX_PLAUSIBLE
    df["Liquidity_cr"] = df["liquidity"] / 1e7
    df["Score"] = df["composite_score"] * 100
    df["n_funds"] = df.groupby("matched_index")["fund_id"].transform("count")
    rets = pd.read_csv(RETURNS)
    df = df.merge(rets[["fund_id", "as_of"] + [c for c, _ in RET_COLS]], on="fund_id", how="left")
    df.attrs["returns_as_of"] = rets["as_of"].iloc[0]
    # Order indices: by category, then by size of their largest fund
    top_aum = df.groupby("matched_index")["aum_cr"].transform("max")
    df["_cat"] = df["Category"].map(CATEGORY_ORDER.index)
    df["_top"] = -top_aum
    return df, x


# ---------- styling ----------

def style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=GRID, top=GRID, left=GRID, right=GRID)
    ws.row_dimensions[row].height = 32


def title_block(ws, title, subtitle, ncols):
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, bold=True, size=14, color=NAVY)
    ws["A2"] = subtitle
    ws["A2"].font = Font(name=FONT, italic=True, size=9, color="595959")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 28


FMT = {"aum": '#,##0', "ter": '0.00%', "score": '0', "liq": '#,##0.0', "int": '0',
       "ret": '0.0%;[Red]-0.0%;0.0%'}


def write_table(ws, start_row, headers, rows, fmts, widths, group_key=None, gold_col=None,
                suspect_cols=None):
    """rows: list of dicts with key per header; fmts: header->number format."""
    for j, h in enumerate(headers, 1):
        ws.cell(row=start_row, column=j, value=h)
    style_header(ws, start_row, len(headers))
    band, last = False, object()
    for i, r in enumerate(rows, start_row + 1):
        if group_key is not None:
            g = r[group_key]
            if g != last:
                band, last = not band, g
        else:
            band = (i % 2 == 0)
        for j, h in enumerate(headers, 1):
            v = r.get(h)
            if isinstance(v, float) and pd.isna(v):
                v = None
            cell = ws.cell(row=i, column=j, value=v)
            cell.font = Font(name=FONT, size=10)
            cell.border = Border(bottom=GRID)
            cell.alignment = Alignment(vertical="center",
                                       horizontal="left" if h not in fmts else "right")
            if h in fmts:
                cell.number_format = fmts[h]
            if band:
                cell.fill = PatternFill("solid", fgColor=BAND)
            if v is None and h in fmts:
                cell.value = "–"
                cell.alignment = Alignment(horizontal="center")
        if gold_col and r.get("_gold"):
            ws.cell(row=i, column=headers.index(gold_col) + 1).fill = PatternFill("solid", fgColor=GOLD)
        for sc in (suspect_cols or []):
            if r.get("_suspect_" + sc):
                c = ws.cell(row=i, column=headers.index(sc) + 1)
                c.font = Font(name=FONT, size=10, color="C00000", italic=True)
    for j, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    end = start_row + len(rows)
    ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{end}"
    ws.freeze_panes = ws.cell(row=start_row + 1, column=3)
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{start_row}:{start_row}"
    return end


# ---------- sheets ----------

def sheet_glance(wb, df):
    ws = wb.create_sheet("At a Glance")
    headers = ["Category", "Index", "Funds ≥ ₹10cr", "Largest Fund (by AUM)", "AUM (₹ cr)",
               "TER", "Best Value Fund (composite)", "Its AUM (₹ cr)", "Its TER", "Same pick?"]
    rows = []
    order = df.sort_values(["_cat", "_top", "matched_index"]).matched_index.unique()
    for ix in order:
        g = df[df.matched_index == ix]
        a = g.sort_values("rank_aum").iloc[0]
        b = g.sort_values("rank_composite").iloc[0]
        same = a.fund_id == b.fund_id
        rows.append({"Category": a.Category, "Index": a.Index, "Funds ≥ ₹10cr": int(a.n_funds),
                     "Largest Fund (by AUM)": a.Fund, "AUM (₹ cr)": a.aum_cr, "TER": a.TER,
                     "Best Value Fund (composite)": "Same as largest" if same else b.Fund,
                     "Its AUM (₹ cr)": None if same else b.aum_cr,
                     "Its TER": None if same else b.TER,
                     "Same pick?": "Yes" if same else "No", "_gold": not same,
                     "_suspect_TER": bool(a.ter_suspect),
                     "_suspect_Its TER": (not same) and bool(b.ter_suspect)})
    title_block(ws, "At a Glance — Largest vs Best-Value Fund for Every Index",
                "One row per index. 'Largest' = highest AUM. 'Best Value' = top composite score "
                "(50% AUM, 30% low TER, 20% liquidity). Highlighted rows: the best-value pick differs "
                "from the largest fund. Red italic TER = implausible (>1%), excluded from scoring.", 10)
    write_table(ws, 4, headers, rows,
                {"Funds ≥ ₹10cr": FMT["int"], "AUM (₹ cr)": FMT["aum"], "TER": FMT["ter"],
                 "Its AUM (₹ cr)": FMT["aum"], "Its TER": FMT["ter"]},
                [17, 40, 10, 50, 12, 8, 50, 12, 8, 9],
                group_key=None, gold_col="Best Value Fund (composite)",
                suspect_cols=["TER", "Its TER"])
    for r in range(5, 5 + len(rows)):
        ws.cell(row=r, column=10).alignment = Alignment(horizontal="center")
    return len(rows)


def sheet_top3(wb, df, name, rank_col, title, subtitle, with_score):
    ws = wb.create_sheet(name)
    top = df[df[rank_col] <= 3].sort_values(["_cat", "_top", "matched_index", rank_col])
    headers = ["Category", "Index", "Rank", "Fund", "Type", "AUM (₹ cr)", "TER"]
    if with_score:
        headers += ["Daily Traded (₹ cr)", "Score (0-100)", "Rank by AUM"]
    else:
        headers += ["Rank by Value"]
    headers += [h for _, h in RET_COLS]
    other = "rank_aum" if with_score else "rank_composite"
    rows = []
    for _, r in top.iterrows():
        d = {"Category": r.Category, "Index": r.Index, "Rank": int(r[rank_col]), "Fund": r.Fund,
             "Type": r.Type, "AUM (₹ cr)": r.aum_cr, "TER": r.TER,
             "Daily Traded (₹ cr)": r.Liquidity_cr, "Score (0-100)": r.Score,
             "Rank by AUM" if with_score else "Rank by Value": int(r[other]),
             "_suspect_TER": bool(r.ter_suspect), "_key": r.matched_index,
             **{h: r[c] for c, h in RET_COLS}}
        rows.append(d)
    title_block(ws, title, subtitle, len(headers))
    fmts = {"Rank": FMT["int"], "AUM (₹ cr)": FMT["aum"], "TER": FMT["ter"],
            "Daily Traded (₹ cr)": FMT["liq"], "Score (0-100)": FMT["score"],
            "Rank by AUM": FMT["int"], "Rank by Value": FMT["int"],
            **{h: FMT["ret"] for _, h in RET_COLS}}
    widths = [17, 38, 6, 52, 11, 11, 8] + ([11, 9, 8] if with_score else [9]) + [9] * len(RET_COLS)
    write_table(ws, 4, headers, rows, fmts, widths, group_key="_key", suspect_cols=["TER"])
    for i, r in enumerate(rows, 5):
        ws.cell(row=i, column=3).alignment = Alignment(horizontal="center")
        if r["Rank"] == 1:
            ws.cell(row=i, column=4).font = Font(name=FONT, size=10, bold=True)
    return len(rows)


IDX_MONTHS = {"r1m": 1, "r3m": 3, "r6m": 6, "r1y": 12, "r2y": 24, "r3y": 36, "r5y": 60}
IDX_RET_COLS = [("r1m", "1M"), ("r3m", "3M"), ("r6m", "6M"), ("r1y", "1Y"),
                ("r2y", "2Y CAGR"), ("r3y", "3Y CAGR"), ("r5y", "5Y CAGR")]


def _largest(sub, kind, n=3):
    """'1. Fund (₹x cr)' lines for the n largest funds of one type, or an em dash."""
    top = sub[sub.Type == kind].sort_values("aum_cr", ascending=False).head(n)
    return "\n".join(f"{i}. {r.Fund} (₹{r.aum_cr:,.0f} cr)"
                     for i, r in enumerate(top.itertuples(), 1)) or "—"


def _proxy_fund(ix, df, fund_rets):
    """Ranked fund for this index with the longest usable NAV history (ties ->
    larger AUM). Skips fixed-NAV liquid ETFs, whose NAV doesn't show returns."""
    g = df[(df.matched_index == ix) & ((df.rank_aum <= 3) | (df.rank_composite <= 3))]
    fr = fund_rets[fund_rets.scheme_code.notna() & fund_rets.returns_note.fillna("").eq("")]
    g = g.merge(fr[["fund_id", "scheme_code", "first_nav_date"]], on="fund_id")
    if g.empty:
        return None
    best = g.sort_values(["first_nav_date", "aum_cr"], ascending=[True, False]).iloc[0]
    return best.Fund, int(best.scheme_code)


def sheet_index_returns(wb, df):
    """One row per index: the index's own returns (NSE Index Dashboard, Total
    Return Index) beside the 3 largest ETFs and 3 largest index funds tracking it."""
    ws = wb.create_sheet("Index Returns")
    idx_ret, as_of = load_index_returns(DASHBOARDS, match_index)
    headers = (["Category", "Index", "Largest ETFs (AUM)", "Largest Index Funds (AUM)"]
               + [h for _, h in IDX_RET_COLS] + ["Data as of"])
    rows, n_proxy = [], 0
    fund_rets = pd.read_csv(RETURNS)
    pending = [p for c, p in (("r6m", "6M (needs the dashboard 3 months earlier)"),
                              ("r2y", "2Y (needs the dashboard 12 months earlier)"))
               if not len(idx_ret) or idx_ret[c].isna().all()]
    for ix in df.sort_values(["_cat", "_top", "matched_index"]).matched_index.unique():
        sub = df[df.matched_index == ix]
        first = sub.iloc[0]
        row = {"Category": first.Category, "Index": first.Index,
               "Largest ETFs (AUM)": _largest(sub, "ETF"),
               "Largest Index Funds (AUM)": _largest(sub, "Index Fund")}
        if ix in idx_ret.index:
            rec = idx_ret.loc[ix]
            for c, h in IDX_RET_COLS:
                row[h] = None if pd.isna(rec[c]) else float(rec[c])
            row["Data as of"] = pd.Timestamp(rec["as_of"]).strftime("%d %b %Y")
        else:
            proxy = _proxy_fund(ix, df, fund_rets)
            if proxy is None:
                row["Data as of"] = "No data (not in NSE dashboard; no fund NAV)"
            else:
                name, code = proxy
                nav = fetch_nav_history(code, DATA / "nav_cache", max_age_days=10 ** 6)
                mr = month_returns(nav, as_of, tuple(IDX_MONTHS.values()))
                for c, h in IDX_RET_COLS:
                    v = mr[IDX_MONTHS[c]]
                    row[h] = None if pd.isna(v) else float(v)
                row["Data as of"] = f"{as_of:%d %b %Y}\nProxy: {name} NAV"
                row["_proxy"] = True
                n_proxy += 1
        row["_lines"] = max(row["Largest ETFs (AUM)"].count("\n"),
                            row["Largest Index Funds (AUM)"].count("\n"),
                            row["Data as of"].count("\n") + (1 if row.get("_proxy") else 0)) + 1
        rows.append(row)
    sub = ("Returns are of the INDEX itself (NSE Indices' Index Dashboard, Total Return Index): "
           "1M–1Y absolute, 2Y/3Y/5Y annualised (CAGR). ETFs and index funds track these closely, "
           "less their fees. Fund columns = the 3 largest ETFs and the 3 largest index funds tracking the "
           f"index (AUM ≥ ₹{AUM_THRESHOLD:g} cr), each ranked by AUM.")
    if n_proxy:
        sub += (f" {n_proxy} debt/hybrid indices aren't in NSE's equity dashboard: their returns (italic) "
                "come from the NAV of the ranked fund tracking them with the longest history, so they "
                "are slightly lower than the index by roughly that fund's fee.")
    if pending:
        sub += " Blank until added to data/index_dashboards/: " + "; ".join(pending) + "."
    title_block(ws, f"Index Returns vs Largest Funds — as of {as_of:%d %b %Y}", sub, len(headers))
    ws.row_dimensions[2].height = 40
    fmts = {h: FMT["ret"] for _, h in IDX_RET_COLS}
    write_table(ws, 4, headers, rows, fmts, [16, 32, 56, 56] + [8] * len(IDX_RET_COLS) + [30],
                group_key=None)
    for i, r in enumerate(rows, 5):
        ws.row_dimensions[i].height = 13.5 * r["_lines"] + 2
        for col in (3, 4):
            ws.cell(row=i, column=col).alignment = Alignment(wrap_text=True, vertical="top")
        for col in (1, 2):
            ws.cell(row=i, column=col).alignment = Alignment(vertical="top")
        for col in range(5, 5 + len(IDX_RET_COLS)):
            ws.cell(row=i, column=col).alignment = Alignment(horizontal="right", vertical="top")
        ws.cell(row=i, column=len(headers)).alignment = Alignment(horizontal="center", vertical="top",
                                                                   wrap_text=True)
        if r.get("_proxy"):
            for col in list(range(5, 5 + len(IDX_RET_COLS))) + [len(headers)]:
                c = ws.cell(row=i, column=col)
                neg = isinstance(c.value, float) and c.value < 0
                c.font = Font(name=FONT, size=10, italic=True, color="C00000" if neg else "595959")
    return as_of


def sheet_overview(wb, df, x, n_idx):
    ws = wb.active
    ws.title = "Overview"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 95
    unresolved, below = x["Unresolved AUM"], x["Below 10cr"]
    w = COMPOSITE_WEIGHTS

    def put(r, a, b=None, bold=False, size=10, color="000000", fmt=None):
        ws.cell(row=r, column=1, value=a).font = Font(name=FONT, bold=True if b is not None else bold,
                                                     size=size, color=color)
        if b is not None:
            c = ws.cell(row=r, column=2, value=b)
            c.font = Font(name=FONT, size=10)
            c.alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
            if fmt:
                c.number_format = fmt
        ws.cell(row=r, column=1).alignment = Alignment(vertical="top", wrap_text=True)

    def section(r, text):
        c = ws.cell(row=r, column=1, value=text)
        c.font = Font(name=FONT, bold=True, size=11, color="FFFFFF")
        for col in (1, 2):
            ws.cell(row=r, column=col).fill = PatternFill("solid", fgColor=NAVY)

    put(1, "Indian Index ETFs & Index Funds — Top 3 Shortlist", bold=True, size=16, color=NAVY)
    ret_asof = pd.Timestamp(df.attrs["returns_as_of"])
    put(2, f"NSE (Nifty) indices only · AUM/TER as of {date.today():%d %b %Y} · returns as of "
           f"{ret_asof:%d %b %Y}", size=9, color="595959")
    for rr in (1, 2):
        ws.merge_cells(start_row=rr, start_column=1, end_row=rr, end_column=2)
    ws.row_dimensions[1].height = 24

    r = 4
    section(r, "HEADLINE NUMBERS"); r += 1
    # Static values (not formulas): previews like Quick Look / mail / Drive don't
    # recalculate, and a presented deck must never show 0.
    firsts = df[df.rank_aum == 1].set_index("matched_index")["fund_id"]
    bests = df[df.rank_composite == 1].set_index("matched_index")["fund_id"]
    stats = [
        ("Indices covered", n_idx, "0"),
        ("Qualifying funds (AUM ≥ ₹10 cr)", len(df), "#,##0"),
        ("Indices where best-value ≠ largest", int((firsts != bests.reindex(firsts.index)).sum()), "0"),
        ("Funds below ₹10 cr (excluded)", len(below), "0"),
        ("Funds with no AUM found (excluded)", len(unresolved), "0"),
    ]
    for a, b, f in stats:
        put(r, a, b, fmt=f)
        ws.cell(row=r, column=2).alignment = Alignment(horizontal="left")
        r += 1

    r += 1
    section(r, "HOW TO READ THIS WORKBOOK"); r += 1
    for a, b in [
        ("At a Glance", "Start here. One row per index — the largest fund next to the best-value fund. "
                        "Highlighted rows are where a smaller/cheaper fund scores better than the biggest one."),
        ("Top 3 by AUM", "The three biggest funds per index. Bigger = more established, lower closure risk, "
                         "usually tighter trading for ETFs. Includes 1/2/3/5-year returns."),
        ("Top 3 Best Value", "The three best funds per index on a blended score of size, cost and tradability. "
                             "'Rank by AUM' shows where the same fund sits on pure size."),
        ("Index Returns", "The index's own returns (1M to 5Y, from NSE's Index Dashboard) next to the ETFs and "
                          "3 largest ETFs and 3 largest index funds tracking it (by AUM). Debt / target-maturity indices aren't in that dashboard."),
        ("Categories", "Broad Market · Sector · Thematic · Strategy / Factor · Debt. Use the filter "
                       "arrows on the Category column to focus (e.g. hide Debt for an equity-only view)."),
    ]:
        put(r, a, b); ws.row_dimensions[r].height = 28; r += 1

    r += 1
    section(r, "METHOD"); r += 1
    for a, b in [
        ("Universe", "Every ETF listed on NSE and every index fund in AMFI's scheme list that tracks an NSE "
                     "(Nifty) index. BSE, international and CRISIL indices excluded. Mutual-fund plans "
                     "collapsed to one row per fund (Direct-Growth preferred). Target-maturity debt funds "
                     "maturing within 3 months are excluded."),
        ("Filter", f"Only funds with AUM ≥ ₹{AUM_THRESHOLD:g} crore are ranked."),
        ("Ranking 1 — AUM", "Within each index, funds sorted by AUM, largest first."),
        ("Ranking 2 — Best Value", f"Composite score = {w['aum']:.0%} AUM + {w['ter']:.0%} low TER + "
                                   f"{w['liq']:.0%} liquidity (daily traded value, ETFs only). Each factor "
                                   "is min-max scaled 0-1 within the index; missing factors are dropped and "
                                   "weights re-split. Score shown 0-100."),
        ("Sources (priority order)", "Manually verified figures (factsheets / Groww / fund portals) → Trendlyne "
                                     "(ETFs) → Tickertape (ETFs) → Groww (index funds). NSE for listings & traded "
                                     "value; AMFI for schemes."),
        ("Returns", f"From each fund's daily NAV history (AMFI, via mfapi.in), measured to {ret_asof:%d %b %Y} "
                    "to match NSE's Index Dashboard. Index funds: Direct-Growth plan. 1Y is absolute; 2Y/3Y/5Y "
                    "are annualised (CAGR). '–' = fund is younger than the period. ETF unit splits are "
                    "adjusted for."),
    ]:
        put(r, a, b); ws.row_dimensions[r].height = 30 if len(b) > 100 else 16; r += 1

    r += 1
    section(r, "CAVEATS & KNOWN DATA GAPS"); r += 1
    for a, b in [
        ("Missing AUM", "Still unknown: four Nifty 50 index funds (ICICI, Tata, Franklin, Nippon) — too small "
                        "to reach the Nifty 50 top 3 — and two funds launched in Nov 2026 that have no AUM yet."),
        ("Hand-entered AUM", "Some AUM figures were entered by hand from factsheets / fund portals (e.g. ICICI "
                             "Nifty Next 50 Index Fund, Motilal Oswal Microcap 250, Bharat Bond Apr 2033). Sources "
                             "are logged in data/manual_etf_overrides.csv."),
        ("Returns", "NAV-based returns, before any exit load or tax. ETF investors transact at market price, "
                    "which can differ slightly from NAV. Nippon Liquid BeES shows '–' because its NAV is held at "
                    "₹1,000 and returns are paid as daily dividends. Past returns don't predict future returns."),
        ("Suspect TERs", f"TERs above {TER_MAX_PLAUSIBLE:g}% (SEBI's cap for index funds/ETFs) are scraping "
                         "errors. They are shown in red italics and ignored in the Best Value score."),
        ("Liquidity", "Traded value is a single-day NSE snapshot, not an average — treat as indicative."),
        ("Single-fund indices", "Where an index has only one qualifying fund, its score is 100 by definition."),
        ("Not considered", "Tracking error, tracking difference and bid-ask spreads. Check these, and the AMC "
                           "factsheet, before investing. This is a shortlist, not investment advice."),
    ]:
        put(r, a, b); ws.row_dimensions[r].height = 30 if len(b) > 100 else 16; r += 1


def main():
    df, x = load()
    wb = Workbook()
    n_idx = df.matched_index.nunique()
    sheet_overview(wb, df, x, n_idx)
    sheet_glance(wb, df)
    sheet_index_returns(wb, df)
    sheet_top3(wb, df, "Top 3 by AUM", "rank_aum", "Top 3 Funds per Index — by Size (AUM)",
               "Ranked by Assets Under Management. 'Rank by Value' = the same fund's position on the "
               "composite (best value) ranking. Red italic TER = implausible, ignored in scoring.", False)
    sheet_top3(wb, df, "Top 3 Best Value", "rank_composite",
               "Top 3 Funds per Index — Best Value (Composite Score)",
               f"Score = {COMPOSITE_WEIGHTS['aum']:.0%} AUM + {COMPOSITE_WEIGHTS['ter']:.0%} low TER + "
               f"{COMPOSITE_WEIGHTS['liq']:.0%} liquidity, each scaled within the index. Daily traded value "
               "applies to ETFs only (index funds don't trade on exchange).", True)
    wb.save(OUT)
    print(f"Wrote {OUT} ({n_idx} indices, {len(df)} funds)")


if __name__ == "__main__":
    main()
