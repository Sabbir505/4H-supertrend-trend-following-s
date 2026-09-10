"""
TradeEdge API Server
Serves Supertrend signal data to the frontend
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging

import requests

app = FastAPI(title="TradeEdge API", version="3.0.0")

logger = logging.getLogger(__name__)

# Enable CORS for the dashboard. Extra origins (your deployed frontends) go
# in the CORS_ORIGINS env var, comma-separated. The regex covers localhost
# and generic netlify/railway preview domains.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",")
                 if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or [
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_origin_regex=(
        r"https?://localhost:\d+"
        r"|https://[a-z0-9-]+\.netlify\.app"
        r"|https://[a-z0-9-]+\.railway\.app"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Configuration ──────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
SIGNALS_FILE = BASE_DIR / "signals.json"
DATA_DIR = BASE_DIR / "data" / "signals"
LAST_RUN_FILE = BASE_DIR / "data" / "scanner_last_run.json"
TRADES_FILE = BASE_DIR / "data" / "trade_history.json"
POSITIONS_FILE = BASE_DIR / "data" / "positions.json"


def _parse_utc(iso_str: str):
    """Parse an ISO datetime string to a timezone-aware UTC datetime."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def load_signals_from_data_dir() -> list:
    """Load all signals from the data/signals/ directory structure"""
    signals = []
    if not DATA_DIR.exists():
        return signals

    for year_dir in sorted(DATA_DIR.iterdir(), reverse=True):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir(), reverse=True):
            if not month_dir.is_dir():
                continue
            for json_file in sorted(month_dir.glob("*.json")):
                data = _cached_json(json_file, [])
                if isinstance(data, list):
                    signals.extend(data)

    return signals


# ─── Data Models ────────────────────────────────────────────────────────────

class Signal(BaseModel):
    id: str
    symbol: str
    direction: str  # BUY | SELL
    price: float    # entry
    atr: float
    atr_pct: float
    interval: str   # 4h | 30m
    detected_at: str
    source: str     # volume | marketcap | both
    alerted: bool = False

    # Legacy RR-based fields (pre round-4 rows only)
    sl: Optional[float] = None
    tp: Optional[float] = None
    rr: Optional[float] = None
    rsi: Optional[float] = None

    # 4H Supertrend trend-ride fields
    initial_stop: Optional[float] = None
    risk_pct: Optional[float] = None
    candle_time: Optional[str] = None  # close time of the flip candle (dedup key)
    strategy: Optional[str] = None
    breadth: Optional[float] = None
    risk_level: Optional[str] = None
    ema200: Optional[float] = None
    supertrend_value: Optional[float] = None
    # Round-5b quality tier (A best … D worst) from the 3-year study
    quality: Optional[str] = None
    quality_reason: Optional[str] = None


class DashboardStats(BaseModel):
    total_signals: int
    signals_24h: int
    buy_count: int
    sell_count: int
    by_interval: Dict[str, int]


class ScannerStatus(BaseModel):
    scan_4h: Optional[str] = None


class VirtualTrade(BaseModel):
    symbol: str
    direction: str  # BUY | SELL (as recorded by PositionTracker)
    entry: float
    exit: float
    exit_reason: str  # stop | flip | time
    gross_r: float
    net_r: float
    bars_held: int
    entry_time: str
    exit_time: str
    risk_level: Optional[str] = None
    strategy: Optional[str] = None


# ─── Helpers ────────────────────────────────────────────────────────────────

# mtime-keyed cache: the dashboard polls every 30s but these files only
# change when the scanner writes them, so re-read only on mtime change.
_json_cache: dict = {}


def _cached_json(path: Path, default):
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return default
    cached = _json_cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read {path.name}: {e}")
        return default
    _json_cache[str(path)] = (mtime, data)
    return data


def load_signals() -> list:
    """Load signals from data/signals/ directory (priority), fallback to signals.json"""
    data_signals = load_signals_from_data_dir()
    if data_signals:
        return data_signals

    if SIGNALS_FILE.exists():
        data = _cached_json(SIGNALS_FILE, [])
        if isinstance(data, list):
            return data

    return []


# ─── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "TradeEdge API", "version": "3.0.0"}


@app.get("/api/signals", response_model=List[Signal])
async def get_signals(
    interval: Optional[str] = Query(None, description="Filter by interval: 4h, 30m"),
    direction: Optional[str] = Query(None, description="Filter by direction: BUY, SELL"),
    limit: int = Query(1000, ge=1, le=10000, description="Max signals returned"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """Get signals (newest first), optionally filtered and paginated."""
    signals = load_signals()

    if interval:
        signals = [x for x in signals if x.get('interval') == interval]
    if direction:
        signals = [x for x in signals if x.get('direction') == direction]

    signals.sort(key=lambda x: x.get('detected_at', ''), reverse=True)
    return signals[offset:offset + limit]


@app.get("/api/signals/recent", response_model=List[Signal])
async def get_recent_signals():
    """Get signals from the last 24 hours."""
    signals = load_signals()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    recent = []
    for sig in signals:
        dt = _parse_utc(sig.get('detected_at', ''))
        if dt is not None and dt >= cutoff:
            recent.append(sig)

    recent.sort(key=lambda x: x.get('detected_at', ''), reverse=True)
    return recent


@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get dashboard statistics for signals."""
    signals = load_signals()

    total_signals = len(signals)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = []
    for sig in signals:
        dt = _parse_utc(sig.get('detected_at', ''))
        if dt is not None and dt >= cutoff:
            recent.append(sig)
    signals_24h = len(recent)

    buy = len([x for x in signals if x.get('direction') == 'BUY'])
    sell = len([x for x in signals if x.get('direction') == 'SELL'])

    by_interval = {}
    for sig in signals:
        interval = sig.get('interval', 'unknown')
        by_interval[interval] = by_interval.get(interval, 0) + 1

    return DashboardStats(
        total_signals=total_signals,
        signals_24h=signals_24h,
        buy_count=buy,
        sell_count=sell,
        by_interval=by_interval,
    )


@app.get("/api/scanner/status", response_model=ScannerStatus)
async def get_scanner_status():
    """Return last-run timestamps for the scanner's main scan job."""
    if not LAST_RUN_FILE.exists():
        return ScannerStatus(scan_4h=None)

    try:
        with open(LAST_RUN_FILE, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read scanner last-run file: {e}")
        return ScannerStatus(scan_4h=None)

    scan_4h = (
        data.get("scan_4h_4h")
        or data.get("scan_4h")
        or data.get("scan_4h_1h")
        or data.get("scan_4h_2h")
        or data.get("scan_4h_6h")
        or data.get("scan_4h_8h")
        or data.get("scan_4h_12h")
    )
    return ScannerStatus(scan_4h=scan_4h)


def _load_json_file(path: Path, default):
    return _cached_json(path, default)


@app.get("/api/health")
async def get_health():
    """Liveness + scan freshness. Point an external uptime monitor at this
    endpoint: it reports stale=true when the 4H heartbeat is older than 8h
    (2× scan interval), which catches a dead or hung scanner even though
    this API process is still serving."""
    last_scan = None
    if LAST_RUN_FILE.exists():
        try:
            with open(LAST_RUN_FILE, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            last_scan = (
                data.get("scan_4h_4h") or data.get("scan_4h")
                or data.get("scan_4h_1h") or data.get("scan_4h_2h")
                or data.get("scan_4h_6h") or data.get("scan_4h_8h")
                or data.get("scan_4h_12h")
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read scanner last-run file: {e}")

    stale = True
    if last_scan:
        try:
            dt = datetime.fromisoformat(last_scan)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            stale = (datetime.now(timezone.utc) - dt).total_seconds() > 8 * 3600
        except ValueError:
            pass

    return {
        "status": "ok",
        "last_scan": last_scan,
        "scan_stale": stale,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/trades", response_model=List[VirtualTrade])
async def get_virtual_trades():
    """Closed virtual positions (4H trend-ride trade management)."""
    trades = _load_json_file(TRADES_FILE, [])
    trades.sort(key=lambda t: t.get('exit_time', ''), reverse=True)
    return trades


@app.get("/api/positions")
async def get_open_positions():
    """Currently open virtual positions."""
    positions = _load_json_file(POSITIONS_FILE, {})
    return list(positions.values())


# ─── Price klines (for frontend sparklines) ─────────────────────────────────

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
KLINE_INTERVALS = {"15m", "30m", "1h", "2h", "4h", "1d"}
KLINE_TTL_OK = 60     # success: serve from cache for 60s
KLINE_TTL_FAIL = 30   # failure: don't retry the same symbol for 30s

_klines_cache: dict = {}  # (symbol, interval, limit) -> (expires_at, data|None)
KLINES_CACHE_MAX = 2000  # the endpoint accepts arbitrary symbol combos, so an
# unbounded cache is a memory-leak vector on a public deployment
_klines_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="klines")


def _cache_put(key, value):
    """Insert into _klines_cache, evicting expired entries first, then the
    soonest-to-expire, when over the size cap."""
    if len(_klines_cache) >= KLINES_CACHE_MAX:
        now = time.time()
        for k in [k for k, v in _klines_cache.items() if v[0] <= now]:
            del _klines_cache[k]
    while len(_klines_cache) >= KLINES_CACHE_MAX:
        del _klines_cache[min(_klines_cache, key=lambda k: _klines_cache[k][0])]
    _klines_cache[key] = value


def _fetch_symbol_klines(symbol: str, interval: str, limit: int) -> Optional[dict]:
    """Fetch close prices for one symbol from Binance. Returns None on failure."""
    key = (symbol, interval, limit)
    now = time.time()
    cached = _klines_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    data = None
    try:
        resp = requests.get(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=8,
        )
        if resp.status_code == 200:
            rows = resp.json()
            closes = [float(r[4]) for r in rows]
            if closes:
                data = {"closes": closes, "current": closes[-1]}
    except (requests.RequestException, ValueError, KeyError, IndexError):
        data = None
    _cache_put(key, (now + (KLINE_TTL_OK if data else KLINE_TTL_FAIL), data))
    return data


@app.get("/api/klines")
def get_klines(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. AVAXUSDT,NMRUSDT"),
    interval: str = Query("1h", description="Kline interval"),
    limit: int = Query(168, ge=10, le=1000, description="Number of candles"),
):
    """Batch close-price history for sparklines. Symbols that fail (delisted,
    rate-limited) are simply absent from the response; the frontend treats
    sparklines as best-effort."""
    interval = interval if interval in KLINE_INTERVALS else "1h"
    wanted = []
    for s in symbols.split(","):
        s = s.strip().upper()
        if s and s not in wanted:
            wanted.append(s)
    wanted = wanted[:100]

    futures = {
        s: _klines_pool.submit(_fetch_symbol_klines, s, interval, limit)
        for s in wanted
    }
    return {s: f.result() for s, f in futures.items() if f.result() is not None}


# ─── Startup ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
