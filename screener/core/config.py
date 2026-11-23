"""App-wide constants, IST time helpers and file locations."""
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30), "IST")  # India has no DST
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
HISTORY_MONTHS = 60          # 5 years of daily history
HISTORY_PAD_DAYS = 7         # so the 5Y anchor has a close on or before it
MAX_ANCHOR_GAP_DAYS = 7      # a past close older than this before the target -> blank
HIST_MIN_INTERVAL_S = 1 / 3  # Kite historical API allows ~3 requests/second
CORE_DIR = Path(__file__).resolve().parent          # screener/core
SCREENER_DIR = CORE_DIR.parent                       # screener/


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def app_dir() -> Path:
    """Writable folder for screener.db, screener.log and nav_cache: SCREENER_DATA_DIR if
    set (web/server), next to the executable when frozen by PyInstaller, else screener/."""
    if os.environ.get("SCREENER_DATA_DIR"):
        return Path(os.environ["SCREENER_DATA_DIR"])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SCREENER_DIR


def resource_path(name: str) -> Path:
    """Read-only files shipped with core (e.g. universe.json)."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "screener" / "core" / name if base else CORE_DIR / name


def _secret(name: str) -> str:
    """Env var first (web), else the git-ignored screener/secrets_local.py (desktop)."""
    if os.environ.get(name):
        return os.environ[name].strip()
    try:
        import screener.secrets_local as local
    except ImportError:
        return ""
    return str(getattr(local, name, "") or "").strip()


def load_api_key() -> str:
    """Kite API key ('' if not configured)."""
    return _secret("KITE_API_KEY")


def load_api_secret() -> str:
    """Kite API secret, only needed to log in inside the app ('' if not configured)."""
    return _secret("KITE_API_SECRET")


def token_cache_file() -> Path:
    return app_dir() / ".token_cache.json"


def load_cached_token(today: date) -> str:
    p = token_cache_file()
    if not p.exists():
        return ""
    try:
        import json
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("date") == today.isoformat() and data.get("token"):
            return str(data["token"]).strip()
    except Exception:
        pass
    return ""


def save_cached_token(today: date, token: str) -> None:
    p = token_cache_file()
    try:
        import json
        p.write_text(json.dumps({"date": today.isoformat(), "token": token.strip()}), encoding="utf-8")
    except Exception:
        pass


def clear_cached_token() -> None:
    try:
        token_cache_file().unlink(missing_ok=True)
    except Exception:
        pass
