# TradeEdge - Agent Rules & Guidelines

## Project Context

TradeEdge is a cryptocurrency trading signal platform. Before making ANY changes, read `AI_CONTEXT.md` for full project architecture, data models, and API documentation.

---

## CRITICAL RULES

### 1. Read AI_CONTEXT.md First

**ALWAYS read `AI_CONTEXT.md` before doing ANY work on this project.**

This file contains:
- Complete architecture overview
- Data models and interfaces
- API endpoints
- RR calculation rules
- File locations
- Common issues and fixes

### 2. Backend Changes Require Server Restart

The Python FastAPI server (`api_server.py`) does NOT auto-reload. After ANY backend change:

```bash
# Find and kill the Python process
taskkill //F //PID <PID>

# Restart
cd /d/Main\ project/files
python api_server.py
```

**Verify the server is running:**
```bash
curl -s http://localhost:8001/api/dashboard/stats
```

### 3. Keep Backend and Frontend in Sync

When modifying RR calculations, signal statuses, or data models:
- **ALWAYS update BOTH `api_server.py` AND `frontend/src/lib/utils.ts`**
- The `calculateRR()` function in `utils.ts` must match the backend `calc_signal_rr()` in `api_server.py`
- Mismatches cause data inconsistency between dashboard and trade history

### 4. Signal Status Classification

| Status | Classification |
|--------|---------------|
| OPEN | Open (active trade) |
| TP1 | Open (partial - 40% closed) |
| TP2 | Open (partial - 70% closed) |
| TP3 | Open (partial - 90% closed) |
| TP4 | Closed (win) |
| WIN | Closed (win) |
| SL | Closed (loss) |
| BREAKEVEN | Closed (neutral) |
| EXPIRED | Closed (neutral) |

**Open statuses:** OPEN, TP1, TP2, TP3
**Closed statuses:** TP4, WIN, SL, BREAKEVEN, EXPIRED

### 5. RR Calculation Rules

**Standard RR values per signal:**
- rr1 = 1.5 (TP1 at 1.5R)
- rr2 = 2.0 (TP2 at 2.0R)
- rr3 = 3.0 (TP3 at 3.0R)
- rr_max = 4.0 (TP4 at 4.0R)

**Calculation by status:**
- **SL:** -1.0R
- **EXPIRED:** 0.0R
- **TP1:** rr1 * 0.40 = 0.60R
- **TP2:** rr1 * 0.40 + rr2 * 0.30 = 1.20R
- **TP3:** rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20 = 1.80R
- **TP4/WIN:** rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20 + rr_max * 0.10 = 2.20R
- **BREAKEVEN:** Sum of hit TPs only (check tp1_hit, tp2_hit, tp3_hit, tp4_hit booleans)

### 6. BREAKEVEN Calculation

**CRITICAL:** BREAKEVEN trades must check which TPs were actually hit:

```python
if status == 'BREAKEVEN':
    total = 0.0
    if tp1_hit: total += rr1 * 0.40
    if tp2_hit: total += rr2 * 0.30
    if tp3_hit: total += rr3 * 0.20
    if tp4_hit: total += rr_max * 0.10
    return total
```

A trade that hit TP2 then breakeven gives 1.20R, NOT 0.60R.

### 7. Win/Loss Definitions

- **Wins:** TP1, TP2, TP3, TP4, WIN (any TP hit = win)
- **Losses:** SL only
- **Neutral:** BREAKEVEN, EXPIRED
- **Win Rate:** wins / (wins + losses) * 100 (excludes neutral)

### 8. Data Source Priority

The backend loads signals in this order:
1. `data/signals/YYYY/MM/*.json` (priority)
2. `signals.json` (fallback)

When modifying signal data, update the correct source.

### 9. Frontend API Proxy

The frontend uses Next.js rewrite to proxy API calls:
```typescript
// next.config.ts
async rewrites() {
  return [
    {
      source: "/api/:path*",
      destination: "http://localhost:8001/api/:path*",
    },
  ];
}
```

Frontend calls `/api/dashboard/stats`, not `http://localhost:8001/api/dashboard/stats`.

### 10. Testing Changes

After ANY change:
1. Restart API server (if backend changed)
2. Verify frontend compiles: `cd frontend && npx tsc --noEmit`
3. Check dashboard stats: `curl -s http://localhost:8001/api/dashboard/stats`
4. Verify in browser

---

## Common Pitfalls

### Don't Assume Defaults
The backend uses `s.get('rr3', 2.5)` but actual signals have `rr3: 3.0`. Always use actual values from signal data, not defaults.

### Don't Forget tp_hit Booleans
BREAKEVEN calculation requires checking `tp1_hit`, `tp2_hit`, `tp3_hit`, `tp4_hit` booleans. These track which TPs were realized before breakeven.

### Don't Mix Up Open/Closed
TP1, TP2, TP3 are OPEN (partial). TP4 is CLOSED. This affects dashboard stats, live trades, and history pages.

### Restart After Data Changes
Modifying `signals.json` requires restarting the API server to pick up changes.

---

## File Reference

### Backend (Python)
- `api_server.py` - FastAPI server
- `signals.py` - Signal generation
- `scanner.py` - Market scanner
- `tracker.py` - Position tracking + WebSocket monitoring
- `telegram_bot.py` - Telegram notifications
- `reporter.py` - Performance reports
- `market_intel.py` - Economic calendar, news, token events
- `backtest.py` - Backtesting
- `backtest_directional.py` - Directional strategy
- `backtest_macro_events.py` - Macro event analysis
- `backtest_trading_hours.py` - Trading hours analysis
- `config.py` - Configuration

### Frontend (TypeScript/React)
- `frontend/src/lib/api.ts` - API client & interfaces
- `frontend/src/lib/utils.ts` - calculateRR, formatPrice
- `frontend/src/app/dashboard/page.tsx` - Dashboard
- `frontend/src/app/live-trades/page.tsx` - Live trades
- `frontend/src/app/trade-history/page.tsx` - History
- `frontend/src/app/analytics/page.tsx` - Analytics
- `frontend/src/app/backtest/page.tsx` - Backtest
- `frontend/src/app/market-intel/page.tsx` - Market intel

### Data
- `signals.json` - Signal database
- `data/signals/YYYY/MM/*.json` - Archived signals
- `data/market_intel/` - Cached market data

---

## Development Commands

```bash
# Start backend
cd /d/Main\ project/files
python api_server.py

# Start frontend
cd /d/Main\ project/files/frontend
npm run dev

# Check TypeScript
cd /d/Main\ project/files/frontend
npx tsc --noEmit

# Test API
curl -s http://localhost:8001/api/dashboard/stats
curl -s http://localhost:8001/api/signals/open
curl -s http://localhost:8001/api/signals/closed
```

---

## Notes

- PNL on Live Trades page shows **R-multiples** (not leveraged values)
- Cache-busting headers are set in `api.ts` to prevent stale data
- The frontend auto-refetches every 30 seconds
- Signal data includes both `status` (current state) and `outcome` (final result)
- Market regime filter is active: BULL=LONGs only, BEAR=SHORTs only, NEUTRAL=no trades
- Quality score filter is currently DISABLED in live trading (commented out in `main.py`)
- WebSocket monitoring runs for all open positions with REST fallback every 5 minutes
- Signals are archived to `data/signals/YYYY/MM/week_XX.json` weekly
