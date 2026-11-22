"""Point-to-point NAV returns (1/2/3/5 years) for funds, from mfapi.in NAV history.

Linking a fund to its NAV history:
  ETF        -> NSE symbol -> ISIN (data/11_nse_etf_list.csv) -> AMFI scheme code
  Index fund -> Direct-Growth ISIN (already on the row)       -> AMFI scheme code
  ISIN -> scheme code comes from AMFI's NAVAll.txt (data/12_amfi_navall.txt).

Conventions match NSE's Index Dashboard: 1-year is an absolute return, longer
periods are CAGR. A fund younger than the period gets NaN (not enough history).
ETF unit splits show up as a one-day NAV jump/crash; we detect them and rescale
earlier NAVs so the split doesn't masquerade as a return.
"""
import json
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

MFAPI_URL = "https://api.mfapi.in/mf/{code}"
PERIODS = (1, 2, 3, 5)
MAX_START_GAP_DAYS = 7          # nearest NAV must be within a week of the start date
SPLIT_LOW, SPLIT_HIGH = 0.55, 1.8  # one-day NAV ratios outside this band = unit split/merge


def load_isin_to_code(navall_path):
    """Map every ISIN in AMFI's NAVAll.txt to its scheme code."""
    out = {}
    with open(navall_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split(";")
            if len(parts) < 6 or not parts[0].strip().isdigit():
                continue
            code = int(parts[0])
            for isin in (parts[1], parts[2]):
                isin = isin.strip().upper()
                if isin.startswith("INF"):
                    out[isin] = code
    return out


def load_etf_isins(nse_etf_list_path):
    df = pd.read_csv(nse_etf_list_path)
    df.columns = [c.strip() for c in df.columns]
    return {str(s).strip().upper(): str(i).strip().upper()
            for s, i in zip(df["Symbol"], df["ISINNumber"])}


def fetch_nav_history(code, cache_dir, max_age_days=1, session=None):
    """Return a date-indexed NAV Series (ascending), using a JSON file cache."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{code}.json"
    payload = None
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400:
        payload = json.loads(path.read_text())
    if payload is None:
        r = (session or requests).get(MFAPI_URL.format(code=code), timeout=30)
        r.raise_for_status()
        payload = r.json()
        path.write_text(json.dumps(payload))
        time.sleep(0.2)
    rows = payload.get("data") or []
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({datetime.strptime(x["date"], "%d-%m-%Y"): float(x["nav"]) for x in rows
                   if x.get("nav") not in (None, "", "0", "0.0")})
    s = s[s > 0].sort_index()
    return adjust_for_splits(s)


def adjust_for_splits(nav):
    """Rescale NAVs before any one-day jump outside [SPLIT_LOW, SPLIT_HIGH]."""
    if len(nav) < 2:
        return nav
    nav = nav.copy()
    ratio = nav / nav.shift(1)
    for dt, r in ratio[(ratio < SPLIT_LOW) | (ratio > SPLIT_HIGH)].items():
        nav[nav.index < dt] *= r
    return nav


def _nav_on_or_before(nav, when):
    sub = nav[nav.index <= pd.Timestamp(when)]
    if sub.empty:
        return None, None
    return sub.index[-1], sub.iloc[-1]


def period_returns(nav, as_of, periods=PERIODS):
    """{years: return as fraction} -- 1y absolute, >1y CAGR, NaN if too young."""
    out = {y: np.nan for y in periods}
    end_dt, end_nav = _nav_on_or_before(nav, as_of)
    if end_dt is None:
        return out
    for y in periods:
        try:
            start = as_of.replace(year=as_of.year - y)
        except ValueError:  # 29 Feb
            start = as_of.replace(year=as_of.year - y, day=28)
        if nav.index[0] > pd.Timestamp(start):
            continue  # fund launched after the start date
        s_dt, s_nav = _nav_on_or_before(nav, start)
        if s_dt is None or (pd.Timestamp(start) - s_dt).days > MAX_START_GAP_DAYS:
            continue
        growth = end_nav / s_nav
        out[y] = growth - 1 if y == 1 else growth ** (1 / y) - 1
    return out


def _is_fixed_nav(nav, as_of):
    """Liquid ETFs that pay daily IDCW keep NAV flat (e.g. Rs 1,000); NAV-based
    returns would wrongly show ~0%."""
    last_year = nav[(nav.index > pd.Timestamp(as_of) - pd.Timedelta(days=365))
                    & (nav.index <= pd.Timestamp(as_of))]
    return len(last_year) > 20 and last_year.max() / last_year.min() < 1.001


def month_returns(nav, as_of, months=(1, 3, 6, 12, 24, 36, 60)):
    """{months: return} -- up to 12 months absolute, longer periods CAGR (same
    convention as NSE's dashboards). NaN when the fund is younger than the period."""
    out = {m: np.nan for m in months}
    end_dt, end_nav = _nav_on_or_before(nav, as_of)
    if end_dt is None:
        return out
    for m in months:
        start = (pd.Timestamp(as_of) - pd.DateOffset(months=m)).date()
        if nav.index[0] > pd.Timestamp(start):
            continue
        s_dt, s_nav = _nav_on_or_before(nav, start)
        if s_dt is None or (pd.Timestamp(start) - s_dt).days > MAX_START_GAP_DAYS:
            continue
        growth = end_nav / s_nav
        out[m] = growth - 1 if m <= 12 else growth ** (12 / m) - 1
    return out


def compute_fund_returns(funds, isin_to_code, etf_isins, cache_dir, as_of: date):
    """funds: DataFrame with fund_id, kind, symbol, isin. Returns one row per fund."""
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    recs = []
    for _, f in funds.iterrows():
        isin = (etf_isins.get(str(f["symbol"]).upper()) if f["kind"] == "ETF"
                else (str(f["isin"]).upper() if pd.notna(f["isin"]) else None))
        code = isin_to_code.get(isin) if isin else None
        rec = {"fund_id": f["fund_id"], "nav_isin": isin, "scheme_code": code,
               "first_nav_date": None, "returns_note": ""}
        rets = {y: np.nan for y in PERIODS}
        if code is None:
            rec["returns_note"] = "no AMFI scheme code for ISIN" if isin else "no ISIN"
        else:
            try:
                nav = fetch_nav_history(code, cache_dir, session=session)
                if nav.empty:
                    rec["returns_note"] = "no NAV history"
                elif _is_fixed_nav(nav, as_of):
                    rec["first_nav_date"] = nav.index[0].date()
                    rec["returns_note"] = "NAV held fixed; returns paid as daily dividends"
                else:
                    rec["first_nav_date"] = nav.index[0].date()
                    rets = period_returns(nav, as_of)
            except Exception as e:  # network/parse issue -- keep going, record why
                rec["returns_note"] = f"fetch failed: {type(e).__name__}"
        for y in PERIODS:
            rec[f"ret_{y}y"] = rets[y]
        recs.append(rec)
    return pd.DataFrame(recs)
