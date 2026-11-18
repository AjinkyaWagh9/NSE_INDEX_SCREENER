"""Fetch per-scheme AUM (cr) and TER (%) from Tickertape (primary) + Groww (fallback).

Discovery spike findings (2026-11-18, live calls against the real APIs):

Tickertape
----------
- Search: https://api.tickertape.in/search?text=<q>&types=etf,mutualfund
  Returns stocks with a `marketCap` field. IMPORTANT: for ETFs this field is
  NOT a reliable AUM figure -- it fluctuates independently of real AUM
  (observed `marketCap` for NIFTYBEES swinging between ~2,675cr and ~6,459cr
  across two calls seconds apart, while the fund's real AUM is ~68,000cr).
  So `marketCap` from search is used only as a fallback/sanity hint, never
  as the primary AUM source.
  Search also never returned `type: "mutualfund"` results in testing (only
  "etf" and "index") for either ETF or open-ended index fund queries, so
  open-ended index funds are not resolvable via Tickertape in this pipeline
  -- they fall through to the Groww path.
- Detail (confirmed working, 200 OK): https://api.tickertape.in/stocks/info/<sid>
  Candidates that do NOT work: /mutualfunds/detail/<sid> (404),
  /mf/detail/<sid> (404), /stocks/<sid> (404), /etf(s)/<sid> (404).
  Real AUM and TER live under `data.ratios`:
    data.ratios.asstUnderMan  -> AUM in INR crore (e.g. 68029.38 for NIFTYBEES)
    data.ratios.expenseRatio  -> TER in percent (e.g. 0.05 for NIFTYBEES)

Groww
-----
- Search: https://groww.in/v1/api/search/v3/query/global/st_query?query=<q>&web=true
  ETFs come back with entity_type "ETF" and a `search_id` (e.g.
  "reliance-etf-nifty-bees"); open-ended schemes come back with entity_type
  "Scheme" and both a `search_id` (slug) and numeric `scheme_code`.
- Detail (confirmed working, 200 OK, MF schemes only):
  https://groww.in/v1/api/data/mf/web/v1/scheme/search/<search_id>
  Candidates that do NOT work: .../web/v3/scheme/<id> (404),
  .../web/v1/scheme/<numeric_id> (502 -- gateway recognizes the route but
  requires the slug, not the numeric scheme_code, in this position),
  .../web/v1/scheme/portfolio/<search_id>/stats (500 -- that endpoint wants
  the *numeric* scheme_code, not the slug; it returns portfolio composition
  plus an `aum` field but no expense ratio, so it is not used here).
  This endpoint returns null for every field when given an ETF search_id
  (ETFs are not "schemes" on Groww) -- so the Groww path is effectively
  MF-only, which is fine since Tickertape covers ETFs.
  Real fields on this response:
    aum             -> AUM in INR crore (float, e.g. 28984.58)
    expense_ratio   -> TER in percent (STRING, e.g. "0.25" -- must cast to float)
"""
import time
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
           "Accept": "application/json"}

TT_SEARCH_URL = "https://api.tickertape.in/search"
GROWW_SEARCH_URL = "https://groww.in/v1/api/search/v3/query/global/st_query"
# Detail URLs confirmed in Step 1 discovery spike (see module docstring for
# the full list of candidates that were tried and failed):
TT_DETAIL_URL = "https://api.tickertape.in/stocks/info/{sid}"
GROWW_DETAIL_URL = "https://groww.in/v1/api/data/mf/web/v1/scheme/search/{sid}"

REQUEST_PAUSE = 0.3
TIMEOUT = 15

# --- Tickertape rate-limit handling -------------------------------------------
# Tickertape's public API caps requests aggressively and replies 403
# {"message":"REQUEST_LIMIT_EXCEEDED"} once the cap is hit. ETF AUM is only
# available from Tickertape (Groww returns aum=None for ETFs), so we must be a
# polite client: enforce a minimum interval between Tickertape calls, and on a
# 403 back off and retry a few times to ride out a short (per-minute) window.
# If 403s persist, `_TT_BLOCKED` latches True for the rest of the process so we
# stop hammering a blocked endpoint — the affected ETFs are left unresolved and
# picked up on a later run (the enrichment cache only retries unresolved funds),
# so coverage converges across runs once the limit resets.
TT_MIN_INTERVAL = 2.0      # seconds between Tickertape requests
TT_BACKOFF_SECONDS = 60    # on 403, wait this long before retrying
TT_BACKOFF_RETRIES = 2     # number of 403 backoff attempts before latching blocked

_tt_last_call = [0.0]
_TT_BLOCKED = [False]


def tt_is_blocked():
    """True once Tickertape has latched a persistent rate-limit block this run."""
    return _TT_BLOCKED[0]


def _tt_throttle():
    wait = TT_MIN_INTERVAL - (time.time() - _tt_last_call[0])
    if wait > 0:
        time.sleep(wait)
    _tt_last_call[0] = time.time()


def _get(url, params=None, retries=2, is_tickertape=False):
    tt_attempts = 0
    for attempt in range(retries + 1):
        try:
            if is_tickertape:
                if _TT_BLOCKED[0]:
                    return None
                _tt_throttle()
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 403 and is_tickertape:
                # Rate-limited: back off and retry a bounded number of times to
                # survive a short window; latch blocked if it won't clear.
                if tt_attempts < TT_BACKOFF_RETRIES:
                    tt_attempts += 1
                    time.sleep(TT_BACKOFF_SECONDS)
                    continue
                _TT_BLOCKED[0] = True
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(0.5 * (attempt + 1))
    return None


def tickertape_search(text):
    data = _get(TT_SEARCH_URL, {"text": text, "types": "etf,mutualfund"}, is_tickertape=True)
    if not data or not data.get("success"):
        return []
    return data.get("data", {}).get("stocks", [])


def groww_search(query):
    data = _get(GROWW_SEARCH_URL, {"query": query, "web": "true"})
    if not data or not data.get("data"):
        return []
    return data["data"].get("content", [])


class AggregatorClient:
    """Resolve AUM (cr) + TER (%) for a fund. Returns None when no confident match.

    `etf_source` is an optional symbol/ISIN -> record map (from
    ranking.trendlyne.load_etf_source). When present it is the primary source
    for ETFs — a bulk, non-rate-limited feed — with Tickertape as fallback for
    ETFs it doesn't carry (the ~31 large funds Trendlyne omits).
    """

    def __init__(self, etf_source=None):
        self.etf_source = etf_source or {}

    def fetch(self, kind, symbol, isin, name):
        query = symbol if (kind == "ETF" and symbol) else name
        if not query:
            return None

        if kind == "ETF":
            # --- Trendlyne bulk primary (ETFs) ---
            hit = self._from_etf_source(symbol, isin)
            if hit:
                return hit
            # --- Tickertape fallback (ETFs only -- see module docstring: the
            # discovery spike found Tickertape search never surfaces true
            # open-ended mutual-fund results, only "etf"/"index" types) ---
            hit = self._tickertape(kind, symbol, isin, name, query)
            if hit:
                return hit
            time.sleep(REQUEST_PAUSE)

        # --- Groww fallback (index funds + any ETF the above missed) ---
        return self._groww(kind, symbol, isin, name, query)

    def _from_etf_source(self, symbol, isin):
        rec = None
        if symbol:
            rec = self.etf_source.get(str(symbol).upper())
        if rec is None and isin:
            rec = self.etf_source.get(str(isin).upper())
        if rec and rec.get("aum_cr") is not None:
            return {"aum_cr": float(rec["aum_cr"]), "ter_pct": rec.get("ter_pct"),
                    "matched_key": rec.get("symbol") or symbol, "source": "trendlyne"}
        return None

    def _tickertape(self, kind, symbol, isin, name, query):
        if _TT_BLOCKED[0]:
            return None
        results = tickertape_search(query)
        if not results:
            return None
        best = _best_tt_match(results, symbol, name)
        if not best:
            return None
        sid = best.get("sid")
        ter = None
        aum = None
        if sid:
            detail = _get(TT_DETAIL_URL.format(sid=sid), is_tickertape=True)
            aum = _extract_tt_aum(detail)
            ter = _extract_tt_ter(detail)
        if aum is None:
            # No marketCap fallback: the spike documented it as unreliable
            # (swings far from true AUM), so a missing detail-AUM means we
            # fall through to Groww instead of returning a bad number.
            return None
        return {"aum_cr": float(aum), "ter_pct": ter,
                "matched_key": best.get("ticker") or sid, "source": "tickertape"}

    def _groww(self, kind, symbol, isin, name, query):
        results = groww_search(query)
        best = _best_groww_match(results, symbol, isin, name)
        if not best:
            return None
        sid = best.get("search_id")
        detail = _get(GROWW_DETAIL_URL.format(sid=sid)) if sid else None
        aum = _extract_groww_aum(detail)
        ter = _extract_groww_ter(detail)
        if aum is None:
            return None
        return {"aum_cr": float(aum), "ter_pct": ter, "matched_key": sid, "source": "groww"}


# --- matching + extraction helpers (field names finalized in Step 1 spike) ---
def _norm(s):
    return "".join(ch for ch in str(s).upper() if ch.isalnum())

def _best_tt_match(results, symbol, name):
    if symbol:
        for r in results:
            if str(r.get("ticker", "")).upper() == symbol.upper():
                return r
    nn = _norm(name)
    for r in results:
        if _norm(r.get("name")) == nn:
            return r
    # Weak fallback: Tickertape marks some results "EXACT" with no
    # symbol/name match above. Only trust it if there's still some
    # correlation to what we asked for, to avoid accepting an unrelated
    # top hit.
    if results and str(results[0].get("match")) == "EXACT":
        top = results[0]
        top_ticker = _norm(top.get("ticker"))
        top_name = _norm(top.get("name"))
        if symbol and top_ticker and (_norm(symbol) in top_ticker or top_ticker in _norm(symbol)):
            return top
        if nn and top_name and (nn in top_name or top_name in nn):
            return top
    return None

def _best_groww_match(results, symbol, isin, name):
    for r in results:
        if isin and str(r.get("isin", "")).upper() == isin.upper():
            return r
    if symbol:
        for r in results:
            if str(r.get("nse_scrip_code", "")).upper() == symbol.upper():
                return r
    nn = _norm(name)
    for r in results:
        if _norm(r.get("title")) == nn:
            return r
    return None

def _extract_tt_ter(detail):
    if not detail:
        return None
    ratios = detail.get("data", {}).get("ratios", {}) if isinstance(detail.get("data"), dict) else {}
    v = ratios.get("expenseRatio")
    return float(v) if v is not None else None

def _extract_tt_aum(detail):
    if not detail:
        return None
    ratios = detail.get("data", {}).get("ratios", {}) if isinstance(detail.get("data"), dict) else {}
    v = ratios.get("asstUnderMan")
    return float(v) if v is not None else None

def _extract_groww_aum(detail):
    if not detail or not isinstance(detail, dict):
        return None
    v = detail.get("aum")
    return float(v) if v is not None else None

def _extract_groww_ter(detail):
    if not detail or not isinstance(detail, dict):
        return None
    v = detail.get("expense_ratio")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
