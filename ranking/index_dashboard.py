"""Index-level returns from NSE Indices' monthly "Index Dashboard" PDFs.

Drop official dashboards (niftyindices.com -> Reports -> Index Dashboard) into
data/index_dashboards/ as Index_Dashboard_<MON><YYYY>.pdf. The latest one gives
1M / 3M / 1Y / 3Y / 5Y returns (Total Return Index; 1Y absolute, 3Y/5Y CAGR).

The dashboard has no 6M or 2Y column, so they are chained from older dashboards:
  6M = (1 + 3M latest) x (1 + 3M from the dashboard 3 months earlier) - 1
  2Y = sqrt((1 + 1Y latest) x (1 + 1Y from the dashboard 12 months earlier)) - 1   (CAGR)
If that older dashboard isn't present, the period is left blank.
"""
import re
import subprocess
from datetime import date
from pathlib import Path

import pandas as pd

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_NUM = r"(-?\d+\.\d+|-)"
_ROW = re.compile(r"^\s*(Nifty.+?)\s{2,}" + r"\s+".join([_NUM] * 5) + r"\s")
COLS = ["r1m", "r3m", "r1y", "r3y", "r5y"]


def dashboard_month(path):
    """Index_Dashboard_OCT2026.pdf -> (2026, 10)."""
    m = re.search(r"([A-Z]{3})(\d{4})", Path(path).stem.upper())
    return int(m.group(2)), MONTHS.index(m.group(1)) + 1


def month_end(year, month):
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def parse_dashboard(pdf_path):
    """Return DataFrame[section, index, r1m, r3m, r1y, r3y, r5y] with returns as fractions."""
    text = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                          capture_output=True, text=True, check=True).stdout
    rows, section = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.endswith("Indices") and not re.search(r"\d", s):
            section = s
            continue
        m = _ROW.match(line + " ")
        if m:
            vals = [None if x == "-" else float(x) / 100 for x in m.groups()[1:]]
            rows.append([section, m.group(1).strip()] + vals)
    return pd.DataFrame(rows, columns=["section", "index"] + COLS)


def load_index_returns(folder, match_index):
    """Latest dashboard's returns keyed by our canonical index name, with 6M/2Y
    chained from older dashboards when available. Adds `as_of` (month-end date)."""
    pdfs = {dashboard_month(p): p for p in Path(folder).glob("Index_Dashboard_*.pdf")}
    if not pdfs:
        return pd.DataFrame(), None
    latest = max(pdfs)
    df = parse_dashboard(pdfs[latest])

    def older(months_back):
        y, mo = latest
        idx = (y * 12 + mo - 1) - months_back
        key = (idx // 12, idx % 12 + 1)
        return parse_dashboard(pdfs[key]).set_index("index") if key in pdfs else None

    df["r6m"], df["r2y"] = float("nan"), float("nan")
    prev3, prev12 = older(3), older(12)
    if prev3 is not None:
        p = df["index"].map(prev3["r3m"])
        df["r6m"] = (1 + df["r3m"]) * (1 + p) - 1
    if prev12 is not None:
        p = df["index"].map(prev12["r1y"])
        df["r2y"] = ((1 + df["r1y"]) * (1 + p)) ** 0.5 - 1

    # Map to our canonical names; where several dashboard rows map to the same
    # canonical index (e.g. "Nifty 100" and "Nifty100 Enhanced ESG"), the
    # shortest name is the plain index itself.
    df["canon"] = df["index"].map(match_index)
    df = (df[df["canon"] != ""].assign(_len=df["index"].str.len())
          .sort_values("_len").drop_duplicates("canon").drop(columns="_len"))
    as_of = month_end(*latest)
    df["as_of"] = as_of
    return df.set_index("canon"), as_of
