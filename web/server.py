"""FastAPI Web Server for NSE Index Screener.

Serves:
    - GET /: Web app interface
    - GET /api/rows: Full initial table data
    - GET /api/status: Current live connection status
    - GET /api/auth/login-url: Zerodha login URL for admin
    - POST /api/auth/connect: Connect using redirect URL or token
    - WS /ws: Real-time tick stream to all connected browsers
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from screener.core.amfi_client import fetch_nav_bars
from screener.core.config import (app_dir, clear_cached_token, load_api_key, load_api_secret,
                                  load_cached_token, now_ist, save_cached_token, today_ist)
from screener.core.db import BarStore
from screener.core.kite_client import (KiteClient, LiveFeed, TokenError, exchange_request_token,
                                        extract_request_token, login_url)
from screener.core.service import ScreenerService
from screener.core.universe import load_universe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

# State
universe = load_universe()
store = BarStore(app_dir() / "screener.db")
service = ScreenerService(universe, store)

api_key = load_api_key()
api_secret = load_api_secret()

live_feed: Optional[LiveFeed] = None
active_client: Optional[KiteClient] = None
status_state = "offline"
status_message = "Not connected"
last_updated = "—"

active_websockets: set[WebSocket] = set()
main_loop: Optional[asyncio.AbstractEventLoop] = None


class ConnectRequest(BaseModel):
    token: str


class ConnectionManager:
    @staticmethod
    async def connect(ws: WebSocket):
        await ws.accept()
        active_websockets.add(ws)

    @staticmethod
    def disconnect(ws: WebSocket):
        active_websockets.discard(ws)

    @staticmethod
    async def broadcast(message: dict):
        if not active_websockets:
            return
        dead = set()
        for ws in active_websockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        active_websockets.difference_update(dead)


def _push_broadcast(message: dict):
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(ConnectionManager.broadcast(message), main_loop)


def _on_quotes_received(quotes: list):
    global last_updated
    changed = service.apply_quotes(quotes)
    if not changed:
        return
    today = today_ist()
    last_updated = now_ist().strftime("%H:%M:%S")
    updated_rows = [service.row(ix, today).to_dict() for ix in changed]
    _push_broadcast({
        "type": "quotes",
        "rows": updated_rows,
        "updated_at": last_updated
    })


def _on_feed_status(state: str, msg: str):
    global status_state, status_message
    status_state = state
    status_message = msg or ("Live" if state == "live" else state)
    if state == "error" and "403" in msg:
        clear_cached_token()
    _push_broadcast({
        "type": "status",
        "state": status_state,
        "message": status_message
    })


def _start_feed(client: KiteClient, token: str):
    global live_feed, active_client
    if live_feed is not None:
        try:
            live_feed.stop()
        except Exception:
            pass
    active_client = client
    save_cached_token(today_ist(), token)
    live_feed = LiveFeed(api_key, token, service.kite_tokens(),
                         on_quotes=_on_quotes_received, on_status=_on_feed_status)
    live_feed.start()


def _do_connect(raw_token: str):
    clean = raw_token.strip()
    if extract_request_token(clean):
        _on_feed_status("busy", "Exchanging request token with Zerodha…")
        token = exchange_request_token(api_key, api_secret, clean)
        client = KiteClient(api_key, token)
        client.validate()
    else:
        try:
            client = KiteClient(api_key, clean)
            client.validate()
            token = clean
        except TokenError:
            if api_secret and len(clean) == 32 and clean.isalnum():
                token = exchange_request_token(api_key, api_secret, f"request_token={clean}")
                client = KiteClient(api_key, token)
                client.validate()
            else:
                raise

    # Start live feed immediately so the user connects in ~1 second
    _start_feed(client, token)
    _on_feed_status("live", "Live")

    # Backfill missing historical candles in the background without blocking the connection
    import threading

    def _backfill_worker():
        global last_updated
        try:
            log.info("Starting background history backfill…")
            service.backfill_kite(client, today_ist())
            log.info("Historical backfill completed in background")
            today = today_ist()
            last_updated = now_ist().strftime("%H:%M:%S")
            _push_broadcast({
                "type": "quotes",
                "rows": [r.to_dict() for r in service.rows(today)],
                "updated_at": last_updated,
            })
        except Exception as e:
            log.warning("Background backfill failed: %s", e)

    threading.Thread(target=_backfill_worker, daemon=True).start()


def _background_init():
    # AMFI update
    try:
        service.refresh_amfi(lambda code: fetch_nav_bars(code, app_dir() / "nav_cache"))
    except Exception as e:
        log.warning("AMFI refresh error: %s", e)

    # Check cached token
    cached = load_cached_token(today_ist())
    if cached:
        try:
            log.info("Found cached session for today, connecting to Kite…")
            _do_connect(cached)
        except Exception as e:
            log.warning("Could not restore cached session: %s", e)
            clear_cached_token()
            _on_feed_status("offline", "Session expired - please log in")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()
    # Run background startup in a separate worker thread so API responds immediately
    asyncio.create_task(asyncio.to_thread(_background_init))
    yield
    if live_feed is not None:
        try:
            live_feed.stop()
        except Exception:
            pass
    store.close()


app = FastAPI(title="NSE Index Screener API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_path = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/")
async def root():
    return FileResponse(static_path / "index.html")


@app.get("/api/rows")
async def get_rows():
    today = today_ist()
    return [r.to_dict() for r in service.rows(today)]


@app.get("/api/status")
async def get_status():
    return {
        "state": status_state,
        "message": status_message,
        "updated_at": last_updated,
        "has_api_key": bool(api_key),
        "has_api_secret": bool(api_secret),
    }


@app.get("/api/auth/login-url")
async def get_login_url():
    if not api_key:
        raise HTTPException(status_code=400, detail="No Kite API key configured")
    return {"url": login_url(api_key)}


@app.post("/api/auth/connect")
async def connect(req: ConnectRequest):
    if not req.token or not req.token.strip():
        raise HTTPException(status_code=400, detail="Token or redirect URL required")
    try:
        await asyncio.to_thread(_do_connect, req.token)
        return {"status": "ok", "message": "Connected successfully"}
    except TokenError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("Connect failed")
        raise HTTPException(status_code=500, detail=f"Connection failed: {e}")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ConnectionManager.connect(ws)
    # Send immediate initial status
    await ws.send_json({
        "type": "status",
        "state": status_state,
        "message": status_message,
        "updated_at": last_updated
    })
    try:
        while True:
            # Keep connection open and listen for pings
            await ws.receive_text()
    except WebSocketDisconnect:
        ConnectionManager.disconnect(ws)
    except Exception:
        ConnectionManager.disconnect(ws)
