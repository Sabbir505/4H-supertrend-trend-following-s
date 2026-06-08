# 🤖 Crypto Signal Bot

Automated crypto trading signal bot — scans top 100 Binance coins on 1H + 4H timeframes and sends Telegram alerts.

---

## 📡 Signal Types

| Type | Condition | Icon |
|------|-----------|------|
| **STRONG** | 4H trend + 1H trigger both confirm | 🔥 |
| **STANDARD** | 1H signal only | ⚡ |

## 📊 Strategy: Triple Confirmation Trend System

| Indicator | Settings | Role |
|-----------|----------|------|
| EMA 21/55 | - | Trend direction |
| RSI 14 | Long >50, Short <50 | Momentum filter |
| MACD 12/26/9 | Histogram cross | Entry trigger |
| ATR 14 | SL=1.5×, TP1=2×, TP2=4×, TP3=6.5× | Risk sizing |
| Volume MA 20 | > average | Quality filter |

## 🎯 Dynamic TP System

- **TP1** — 1:2 RR → Close 40% of position
- **TP2** — 1:4 RR → Close 30% of position
- **TP3** — 1:6.5 RR → Trail the rest (catch big moves)

---

## ⚙️ Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create Telegram Bot
1. Open Telegram → search **@BotFather**
2. Send `/newbot` → follow instructions → copy the **token**
3. Start a chat with your bot
4. Get your chat ID: visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Send any message to your bot first
   - Look for `"chat":{"id":XXXXXXX}` in the response

### 3. Configure .env
```bash
cp .env.example .env
```
Edit `.env`:
```
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=123456789
```

### 4. Run the bot
```bash
python main.py
```

---

## 📁 File Structure

```
crypto_bot/
├── main.py          # Scheduler + orchestration
├── config.py        # Settings management
├── scanner.py       # Binance API + symbol fetching
├── signals.py       # Indicator calculations + signal logic
├── telegram_bot.py  # Telegram alert formatting + sending
├── requirements.txt
├── .env.example
└── bot.log          # Auto-generated log file
```

---

## ⏰ Schedule

- **Every 1H** → Scans all 100 coins on 1H candles
- **Every 4H** → Updates trend bias on 4H candles (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)

---

## 🔧 Customization

Edit `.env` to adjust:
- `TOP_N_COINS` — how many coins to scan (default: 100)
- `MAX_SIGNALS_PER_SCAN` — max alerts per scan (default: 5)
- `ATR_SL_MULTIPLIER` — stop loss distance (default: 1.5)
- `ATR_TP1/TP2/TP3_MULTIPLIER` — take profit levels

---

## ⚠️ Disclaimer

This bot is for informational purposes only. Not financial advice. Always do your own research and manage your risk.
