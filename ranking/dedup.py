"""Build the canonical passive-fund universe from 06_mapped_funds."""
import numpy as np
import pandas as pd

EXCLUDED_INDICES = {"", "COMMODITY (Gold/Silver)", "INTERNATIONAL INDEX"}
OUT_COLUMNS = ["fund_id","name","kind","isin","symbol","amc","matched_index","liquidity","nav"]


def _to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def _pick_canonical(group: pd.DataFrame) -> pd.Series:
    """Prefer Direct plan, then Growth option; fall back to first row."""
    plan = group["Plan"].fillna("")
    direct = group[plan.str.contains("Direct", case=False)]
    use = direct if len(direct) else group
    opt = use["Option"].fillna("")
    growth = use[opt.str.contains("Growth", case=False)]
    return (growth if len(growth) else use).iloc[0]


def build_universe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Matched_Index"] = df["Matched_Index"].fillna("")
    df = df[~df["Matched_Index"].isin(EXCLUDED_INDICES)]

    # --- ETFs: NSE-listed rows only ---
    nse = df[df["Source"] == "NSE_ETF"]
    etf_rows = []
    for _, r in nse.iterrows():
        etf_rows.append({
            "fund_id": str(r["Symbol"]),
            "name": str(r["Scheme_Name"]),
            "kind": "ETF",
            "isin": "",
            "symbol": str(r["Symbol"]),
            "amc": "",
            "matched_index": r["Matched_Index"],
            "liquidity": _to_float(r.get("Traded_Value")),
            "nav": _to_float(r.get("NAV")),
        })

    # --- Index funds: AMFI Index Fund rows, collapsed to one canonical per (name, AMC) ---
    idx = df[(df["Source"] == "AMFI") & (df["Scheme_Type"] == "Index Fund")].copy()
    if_rows = []
    if len(idx):
        for (name, amc), g in idx.groupby(["Scheme_Name", "AMC"], dropna=False):
            r = _pick_canonical(g)
            if_rows.append({
                "fund_id": f"{amc}|{name}",
                "name": str(name),
                "kind": "IndexFund",
                "isin": "" if pd.isna(r.get("ISIN")) else str(r["ISIN"]),
                "symbol": "",
                "amc": str(amc),
                "matched_index": r["Matched_Index"],
                "liquidity": np.nan,
                "nav": _to_float(r.get("NAV")),
            })

    out = pd.DataFrame(etf_rows + if_rows, columns=OUT_COLUMNS)
    return out.reset_index(drop=True)
