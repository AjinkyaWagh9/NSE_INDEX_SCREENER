# Building NSE Index Screener

PyInstaller builds for the OS it runs on: build the Windows `.exe` on a Windows PC and the
macOS app on a Mac.

## One-time setup (either OS)

1. Install Python 3.12 or 3.13 and Git, then clone this repository.
2. From the repo root, create a **fresh virtual environment** (keeps unrelated packages out of
   the build; the spec also excludes heavy ones) and install the requirements:
   ```
   python -m venv .venv
   .venv\Scripts\activate            # macOS: source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `screener/secrets_local.example.py` to `screener/secrets_local.py` and put your Kite
   Connect API key in it. **Anyone who has the built executable can extract this key.**
   The API secret is not needed.

## Build

```
python -m pytest tests/screener -q
pyinstaller --noconfirm screener/NSEScreener.spec
dist/NSEScreener --selftest          # Windows: dist\NSEScreener.exe --selftest
```

The self-test prints (and writes to `selftest.txt` next to the executable)
`selftest ok: 130 indices (89 equity, 41 debt), 130 rows, API key set`.
The executable is about 45 MB. It takes ~10 seconds to open, because a one-file build unpacks
itself first. Re-build after changing the API key in `secrets_local.py`; the key is baked in.

## Running without building

```
python -m screener.desktop.app
```

## Using the app

1. Put `NSEScreener(.exe)` in its own folder. It creates `screener.db`, `screener.log`
   and `nav_cache/` next to itself.
2. Open it, paste today's Kite access token, click **Connect**.
   The first connection downloads ~5 years of history (about a minute). Later ones only fetch
   missing days.
3. The token is kept in memory only. Tokens expire daily (around 6 am), so restart the app
   and paste the new token each morning.

## Checking Kite access (once)

```
python -m screener.tools.probe_kite
```
Paste the token when asked. It reports how far back each index's history goes and compares
1M/3M returns with NSE's latest Index Dashboard.

## Updating the index list

After re-running the ranking pipeline (`run_ranking.py`, `compute_returns.py`):
```
python -m screener.tools.build_universe
```
then rebuild. Indices added this way start with empty history and fill in on the next Connect.

## Moving to the web app

Copy `screener/core/` into the backend; it needs only `requests` and `kiteconnect`.
Nothing in `core/` imports Qt (`tests/screener/test_core_is_portable.py` enforces it).
Set `KITE_API_KEY` and `SCREENER_DATA_DIR` as environment variables, swap `BarStore` for a
class with the same four `BarRepository` methods if the web app has its own database, serve
`ScreenerService.rows()` as JSON via `RowData.to_dict()`, and push `apply_quotes` updates to
browsers over a WebSocket. `screener/desktop/` is not needed there.
