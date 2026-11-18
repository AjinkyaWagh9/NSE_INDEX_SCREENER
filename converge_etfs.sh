#!/bin/bash
# Auto-convergence job for the ~25 large ETFs that Trendlyne omits and whose AUM
# only Tickertape has. Each run retries only the unresolved funds (the enrichment
# cache skips resolved ones), so coverage climbs as Tickertape's rate-limit window
# resets. The job stops itself once ETF coverage is near-complete OR after a run
# cap, so it never hammers the APIs indefinitely.
#
# Installed as an hourly crontab entry (see the companion note). Logs to
# data/convergence.log. To stop early:  crontab -l | grep -v converge_etfs | crontab -

set -u
REPO="/Users/ajinkyawagh/Desktop/STARTUP/ETF_Indices"
PY="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
LOG="$REPO/data/convergence.log"
UNRESOLVED_STOP=3     # stop when <= this many ETFs remain unresolved
MAX_RUNS=24           # safety cap on total runs

cd "$REPO" || exit 1

runs=$(grep -c '^RUN ' "$LOG" 2>/dev/null || echo 0)
runs=$((runs + 1))

"$PY" run_ranking.py >> "$LOG" 2>&1

# Count unresolved ETFs from the fresh cache against the ETF universe.
unresolved=$("$PY" - <<'PY'
import pandas as pd
from ranking.dedup import build_universe
u = build_universe(pd.read_csv("data/06_mapped_funds.csv"))
etf = u[u.kind == "ETF"]
cache = pd.read_csv("data/08_aum_ter.csv")
m = etf.merge(cache, on="fund_id", how="left")
print(int((~m.resolved.fillna(False).astype(bool)).sum()))
PY
)

printf 'RUN %s  %s  unresolved_etfs=%s  run=%s/%s\n' \
  "$runs" "$(date '+%Y-%m-%d %H:%M')" "$unresolved" "$runs" "$MAX_RUNS" >> "$LOG"

if [ "${unresolved:-99}" -le "$UNRESOLVED_STOP" ] || [ "$runs" -ge "$MAX_RUNS" ]; then
  crontab -l 2>/dev/null | grep -v 'converge_etfs.sh' | crontab -
  printf 'CONVERGED/STOPPED at run %s (unresolved_etfs=%s). Cron entry removed.\n' \
    "$runs" "$unresolved" >> "$LOG"
fi
