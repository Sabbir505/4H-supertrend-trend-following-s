# Trading System Analysis & Improvement Plan

## Context

Comprehensive analysis of the crypto trading system to identify issues, improvements, and AI integration opportunities using **only free/open-source tools** (no paid APIs).

---

## Executive Summary

This is a **trend-following crypto trading system** scanning top 100 Binance coins on 1H/4H timeframes. The system generates signals using EMA, RSI, MACD, ADX, and ATR indicators with a 4-TP incremental closing system.

**Current Status (as of 2026-06):**
- Market regime filter **IMPLEMENTED** in live trading (`main.py`)
- Quality score calculation **IMPLEMENTED** but filter **DISABLED** in live trading
- Trading hours filter **IMPLEMENTED** in live trading
- Symbol win rate tracking **IMPLEMENTED** in `tracker.py`
- Adaptive TP multipliers **IMPLEMENTED** in `signals.py`
- WebSocket price monitoring **IMPLEMENTED** in `tracker.py`
- Market intel module **IMPLEMENTED** with RSS news, economic calendar, token events
- Next.js dashboard **IMPLEMENTED** with 6 pages
- ML win predictor **OPTIONAL** (may not exist)

---

## Part 1: Implemented Features (Status Update)

### ✅ 1. Market Regime Filter in Live Trading
**Status:** IMPLEMENTED

The `main.py` scan loop now includes BTC 4H regime detection:
```python
market_regime = get_market_regime(scanner, signal_engine)
# ...
if market_regime == 'BULL' and signal['direction'] != 'LONG':
    continue
if market_regime == 'BEAR' and signal['direction'] != 'SHORT':
    continue
if market_regime == 'NEUTRAL':
    continue
```

### ✅ 2. Quality Score Calculation
**Status:** IMPLEMENTED (calculation) / DISABLED (filter)

Quality scores are calculated in `signals.py` but the filter is commented out in `main.py`:
```python
# Quality Score Filter (DISABLED)
# if signal['quality_score'] < min_quality_score:
#     continue
```

### ✅ 3. Trading Hours Filter
**Status:** IMPLEMENTED

```python
def is_good_trading_hour(config) -> bool:
    current_hour = datetime.now(timezone.utc).hour
    return config.trading_start_hour <= current_hour < config.trading_end_hour
```

### ✅ 4. Symbol Win Rate Tracking
**Status:** IMPLEMENTED

```python
tracker.get_symbol_stats(symbol, lookback=20)
tracker.should_skip_symbol(symbol, min_win_rate=0.40)
tracker.get_worst_symbols(limit=5)
```

### ✅ 5. Adaptive TP Multipliers
**Status:** IMPLEMENTED

```python
def get_adaptive_tp_multipliers(self, atr, atr_ma) -> list:
    volatility_ratio = atr / atr_ma
    if volatility_ratio > 1.5:
        return [2.0, 2.5, 3.0, 4.0]
    elif volatility_ratio > 1.2:
        return [1.75, 2.25, 2.75, 3.5]
    else:
        return [1.5, 2.0, 3.0, 4.0]
```

### ✅ 6. WebSocket Price Monitoring
**Status:** IMPLEMENTED

- Real-time Binance WebSocket for all open positions
- Dynamic symbol subscription based on open trades
- REST fallback every 5 minutes
- Watchdog for stuck connections

### ✅ 7. Next.js Dashboard
**Status:** IMPLEMENTED

- Dashboard with stats, equity curve, outcome distribution
- Live Trades with real-time price feed
- Trade History with filters and pagination
- Analytics with direction/strength/symbol analysis
- Backtest results viewer
- Market Intel with calendar, news, token events

### ✅ 8. Market Intel Module
**Status:** IMPLEMENTED

- Economic calendar (estimated dates for FOMC, CPI, NFP, etc.)
- Crypto news from RSS feeds (CoinDesk, Cointelegraph, Decrypt)
- Token events from CoinGecko
- Impact analysis for open positions

---

## Part 2: Remaining Improvements

### 🔧 1. Enable Quality Score Filter
**File:** `main.py`

Currently disabled:
```python
# ── QUALITY SCORE FILTER (DISABLED) ────────────────────────────
# Temporarily disabled to allow more signals through
# if signal['quality_score'] < min_quality_score:
#     logger.debug(f"Skipping {symbol} — quality score ...")
#     continue
```

**Action:** Uncomment and tune threshold based on backtest data.

---

### 🔧 2. Dynamic Position Sizing by Quality
**File:** `signals.py` (future enhancement)

```python
def get_position_multiplier(quality_score):
    """Kelly-inspired position sizing"""
    if quality_score >= 80:
        return 2.0  # Double size on high-quality
    elif quality_score >= 70:
        return 1.5
    elif quality_score >= 60:
        return 1.0
    else:
        return 0.0  # Don't take the trade
```

**Status:** Not yet implemented.

---

### 🔧 3. ML Win Probability Model
**File:** `win_predictor.py` (optional)

**Status:** Optional module — may not exist.

If implemented:
```python
from win_predictor import WinPredictor

predictor = WinPredictor()
prob = predictor.predict_proba(signal)
if prob < 0.55:
    continue
```

**Features:**
- quality_score
- rsi
- adx
- vol_ratio
- atr
- hour_of_day

---

### 🔧 4. Fear & Greed Index Integration
**File:** `market_intel.py` (future enhancement)

**Free API:** `https://api.alternative.me/fng/` (no key required)

```python
def fetch_fear_greed_index() -> dict:
    """Fetch Fear & Greed Index (free, no auth)"""
    try:
        url = "https://api.alternative.me/fng/"
        response = requests.get(url, timeout=10)
        data = response.json()['data'][0]
        return {
            'value': int(data['value']),
            'classification': data['value_classification'],
            'timestamp': data['timestamp']
        }
    except Exception as e:
        logger.warning(f"Failed to fetch F&G index: {e}")
        return {'value': 50, 'classification': 'Neutral'}
```

**Status:** Not yet implemented.

---

### 🔧 5. Funding Rate Analysis
**File:** `market_intel.py` (future enhancement)

**Free API:** Binance Futures (no auth)

```python
def get_funding_rate(symbol: str = 'BTCUSDT') -> float:
    """Get current funding rate from Binance"""
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    params = {'symbol': symbol, 'limit': 1}
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    return float(data[0]['fundingRate'])
```

**Status:** Not yet implemented.

---

### 🔧 6. Consolidate Backtest Files
**Files:** `backtest.py`, `backtest_directional.py`

**Status:** Partially done. `backtest.py` includes `run_directional_backtest()` but `backtest_directional.py` still exists as a standalone runner.

**Action:** Consider merging or deprecating `backtest_directional.py`.

---

## Part 3: Implementation Priority

### Phase 1: Quick Wins
| Task | File | Effort | Impact |
|------|------|--------|--------|
| Enable quality score filter | `main.py` | 30 min | Medium |
| Tune trading hours | `config.py` | 15 min | Low |
| Review excluded pairs | `config.py` | 15 min | Low |

### Phase 2: Medium Effort
| Task | File | Effort | Impact |
|------|------|--------|--------|
| Dynamic position sizing | `signals.py`, `main.py` | 2-3 hours | Medium |
| Fear & Greed integration | `market_intel.py` | 1-2 hours | Low |
| Funding rate analysis | `market_intel.py` | 1-2 hours | Low |

### Phase 3: High Effort
| Task | File | Effort | Impact |
|------|------|--------|--------|
| ML win predictor | `win_predictor.py` | 4-6 hours | High |
| Train model on historical data | — | 2-3 hours | High |
| Backtest with all filters | `backtest.py` | 2-3 hours | Medium |

---

## Part 4: Expected Improvements

| Metric | Current | Expected | How |
|--------|---------|----------|-----|
| Win Rate | ~45% | 50-55% | Regime filter, quality threshold |
| False Signals | Medium | -30% | All filters combined |
| Avg RR/Trade | ~0.5R | 0.7-1.0R | Better entries, adaptive TPs |

---

## Part 5: Files Summary

### Files to Create (Optional)
```
win_predictor.py       # ML win probability (optional)
models/win_predictor.pkl  # Trained model (optional)
```

### Files to Modify
```
main.py                # Enable quality filter, tune parameters
config.py              # Adjust thresholds
signals.py             # Dynamic position sizing (optional)
market_intel.py        # Fear & Greed, funding rates (optional)
```

### Files to Review
```
backtest_directional.py  # Consider merging into backtest.py
```

---

## Verification Checklist

- [ ] Regime filter working (check logs for skipped signals)
- [ ] Trading hours filter preventing signals outside window
- [ ] Symbol win rate filter skipping poor performers
- [ ] Adaptive TPs showing different values for different volatility
- [ ] WebSocket monitoring active for open positions
- [ ] Dashboard showing real-time data
- [ ] Market intel showing calendar/news/events
