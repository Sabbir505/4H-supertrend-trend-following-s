"""
Test script to send a Cornix-formatted signal and human-readable signal to the Telegram channel.
"""
import os
import sys
import requests

# Load .env file manually
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_message(text, parse_mode=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    response = requests.post(url, json=payload, timeout=10)
    return response.json()

def test_cornix_signal():
    # Sample signal data (like what the bot would generate)
    # Fetch real-time price and calculate proper signal values
    import requests as req

    symbol = "ENAUSDT"
    r = req.get('https://api.binance.com/api/v3/ticker/price', params={'symbol': symbol}, timeout=10)
    price = float(r.json()['price'])

    # Calculate ATR for proper SL/TP
    r2 = req.get('https://api.binance.com/api/v3/klines', params={'symbol': symbol, 'interval': '1h', 'limit': 20}, timeout=10)
    data = r2.json()
    highs = [float(c[2]) for c in data]
    lows = [float(c[3]) for c in data]
    closes = [float(c[4]) for c in data]
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    atr = sum(trs) / len(trs)

    entry = round(price, 4)
    sl = round(entry - atr, 4)
    tp1 = round(entry + atr * 1.5, 4)
    tp2 = round(entry + atr * 2.0, 4)
    rr1 = round((tp1 - entry) / (entry - sl), 2)
    rr_max = round((tp2 - entry) / (entry - sl), 2)

    signal = {
        "symbol": symbol,
        "direction": "LONG",
        "strength": "STRONG",
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr1": rr1,
        "rr_max": rr_max,
        "rsi": 58,
        "adx": 31,
        "vol_ratio": 2.1,
        "quality_score": 82,
    }

    # 1. Cornix-readable signal (plain text, no emojis)
    s = signal
    # Convert symbol format for Cornix: ETHUSDT -> ETH/USDT
    raw_symbol = s["symbol"]
    if raw_symbol.endswith("USDT") and "/" not in raw_symbol:
        pair = raw_symbol.replace("USDT", "/USDT")
    else:
        pair = raw_symbol

    cornix_msg = (
        f"{pair}\n"
        f"\n"
        f"Exchanges: Binance Futures\n"
        f"Signal Type: Regular ({s['direction'].capitalize()})\n"
        f"Leverage: Cross (10X)\n"
        f"\n"
        f"Entry:\n"
        f"{s['entry']}\n"
        f"\n"
        f"Take-Profit Targets:\n"
        f"1) {s['tp1']}\n"
        f"2) {s['tp2']}\n"
        f"\n"
        f"Stop Targets:\n"
        f"1) {s['sl']}\n"
        f"\n"
        f"Trailing Configuration:\n"
        f"Stop: Breakeven - Trigger: Target (1)"
    )

    print("Sending Cornix signal...")
    print("-" * 40)
    print(cornix_msg)
    print("-" * 40)
    result = send_message(cornix_msg)
    if result.get("ok"):
        print(f"Cornix signal sent! Message ID: {result['result']['message_id']}")
    else:
        print(f"FAILED: {result.get('description', 'Unknown error')}")
        return

    # 2. Human-readable follow-up
    blended_rr = round(s['rr1'] * 0.5 + s['rr_max'] * 0.5, 2)
    human_msg = (
        f"<b>Signal Details</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"🟢 <b>BTCUSDT</b> | LONG\n"
        f"🔥 STRONG (4H + 1H confirmed)\n"
        f"Action: <b>BUY / LONG</b>\n"
        f"\n"
        f"Entry: <code>{s['entry']}</code>\n"
        f"Stop Loss: <code>{s['sl']}</code>\n"
        f"TP1: <code>{s['tp1']}</code> (1:{s['rr1']} RR, close 50%)\n"
        f"TP2: <code>{s['tp2']}</code> (1:{s['rr_max']} RR, close 50%)\n"
        f"\n"
        f"Blended RR: 1:{blended_rr}\n"
        f"SL moves to breakeven after TP1\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"RSI: {s['rsi']} | ADX: {s['adx']}\n"
        f"Vol: {s['vol_ratio']}x | Score: {s['quality_score']}/100\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    print("\nSending human-readable signal...")
    result2 = send_message(human_msg, parse_mode="HTML")
    if result2.get("ok"):
        print(f"Human signal sent! Message ID: {result2['result']['message_id']}")
    else:
        print(f"FAILED: {result2.get('description', 'Unknown error')}")


if __name__ == "__main__":
    test_cornix_signal()
