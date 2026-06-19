# TradeEdge Trading System - Complete Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Backend Components](#backend-components)
4. [Frontend Components](#frontend-components)
5. [Trading Strategy](#trading-strategy)
6. [Signal Flow](#signal-flow)
7. [API Reference](#api-reference)
8. [Configuration](#configuration)
9. [AI/ML Features](#aiml-features)
10. [Deployment](#deployment)

---

## System Overview

**TradeEdge** is a cryptocurrency trading signal platform that:
- Scans top 100 USDT pairs on Binance for trading setups
- Generates signals using technical analysis (EMA, RSI, MACD, ADX, ATR)
- Tracks positions with real-time WebSocket price monitoring
- Provides a Next.js dashboard for monitoring and analytics
- Sends Telegram alerts for new signals

**Tech Stack:**
- **Backend:** Python 3.14, FastAPI, pandas, numpy
- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS v4
- **Data Sources:** Binance API (public), CoinGecko API
- **ML:** scikit-learn (RandomForest)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        TRADEEDGE SYSTEM                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │   main.py   │───>│  scanner.py │───>│ signals.py  │         │
│  │  (Scheduler)│    │ (Binance API)│   │  (Strategy) │         │
│  └──────┬──────┘    └─────────────┘    └──────┬──────┘         │
│         │                                      │                │
│         v                                      v                │
│  ┌─────────────┐                      ┌─────────────┐          │
│  │  tracker.py │<─────────────────────│  Telegram   │          │
│  │ (Positions) │                      │    Bot      │          │
│  └──────┬──────┘                      └─────────────┘          │
│         │                                                       │
│         v                                                       │
│  ┌─────────────────────────────────────────────────────┐       │
│  │              api_server.py (FastAPI)                 │       │
│  │  /api/signals  /api/dashboard  /api/market-intel    │       │
│  └─────────────────────┬───────────────────────────────┘       │
│                        │                                        │
│                        v                                        │
│  ┌─────────────────────────────────────────────────────┐       │
│  │              Next.js Frontend (:3000)                │       │
│  │  Dashboard | Live Trades | History | Analytics      │       │
│  └─────────────────────────────────────────────────────┘       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Backend Components

### Core Modules

| File | Purpose |
|------|---------|
| `main.py` | Main entry point, scheduler for hourly scans |
| `config.py` | Configuration management from environment |
| `scanner.py` | Fetches top 100 coins by volume, candle data |
| `signals.py` | Signal generation with technical indicators |
| `tracker.py` | Position tracking, WebSocket price monitoring |
| `api_server.py` | FastAPI REST API server |
| `win_predictor.py` | ML-based win probability prediction |
| `market_intel.py` | Economic calendar, crypto news, token events |
| `telegram_bot.py` | Telegram notifications |
| `backtest.py` | Historical strategy backtesting |
| `reporter.py` | Performance reports |

### Scanner (`scanner.py`)

**Purpose:** Fetch market data from Binance

```python
# Key methods:
scanner.get_top_100_symbols()  # Top USDT pairs by 24h volume
scanner.fetch_candles(symbol, interval, limit)  # OHLCV data
scanner.get_futures_symbol(spot_symbol)  # Map spot to futures symbol
```

**Filters applied:**
- Excludes stablecoins (USDT, USDC, DAI, etc.)
- Excludes forex pairs (EURUSDT, GBPUSDT, etc.)
- Excludes pairs not available on Binance Futures
- Excludes known poor performers (TRXUSDT, SOLUSDT, PORTALUSDT)

### Signal Engine (`signals.py`)

**Indicators Used:**
- **EMA 21/55** - Trend direction
- **RSI 14** - Momentum (LONG: 50-75, SHORT: 25-50)
- **MACD** - Histogram direction + strength
- **ADX 14** - Trend strength (must be >= 25)
- **ATR 14** - Volatility for SL/TP calculation
- **Volume** - Must be > 1.2x 20-period MA

**Signal Generation Flow:**
```
1. Check ADX >= 25 (trend strength)
2. Check Volume > 1.2x MA (volume confirmation)
3. Check EMA alignment (21 > 55 for LONG, 21 < 55 for SHORT)
4. Check RSI range (50-75 for LONG, 25-50 for SHORT)
5. Check MACD histogram direction
6. Calculate SL = Entry - (ATR * 1.0)
7. Calculate TP levels (1.5x, 2.0x, 2.5x, 3.0x SL distance)
8. Calculate quality score (0-100)
```

**Quality Score Factors:**
- RSI proximity to optimal range (25 points)
- MACD histogram strength (30 points)
- Volume surge (30 points)
- ADX trend quality (20 points)

**New: Adaptive TP Multipliers**
```python
def get_adaptive_tp_multipliers(atr, atr_ma):
    ratio = atr / atr_ma
    if ratio > 1.5:    # High volatility
        return [2.0, 2.5, 3.0, 4.0]
    elif ratio > 1.2:  # Elevated volatility
        return [1.75, 2.25, 2.75, 3.5]
    else:              # Normal volatility
        return [1.5, 2.0, 2.5, 3.0]
```

### Tracker (`tracker.py`)

**Purpose:** Monitor open positions and detect TP/SL hits

**Key Features:**
- **WebSocket Price Monitoring** - Real-time prices via Binance WebSocket
- **REST Fallback** - Polls every 5 minutes as backup
- **4-TP Incremental Closing** - Tracks partial closes
- **Breakeven Logic** - Moves SL to entry after TP1 hit
- **Cooldown System** - 4-hour cooldown after trade closes

**Position Statuses:**
| Status | Meaning | Position Remaining |
|--------|---------|-------------------|
| OPEN | No TP hit yet | 100% |
| TP1 | First TP hit | 60% |
| TP2 | Second TP hit | 30% |
| TP3 | Third TP hit | 10% |
| TP4 | All TPs hit | 0% (closed) |
| SL | Stop loss hit | 0% (closed) |
| BREAKEVEN | Exited at entry | 0% (closed) |
| EXPIRED | Time expiry (7 days) | 0% (closed) |

**New: Symbol Statistics**
```python
tracker.get_symbol_stats(symbol, lookback=20)  # Win rate per symbol
tracker.should_skip_symbol(symbol, min_win_rate=0.40)  # Skip poor performers
tracker.get_worst_symbols(limit=5)  # Worst performing symbols
```

### API Server (`api_server.py`)

**Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/signals` | All signals |
| GET | `/api/signals/open` | Open positions (OPEN, TP1, TP2, TP3) |
| GET | `/api/signals/closed` | Closed trades |
| GET | `/api/signals/{id}` | Single signal by ID |
| GET | `/api/dashboard/stats` | Aggregated statistics |
| GET | `/api/live-trades` | Live trade data with current prices |
| GET | `/api/analytics/summary` | Performance analytics |
| GET | `/api/backtest` | Backtest results |
| GET | `/api/market/calendar` | Economic calendar events |
| GET | `/api/market/news` | Crypto news feed |
| GET | `/api/market/events` | Token events (unlocks, etc.) |
| GET | `/api/market/impact` | Events affecting open positions |

### Win Predictor (`win_predictor.py`)

**Purpose:** ML model to predict trade success probability

**Features Used:**
- quality_score
- rsi
- adx
- vol_ratio
- atr
- hour_of_day

**Usage:**
```python
from win_predictor import WinPredictor, train_model_from_tracker

# Train model from historical signals
train_model_from_tracker(tracker)

# Predict win probability
predictor = WinPredictor()
prob = predictor.predict_proba(signal)  # Returns 0.0-1.0
```

---

## Frontend Components

### Pages

| Route | Page | Description |
|-------|------|-------------|
| `/dashboard` | Dashboard | Stats, equity curve, recent trades |
| `/live-trades` | Live Trades | Real-time position monitoring |
| `/trade-history` | Trade History | Closed trades table |
| `/analytics` | Analytics | Performance charts and metrics |
| `/backtest` | Backtest | Strategy backtest results |
| `/market-intel` | Market Intel | Economic calendar, news, events |

### Dashboard (`/dashboard`)

**Features:**
- Total signals count
- Win rate percentage
- Average quality score
- Total RR (risk units)
- Backtest win rate
- Equity curve (cumulative RR over time)
- Outcome distribution pie chart
- Symbol performance bar chart
- Recent 5 closed trades

**Auto-refresh:** Every 30 seconds

### Live Trades (`/live-trades`)

**Features:**
- Real-time price from Binance API
- Position cards with entry/SL/TP levels
- PNL calculation (10x leverage)
- Progress indicator toward TP1
- Market bias gauge (LONG vs SHORT ratio)
- Signal strength breakdown

**PNL Formula:**
```
PNL% = (priceDiff / entryPrice) * 100 * 10 (leverage)
R-Multiples = priceDiff / slDistance
```

### Trade History (`/trade-history`)

**Features:**
- Paginated table (15 per page)
- Filter by symbol, direction, outcome
- Shows: symbol, direction, entry, SL, TP1, TP2, outcome, RR, quality

### Analytics (`/analytics`)

**Features:**
- Win rate by direction (LONG vs SHORT)
- Win rate by signal strength (STRONG vs STANDARD)
- Symbol performance table
- Day of week analysis
- Quality score distribution

### Market Intel (`/market-intel`)

**Features:**
- Economic calendar (CPI, PPI, FOMC, etc.)
- Crypto news feed with sentiment
- Token events (unlocks, listings)
- Impact analysis for open positions
- Filter by impact level

---

## Trading Strategy

### 4-TP Incremental Closing System

| Level | ATR Multiplier | RR Value | Close % | Cumulative |
|-------|----------------|----------|---------|------------|
| TP1 | 1.5x | 1.5R | 40% | 0.60R |
| TP2 | 2.0x | 2.0R | 30% | 1.20R |
| TP3 | 2.5x | 2.5R | 20% | 1.80R |
| TP4 | 3.0x | 3.0R | 10% | 2.20R |

**Stop Loss:** 1.0x ATR (full position at risk)

### RR Calculation

```python
# Full loss
SL = -1.0R

# Expired (no gain/loss)
EXPIRED = 0.0R

# Partial closes
TP1 = rr1 * 0.40 = 0.60R
TP2 = rr1 * 0.40 + rr2 * 0.30 = 1.20R
TP3 = rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20 = 1.80R
TP4 = rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20 + rr_max * 0.10 = 2.20R

# Breakeven (sum of hit TPs)
BREAKEVEN = tp1_hit * rr1 * 0.40 + tp2_hit * rr2 * 0.30 + ...
```

### Entry Conditions

**LONG Signal:**
1. EMA21 > EMA55 (bullish trend)
2. RSI between 50-75 (momentum not overbought)
3. MACD histogram positive with strength
4. ADX >= 25 (strong trend)
5. Volume > 1.2x 20-period MA
6. 4H trend bias = LONG (if available)

**SHORT Signal:**
1. EMA21 < EMA55 (bearish trend)
2. RSI between 25-50 (momentum not oversold)
3. MACD histogram negative with strength
4. ADX >= 25 (strong trend)
5. Volume > 1.2x 20-period MA
6. 4H trend bias = SHORT (if available)

---

## Signal Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                      SIGNAL GENERATION FLOW                      │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. SCHEDULER (main.py)                                         │
│     │                                                            │
│     ├─> Check trading hours (14:00-22:00 UTC)                   │
│     │                                                            │
│     ├─> Get BTC 4H market regime                                │
│     │   └─> BULL = only LONGs allowed                           │
│     │   └─> BEAR = only SHORTs allowed                          │
│     │   └─> NEUTRAL = no trades allowed                         │
│     │                                                            │
│     └─> For each symbol in top 100:                             │
│                                                                  │
│  2. FILTERS                                                      │
│     │                                                            │
│     ├─> Skip if already has open signal                         │
│     ├─> Skip if signal fired < 30 min ago                       │
│     ├─> Skip if symbol on cooldown                              │
│     ├─> Skip if symbol win rate < 40% (last 20 trades)          │
│     ├─> Skip if excluded pair (SOLUSDT, TRXUSDT, etc.)          │
│     │                                                            │
│  3. SIGNAL GENERATION (signals.py)                              │
│     │                                                            │
│     ├─> Fetch 1H candles                                        │
│     ├─> Calculate indicators (EMA, RSI, MACD, ADX, ATR)         │
│     ├─> Check entry conditions                                  │
│     ├─> Calculate SL/TP levels                                  │
│     ├─> Calculate quality score                                 │
│     │                                                            │
│  4. POST-GENERATION FILTERS                                      │
│     │                                                            │
│     ├─> Skip if quality_score < 60                              │
│     ├─> Skip if regime doesn't match direction                  │
│     ├─> Predict win probability (if model exists)               │
│     ├─> Skip if win_probability < 0.55                          │
│     │                                                            │
│  5. OUTPUT                                                       │
│     │                                                            │
│     ├─> Send to Telegram                                        │
│     ├─> Log to signals.json                                     │
│     └─> Start WebSocket monitoring for TP/SL                    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## API Reference

### Signals

```typescript
GET /api/signals
Response: Signal[]

GET /api/signals/open
Response: Signal[]  // OPEN, TP1, TP2, TP3

GET /api/signals/closed
Response: Signal[]  // TP4, SL, BREAKEVEN, EXPIRED, WIN

GET /api/signals/{id}
Response: Signal
```

### Dashboard

```typescript
GET /api/dashboard/stats
Response: {
  total_signals: number
  open_signals: number
  closed_signals: number
  win_rate: number
  avg_quality_score: number
  total_rr: number
  total_trades_backtest: number
  overall_backtest_wr: number
}
```

### Live Trades

```typescript
GET /api/live-trades
Response: LiveTrade[]  // With current_price, pnl, pnl_percent
```

### Market Intel

```typescript
GET /api/market/calendar
Response: EconomicEvent[]

GET /api/market/news
Response: CryptoNews[]

GET /api/market/events
Response: TokenEvent[]

GET /api/market/impact
Response: ImpactCorrelation[]
```

---

## Configuration

### Environment Variables (`.env`)

```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

# Strategy
TOP_N_COINS=100
MAX_SIGNALS_PER_SCAN=20

# ATR Multipliers
ATR_SL_MULTIPLIER=1.0
ATR_TP1_MULTIPLIER=1.5
ATR_TP2_MULTIPLIER=2.0
ATR_TP3_MULTIPLIER=2.5
ATR_TP4_MULTIPLIER=3.0

# TP Close Percentages (must sum to 100)
TP1_CLOSE_PERCENT=40
TP2_CLOSE_PERCENT=30
TP3_CLOSE_PERCENT=20
TP4_CLOSE_PERCENT=10

# Signal Settings
LEVERAGE=10
SIGNAL_EXPIRATION_MINUTES=10080  # 7 days

# NEW: Trading System Improvements
MIN_QUALITY_SCORE=60
TRADING_START_HOUR=14  # UTC
TRADING_END_HOUR=22    # UTC
SYMBOL_WIN_RATE_MIN=0.40
ADAPTIVE_TP_ENABLED=true
```

### New Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `min_quality_score` | 60 | Minimum quality score to fire signal |
| `trading_start_hour` | 14 | UTC hour to start scanning |
| `trading_end_hour` | 22 | UTC hour to stop scanning |
| `symbol_win_rate_min` | 0.40 | Minimum win rate to trade symbol |
| `adaptive_tp_enabled` | true | Adjust TPs based on volatility |

---

## AI/ML Features

### Win Probability Model

**Location:** `win_predictor.py`

**Model:** RandomForestClassifier (scikit-learn)

**Features:**
- quality_score (0-100)
- rsi (0-100)
- adx (trend strength)
- vol_ratio (volume / volume_ma)
- atr (volatility)
- hour_of_day (0-23)

**Training:**
```python
from win_predictor import train_model_from_tracker

# Train from historical signals
train_model_from_tracker(tracker)
# Model saved to models/win_predictor.pkl
```

**Usage:**
```python
from win_predictor import WinPredictor

predictor = WinPredictor()
probability = predictor.predict_proba(signal)
# Returns 0.0-1.0 (probability of winning)
```

### Signal Filters (Applied in Order)

1. **Trading Hours** - Only scan 14:00-22:00 UTC
2. **Open Signal Check** - Skip if symbol already has open position
3. **Recent Signal Check** - Skip if signal fired < 30 minutes ago
4. **Cooldown Check** - Skip if symbol on 4-hour cooldown
5. **Symbol Win Rate** - Skip if win rate < 40% over last 20 trades
6. **Excluded Pairs** - Skip SOLUSDT, TRXUSDT, PORTALUSDT
7. **Quality Score** - Skip if quality < 60
8. **Market Regime** - Skip if direction doesn't match BTC 4H trend
9. **Win Probability** - Skip if predicted win prob < 55%

---

## Deployment

### Starting the System

**1. Start Backend:**
```bash
cd /d/Main\ project/files
python api_server.py
# Runs on http://localhost:8001
```

**2. Start Trading Bot:**
```bash
cd /d/Main\ project/files
python main.py
# Runs scheduled scans every hour
```

**3. Start Frontend:**
```bash
cd /d/Main\ project/files/frontend
npm run dev
# Runs on http://localhost:3000
```

### Directory Structure

```
D:\Main project\files\
├── main.py                    # Trading bot entry point
├── api_server.py              # FastAPI server
├── config.py                  # Configuration
├── scanner.py                 # Binance data fetcher
├── signals.py                 # Signal generation
├── tracker.py                 # Position tracking
├── win_predictor.py           # ML win prediction
├── market_intel.py            # Market intelligence
├── telegram_bot.py            # Telegram notifications
├── backtest.py                # Backtesting engine
├── reporter.py                # Performance reports
├── signals.json               # Signal database
├── backtest_results.json      # Backtest results
├── models/
│   └── win_predictor.pkl      # Trained ML model
├── data/
│   ├── signals/               # Archived signals
│   └── market_intel/          # Cached market data
└── frontend/
    ├── src/
    │   ├── app/               # Next.js pages
    │   ├── lib/               # API client, utilities
    │   └── components/        # React components
    ├── next.config.ts
    └── package.json
```

### Verification Checklist

- [ ] Backend starts without errors
- [ ] API responds at http://localhost:8001/api/dashboard/stats
- [ ] Frontend builds without TypeScript errors
- [ ] Frontend loads at http://localhost:3000
- [ ] Dashboard shows signal data
- [ ] Live Trades shows open positions
- [ ] Market Intel shows calendar/news

---

## Performance Metrics

### Current Stats (as of documentation)

| Metric | Value |
|--------|-------|
| Total Signals | 92 |
| Open Signals | 13 |
| Closed Signals | 79 |
| Win Rate | 39.22% |
| Average Quality Score | 58.1 |
| Total RR | 62.7R |

### Expected Improvements (with new filters)

| Metric | Current | Target |
|--------|---------|--------|
| Win Rate | 39% | 52-55% |
| Avg RR/Trade | 0.79R | 1.0R+ |
| False Signals | High | -40% |
| TP4 Hit Rate | ~10% | 15-20% |

---

## Troubleshooting

### API Server Won't Start
```bash
# Check if port is in use
netstat -ano | findstr 8001

# Kill existing process
taskkill /F /PID <PID>
```

### Frontend Shows Loading Forever
- Check if API server is running on port 8001
- Check browser console for errors
- Verify CORS is configured correctly

### Signals Not Generating
- Check if trading hours filter is blocking (14:00-22:00 UTC)
- Check if market regime is NEUTRAL (blocks all trades)
- Check if quality threshold is too high
- Check bot.log for details

### WebSocket Not Receiving Prices
- Check internet connection
- Verify Binance API is accessible
- Check bot.log for WebSocket errors
- REST fallback kicks in automatically

---

## Contact & Support

- **Project Root:** `D:\Main project\files`
- **API Server:** http://localhost:8001
- **Frontend:** http://localhost:3000
- **Logs:** `bot.log` (trading bot), `api_output.log` (API server)
