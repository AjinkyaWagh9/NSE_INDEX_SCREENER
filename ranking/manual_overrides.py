"""User-supplied per-ETF AUM/TER overrides — the highest-priority source.

For ETFs that no automated source exposes (flagship funds absent from
Trendlyne's public feed, or just-launched funds), AUM/TER can be entered by hand
in data/manual_etf_overrides.csv. These win over Trendlyne/Tickertape/Groww, and
because the enrichment cache marks them resolved they are never re-fetched or
overwritten by later runs.

CSV columns: symbol, aum_cr, ter_pct, name (note is optional/ignored).
A row with no numeric aum_cr is skipped (AUM is required to filter/rank).
"""
import csv
import os


def _num(v):
    v = (v or "").strip()
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_manual_etf_overrides(path):
    """Return {UPPER_SYMBOL: {"aum_cr", "ter_pct", "name"}} from the CSV, or {}."""
    overrides = {}
    if not os.path.exists(path):
        return overrides
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            symbol = (row.get("symbol") or "").strip().upper()
            aum = _num(row.get("aum_cr"))
            if not symbol or aum is None:
                continue
            overrides[symbol] = {
                "aum_cr": aum,
                "ter_pct": _num(row.get("ter_pct")),
                "name": (row.get("name") or "").strip() or None,
            }
    return overrides
