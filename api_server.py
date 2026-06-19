"""
TradeEdge API Server
Serves trading signals and backtest data to the Next.js frontend
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import asyncio

app = FastAPI(title="TradeEdge API", version="1.0.0")

# Import market intel module
try:
    from market_intel import (
        market_intel_fetcher,
        analyze_event_impact_for_position,
        analyze_macro_event_impact,
    )
    MARKET_INTEL_AVAILABLE = True
except ImportError:
    MARKET_INTEL_AVAILABLE = False
    logging.warning("Market intel module not available")

logger = logging.getLogger(__name__)

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Configuration ──────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent  # Project root
SIGNALS_FILE = BASE_DIR / "signals.json"
BACKTEST_FILE = BASE_DIR / "backtest_results.json"
DATA_DIR = BASE_DIR / "data" / "signals"


def load_signals_from_data_dir() -> list:
    """Load all signals from the data/signals/ directory structure"""
    signals = []
    if not DATA_DIR.exists():
        return signals

    # Walk through year/month directories and find all JSON files
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


# ─── Data Models ──────────────────────────────────────────────────────────────

class Signal(BaseModel):
    id: str
    symbol: str
    direction: str
    strength: Optional[str] = None
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: Optional[float] = None
    tp4: Optional[float] = None
    rr1: float
    rr2: Optional[float] = None
    rr3: Optional[float] = None
    rr_max: float
    quality_score: float
    fired_at: str
    status: str
    outcome: Optional[str] = None
    closed_at: Optional[str] = None
    max_rr_hit: Optional[float] = None
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    tp4_hit: bool = False
    sl_hit: bool = False
    sl_at_breakeven: Optional[bool] = False
    minutes_to_close: Optional[int] = None


class BacktestTrade(BaseModel):
    symbol: str
    direction: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: Optional[float] = None
    tp4: Optional[float] = None
    sl_distance: float
    entry_time: str
    sl_original: float
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: str
    rr_achieved: Optional[float] = None
    bars_held: Optional[int] = None
    quality_score: float
    adx_at_entry: float
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    sl_at_breakeven: bool = False


class BacktestResult(BaseModel):
    symbol: str
    timeframe: str
    period_months: int
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    win_rate: float = 0.0
    avg_rr: float = 0.0
    max_rr: float = 0.0
    total_rr: float = 0.0
    max_drawdown: float = 0.0
    avg_bars_held: float = 0.0
    long_trades: int = 0
    short_trades: int = 0
    long_win_rate: float = 0.0
    short_win_rate: float = 0.0
    tp1_rate: float = 0.0
    tp2_rate: float = 0.0
    tp3_rate: float = 0.0
    tp4_rate: float = 0.0
    breakeven_rate: float = 0.0
    any_tp_rate: Optional[float] = None
    trades: List[BacktestTrade] = []


class DashboardStats(BaseModel):
    total_signals: int
    open_signals: int
    closed_signals: int
    win_rate: float
    avg_quality_score: float
    total_trades_backtest: int
    total_backtest_wins: int
    total_backtest_losses: int
    overall_backtest_wr: float
    total_rr: float


class LiveTrade(BaseModel):
    id: str
    symbol: str
    direction: str
    strength: Optional[str] = None
    entry: float
    current_price: Optional[float] = None
    sl: float
    tp1: float
    tp2: float
    rr_ratio: str
    quality_score: float
    status: str
    time_ago: str
    pnl: Optional[float] = None
    tp1_progress: Optional[float] = None


# ─── Market Intel Data Models ─────────────────────────────────────────────────

class EconomicEvent(BaseModel):
    id: str
    title: str
    currency: str
    impact: str  # LOW, MEDIUM, HIGH
    event_type: str  # CPI, PPI, FOMC, GDP, etc.
    timestamp: str
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None
    sentiment: Optional[str] = None


class CryptoNews(BaseModel):
    id: str
    title: str
    source: str
    published_at: str
    sentiment: Optional[str] = None  # positive, negative, neutral
    currencies: List[str] = []
    url: Optional[str] = None
    impact_score: Optional[int] = None


class TokenEvent(BaseModel):
    id: str
    token: str
    event_type: str
    timestamp: str
    description: str
    impact: str  # LOW, MEDIUM, HIGH
    amount: Optional[float] = None
    url: Optional[str] = None


class ImpactCorrelation(BaseModel):
    event_id: str
    event_title: str
    affected_symbols: List[str]
    position_impact: str  # POSITIVE, NEGATIVE, NEUTRAL
    risk_adjustment: str  # INCREASE_SL, MONITOR, HOLD, CLOSE_POSITION
    reason: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_signals() -> list:
    """Load signals from signals.json (source of truth), fallback to data directory for historical"""
    # Primary source: signals.json (current active signals)
    if SIGNALS_FILE.exists():
        try:
            with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse signals.json: {e}")
        except Exception as e:
            logger.warning(f"Failed to read signals.json: {e}")

    # Fallback: data directory (for historical data if signals.json missing)
    return load_signals_from_data_dir()


def load_backtest_results() -> list:
    """Load backtest results from backtest_results.json"""
    if not BACKTEST_FILE.exists():
        return []
    try:
        with open(BACKTEST_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse backtest_results.json: {e}")
        return []
    except Exception as e:
        logger.warning(f"Failed to read backtest_results.json: {e}")
        return []


def format_time_ago(fired_at_str: str) -> str:
    """Format time since signal was fired"""
    try:
        fired = datetime.fromisoformat(fired_at_str.replace('Z', '+00:00'))
        delta = datetime.now(timezone.utc) - fired
        minutes = int(delta.total_seconds() / 60)
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"
    except Exception:
        return "unknown"


def calculate_pnl(signal: dict) -> Optional[float]:
    """Calculate approximate P&L for open signals"""
    if signal.get('status') != 'OPEN':
        return None
    # For open signals, we can't know current price without fetching it
    # Return None and let frontend handle it
    return None


# ─── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "TradeEdge API", "version": "1.0.0"}


@app.get("/api/signals", response_model=List[Signal])
async def get_signals(status: Optional[str] = Query(None, description="Filter by status: OPEN, TP1, TP2, TP3, TP4, SL, BREAKEVEN, EXPIRED")):
    """Get all signals, optionally filtered by status"""
    signals = load_signals()
    if status:
        signals = [s for s in signals if s.get('status') == status]
    return signals


@app.get("/api/signals/open", response_model=List[Signal])
async def get_open_signals():
    """Get all open signals (live trades) — includes OPEN, TP1, TP2, TP3 (not fully closed)"""
    signals = load_signals()
    open_statuses = ['OPEN', 'TP1', 'TP2', 'TP3']
    open_signals = [s for s in signals if s.get('status') in open_statuses]
    return open_signals


@app.get("/api/signals/closed", response_model=List[Signal])
async def get_closed_signals():
    """Get all fully closed signals (trade history) — only TP4, SL, BREAKEVEN, EXPIRED, WIN"""
    signals = load_signals()
    closed_statuses = ['TP4', 'SL', 'BREAKEVEN', 'EXPIRED', 'WIN']
    closed = [s for s in signals if s.get('status') in closed_statuses]
    return closed


@app.get("/api/signals/partial", response_model=List[Signal])
async def get_partial_signals():
    """Get partially closed signals — TP1, TP2, TP3 (position still partially open)"""
    signals = load_signals()
    partial_statuses = ['TP1', 'TP2', 'TP3']
    partial = [s for s in signals if s.get('status') in partial_statuses]
    return partial


@app.get("/api/signals/{signal_id}")
async def get_signal(signal_id: str):
    """Get a specific signal by ID"""
    signals = load_signals()
    for sig in signals:
        if sig.get('id') == signal_id:
            return sig
    raise HTTPException(status_code=404, detail="Signal not found")


@app.get("/api/backtest", response_model=List[BacktestResult])
async def get_backtest_results():
    """Get all backtest results"""
    return load_backtest_results()


@app.get("/api/backtest/{symbol}")
async def get_backtest_for_symbol(symbol: str):
    """Get backtest result for a specific symbol"""
    results = load_backtest_results()
    for result in results:
        if result.get('symbol') == symbol:
            return result
    raise HTTPException(status_code=404, detail="Backtest result not found")


@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get aggregated dashboard statistics"""
    signals = load_signals()
    backtest_results = load_backtest_results()

    # Signal stats
    # OPEN = trades that haven't hit any TP or SL (position fully active)
    # PARTIAL = trades that hit TP1/TP2/TP3 but still have position open
    # CLOSED = trades that are fully closed (TP4, SL, BREAKEVEN, EXPIRED, WIN)
    total_signals = len(signals)
    open_statuses = ['OPEN', 'TP1', 'TP2', 'TP3']
    closed_statuses_list = ['TP4', 'SL', 'BREAKEVEN', 'EXPIRED', 'WIN']

    open_signals = len([s for s in signals if s.get('status') in open_statuses])
    closed_signals = len([s for s in signals if s.get('status') in closed_statuses_list])

    # Win rate from all non-open signals (partial + fully closed)
    # Count TP1, TP2, TP3, TP4, WIN as wins, SL as losses, BREAKEVEN/EXPIRED as neutral
    non_open = [s for s in signals if s.get('status') not in ('OPEN',)]
    wins = len([s for s in non_open if s.get('status') in ('TP1', 'TP2', 'TP3', 'TP4', 'WIN')])
    losses = len([s for s in non_open if s.get('status') == 'SL'])
    win_rate = round(wins / (wins + losses) * 100, 2) if (wins + losses) > 0 else 0.0

    # Average quality score
    avg_qs = round(sum(s.get('quality_score', 0) for s in signals) / len(signals), 1) if signals else 0.0

    # Backtest stats
    total_bt_trades = sum(r.get('total_trades', 0) for r in backtest_results)
    total_bt_wins = sum(r.get('wins', 0) for r in backtest_results)
    total_bt_losses = sum(r.get('losses', 0) for r in backtest_results)
    overall_wr = round(total_bt_wins / total_bt_trades * 100, 1) if total_bt_trades else 0.0
    bt_total_rr = round(sum(r.get('total_rr', 0) for r in backtest_results), 2)

    # Calculate total RR from all signals (including partial)
    def calc_signal_rr(s):
        status = s.get('status', '')
        rr1 = s.get('rr1', 1.5)
        rr2 = s.get('rr2', 2.0)
        rr3 = s.get('rr3', 3.0)
        rr_max = s.get('rr_max', 4.0)
        if status == 'SL':
            return -1.0
        if status == 'EXPIRED':
            return 0.0
        if status == 'BREAKEVEN':
            # Calculate based on which TPs were actually hit before breakeven
            total = 0.0
            if s.get('tp1_hit', False):
                total += rr1 * 0.40
            if s.get('tp2_hit', False):
                total += rr2 * 0.30
            if s.get('tp3_hit', False):
                total += rr3 * 0.20
            if s.get('tp4_hit', False):
                total += rr_max * 0.10
            return round(total, 2)
        if status == 'TP1':
            return round(rr1 * 0.40, 2)
        if status == 'TP2':
            return round(rr1 * 0.40 + rr2 * 0.30, 2)
        if status == 'TP3':
            return round(rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20, 2)
        if status == 'TP4' or status == 'WIN':
            return round(rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20 + rr_max * 0.10, 2)
        return s.get('max_rr_hit', 0) or 0.0

    total_rr = round(sum(calc_signal_rr(s) for s in signals if s.get('status') != 'OPEN'), 2)

    return DashboardStats(
        total_signals=total_signals,
        open_signals=open_signals,
        closed_signals=closed_signals,
        win_rate=win_rate,
        avg_quality_score=avg_qs,
        total_trades_backtest=total_bt_trades,
        total_backtest_wins=total_bt_wins,
        total_backtest_losses=total_bt_losses,
        overall_backtest_wr=overall_wr,
        total_rr=total_rr
    )


@app.get("/api/live-trades", response_model=List[LiveTrade])
async def get_live_trades():
    """Get live trades formatted for the Live Trades page"""
    signals = load_signals()
    open_statuses = ['OPEN', 'TP1', 'TP2', 'TP3']
    open_signals = [s for s in signals if s.get('status') in open_statuses]

    trades = []
    for sig in open_signals:
        trade = LiveTrade(
            id=sig.get('id', ''),
            symbol=sig.get('symbol', ''),
            direction=sig.get('direction', ''),
            strength=sig.get('strength'),
            entry=sig.get('entry', 0),
            sl=sig.get('sl', 0),
            tp1=sig.get('tp1', 0),
            tp2=sig.get('tp2', 0),
            rr_ratio=f"1 : {sig.get('rr1', 0)}",
            quality_score=sig.get('quality_score', 0),
            status=sig.get('status', 'OPEN'),
            time_ago=format_time_ago(sig.get('fired_at', ''))
        )
        trades.append(trade)

    return trades


@app.get("/api/analytics/summary")
async def get_analytics_summary():
    """Get analytics summary data"""
    signals = load_signals()
    backtest_results = load_backtest_results()

    # Direction performance
    long_signals = [s for s in signals if s.get('direction') == 'LONG']
    short_signals = [s for s in signals if s.get('direction') == 'SHORT']

    # Strength performance
    strong_signals = [s for s in signals if s.get('strength') == 'STRONG']
    standard_signals = [s for s in signals if s.get('strength') == 'STANDARD']

    # Outcome distribution
    outcomes = {}
    for s in signals:
        outcome = s.get('outcome', 'UNKNOWN')
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

    # Monthly performance (from backtest)
    monthly = []
    for result in backtest_results:
        monthly.append({
            'symbol': result.get('symbol'),
            'win_rate': result.get('win_rate'),
            'total_trades': result.get('total_trades'),
            'total_rr': result.get('total_rr')
        })

    return {
        'direction_counts': {
            'LONG': len(long_signals),
            'SHORT': len(short_signals)
        },
        'strength_counts': {
            'STRONG': len(strong_signals),
            'STANDARD': len(standard_signals)
        },
        'outcome_distribution': outcomes,
        'symbol_performance': monthly,
        'total_signals': len(signals)
    }


# ─── Market Intel Endpoints ────────────────────────────────────────────────────

@app.get("/api/market/calendar", response_model=List[EconomicEvent])
async def get_economic_calendar():
    """Get economic calendar events for the next 14 days"""
    if not MARKET_INTEL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Market intel service unavailable")

    events = await market_intel_fetcher.fetch_economic_calendar()
    return events


@app.get("/api/market/news", response_model=List[CryptoNews])
async def get_crypto_news():
    """Get latest crypto news from CryptoPanic"""
    if not MARKET_INTEL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Market intel service unavailable")

    news = await market_intel_fetcher.fetch_crypto_news()
    return news


@app.get("/api/market/events", response_model=List[TokenEvent])
async def get_token_events():
    """Get upcoming token-specific events from CoinGecko"""
    if not MARKET_INTEL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Market intel service unavailable")

    events = await market_intel_fetcher.fetch_token_events()
    return events


@app.get("/api/market/impact", response_model=List[ImpactCorrelation])
async def get_impact_analysis():
    """
    Analyze impact of upcoming events on open positions.
    Correlates economic events, token events, and news with open trades.
    Groups affected symbols together for cleaner output.
    """
    if not MARKET_INTEL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Market intel service unavailable")

    signals = load_signals()
    open_statuses = ["OPEN", "TP1", "TP2", "TP3"]
    open_signals = [s for s in signals if s.get("status") in open_statuses]

    if not open_signals:
        return []

    # Fetch market intel data
    calendar, token_events, news = await asyncio.gather(
        market_intel_fetcher.fetch_economic_calendar(),
        market_intel_fetcher.fetch_token_events(),
        market_intel_fetcher.fetch_crypto_news(),
    )

    # Track events by ID to group affected symbols
    event_impacts: Dict[str, dict] = {}

    # Only consider events in next 48 hours for impact alerts
    now = datetime.now(timezone.utc)
    forty_eight_hours = now + timedelta(hours=48)

    for sig in open_signals:
        symbol = sig.get("symbol", "")
        direction = sig.get("direction", "LONG")
        base_symbol = symbol.replace("USDT", "").replace("USD", "").replace("USDC", "")

        # Check token events for symbol match
        for event in token_events:
            if event.get("token", "") == base_symbol:
                impact = analyze_event_impact_for_position(event, symbol, direction)
                if impact["position_impact"] != "NEUTRAL":
                    event_id = event["id"]
                    if event_id not in event_impacts:
                        event_impacts[event_id] = {
                            "event_id": event_id,
                            "event_title": event["description"],
                            "affected_symbols": [],
                            "position_impact": impact["position_impact"],
                            "risk_adjustment": impact["risk_adjustment"],
                            "reason": impact["reason"],
                        }
                    if symbol not in event_impacts[event_id]["affected_symbols"]:
                        event_impacts[event_id]["affected_symbols"].append(symbol)

        # Check high-impact macro events (affects all USD pairs) - only next 48 hours
        for event in calendar:
            if event["impact"] == "HIGH":
                # Parse event timestamp and check if within 48 hours
                try:
                    event_time = datetime.fromisoformat(event["timestamp"].replace('Z', '+00:00'))
                    if event_time.tzinfo is None:
                        event_time = event_time.replace(tzinfo=timezone.utc)
                    if event_time > forty_eight_hours:
                        continue
                except:
                    pass

                impact = analyze_macro_event_impact(event, direction)
                if impact["risk_adjustment"] != "HOLD":
                    event_id = event["id"]
                    if event_id not in event_impacts:
                        event_impacts[event_id] = {
                            "event_id": event_id,
                            "event_title": event["title"],
                            "affected_symbols": [],
                            "position_impact": impact["position_impact"],
                            "risk_adjustment": impact["risk_adjustment"],
                            "reason": impact["reason"],
                        }
                    if symbol not in event_impacts[event_id]["affected_symbols"]:
                        event_impacts[event_id]["affected_symbols"].append(symbol)

        # Check news for symbol mentions
        for article in news[:10]:
            if base_symbol in article.get("currencies", []):
                sentiment = article.get("sentiment", "neutral")
                if direction == "LONG" and sentiment == "negative":
                    event_id = article["id"]
                    if event_id not in event_impacts:
                        event_impacts[event_id] = {
                            "event_id": event_id,
                            "event_title": article["title"],
                            "affected_symbols": [],
                            "position_impact": "NEGATIVE",
                            "risk_adjustment": "MONITOR",
                            "reason": f"Negative news may affect {base_symbol}",
                        }
                    if symbol not in event_impacts[event_id]["affected_symbols"]:
                        event_impacts[event_id]["affected_symbols"].append(symbol)
                elif direction == "SHORT" and sentiment == "positive":
                    event_id = article["id"]
                    if event_id not in event_impacts:
                        event_impacts[event_id] = {
                            "event_id": event_id,
                            "event_title": article["title"],
                            "affected_symbols": [],
                            "position_impact": "NEGATIVE",
                            "risk_adjustment": "MONITOR",
                            "reason": f"Positive news may affect {base_symbol}",
                        }
                    if symbol not in event_impacts[event_id]["affected_symbols"]:
                        event_impacts[event_id]["affected_symbols"].append(symbol)

    # Convert to list and limit to top 10 most relevant
    correlations = list(event_impacts.values())[:10]
    return correlations


# ─── Startup ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
