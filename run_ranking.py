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
from ranking.rank import (split_by_aum, rank_by_aum, rank_composite,
                          top_n_per_index, COMPOSITE_WEIGHTS)
from ranking.build_output import write_shortlist_xlsx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DATA = Path(__file__).parent / "data"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    mapped = pd.read_csv(DATA / "06_mapped_funds.csv")
    universe = build_universe(mapped)
    if args.limit:
        universe = universe.head(args.limit)
    log.info("Universe: %d funds (%s)", len(universe), universe.kind.value_counts().to_dict())

    etf_source = load_etf_source(DATA / "09_trendlyne_etfs.csv", refresh=args.refresh)
    log.info("Trendlyne ETF source: %d symbol/ISIN keys", len(etf_source))

    # NSE labels ETFs by their underlying index ("Nifty 50"); use Trendlyne's
    # proper fund name ("Nippon India ETF Nifty 50 BeES") where available so the
    # shortlist is readable.
    def _better_name(row):
        if row["kind"] == "ETF" and row["symbol"]:
            rec = etf_source.get(str(row["symbol"]).upper())
            if rec and rec.get("name"):
                return rec["name"]
        return row["name"]
    universe["name"] = universe.apply(_better_name, axis=1)

    enriched = enrich_universe(universe, AggregatorClient(etf_source=etf_source),
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


def _try_read(path):
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, OSError):
        return None


if __name__ == "__main__":
    main()
