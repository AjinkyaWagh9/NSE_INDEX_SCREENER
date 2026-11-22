#!/usr/bin/env python3
"""Generate screener/core/universe.json from this project's shortlist + Kite's instrument list.

Run from the repo root after run_ranking.py and compute_returns.py:
    python3 -m screener.tools.build_universe            # downloads Kite's public instrument list
    python3 -m screener.tools.build_universe --instruments path/to/instruments.csv
"""
import argparse
import io
import json
import re
from pathlib import Path

import pandas as pd
import requests

import build_presentation as bp

KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"
OUT = Path(__file__).resolve().parent.parent / "core" / "universe.json"

# Our canonical index id -> Kite tradingsymbol, where names differ after normalisation.
KITE_ALIASES = {
    "NIFTY SMALLCAP 250": "NIFTY SMLCAP 250",
    "NIFTY SMALLCAP 100": "NIFTY SMLCAP 100",
    "NIFTY SMALLCAP 50": "NIFTY SMLCAP 50",
    "NIFTY LARGEMIDCAP 250": "NIFTY LARGEMID250",
    "NIFTY TOTAL MARKET": "NIFTY TOTAL MKT",
    "NIFTY MIDSMALLCAP 400": "NIFTY MIDSML 400",
    "NIFTY MIDSMALLCAP400 50:50": "NIFTY MIDSMALL 50 50",
    "NIFTY PRIVATE BANK": "NIFTY PVT BANK",
    "NIFTY OIL & GAS": "NIFTY OIL AND GAS",
    "NIFTY MIDSMALL HEALTHCARE": "NIFTY MIDSML HLTH",
    "NIFTY FINANCIAL SERVICES EX-BANK": "NIFTY FINSEREXBNK",
    "NIFTY500 HEALTHCARE": "NIFTY500 HEALTH",
    "NIFTY INFRASTRUCTURE": "NIFTY INFRA",
    "NIFTY INDIA MANUFACTURING": "NIFTY INDIA MFG",
    "NIFTY INDIA CONSUMPTION": "NIFTY CONSUMPTION",
    "NIFTY INDIA DIGITAL": "NIFTY IND DIGITAL",
    "NIFTY INDIA RAILWAYS PSU": "NIFTY RAILWAYS PSU",
    "NIFTY INDIA INTERNET": "NIFTY INTERNET",
    "NIFTY INDIA INFRASTRUCTURE & LOGISTICS": "NIFTY INFRALOG",
    "NIFTY200 MOMENTUM 30": "NIFTY200MOMENTM30",
    "NIFTY100 LOW VOLATILITY 30": "NIFTY100 LOWVOL30",
    "NIFTY50 EQUAL WEIGHT": "NIFTY50 EQL WGT",
    "NIFTY MIDCAP150 MOMENTUM 50": "NIFTYM150MOMNTM50",
    "NIFTY ALPHA LOW-VOLATILITY 30": "NIFTY ALPHALOWVOL",
    "NIFTY500 MULTICAP 50:25:25": "NIFTY500 MULTICAP",
    "NIFTY200 QUALITY 30": "NIFTY200 QUALTY30",
    "NIFTY100 EQUAL WEIGHT": "NIFTY100 EQL WGT",
    "NIFTY MIDCAP150 QUALITY 50": "NIFTY M150 QLTY50",
    "NIFTY500 FLEXICAP QUALITY 30": "NIFTY500 FLEXICAP",
    "NIFTY500 MULTICAP INDIA MANUFACTURING 50:30:20": "NIFTY MULTI MFG",
    "NIFTY100 QUALITY 30": "NIFTY100 QUALTY30",
    "NIFTY100 ESG SECTOR LEADERS": "NIFTY100ESGSECLDR",
    "NIFTY500 QUALITY 50": "NIFTY500 QLTY50",
    "NIFTY DIVIDEND OPPORTUNITIES 50": "NIFTY DIV OPPS 50",
    "NIFTY500 MULTICAP INFRASTRUCTURE 50:30:20": "NIFTY MULTI INFRA",
    "NIFTY TOTAL MARKET MOMENTUM QUALITY 50": "NIFTY TMMQ 50",
    "NIFTY500 LOW VOLATILITY 50": "NIFTY500 LOWVOL50",
    "NIFTY GROWTH SECTORS 15": "NIFTY GROWSECT 15",
    # debt indices that Kite carries
    "NIFTY 10 YR BENCHMARK G-SEC": "NIFTY GS 10YR",
    "NIFTY 8-13 YR G-SEC": "NIFTY GS 8 13YR",
    "NIFTY BHARAT BOND INDEX - APRIL 2030": "BHARATBOND-APR30",
    "NIFTY BHARAT BOND INDEX - APRIL 2031": "BHARATBOND-APR31",
    "NIFTY BHARAT BOND INDEX - APRIL 2032": "BHARATBOND-APR32",
    "NIFTY BHARAT BOND INDEX - APRIL 2033": "BHARATBOND-APR33",
}


class UniverseError(Exception):
    """An index could not be resolved; fix KITE_ALIASES rather than drop it silently."""


def norm(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper().replace("NIFTY", ""))


def kite_index_table(csv_text: str) -> pd.DataFrame:
    k = pd.read_csv(io.StringIO(csv_text), low_memory=False)
    k = k[(k["segment"] == "INDICES") & (k["exchange"] == "NSE")]
    return k[["instrument_token", "tradingsymbol", "name"]].reset_index(drop=True)


def resolve_kite(index_id: str, display_name: str, tab: str, kite: pd.DataFrame):
    """(tradingsymbol, instrument_token) or (None, None). Debt only via KITE_ALIASES."""
    by_sym = dict(zip(kite["tradingsymbol"], kite["instrument_token"]))
    sym = KITE_ALIASES.get(index_id)
    if sym is None and tab == "equity":
        lookup = {norm(n): s for n, s in zip(kite["name"], kite["tradingsymbol"])}
        lookup.update({norm(s): s for s in kite["tradingsymbol"]})
        sym = lookup.get(norm(display_name))
    if sym is None or sym not in by_sym:
        return None, None
    return sym, int(by_sym[sym])


def debt_category(index_id: str) -> str:
    u = index_id.upper()
    if "BHARAT BOND" in u:
        return "Bharat Bond"
    if "1D RATE" in u or "LIQUID" in u:
        return "Liquid / Overnight"
    if "HYBRID" in u:
        return "Hybrid"
    if "BENCHMARK" in u or "8-13 YR" in u:
        return "G-Sec Benchmark"
    return "Target Maturity"


def _top_names(sub: pd.DataFrame, kind: str, n: int = 3) -> list:
    return list(sub[sub["Type"] == kind].sort_values("aum_cr", ascending=False)["Fund"].head(n))


def build_records(df: pd.DataFrame, fund_rets: pd.DataFrame, kite: pd.DataFrame) -> list:
    recs, unresolved = [], []
    for ix in df.sort_values(["_cat", "_top", "matched_index"])["matched_index"].unique():
        sub = df[df["matched_index"] == ix]
        first = sub.iloc[0]
        tab = "debt" if first["Category"] == "Debt" else "equity"
        sym, tok = resolve_kite(ix, first["Index"], tab, kite)
        fund = code = None
        if sym:
            source = "kite"
        elif tab == "debt" and (proxy := bp._proxy_fund(ix, df, fund_rets)):
            source, (fund, code) = "amfi", proxy
        else:
            source = "none"
            if tab == "equity":
                unresolved.append(ix)
        recs.append({
            "id": ix,
            "display_name": first["Index"],
            "tab": tab,
            "category": debt_category(ix) if tab == "debt" else first["Category"],
            "source": source,
            "kite_symbol": sym,
            "kite_instrument_token": tok,
            "nav_scheme_code": int(code) if code is not None else None,
            "nav_fund_name": fund,
            "etfs": _top_names(sub, "ETF"),
            "index_funds": _top_names(sub, "Index Fund"),
        })
    if unresolved:
        raise UniverseError(f"No Kite symbol for equity indices: {unresolved} - add them to KITE_ALIASES")
    return recs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instruments", help="local copy of Kite's instruments CSV (default: download)")
    args = ap.parse_args()
    if args.instruments:
        text = Path(args.instruments).read_text(encoding="utf-8")
    else:
        resp = requests.get(KITE_INSTRUMENTS_URL, timeout=60)
        resp.raise_for_status()
        text = resp.text
    df, _ = bp.load()
    recs = build_records(df, pd.read_csv(bp.RETURNS), kite_index_table(text))
    OUT.write_text(json.dumps(recs, indent=1, ensure_ascii=False), encoding="utf-8")
    count = lambda tab, src: sum(r["tab"] == tab and r["source"] == src for r in recs)
    print(f"Wrote {OUT}: equity kite={count('equity', 'kite')} | debt kite={count('debt', 'kite')} "
          f"amfi={count('debt', 'amfi')} none={count('debt', 'none')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
