#!/usr/bin/env python3
"""Compute 1/2/3/5-year NAV returns for every fund in either top-3 list.

Usage:  python3 compute_returns.py [--as-of 2026-10-31]
Default as-of date is 31 Oct 2026, the date of NSE's Index Dashboard, so fund
returns can be compared directly with the index returns there.
Output: data/10_fund_returns.csv (read by build_presentation.py).
"""
import argparse
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from ranking.returns import (compute_fund_returns, load_etf_isins, load_isin_to_code)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
DATA = Path(__file__).parent / "data"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-31")
    args = ap.parse_args()
    as_of = date.fromisoformat(args.as_of)

    x = pd.read_excel(DATA / "07_final_shortlist.xlsx", sheet_name=None)
    top = (pd.concat([x["Top 3 by AUM"], x["Top 3 by Composite"]])
           .drop_duplicates("fund_id")[["fund_id", "kind", "symbol", "isin", "name"]])
    log.info("Computing returns for %d top-3 funds as of %s", len(top), as_of)

    out = compute_fund_returns(top, load_isin_to_code(DATA / "12_amfi_navall.txt"),
                               load_etf_isins(DATA / "11_nse_etf_list.csv"),
                               DATA / "nav_cache", as_of)
    out.insert(1, "as_of", as_of.isoformat())
    out.to_csv(DATA / "10_fund_returns.csv", index=False)
    have = out[[f"ret_{y}y" for y in (1, 2, 3, 5)]].notna().sum().to_dict()
    log.info("Wrote %s | funds with return: %s | issues: %d",
             DATA / "10_fund_returns.csv", have, (out.returns_note != "").sum())


if __name__ == "__main__":
    main()
