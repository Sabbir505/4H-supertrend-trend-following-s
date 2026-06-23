# 🤖 TradeEdge — Crypto Signal Bot & Dashboard

Automated cryptocurrency trading signal platform. Scans top 100 Binance coins on 1H and 4H timeframes, generates trading signals via technical analysis, tracks live positions, and provides a Next.js dashboard for monitoring, analytics, and backtesting.

---

## 📡 Signal Types

| Type | Condition | Icon |
|------|-----------|------|
| **STRONG** | 4H trend + 1H trigger both confirm | 🔥 |
| **STANDARD** | 1H signal only | ⚡ |

## 📊 Strategy: Triple Confirmation Trend System (4-TP)

| Indicator | Settings | Role |
|-----------|----------|------|
| EMA 21/55 | — | Trend direction |
| RSI 14 | LONG: 40-80, SHORT: 20-60 | Momentum filter |
| MACD 12/26/9 | Histogram direction + strength | Entry trigger |
| ADX 14 | ≥ 25 | Trend strength filter |
| ATR 14 | SL = 1.0×, TP1 = 1.5×, TP2 = 2.0×, TP3 = 3.0×, TP4 = 4.0× | Risk sizing |
| Volume MA 20 | > 1.2× average | Quality filter |

## 🎯 4-TP Incremental Closing System

| Level | ATR Multiplier | RR Value | Close % | Position Remaining |
|-------|----------------|----------|---------|-------------------|
| **TP1** | 1.5× | 1.5R | 40% | 60% |
| **TP2** | 2.0× | 2.0R | 30% | 30% |
| **TP3** | 3.0× | 3.0R | 20% | 10% |
| **TP4** | 4.0× | 4.0R | 10% | 0% |

- SL moves to breakeven (entry price) after TP1 hit
- BREAKEVEN = sum of hit TPs only (uses `tp1_hit`, `tp2_hit`, etc.)

---

## ⚙️ Setup

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Install frontend dependencies
```bash
cd frontend
npm install
```

### 3. Create Telegram Bot
1. Open Telegram → search **@BotFather**
2. Send `/newbot` → follow instructions → copy the **token**
3. Start a chat with your bot
4. Get your chat ID: visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`

### 4. Configure .env
```bash
cp .env.example .env
```
Edit `.env`:
```
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=123456789

# Strategy
TOP_N_COINS=100
MAX_SIGNALS_PER_SCAN=20

# ATR Multipliers
ATR_SL_MULTIPLIER=1.0
ATR_TP1_MULTIPLIER=1.5
ATR_TP2_MULTIPLIER=2.0
ATR_TP3_MULTIPLIER=3.0
ATR_TP4_MULTIPLIER=4.0

# Trading hours (UTC)
TRADING_START_HOUR=14
TRADING_END_HOUR=22

# Quality filter
MIN_QUALITY_SCORE=60
```

### 5. Run the bot
```bash
python main.py
```
This starts:
- Trading bot scheduler (1H scans, 4H trend updates)
- FastAPI backend server on `http://localhost:8001`
- Next.js frontend dev server on `http://localhost:3000`
- WebSocket price monitoring for live positions

---

## 📁 File Structure

```
D:\Main project\files\
├── main.py                    # Scheduler + orchestration + servers
├── api_server.py              # FastAPI REST API
├── config.py                  # Settings management (.env)
├── scanner.py                 # Binance API + symbol fetching
├── signals.py                 # Indicator calculations + signal logic
├── telegram_bot.py            # Telegram alerts (Cornix format)
├── tracker.py                 # Position tracking + WebSocket monitoring
├── reporter.py                # Daily/weekly performance reports
├── market_intel.py            # Economic calendar, news, token events
├── backtest.py                # Backtesting engine
├── backtest_directional.py    # Directional strategy with BTC regime filter
├── backtest_macro_events.py   # Macro event avoidance analysis
├── backtest_trading_hours.py  # Trading hours filter analysis
├── signals.json               # Signal database
├── backtest_results.json      # Backtest results
├── data/
│   ├── signals/               # Archived signals by year/month/week
│   └── market_intel/          # Cached market data
└── frontend/                  # Next.js dashboard
    ├── src/
    │   ├── app/               # Pages (dashboard, live-trades, etc.)
    │   ├── lib/               # API client, utilities
    │   └── components/        # React components, sidebar, layout
    ├── next.config.ts
    └── package.json
```

---

## ⏰ Schedule

- **Every 1H** → Scans all coins on 1H candles (at :05 past the hour)
- **Every 4H** → Updates trend bias on 4H candles (00:02, 04:02, 08:02, 12:02, 16:02, 20:02 UTC)
- **Every 15 min** → Checks open signals via REST fallback
- **WebSocket** → Real-time price monitoring for all open positions
- **Daily** → Performance report at 00:05 UTC
- **Weekly** → Report every Monday at 00:10 UTC

---

## 🖥️ Dashboard Pages

| Page | Route | Description |
|------|-------|-------------|
| **Dashboard** | `/dashboard` | Stats, equity curve, outcome distribution, recent trades |
| **Live Trades** | `/live-trades` | Real-time position monitoring with Binance price feed |
| **Trade History** | `/trade-history` | Filterable table of closed trades with pagination |
| **Analytics** | `/analytics` | Performance metrics, direction/strength/symbol analysis |
| **Backtest** | `/backtest` | Historical strategy backtest results |
| **Market Intel** | `/market-intel` | Economic calendar, crypto news, token events |

---

## 🔧 Customization

Edit `.env` to adjust:
- `TOP_N_COINS` — how many coins to scan (default: 100)
- `MAX_SIGNALS_PER_SCAN` — max alerts per scan (default: 20)
- `ATR_SL_MULTIPLIER` — stop loss distance (default: 1.0)
- `ATR_TP1/TP2/TP3/TP4_MULTIPLIER` — take profit levels
- `TRADING_START_HOUR` / `TRADING_END_HOUR` — trading window (default: 14-22 UTC)
- `MIN_QUALITY_SCORE` — minimum quality score to fire signal (default: 60)
- `LEVERAGE` — leverage for Telegram signals (default: 10)
- `SIGNAL_EXPIRATION_MINUTES` — signal expiry time (default: 10080 = 7 days)

---

## ⚠️ Disclaimer

This bot is for informational purposes only. Not financial advice. Always do your own research and manage your risk.
