"""One-off check of your Kite access. Run from the repo root:
    python3 -m screener.tools.probe_kite
It asks for today's access token (not echoed), confirms historical-data access, reports how far
back daily history goes for every Kite index, and compares 1M/3M with NSE's latest Index Dashboard
(TRI, so small differences of a few tenths of a percent are expected)."""
import getpass
from datetime import timedelta

from screener.core.config import HISTORY_MONTHS, HISTORY_PAD_DAYS, load_api_key, today_ist
from screener.core.kite_client import KiteClient, TokenError
from screener.core.returns import compute_returns, months_back
from screener.core.universe import load_universe


def _dashboard():
    try:
        from fetch_etf_index_data import match_index
        from ranking.index_dashboard import load_index_returns
        return load_index_returns("data/index_dashboards", match_index)
    except Exception as e:  # noqa: BLE001
        print(f"(No NSE dashboard comparison: {e})")
        return None, None


def main() -> int:
    token = getpass.getpass("Kite access token: ")
    try:
        client = KiteClient(load_api_key(), token)
        print("Connected as", client.validate())
    except TokenError as e:
        print("Token problem:", e)
        return 1
    dash, dash_asof = _dashboard()
    today = today_ist()
    start = months_back(today, HISTORY_MONTHS) - timedelta(days=HISTORY_PAD_DAYS)
    short = []
    for info in (i for i in load_universe() if i.source == "kite"):
        try:
            bars = client.daily_bars(info.kite_instrument_token, start, today - timedelta(days=1))
        except Exception as e:  # noqa: BLE001
            print(f"{info.display_name:48} ERROR {e}")
            continue
        first = bars[0].date if bars else None
        line = f"{info.display_name:48} {len(bars):5d} days from {first}"
        if first is None or first > start + timedelta(days=14):
            short.append(info.display_name)
        if dash is not None and info.id in dash.index and bars:
            r = compute_returns([b for b in bars if b.date <= dash_asof], dash_asof)
            d = dash.loc[info.id]
            for p, col in (("1M", "r1m"), ("3M", "r3m")):
                if r.periods[p] is not None and d[col] == d[col]:
                    line += f" | {p} Kite {r.periods[p] * 100:+.2f}% vs NSE {d[col] * 100:+.2f}%"
        print(line)
    print(f"\n{len(short)} indices have less than 5 years of history "
          "(their 3Y/5Y will show '—' until enough data exists):")
    for name in short:
        print("  -", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
