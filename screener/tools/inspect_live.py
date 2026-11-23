"""Check live quotes and return calculation for any index.

Usage:
    python3 -m screener.tools.inspect_live "NIFTY PHARMA"
    python3 -m screener.tools.inspect_live "NIFTY 50"
"""
import sys
from screener.core.config import app_dir, load_api_key, load_cached_token, today_ist
from screener.core.db import BarStore
from screener.core.kite_client import KiteClient
from screener.core.returns import PERIODS, compute_returns
from screener.core.universe import load_universe


def main():
    target = sys.argv[1].upper() if len(sys.argv) > 1 else "NIFTY 50"
    universe = load_universe()
    match = next((i for i in universe if target in i.id.upper() or target in i.display_name.upper()), None)
    if not match:
        print(f"Index matching '{target}' not found.")
        return 1

    token = load_cached_token(today_ist())
    if not token:
        print("No active session cached for today. Start the screener and connect first.")
        return 1

    client = KiteClient(load_api_key(), token)
    store = BarStore(app_dir() / "screener.db")
    bars = store.bars(match.id)

    symbol = f"NSE:{match.kite_symbol}"
    quote_data = client.kite.quote([symbol]).get(symbol, {})
    ltp = quote_data.get("last_price")
    ohlc = quote_data.get("ohlc", {})
    open_price = ohlc.get("open")
    prev_close = ohlc.get("close") or (bars[-1].close if bars else None)

    ret = compute_returns(bars, today_ist(), live_price=ltp, live_open=open_price)

    print(f"\n=== Live Verification for {match.display_name} ({match.id}) ===")
    print(f"Kite Symbol:         {match.kite_symbol} (Token: {match.kite_instrument_token})")
    print(f"Previous Close:      {prev_close}")
    print(f"Today's Open:        {open_price}")
    print(f"Live Price (LTP):    {ltp}")
    print("--------------------------------------------------")
    if open_price and prev_close:
        print(f"Gap %:               {ret.gap * 100:+.2f}%  (Formula: ({open_price} - {prev_close}) / {prev_close})")
    if ltp and prev_close:
        print(f"Day %:               {ret.day * 100:+.2f}%  (Formula: ({ltp} - {prev_close}) / {prev_close})")
    print("--------------------------------------------------")
    print("Period Returns (computed vs historical daily closes):")
    for p in PERIODS:
        val = ret.periods[p]
        cagr = " (CAGR)" if p in ("2Y", "3Y", "5Y") else ""
        print(f"  {p:4s}: {f'{val * 100:+.2f}%{cagr}' if val is not None else '—'}")
    print("==================================================\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
