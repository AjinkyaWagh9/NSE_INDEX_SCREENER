"""Debt-row NAV history from AMFI (via mfapi.in), reusing the pipeline's cached fetcher."""
from pathlib import Path

from ranking.returns import fetch_nav_history
from screener.core.returns import Bar


def fetch_nav_bars(scheme_code: int, cache_dir: Path, max_age_days: float = 0.5,
                   session=None) -> list[Bar]:
    nav = fetch_nav_history(int(scheme_code), cache_dir, max_age_days=max_age_days, session=session)
    return [Bar(ts.date(), None, float(v)) for ts, v in nav.items()]
