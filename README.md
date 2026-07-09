# 🤖 TradeEdge — Crypto Signal Bot & Dashboard

Automated cryptocurrency signal scanner. Scans the top 100 Binance USDT pairs by 24h volume and top 100 by ATR volatility for **Supertrend flips on the 4H timeframe**, filtered by a 200 EMA trend filter, RSI(14) momentum filter, and an ATR% volatility band. Each signal comes with a full RR-based trade plan (entry / SL / TP). Alerts go to Telegram; a Next.js dashboard shows everything live.

---

## 📡 Signal Definition

A signal fires on the just-closed 4H candle when **all** of these are true:

| Direction | Supertrend flip | 200 EMA | RSI(14) | ATR% range |
|-----------|-----------------|---------|---------|------------|
| **BUY** | bearish → bullish | price > EMA200 | RSI > 55 | 0.5% – 5.0% |
| **SELL** | bullish → bearish | price < EMA200 | RSI < 45 | 0.5% – 5.0% |

### Trade Plan (per signal, RR-based)

For a BUY (SELL mirrored):
- `entry` = current close
- `atr` = ATR(12) at signal candle
- `sl` = entry − 1.5 × atr
- `tp` = entry + 1.5 × atr
- `rr` = 1.5
- `supertrend_value` = Supertrend line at signal candle

---

## 📊 Strategy Configuration

| Indicator | Settings | Role |
|-----------|----------|------|
| Supertrend | ATR 12, multiplier 3.5 | Flip trigger |
| EMA 200 | — | Trend filter |
| RSI 14 | Long > 55, Short < 45 | Momentum filter |
| ATR % | 0.5% – 5.0% of price | Volatility filter |
| RR multiplier | 1.5 × ATR | Trade plan sizing |

- **Timeframe:** 4H
- **Universe:** Top 100 by 24h quote volume + Top 100 by ATR volatility (merged, deduped)
- **Cooldown:** 4 hours per (symbol, direction)
- **Scan cadence:** hourly at :05 (overlap-safe; dedup suppresses repeats)

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

# Supertrend strategy (4H)
SUPERTREND_ATR_PERIOD=12
SUPERTREND_MULTIPLIER=3.5
EMA_FILTER_PERIOD=200
RSI_PERIOD=14
RSI_LONG_THRESHOLD=55
RSI_SHORT_THRESHOLD=45
MIN_ATR_PCT=0.5
MAX_ATR_PCT=5.0
RR_MULTIPLIER=1.5
SCAN_TIMEFRAME=4h
SIGNAL_COOLDOWN_HOURS=4
```

### 5. Run the bot
```bash
python main.py
```
This starts:
- Scanner scheduler (4H scan every hour at :05)
- FastAPI backend server on `http://localhost:8001`
- Next.js frontend dev server on `http://localhost:3001`

---

## 📁 File Structure

```
D:\Main project\files\
├── main.py                    # Scheduler + orchestration + servers
├── api_server.py              # FastAPI REST API
├── config.py                  # Settings management (.env)
├── scanner.py                 # Binance API + Supertrend + filters
├── signal_tracker.py          # Signal persistence & dedup
├── telegram_bot.py            # Telegram alerts
├── signals.json               # Signal database (live)
├── data/
│   └── signals/               # Live weekly archives by year/month/week
└── frontend/                  # Next.js dashboard
    ├── src/
    │   ├── app/               # Pages (dashboard, signals)
    │   ├── lib/               # API client, utilities
    │   └── components/        # React components, sidebar, layout
    ├── next.config.ts
    └── package.json
```

---

## ⏰ Schedule

- **Every hour at :05** → 4H Supertrend scan (overlap-safe; dedup suppresses repeats within the 4h cooldown)
- **Startup** → one immediate 4H scan

---

## 🖥️ Dashboard Pages

| Page | Route | Description |
|------|-------|-------------|
| **Dashboard** | `/dashboard` | Stat cards (total / 24h / buy / sell), hourly bar chart, buy-vs-sell pie, recent signals |
| **Signals** | `/signals` | Filterable table: symbol, direction, entry, SL, TP, RSI, ATR%, EMA200, Supertrend, source, timestamp |

Both pages auto-refresh every 30 seconds.

---

## 🔧 Customization

Edit `.env` to adjust:
- `TOP_N_COINS` — how many coins per universe (default: 100)
- `MAX_SIGNALS_PER_SCAN` — max alerts per scan (default: 20)
- `SUPERTREND_ATR_PERIOD` / `SUPERTREND_MULTIPLIER` — Supertrend params (default: 12 / 3.5)
- `EMA_FILTER_PERIOD` — trend filter EMA (default: 200)
- `RSI_LONG_THRESHOLD` / `RSI_SHORT_THRESHOLD` — RSI gates (default: 55 / 45)
- `MIN_ATR_PCT` / `MAX_ATR_PCT` — volatility band (default: 0.5 / 5.0)
- `RR_MULTIPLIER` — TP/SL distance in ATR (default: 1.5)
- `SIGNAL_COOLDOWN_HOURS` — dedup window (default: 4)

---

## 📚 Documentation

- **`AI_CONTEXT.md`** — full architecture, data models, API reference (read this first)
- **`CLAUDE.md`** — agent rules and dev workflow
- **`SYSTEM_DOCUMENTATION.md`** — system overview and component reference
- **`DESIGN.md`** — visual design system
- **`PRODUCT.md`** — product positioning

---

## ⚠️ Disclaimer

This bot is for informational purposes only. Not financial advice. Always do your own research and manage your risk.
