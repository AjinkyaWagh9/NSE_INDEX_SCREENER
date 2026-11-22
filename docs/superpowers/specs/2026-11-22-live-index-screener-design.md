# Live Index Screener — Design

**Date:** 2026-11-22
**Status:** Approved design, pending spec review
**Location:** `screener/` (new folder in this repository)

## 1. Purpose

A desktop app that shows live and historical returns for every NSE index in our
shortlist, beside the ETFs and index funds that track each index. It replaces the
static "Index Returns" sheet in `data/ETF_Index_Shortlist.xlsx` with a version
that updates during market hours.

The app is read-only: it never places orders.

## 2. Scope

**In scope**
- Two tabs: **Equity** (89 indices) and **Debt** (41 indices).
- Return columns: Gap %, Day %, 7D, 15D, 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y.
- Live updates via Zerodha Kite Connect during market hours.
- A local SQLite database of daily closes, seeded once from Kite historical data
  (equity + 6 debt indices) and AMFI NAV history (35 debt indices), then extended daily.
- Sortable columns, category filter, text search.
- Fund names (ETFs, index funds) per index — no AUM figures.
- Single-file packaging with PyInstaller (Windows .exe built on Windows; macOS build on Mac).

**Out of scope**
- Charts, alerts, watchlists, portfolio tracking, order placement.
- Total Return Index (TRI) data — Kite provides price indices only (see §6.3).
- Changing the index universe at runtime (it is regenerated from the pipeline; see §4.1).
- How the app is distributed to other users.

## 3. User interface

One window (PySide6).

**Top bar**
- *Access token* input (masked) and **Connect** button.
- Status indicator:
  - 🟢 Live — ticks streaming.
  - 🟡 Market closed / not connected — showing last stored close.
  - 🔴 Token invalid or expired — message asks for today's token.
- "Last updated HH:MM:SS".
- **Refresh history** button — re-runs the history fill-in (§5.2 step 2) and AMFI refresh.

**Tabs: Equity | Debt** — identical table layout:

| Category | Index | ETFs | Index Funds | Gap % | Day % | 7D | 15D | 1M | 3M | 6M | 1Y | 2Y | 3Y | 5Y |

- Click a column header to sort descending; click again for ascending (Qt `QSortFilterProxyModel`;
  numeric sort, blanks always last).
- **Category** dropdown filter and a **search** box (matches index or fund names).
- Positive values green, negative red; Day % / Gap % briefly highlight when a tick changes them.
- ETFs / Index Funds cells list fund names, one per line, largest first (from the shortlist).
- Footer note on the Equity tab: "Price index returns (excl. dividends). 2Y+ are annualised (CAGR)."
- Debt rows sourced from AMFI NAV show a tag "NAV · <date>" in the Index cell tooltip
  and a small marker; their Gap % is "—".
- A "—" cell has a tooltip explaining why (e.g. "Index younger than 3 years",
  "No Kite data").

## 4. Components

Each unit has one job and a narrow interface.

**Web-portability rule:** code lives in two packages. `screener/core/` (config, returns
engine, storage, universe, Kite and AMFI clients, service) has no Qt imports and is copied
unchanged into the future web app. `screener/desktop/` (Qt controller, UI, entry point) is
replaced by a web backend. Storage sits behind a `BarRepository` interface so the web app can
use its own database. Rows serialise with `RowData.to_dict()`. The API key can also come from
the `KITE_API_KEY` environment variable, and the data folder from `SCREENER_DATA_DIR`.
A test fails if anything in core imports Qt or desktop code.

| Unit | Responsibility | Depends on |
|---|---|---|
| `universe.json` + `build_universe.py` | Fixed list of indices and their metadata (§4.1). Generated from this repo's pipeline outputs. | `data/07_final_shortlist.xlsx`, Kite instrument list |
| `config.py` / `secrets_local.py` | API key (bundled, git-ignored), paths, constants (throttle rate, market hours). | — |
| `kite_client.py` | Kite Connect wrapper: validate token, fetch daily history, run KiteTicker live feed. | `kiteconnect` SDK |
| `amfi_client.py` | Fetch NAV history (mfapi.in) for debt proxy funds. Self-contained (no pandas) with the same cache format and split rule as `ranking/returns.py`, so the packaged app stays small and core needs only `requests` + `kiteconnect`. | `requests` |
| `db.py` | SQLite access: upsert/read daily bars, last stored date per index. | `sqlite3` |
| `returns.py` (engine) | Pure functions: given a series of daily closes, today's open, latest price → all return columns. No I/O. | — |
| `controller.py` | Orchestrates connect → backfill → live; turns ticks into table updates; end-of-day close capture. Runs network work off the UI thread (`QThread`). | all of the above |
| `ui/` | Main window, tabs, table model, filters. Displays rows from the controller only. | PySide6 |

### 4.1 `universe.json`

One record per index:

```json
{
  "id": "NIFTY SMALLCAP 250",
  "display_name": "Nifty Smallcap 250",
  "tab": "equity",
  "category": "Broad Market",
  "source": "kite",
  "kite_symbol": "NIFTY SMLCAP 250",
  "kite_instrument_token": 123456,
  "nav_scheme_code": null,
  "etfs": ["HDFC Nifty Smallcap 250 ETF", "..."],
  "index_funds": ["Nippon India Nifty Smallcap 250 Index Fund", "..."]
}
```

- `category` — Equity: Broad Market, Sector, Thematic, Strategy / Factor (as in the Excel
  workbook). Debt: Target Maturity, G-Sec Benchmark, Bharat Bond, Liquid / Overnight, Hybrid.
- Debt indices not on Kite use `"source": "amfi"` and `nav_scheme_code` of the proxy fund
  (ranked fund with the longest NAV history; fixed-NAV liquid ETFs excluded — same rule as
  `build_presentation._proxy_fund`).
- Kite symbols are matched by normalised name first, then an explicit alias table for Kite's
  abbreviations (Appendix A). `build_universe.py` fails loudly if any equity index has no
  Kite symbol, rather than silently dropping it.
- Instrument tokens are looked up from Kite's public instrument list
  (`https://api.kite.trade/instruments`) at build time.

### 4.2 Database schema

```sql
CREATE TABLE daily_bar (
  index_id   TEXT NOT NULL,      -- universe.json id
  trade_date TEXT NOT NULL,      -- YYYY-MM-DD
  open       REAL,               -- NULL for AMFI NAV rows
  close      REAL NOT NULL,      -- index close, or NAV for AMFI rows
  source     TEXT NOT NULL,      -- 'kite' | 'amfi'
  PRIMARY KEY (index_id, trade_date)
);
```

The database file (`screener.db`) sits next to the app. Writes happen in transactions;
re-running a fill-in is idempotent (upsert).

## 5. Data flow

### 5.1 App start (no token)
Load `universe.json` and the database. Compute returns from stored closes. Status 🟡.
Refresh AMFI NAVs in the background (no token needed).

### 5.2 Connect
1. **Validate token** (`kite.profile()`); on failure → 🔴 with message, stay on stored data.
2. **Fill in history** for each Kite index: fetch daily candles from the day after the last
   stored date (or 5 years + 7 days back on first run) up to yesterday. Throttled to
   Kite's historical-API limit (~3 requests/second); progress bar "Loading history n/95";
   resumable because each index's last stored date is in the database.
3. **Go live**: subscribe all Kite instrument tokens (89 equity + 6 debt) in KiteTicker
   `quote` mode (gives last price and today's OHLC). Each tick → recompute that row →
   update the table. Status 🟢.

### 5.3 End of day
After 15:30 IST, the day's close (from the last tick's OHLC) is upserted into the database.
If the app was not running at the close, step 2 of the next Connect backfills it from
historical data, so the database never has gaps.

### 5.4 Debt NAVs
AMFI NAVs refresh at app start and on **Refresh history**; AMFI publishes once per evening,
so these rows are as of the previous business day.

## 6. Returns engine

### 6.1 Definitions
All dates and times are IST (Asia/Kolkata), regardless of the computer's time zone.
- *Previous close* — last stored daily close strictly before today.
- *Latest price* — live last price in market hours; today's close after the close;
  last stored close otherwise.

| Column | Formula |
|---|---|
| Gap % | today's open / previous close − 1 (before 09:15 shows the last session's gap, greyed) |
| Day % | latest price / previous close − 1 |
| 7D, 15D | latest price / close 7 or 15 **calendar days** ago − 1 |
| 1M, 3M, 6M, 1Y | latest price / close on the same date 1/3/6/12 **calendar months** ago − 1 |
| 2Y, 3Y, 5Y | (latest price / close N years ago)^(1/N) − 1 (CAGR) |

### 6.2 Rules
- If the target past date is not a trading day, use the last trading day on or before it.
  If no close exists within 7 days before the target, the cell is "—".
- If the series starts after the target date, the cell is "—" ("Index younger than …").
- AMFI rows: identical formulas with NAV; *latest* = most recent NAV; Gap % = "—".

### 6.3 Known differences from NSE's Index Dashboard
- Equity 1Y+ returns will be ~1–1.5 %/yr below NSE's TRI-based figures for dividend-heavy
  indices (Kite = price index). Short periods (≤3M) are nearly identical.
- AMFI-proxy debt rows run ~0.05–0.2 %/yr below their index (the fund's expense ratio).

## 7. Error handling

| Situation | Behaviour |
|---|---|
| Token invalid / expired | 🔴 "Token expired — paste today's token"; tables keep stored data |
| Network drop while live | Banner "Reconnecting…"; KiteTicker auto-reconnect; values freeze until ticks resume |
| Historical rate limit / transient error | Retry with backoff; continue with remaining indices; failed ones listed in the log |
| Index missing on Kite or short history | Cells "—" with explanatory tooltip |
| AMFI unreachable | Keep last NAVs; date tag shows staleness |
| Unexpected exception in a worker | Logged with traceback to `screener.log`; status bar message; UI stays responsive |

## 8. Secrets and token

- **API key** lives in `screener/secrets_local.py` (git-ignored), bundled into the build.
  A committed `secrets_local.example.py` shows the format.
- **API secret is not used.** The user pastes an already-generated access token.
- The access token is held **in memory only** — never written to disk or logs.

## 9. Testing

- **Returns engine** (unit, no I/O): synthetic series covering holidays, young indices,
  CAGR maths, calendar-month anchoring (e.g. 31 Mar → 29 Feb/28 Feb), Gap % before/after open.
- **Database**: temp SQLite file; upsert idempotency, last-date lookup.
- **Kite / AMFI clients**: fake responses (no network); throttling and resume logic.
- **build_universe.py**: every equity index resolves to a Kite symbol; alias table applied.
- **UI smoke test** (offscreen Qt): window opens with fake data; sorting and filtering work.
- **Live probe script** `screener/probe_kite.py` (run by the user with their token): confirms
  API access and historical-data entitlement, reports earliest available date per index,
  and compares 1M/3M returns with the latest NSE Index Dashboard.

## 10. Packaging

- PyInstaller one-file build, spec file in `screener/`.
- Windows `.exe` must be built on Windows (PyInstaller does not cross-compile); a
  `BUILD.md` gives the steps. macOS build runs on the developer's Mac.

## Appendix A — Kite symbol aliases (names that don't match after normalisation)

| Our index | Kite symbol |
|---|---|
| Nifty Smallcap 250 | NIFTY SMLCAP 250 |
| Nifty Smallcap 100 | NIFTY SMLCAP 100 |
| Nifty Smallcap 50 | NIFTY SMLCAP 50 |
| Nifty LargeMidcap 250 | NIFTY LARGEMID250 |
| Nifty Total Market | NIFTY TOTAL MKT |
| Nifty MidSmallcap 400 | NIFTY MIDSML 400 |
| Nifty MidSmallcap400 50:50 | NIFTY MIDSMALL 50 50 |
| Nifty Private Bank | NIFTY PVT BANK |
| Nifty Oil & Gas | NIFTY OIL AND GAS |
| Nifty MidSmall Healthcare | NIFTY MIDSML HLTH |
| Nifty Financial Services Ex-Bank | NIFTY FINSEREXBNK |
| Nifty500 Healthcare | NIFTY500 HEALTH |
| Nifty Infrastructure | NIFTY INFRA |
| Nifty India Manufacturing | NIFTY INDIA MFG |
| Nifty India Consumption | NIFTY CONSUMPTION |
| Nifty India Digital | NIFTY IND DIGITAL |
| Nifty India Railways PSU | NIFTY RAILWAYS PSU |
| Nifty India Internet | NIFTY INTERNET |
| Nifty India Infrastructure & Logistics | NIFTY INFRALOG |
| Nifty200 Momentum 30 | NIFTY200MOMENTM30 |
| Nifty100 Low Volatility 30 | NIFTY100 LOWVOL30 |
| Nifty50 Equal Weight | NIFTY50 EQL WGT |
| Nifty Midcap150 Momentum 50 | NIFTYM150MOMNTM50 |
| Nifty Alpha Low-Volatility 30 | NIFTY ALPHALOWVOL |
| Nifty500 Multicap 50:25:25 | NIFTY500 MULTICAP |
| Nifty200 Quality 30 | NIFTY200 QUALTY30 |
| Nifty100 Equal Weight | NIFTY100 EQL WGT |
| Nifty Midcap150 Quality 50 | NIFTY M150 QLTY50 |
| Nifty500 Flexicap Quality 30 | NIFTY500 FLEXICAP |
| Nifty500 Multicap India Manufacturing 50:30:20 | NIFTY MULTI MFG |
| Nifty100 Quality 30 | NIFTY100 QUALTY30 |
| Nifty100 ESG Sector Leaders | NIFTY100ESGSECLDR |
| Nifty500 Quality 50 | NIFTY500 QLTY50 |
| Nifty Dividend Opportunities 50 | NIFTY DIV OPPS 50 |
| Nifty500 Multicap Infrastructure 50:30:20 | NIFTY MULTI INFRA |
| Nifty Total Market Momentum Quality 50 | NIFTY TMMQ 50 |
| Nifty500 Low Volatility 50 | NIFTY500 LOWVOL50 |
| Nifty Growth Sectors 15 | NIFTY GROWSECT 15 |
| Nifty 10 Yr Benchmark G-Sec (debt) | NIFTY GS 10YR |
| Nifty 8-13 Yr G-Sec (debt) | NIFTY GS 8 13YR |
| Nifty Bharat Bond – April 2030/31/32/33 (debt) | BHARATBOND-APR30 / -APR31 / -APR32 / -APR33 |
