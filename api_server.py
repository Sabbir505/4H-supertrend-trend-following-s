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
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging

app = FastAPI(title="TradeEdge API", version="3.0.0")

logger = logging.getLogger(__name__)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://*.netlify.app",
        "https://*.railway.app",
        "https://stellar-sorbet-b0f512.netlify.app",
        "https://algo-testing-phase.netlify.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Configuration ──────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
SIGNALS_FILE = BASE_DIR / "signals.json"
DATA_DIR = BASE_DIR / "data" / "signals"


def load_signals_from_data_dir() -> list:
    """Load all signals from the data/signals/ directory structure"""
    signals = []
    if not DATA_DIR.exists():
        return signals

    for year_dir in DATA_DIR.iterdir():
        if not year_dir.is_dir():
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue
            for json_file in month_dir.glob("*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            signals.extend(data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse {json_file}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to read {json_file}: {e}")

    return signals


# ─── Data Models ────────────────────────────────────────────────────────────

class Signal(BaseModel):
    id: str
    symbol: str
    direction: str  # BUY | SELL
    price: float    # entry
    ema200: float
    rsi: float
    atr: float
    atr_pct: float
    supertrend_value: float
    sl: float
    tp: float
    rr: float
    interval: str   # 4h
    detected_at: str
    source: str     # volume | volatility | both
    alerted: bool = False


class DashboardStats(BaseModel):
    total_signals: int
    signals_24h: int
    buy_count: int
    sell_count: int
    by_interval: Dict[str, int]


# ─── Helpers ────────────────────────────────────────────────────────────────

def load_signals() -> list:
    """Load signals from data/signals/ directory (priority), fallback to signals.json"""
    data_signals = load_signals_from_data_dir()
    if data_signals:
        return data_signals

    if SIGNALS_FILE.exists():
        try:
            with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse signals.json: {e}")
        except Exception as e:
            logger.warning(f"Failed to read signals.json: {e}")

    return []


# ─── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "TradeEdge API", "version": "3.0.0"}


@app.get("/api/signals", response_model=List[Signal])
async def get_signals(
    interval: Optional[str] = Query(None, description="Filter by interval: 4h"),
    direction: Optional[str] = Query(None, description="Filter by direction: BUY, SELL"),
):
    """Get all signals, optionally filtered."""
    signals = load_signals()

    if interval:
        signals = [x for x in signals if x.get('interval') == interval]
    if direction:
        signals = [x for x in signals if x.get('direction') == direction]

    signals.sort(key=lambda x: x.get('detected_at', ''), reverse=True)
    return signals


@app.get("/api/signals/recent", response_model=List[Signal])
async def get_recent_signals():
    """Get signals from the last 24 hours."""
    signals = load_signals()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    recent = []
    for sig in signals:
        try:
            dt = datetime.fromisoformat(sig.get('detected_at', ''))
            if dt >= cutoff:
                recent.append(sig)
        except (ValueError, TypeError):
            continue

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
        try:
            dt = datetime.fromisoformat(sig.get('detected_at', ''))
            if dt >= cutoff:
                recent.append(sig)
        except (ValueError, TypeError):
            continue
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


# ─── Startup ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
