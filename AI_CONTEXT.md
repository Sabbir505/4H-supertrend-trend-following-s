# TradeEdge - AI Context Document

## Project Overview

TradeEdge is a cryptocurrency trading signal platform with a Python backend that generates trading signals based on technical analysis, and a Next.js frontend dashboard for monitoring trades, backtesting, and analytics.

**Project Root:** `D:\Main project\files`
**Backend:** Python (FastAPI + uvicorn)
**Frontend:** Next.js 16 (TypeScript, React 19, Tailwind CSS v4, shadcn/ui)
**API Server:** `http://localhost:8001`
**Frontend Dev Server:** `http://localhost:3000`

---

## Architecture

### Backend (Python)

| File | Purpose |
|------|---------|
| `api_server.py` | FastAPI server serving signals/backtest data to frontend |
| `signals.py` | Core signal generation engine (ADX, EMA, RSI, volume filters) |
| `scanner.py` | Market scanner fetching Binance data and detecting setups |
| `backtest.py` | Backtesting engine with trade simulation |
| `backtest_directional.py` | Directional strategy with BTC 4H trend filter |
| `config.py` | Configuration (ATR multipliers, TP/SL settings) |
| `tracker.py` | Trade tracking and status updates |
| `telegram_bot.py` | Telegram notifications |
| `reporter.py` | Reporting/analytics generation |
| `data_splitter.py` | Archives old signals to `data/signals/YYYY/MM/` |

### Frontend (Next.js)

| File | Purpose |
|------|---------|
| `frontend/src/app/dashboard/page.tsx` | Main dashboard with stats, equity curve, charts |
| `frontend/src/app/live-trades/page.tsx` | Real-time trade monitoring with Binance price feed |
| `frontend/src/app/trade-history/page.tsx` | Closed trades history table |
| `frontend/src/app/analytics/page.tsx` | Analytics and performance metrics |
| `frontend/src/app/backtest/page.tsx` | Backtest results viewer |
| `frontend/src/lib/api.ts` | API client (fetch wrapper) with TypeScript interfaces |
| `frontend/src/lib/utils.ts` | Utility functions (calculateRR, formatPrice, cn) |

### Data Files

| File | Purpose |
|------|---------|
| `signals.json` | Primary signal database (80 signals) |
| `backtest_results.json` | Backtest results |
| `data/signals/2026/6/week_23.json` | Weekly signal archive |

---

## Core Strategy Configuration

### 4-TP Incremental Closing System

The system uses a 4-level take-profit strategy with incremental position closing:

| Level | Close % | ATR Multiplier | RR Value |
|-------|---------|----------------|----------|
| TP1 | 40% | 1.5x | rr1 = 1.5 |
| TP2 | 30% | 2.0x | rr2 = 2.0 |
| TP3 | 20% | 2.5x | rr3 = 3.0 |
| TP4 | 10% | 3.0x | rr_max = 4.0 |

**SL:** 1.0x ATR (full position)
**Entry:** Based on EMA21/EMA55 + ADX + RSI + volume confirmation

### Signal Statuses

| Status | Meaning | Classification |
|--------|---------|----------------|
| OPEN | Trade active, no TP hit yet | Open |
| TP1 | Hit TP1, 40% closed, 60% remaining | Open (partial) |
| TP2 | Hit TP2, 70% closed, 30% remaining | Open (partial) |
| TP3 | Hit TP3, 90% closed, 10% remaining | Open (partial) |
| TP4 | Hit TP4, 100% closed | Closed (win) |
| WIN | Alternative TP4 status | Closed (win) |
| SL | Hit stop loss | Closed (loss) |
| BREAKEVEN | Moved SL to breakeven after hitting TP(s) | Closed (neutral) |
| EXPIRED | Time-based expiry | Closed (neutral) |

### RR Calculation Rules

**Backend (`api_server.py`) and Frontend (`utils.ts`):**

```python
# SL: Full loss
-1.0

# EXPIRED: No gain/loss
0.0

# BREAKEVEN: Sum of hit TPs (uses tp1_hit, tp2_hit, tp3_hit, tp4_hit booleans)
tp1_hit * rr1 * 0.40 + tp2_hit * rr2 * 0.30 + tp3_hit * rr3 * 0.20 + tp4_hit * rr_max * 0.10

# TP1: Only 40% at TP1
rr1 * 0.40

# TP2: 40% at TP1 + 30% at TP2
rr1 * 0.40 + rr2 * 0.30

# TP3: 40% at TP1 + 30% at TP2 + 20% at TP3
rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20

# TP4/WIN: Full blend
rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20 + rr_max * 0.10
```

**Critical:** BREAKEVEN calculation must check `tp1_hit`, `tp2_hit`, `tp3_hit`, `tp4_hit` booleans to calculate correct realized RR. A trade that hit TP2 then breakeven should give 1.20R, not 0.60R.

---

## API Endpoints

### Signal Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/signals` | All signals (optional `?status=` filter) |
| `GET /api/signals/open` | OPEN, TP1, TP2, TP3 (partial trades) |
| `GET /api/signals/closed` | TP4, SL, BREAKEVEN, EXPIRED, WIN |
| `GET /api/signals/partial` | TP1, TP2, TP3 only |
| `GET /api/signals/{id}` | Specific signal by ID |

### Dashboard/Analytics

| Endpoint | Description |
|----------|-------------|
| `GET /api/dashboard/stats` | Aggregated stats (total_signals, win_rate, total_rr, etc.) |
| `GET /api/live-trades` | Open signals formatted for Live Trades page |
| `GET /api/analytics/summary` | Direction counts, strength counts, outcome distribution |

### Backtest

| Endpoint | Description |
|----------|-------------|
| `GET /api/backtest` | All backtest results |
| `GET /api/backtest/{symbol}` | Backtest for specific symbol |

---

## Data Models

### Signal (Backend Pydantic + Frontend TypeScript)

```typescript
interface Signal {
  id: string;
  symbol: string;
  direction: "LONG" | "SHORT";
  strength?: "STRONG" | "STANDARD";
  entry: number;
  sl: number;
  tp1: number;
  tp2: number;
  tp3?: number;
  tp4?: number;
  rr1: number;
  rr2?: number;
  rr3?: number;
  rr_max: number;
  quality_score: number;
  fired_at: string;
  status: "OPEN" | "TP1" | "TP2" | "TP3" | "TP4" | "SL" | "BREAKEVEN" | "EXPIRED" | "WIN";
  outcome?: "WIN" | "LOSS" | "PARTIAL" | "BREAKEVEN" | "EXPIRED";
  closed_at?: string;
  max_rr_hit?: number;
  tp1_hit: boolean;
  tp2_hit: boolean;
  tp3_hit: boolean;
  tp4_hit: boolean;
  sl_hit: boolean;
  sl_at_breakeven?: boolean;
  minutes_to_close?: number;
  current_price?: number;
  pnl?: number;
  pnl_percent?: number;
}
```

### DashboardStats

```typescript
interface DashboardStats {
  total_signals: number;
  open_signals: number;
  closed_signals: number;
  win_rate: number;
  avg_quality_score: number;
  total_trades_backtest: number;
  total_backtest_wins: number;
  total_backtest_losses: number;
  overall_backtest_wr: number;
  total_rr: number;
}
```

---

## Frontend Architecture

### Next.js Config (`frontend/next.config.ts`)

- **Proxy:** `/api/:path*` → `http://localhost:8001/api/:path*`
- **Images:** `unoptimized: true` (static export compatible)
- **Dev Server:** Port 3000

### API Client (`frontend/src/lib/api.ts`)

- Base URL: `process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001"`
- Timeout: 10 seconds
- Cache-busting headers: `Cache-Control: no-cache, no-store, must-revalidate`
- Functions: `getAllSignals()`, `getOpenSignals()`, `getClosedSignals()`, `getDashboardStats()`, `getLiveTrades()`, `getAnalyticsSummary()`, `getBacktestResults()`

### Utility Functions (`frontend/src/lib/utils.ts`)

- `calculateRR(signal)` - Calculates realized RR for any signal status
- `formatPrice(price)` - Formats prices (2 decimals for >=1, 4 for >=0.01, 6 otherwise)
- `cn(...inputs)` - Tailwind class merging utility

### Pages

1. **Dashboard (`/dashboard`)**
   - Top stats cards (Total Signals, Win Rate, Avg Quality, Total RR, Backtest WR)
   - Equity Curve (cumulative RR over time)
   - Outcome Distribution (pie chart)
   - Symbol Win Rates (bar chart)
   - Recent Trades list

2. **Live Trades (`/live-trades`)**
   - Real-time trade cards with Binance price feed
   - Auto-refresh every 30 seconds
   - Shows: symbol, direction, strength, entry/SL/TP prices, current price, PNL
   - Sidebar: Market Bias gauge, Signal Strength donut, Active Trades Summary

3. **Trade History (`/trade-history`)**
   - Table of closed trades with filters
   - Shows: symbol, direction, entry, SL, TP1, TP2, outcome, RR, quality score

4. **Analytics (`/analytics`)**
   - Performance metrics: win rate, avg RR, profit factor
   - Direction performance (LONG vs SHORT)
   - Strength performance (STRONG vs STANDARD)
   - Symbol performance table

5. **Backtest (`/backtest`)**
   - Backtest results table
   - Per-symbol performance metrics

---

## Key Technical Decisions

### Signal Classification

- **Open signals:** OPEN, TP1, TP2, TP3 (position still partially active)
- **Closed signals:** TP4, SL, BREAKEVEN, EXPIRED, WIN (position fully closed)
- **Partial endpoint:** TP1, TP2, TP3 only

### Win/Loss Definitions

- **Wins:** TP1, TP2, TP3, TP4, WIN (any TP hit = win)
- **Losses:** SL only
- **Neutral:** BREAKEVEN, EXPIRED
- **Win Rate:** wins / (wins + losses) * 100 (excludes neutral)

### PNL Calculation (Live Trades)

- PNL is shown with **10x leverage**
- Formula: `(priceDiff / entryPrice) * 100 * 10`
- Also shows R-multiples: `priceDiff / slDistance`

### Data Flow

1. Python backend loads signals from `signals.json` or `data/signals/YYYY/MM/*.json`
2. FastAPI serves data via REST endpoints
3. Next.js frontend proxies `/api/*` to backend
4. Frontend fetches data every 30 seconds (auto-refresh)

---

## Common Issues & Fixes

### 1. API Server Not Picking Up Changes
**Symptom:** Dashboard shows old data after code changes
**Fix:** Kill the Python process and restart:
```bash
taskkill //F //PID <PID>
cd /d/Main
cd project/files && python api_server.py
```

### 2. CORS Errors
**Symptom:** Frontend can't fetch from backend
**Fix:** Backend already has CORS configured for `localhost:3000` and `localhost:3001`

### 3. RR Values Corrupted
**Symptom:** `rr3` shows 3.0 instead of 2.5, `rr_max` shows 4.0 instead of 3.0
**Note:** These values are actually correct as configured. The ATR multipliers are:
- TP1: 1.5x → rr1 = 1.5
- TP2: 2.0x → rr2 = 2.0
- TP3: 3.0x → rr3 = 3.0
- TP4: 4.0x → rr_max = 4.0

### 4. Dashboard Shows "Loading..."
**Symptom:** Dashboard stuck on loading
**Fix:** Check if API server is running on port 8001:
```bash
netstat -ano | grep 8001
```

### 5. BREAKEVEN RR Calculation Wrong
**Symptom:** BREAKEVEN trades show lower RR than expected
**Fix:** Ensure `tp1_hit`, `tp2_hit`, `tp3_hit` booleans are set in signal data. The calculation uses these to determine which TPs were realized before breakeven.

---

## File Locations

### Critical Files

```
D:\Main project\files\
├── api_server.py              # FastAPI backend
├── signals.py                 # Signal generation engine
├── scanner.py                 # Market scanner
├── backtest.py                # Backtesting engine
├── backtest_directional.py    # Directional strategy with BTC filter
├── config.py                  # Strategy configuration
├── signals.json               # Signal database
├── backtest_results.json      # Backtest results
├── data/
│   ├── signals/               # Archived signals by year/month
│   └── archive/               # Backup files
└── frontend/
    ├── src/
    │   ├── app/
    │   │   ├── dashboard/page.tsx
    │   │   ├── live-trades/page.tsx
    │   │   ├── trade-history/page.tsx
    │   │   ├── analytics/page.tsx
    │   │   └── backtest/page.tsx
    │   ├── lib/
    │   │   ├── api.ts         # API client & interfaces
    │   │   └── utils.ts       # calculateRR, formatPrice
    │   └── components/
    │       ├── dashboard-layout.tsx
    │       ├── sidebar.tsx
    │       └── ui/            # shadcn components
    ├── next.config.ts         # Next.js config with API proxy
    └── package.json
```

---

## Development Workflow

### Starting the Project

1. **Start Backend:**
   ```bash
   cd /d/Main\ project/files
   python api_server.py
   ```

2. **Start Frontend:**
   ```bash
   cd /d/Main\ project/files/frontend
   npm run dev
   ```

3. **Access:**
   - Frontend: http://localhost:3000
   - API: http://localhost:8001

### Making Changes

1. Edit backend → Restart `api_server.py` (does not auto-reload)
2. Edit frontend → Auto-reloads via Next.js dev server
3. Edit `signals.json` → Restart API server to pick up changes

---

## Technology Stack

### Backend
- Python 3.14
- FastAPI + uvicorn
- Pydantic (data validation)
- pandas, numpy (data processing)
- requests (Binance API)

### Frontend
- Next.js 16.2.7
- React 19.2.4
- TypeScript 5
- Tailwind CSS v4
- shadcn/ui components
- recharts (charts)
- lucide-react (icons)

---

## Notes for AI Assistants

1. **Always check both backend and frontend** when making RR/signal-related changes. They must stay in sync.

2. **Signal status classification** is critical. OPEN/TP1/TP2/TP3 are "open", TP4/SL/BREAKEVEN/EXPIRED/WIN are "closed".

3. **BREAKEVEN calculation** must use `tp1_hit`, `tp2_hit`, `tp3_hit`, `tp4_hit` booleans. Never assume only TP1 was hit.

4. **RR values** are stored per-signal. Defaults are rr1=1.5, rr2=2.0, rr3=3.0, rr_max=4.0 (based on ATR multipliers).

5. **Data directory** (`data/signals/`) takes priority over `signals.json`. The backend loads from `data/signals/` first, then falls back to `signals.json`.

6. **Restart API server** after any backend changes. It does not auto-reload.

7. **Frontend uses proxy** via `next.config.ts` rewrite rule: `/api/*` → `http://localhost:8001/api/*`

8. **PNL is shown with 10x leverage** on the Live Trades page.

9. **Cache busting** is enabled via headers in `api.ts` to prevent stale data.

10. **Signal data structure** includes both `status` (current state) and `outcome` (final result). For partial trades, `outcome` may be "PARTIAL" while `status` is TP1/TP2/TP3.
