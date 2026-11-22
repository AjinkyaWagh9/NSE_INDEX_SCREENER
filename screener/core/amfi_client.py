"""Debt-row NAV history from AMFI (via mfapi.in). Dependency-light on purpose (requests only,
no pandas) so the packaged app stays small and the module ports to the web app as-is.
Same cache format and split rule as the pipeline's ranking/returns.py."""
import json
import time
from datetime import datetime
from pathlib import Path

import requests

from screener.core.returns import Bar

MFAPI_URL = "https://api.mfapi.in/mf/{code}"
SPLIT_LOW, SPLIT_HIGH = 0.55, 1.8   # one-day NAV ratios outside this band = unit split/merge


def _payload(code: int, cache_dir: Path, max_age_days: float, session) -> dict:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{code}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400:
        return json.loads(path.read_text())
    r = (session or requests).get(MFAPI_URL.format(code=code), timeout=30)
    r.raise_for_status()
    payload = r.json()
    path.write_text(json.dumps(payload))
    return payload


def _adjust_for_splits(points: list) -> list:
    """Rescale earlier NAVs at any one-day jump outside [SPLIT_LOW, SPLIT_HIGH]."""
    out = [list(p) for p in points]
    for i in range(1, len(out)):
        ratio = out[i][1] / out[i - 1][1]
        if ratio < SPLIT_LOW or ratio > SPLIT_HIGH:
            for j in range(i):
                out[j][1] *= ratio
    return [tuple(p) for p in out]


def fetch_nav_bars(scheme_code: int, cache_dir: Path, max_age_days: float = 0.5,
                   session=None) -> list[Bar]:
    rows = _payload(int(scheme_code), cache_dir, max_age_days, session).get("data") or []
    points = {}
    for x in rows:
        try:
            nav = float(x.get("nav") or 0)
        except ValueError:
            continue
        if nav > 0:
            points[datetime.strptime(x["date"], "%d-%m-%Y").date()] = nav
    return [Bar(d, None, nav) for d, nav in _adjust_for_splits(sorted(points.items()))]
