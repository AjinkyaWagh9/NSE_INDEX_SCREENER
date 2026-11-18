"""Enrich the universe with AUM (cr) + TER (%) via an aggregator client, with a CSV cache."""
import numpy as np
import pandas as pd

CACHE_COLUMNS = ["fund_id", "aum_cr", "ter_pct", "aum_source", "matched_key", "resolved"]


def _load_cache(cache_path):
    try:
        c = pd.read_csv(cache_path)
        return {row["fund_id"]: row for _, row in c.iterrows()}
    except (FileNotFoundError, OSError, pd.errors.EmptyDataError):
        return {}


def enrich_universe(df, client, cache_path, refresh=False):
    df = df.copy().reset_index(drop=True)
    cache = {} if refresh else _load_cache(cache_path)
    records = []

    for _, r in df.iterrows():
        fid = r["fund_id"]
        cached = cache.get(fid)
        if cached is not None and bool(cached.get("resolved")):
            records.append({
                "aum_cr": float(cached["aum_cr"]),
                "ter_pct": float(cached["ter_pct"]) if pd.notna(cached["ter_pct"]) else np.nan,
                "aum_source": str(cached.get("aum_source")) if pd.notna(cached.get("aum_source")) else "",
                "matched_key": str(cached.get("matched_key")) if pd.notna(cached.get("matched_key")) else "",
                "resolved": True,
            })
            continue

        hit = client.fetch(r["kind"], r["symbol"], r["isin"], r["name"])
        if hit:
            ter = hit.get("ter_pct")
            records.append({
                "aum_cr": float(hit["aum_cr"]),
                "ter_pct": float(ter) if ter is not None else np.nan,
                "aum_source": hit.get("source", ""),
                "matched_key": hit.get("matched_key", ""),
                "resolved": True,
            })
        else:
            records.append({"aum_cr": np.nan, "ter_pct": np.nan, "aum_source": "",
                            "matched_key": "", "resolved": False})

    enriched = pd.concat([df, pd.DataFrame(records)], axis=1)
    _write_cache(enriched, cache_path, cache)
    return enriched


def _write_cache(enriched, cache_path, prior_cache=None):
    out = enriched[["fund_id", "aum_cr", "ter_pct", "aum_source", "matched_key", "resolved"]].copy()

    if prior_cache:
        # Merge previously-cached rows (not present in the current run) with the
        # current run's rows, so a smaller/different universe (e.g. --limit) doesn't
        # drop previously-resolved fund_ids from the cache. Current-run rows win.
        current_ids = set(out["fund_id"])
        prior_rows = [row for fid, row in prior_cache.items() if fid not in current_ids]
        if prior_rows:
            prior_df = pd.DataFrame(prior_rows)[CACHE_COLUMNS]
            out = pd.concat([out, prior_df], ignore_index=True)

    out.to_csv(cache_path, index=False)
