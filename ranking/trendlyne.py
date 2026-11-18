"""Bulk ETF AUM / TER / tracking-error from Trendlyne's ETF dashboard API.

Why this exists: ETF AUM is not available from AMFI (AMC-level only) and Groww
returns aum=None for ETFs. Tickertape has it but rate-limits aggressively
(it 403s after a few hundred calls). Trendlyne's ETF dashboard returns the whole
table in ~8 paginated calls with no rate limit, covering ~252 of our ~283 ETFs.
The ~31 it omits (large BeES/SBI funds) fall back to Tickertape.

Endpoint (discovered 2026-11-18 from the dashboard's React bundle):
  GET https://trendlyne.com/equity/api/get-etfs-tabledata-v2/byslug/all/?pageNumber=N
  Needs header X-Requested-With: XMLHttpRequest. 50 rows/page; body.isNextPage
  flags more pages. Each row is a 27-element list aligned to body.tableHeaders;
  the columns we use (indices confirmed against the header names):
    0  Stock Name
    1  NSE Symbol       (NSEcode)
    5  ISIN
    13 AUM              (raw INR -> divide by 1e7 for crore; e.g. 2.78e10 = 2786 cr)
    17 3 Months Avg Volume
    18 Liquidity        (categorical: High/Medium/Low)
    19 Expense ratio    (TER, percent)
    20 Tracking error   (percent; often null)
"""
import csv
import requests

API_URL = "https://trendlyne.com/equity/api/get-etfs-tabledata-v2/byslug/all/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json",
}
TIMEOUT = 20
MAX_PAGES = 15  # safety bound; the feed is ~7 pages

# Column indices within a tableData row.
C_NAME, C_SYM, C_ISIN, C_AUM, C_VOL, C_LIQ, C_TER, C_TRACKERR = 0, 1, 5, 13, 17, 18, 19, 20

# AUM is reported in raw rupees; divide to get crore.
AUM_RUPEES_PER_CRORE = 1e7

CACHE_COLUMNS = ["symbol", "isin", "name", "aum_cr", "ter_pct", "tracking_error",
                 "vol_3m", "liquidity_label"]


def _num(v):
    """Coerce a cell to float, or None if missing/non-numeric."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_etf_rows(getter=requests.get):
    """Paginate the Trendlyne ETF dashboard, returning the raw tableData rows.

    Returns whatever pages were fetched before any error. A transient outage or
    non-JSON/403 response ends pagination gracefully (returning rows so far, or
    [] on a first-page failure) rather than raising, so the caller can fall back
    to the per-ETF Tickertape path instead of crashing the whole run.
    """
    rows = []
    page = 1
    while page <= MAX_PAGES:
        try:
            resp = getter(API_URL, params={"pageNumber": page}, headers=HEADERS, timeout=TIMEOUT)
            body = resp.json().get("body", {})
        except (requests.RequestException, ValueError):
            break
        page_rows = body.get("tableData") or []
        rows.extend(page_rows)
        if not body.get("isNextPage"):
            break
        page += 1
    return rows


def rows_to_records(rows):
    """Turn raw rows into clean per-ETF dicts (AUM converted to crore)."""
    records = []
    for r in rows:
        if len(r) <= C_TRACKERR:
            continue
        aum_raw = _num(r[C_AUM])
        records.append({
            "symbol": str(r[C_SYM] or "").upper(),
            "isin": str(r[C_ISIN] or "").upper(),
            "name": r[C_NAME],
            "aum_cr": aum_raw / AUM_RUPEES_PER_CRORE if aum_raw is not None else None,
            "ter_pct": _num(r[C_TER]),
            "tracking_error": _num(r[C_TRACKERR]),
            "vol_3m": _num(r[C_VOL]),
            "liquidity_label": r[C_LIQ],
        })
    return records


def build_etf_map(records):
    """Index records by uppercase NSE symbol and by ISIN for lookup."""
    m = {}
    for rec in records:
        if rec["symbol"]:
            m[rec["symbol"]] = rec
        if rec["isin"]:
            m[rec["isin"]] = rec
    return m


def _write_cache(records, cache_path):
    with open(cache_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CACHE_COLUMNS)
        w.writeheader()
        for rec in records:
            w.writerow({k: rec.get(k) for k in CACHE_COLUMNS})


def _read_cache(cache_path):
    records = []
    with open(cache_path, newline="") as f:
        for row in csv.DictReader(f):
            records.append({
                "symbol": row["symbol"],
                "isin": row["isin"],
                "name": row["name"],
                "aum_cr": _num(row["aum_cr"]),
                "ter_pct": _num(row["ter_pct"]),
                "tracking_error": _num(row["tracking_error"]),
                "vol_3m": _num(row["vol_3m"]),
                "liquidity_label": row["liquidity_label"] or None,
            })
    return records


def load_etf_source(cache_path, refresh=False, getter=requests.get):
    """Return a symbol/ISIN -> record map, fetching once and caching to CSV.

    On a cached run (cache exists and not refresh) no network call is made.
    """
    import os
    if not refresh and os.path.exists(cache_path):
        records = _read_cache(cache_path)
    else:
        records = rows_to_records(fetch_etf_rows(getter))
        if records:
            _write_cache(records, cache_path)
    return build_etf_map(records)
