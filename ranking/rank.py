"""Filter at the AUM threshold and produce two per-index rankings."""
import numpy as np
import pandas as pd

AUM_THRESHOLD = 10.0
COMPOSITE_WEIGHTS = {"aum": 0.5, "ter": 0.3, "liq": 0.2}


def split_by_aum(df, threshold=AUM_THRESHOLD):
    df = df.copy()
    resolved = df["resolved"].astype(bool) & df["aum_cr"].notna()
    unresolved = df[~resolved]
    qualifying = df[resolved & (df["aum_cr"] >= threshold)]
    below = df[resolved & (df["aum_cr"] < threshold)]
    return (qualifying.reset_index(drop=True),
            unresolved.reset_index(drop=True),
            below.reset_index(drop=True))


def rank_by_aum(qualifying):
    df = qualifying.copy()
    df["rank_aum"] = (df.groupby("matched_index")["aum_cr"]
                        .rank(method="first", ascending=False).astype(int))
    return df.sort_values(["matched_index", "rank_aum"]).reset_index(drop=True)


def _minmax(series, higher_better=True):
    s = series.astype(float)
    lo, hi = s.min(), s.max()
    if np.isclose(hi, lo):
        return pd.Series(1.0, index=s.index)
    norm = (s - lo) / (hi - lo)
    return norm if higher_better else 1.0 - norm


def _score_group(g, weights):
    g = g.copy()
    g["aum_norm"] = _minmax(g["aum_cr"], higher_better=True)
    # TER: lower better; missing -> NaN norm (term dropped per-row)
    ter_present = g["ter_pct"].notna()
    g["ter_norm"] = np.nan
    if ter_present.any():
        g.loc[ter_present, "ter_norm"] = _minmax(g.loc[ter_present, "ter_pct"], higher_better=False)
    # Liquidity: higher better; missing -> NaN norm (term dropped)
    liq_present = g["liquidity"].notna()
    g["liq_norm"] = np.nan
    if liq_present.any():
        g.loc[liq_present, "liq_norm"] = _minmax(g.loc[liq_present, "liquidity"], higher_better=True)

    def row_score(row):
        terms = [("aum", row["aum_norm"]), ("ter", row["ter_norm"]), ("liq", row["liq_norm"])]
        num = sum(weights[k] * v for k, v in terms if pd.notna(v))
        den = sum(weights[k] for k, v in terms if pd.notna(v))
        return num / den if den > 0 else np.nan

    g["composite_score"] = g.apply(row_score, axis=1)
    g["rank_composite"] = g["composite_score"].rank(method="first", ascending=False).astype(int)
    return g


def rank_composite(qualifying, weights=COMPOSITE_WEIGHTS):
    df = qualifying.copy()
    out = df.groupby("matched_index", group_keys=False).apply(lambda g: _score_group(g, weights))
    return out.sort_values(["matched_index", "rank_composite"]).reset_index(drop=True)


def top_n_per_index(df, n=3, rank_col="rank_aum"):
    return (df[df[rank_col] <= n]
            .sort_values(["matched_index", rank_col])
            .reset_index(drop=True))
