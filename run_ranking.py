#!/usr/bin/env python3
"""Enrich mapped passive funds with AUM/TER and build the dual-ranked shortlist.

Usage:
  python3 run_ranking.py                # full run (uses cache if present)
  python3 run_ranking.py --refresh      # ignore cache, re-scrape everything
  python3 run_ranking.py --limit 25     # trial run on first 25 funds
"""
import argparse
import logging
from pathlib import Path

import pandas as pd

from ranking.dedup import build_universe
from ranking.enrich import enrich_universe
from ranking.aggregator import AggregatorClient
from ranking.trendlyne import load_etf_source
from ranking.manual_overrides import load_manual_etf_overrides
from ranking.rank import (split_by_aum, rank_by_aum, rank_composite,
                          top_n_per_index, COMPOSITE_WEIGHTS)
from ranking.build_output import write_shortlist_xlsx
from fetch_etf_index_data import match_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DATA = Path(__file__).parent / "data"

# ETFs whose AUM came from Tickertape (no fund name) and that NSE labels only by
# the underlying index, so they would otherwise show as e.g. "Nifty 50".
ETF_NAME_FIXES = {
    "NIFTYBEES": "Nippon India ETF Nifty 50 BeES",
    "HDFCNIFTY": "HDFC Nifty 50 ETF",
    "BSLNIFTY": "Aditya Birla Sun Life Nifty 50 ETF",
    "BANKBEES": "Nippon India ETF Nifty Bank BeES",
    "PSUBNKBEES": "Nippon India ETF Nifty PSU Bank BeES",
    "CPSEETF": "Nippon India ETF Nifty CPSE",
    "ICICIB22": "ICICI Prudential BSE Bharat 22 ETF",
    "SENSEXIETF": "ICICI Prudential BSE Sensex ETF",
    "SENSEXBETA": "UTI BSE Sensex ETF",
    "LIQUIDBEES": "Nippon India ETF Nifty 1D Rate Liquid BeES",
    "EBBETF0430": "Bharat Bond ETF - April 2030",
    "EBBETF0431": "Bharat Bond ETF - April 2031",
    "EBBETF0433": "Bharat Bond ETF - April 2033",
    "NXT100CASE": "Zerodha Nifty Next 100 ETF",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    # NSE (Nifty) indices only. Drop BSE, foreign (Nasdaq/MSCI/
    # S&P 500/HangSeng/FTSE) and CRISIL debt indices.
    EXCLUDE_PROVIDERS = {"International", "CRISIL", "BSE", "Other"}

    etf_source = load_etf_source(DATA / "09_trendlyne_etfs.csv", refresh=args.refresh)
    manual_source = load_manual_etf_overrides(DATA / "manual_etf_overrides.csv")
    log.info("Trendlyne ETF source: %d keys | manual overrides: %d",
             len(etf_source), len(manual_source))

    mapped = pd.read_csv(DATA / "06_mapped_funds.csv")
    mapped["Matched_Index"] = mapped.apply(
        lambda r: _remap_index(r, manual_source, etf_source), axis=1)
    universe = build_universe(mapped, exclude_providers=EXCLUDE_PROVIDERS)
    # NSE's ETF feed occasionally lists a symbol twice.
    universe = universe.drop_duplicates("fund_id").reset_index(drop=True)
    matured = universe["matched_index"].map(_matures_soon)
    if matured.any():
        log.info("Dropping %d target-maturity funds matured/maturing within %d days",
                 int(matured.sum()), MATURITY_BUFFER_DAYS)
    universe = universe[~matured].reset_index(drop=True)
    if args.limit:
        universe = universe.head(args.limit)
    log.info("Universe: %d funds (%s)", len(universe), universe.kind.value_counts().to_dict())

    # NSE labels ETFs by their underlying index ("Nifty 50"); use the proper fund
    # name ("SBI Nifty 50 ETF") from the manual override or Trendlyne where
    # available so the shortlist is readable.
    def _better_name(row):
        if row["kind"] == "ETF" and pd.notna(row["symbol"]) and row["symbol"]:
            sym = str(row["symbol"]).upper()
            if sym in ETF_NAME_FIXES:
                return ETF_NAME_FIXES[sym]
            rec = manual_source.get(sym) or etf_source.get(sym)
            if rec and rec.get("name"):
                return rec["name"]
        return row["name"]
    universe["name"] = universe.apply(_better_name, axis=1)

    enriched = enrich_universe(
        universe, AggregatorClient(etf_source=etf_source, manual_source=manual_source),
        DATA / "08_aum_ter.csv", refresh=args.refresh)
    resolved = int(enriched["resolved"].sum())
    log.info("Resolved AUM for %d/%d funds", resolved, len(enriched))

    qualifying, unresolved, below = split_by_aum(enriched)
    by_aum = rank_by_aum(qualifying)
    by_composite = rank_composite(qualifying)
    top_aum = top_n_per_index(by_aum, n=3, rank_col="rank_aum")
    top_composite = top_n_per_index(by_composite, n=3, rank_col="rank_composite")

    df_indices = _try_read(DATA / "01_nse_indices.csv")
    df_benchmarks = _try_read(DATA / "04_benchmark_codes.csv")

    out = DATA / "07_final_shortlist.xlsx"
    write_shortlist_xlsx(out, by_aum, by_composite, top_aum, top_composite,
                         unresolved, below, df_indices, df_benchmarks,
                         weights=COMPOSITE_WEIGHTS)
    log.info("Wrote %s  (qualifying=%d, unresolved=%d, below=%d)",
             out, len(qualifying), len(unresolved), len(below))


MATURITY_BUFFER_DAYS = 90
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _matures_soon(index_name, today=None):
    """True for a target-maturity index whose maturity month has passed or is
    within MATURITY_BUFFER_DAYS -- those funds are closed or about to close."""
    import re
    from datetime import date, timedelta
    m = re.search(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s*(20\d\d)\b",
                  str(index_name).upper())
    if not m:
        return False
    y, mo = int(m.group(2)), _MONTHS[m.group(1)]
    month_end = date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)
    return month_end < (today or date.today()) + timedelta(days=MATURITY_BUFFER_DAYS)


def _remap_index(row, manual_source, etf_source):
    """Re-derive the tracked index with the current (most-specific) matcher.

    NSE labels ETFs only by a terse underlying ("SENSEX", "Index"), so for ETFs
    try the proper fund name from the manual/Trendlyne source first.
    """
    if row.get("Source") == "NSE_ETF":
        sym = str(row.get("Symbol", "")).upper()
        rec = manual_source.get(sym) or etf_source.get(sym)
        name = ETF_NAME_FIXES.get(sym) or (rec or {}).get("name")
        if name:
            hit = match_index(str(name))
            if hit:
                return hit
        return match_index(str(row.get("Scheme_Name", "")))
    return match_index(str(row.get("Scheme_Name", "")))


def _try_read(path):
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, OSError):
        return None


if __name__ == "__main__":
    main()
