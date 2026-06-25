"""
Telegram Bot - Sends formatted signal alerts
Two message types:
1. Cornix-readable signal (plain text, strict format for auto-trading)
2. Human-readable signal (HTML formatted, detailed info)
"""

import requests
import time
import logging
from config import Config

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, config: Config, scanner=None):
        self.config = config
        self.token = config.telegram_token
        self.chat_id = config.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.scanner = scanner  # For futures symbol mapping

    def send_message(self, text: str, parse_mode: str = 'HTML') -> bool:
        for attempt in range(3):
            try:
                url = f"{self.base_url}/sendMessage"
                payload = {
                    'chat_id': self.chat_id,
                    'text': text,
                }
                if parse_mode:
                    payload['parse_mode'] = parse_mode
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                wait_time = 0.5 * (2 ** attempt)
                logger.warning(f"Telegram send attempt {attempt+1} failed: {e}, retrying in {wait_time}s...")
                time.sleep(wait_time)
            except Exception as e:
                logger.error(f"Telegram send error (non-retryable): {e}")
                return False

        logger.error("All Telegram send attempts failed")
        return False

    def send_signal(self, signal: dict) -> bool:
        # Send only Cornix-readable signal (Cornix handles TP/SL outcomes)
        cornix_msg = self._format_cornix_signal(signal)
        return self.send_message(cornix_msg, parse_mode=None)

    def _format_cornix_signal(self, s: dict) -> str:
        """Format signal for Cornix auto-trading bot (strict format, no emojis).

        Cornix rules:
        - Always include full coin pair name (BTC/USDT)
        - Always include 'Buy' or 'Entry' keyword
        - Always include 'Sell' or 'Stop' keywords
        - Use 'Take-Profit' for targets
        - All targets as prices (not percentages)
        - Only one Stop Loss
        - Minimize emojis, unicode, extra text
        - Trailing config must use exact header phrase
        - Stop can't be above entry for LONG or below entry for SHORT
        """
        symbol = s['symbol']
        # Get the correct futures symbol name (handles 1000PEPEUSDT etc.)
        if self.scanner:
            futures_sym = self.scanner.get_futures_symbol(symbol)
        else:
            futures_sym = symbol
        # Convert to Cornix pair format: BTCUSDT -> BTC/USDT
        if futures_sym.endswith('USDT') and '/' not in futures_sym:
            pair = futures_sym.replace('USDT', '/USDT')
        else:
            pair = futures_sym

        direction = s['direction']
        entry = s['entry']
        sl = s['sl']
        tp1 = s['tp1']
        tp2 = s['tp2']
        tp3 = s['tp3']
        tp4 = s['tp4']

        # Cornix auto-detects direction from buy/sell prices
        # But we specify it explicitly for clarity
        if direction == 'LONG':
            signal_type = "Signal Type: Regular (Long)"
        else:
            signal_type = "Signal Type: Regular (Short)"

        leverage = getattr(self.config, 'leverage', 10)
        msg = (
            f"{pair}\n"
            f"\n"
            f"Exchanges: Binance Futures\n"
            f"{signal_type}\n"
            f"Leverage: Cross ({leverage}X)\n"
            f"\n"
            f"Entry:\n"
            f"{entry}\n"
            f"\n"
            f"Take-Profit Targets:\n"
            f"1) {tp1}\n"
            f"2) {tp2}\n"
            f"3) {tp3}\n"
            f"4) {tp4}\n"
            f"\n"
            f"Stop Targets:\n"
            f"1) {sl}\n"
            f"\n"
            f"Trailing Configuration:\n"
            f"Stop: Breakeven - Trigger: Target (1)"
        )
        return msg

    def send_ema_crossover_alert(self, alert: dict) -> bool:
        """Send informational EMA crossover alert (not a trade signal)."""
        symbol = alert['symbol']
        crossover_type = alert['crossover_type']
        price = alert['price']
        ema_fast = alert['ema_fast']
        ema_slow = alert['ema_slow']
        interval = alert.get('interval', '4h')

        if crossover_type == 'GOLDEN_CROSS':
            emoji = '\U0001f7e2'  # Green circle
            direction = 'BULLISH CROSS'
            description = f"{symbol} is crossing above the EMA"
        else:
            emoji = '\U0001f534'  # Red circle
            direction = 'BEARISH CROSS'
            description = f"{symbol} is crossing below the EMA"

        msg = (
            f"<b>{emoji} EMA Crossover Alert</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"<b>{symbol}</b> | {direction}\n"
            f"{description}\n"
            f"\n"
            f"Price: <code>{price}</code>\n"
            f"EMA{alert.get('ema_fast_period', 21)}: <code>{ema_fast}</code>\n"
            f"EMA{alert.get('ema_slow_period', 55)}: <code>{ema_slow}</code>\n"
            f"Timeframe: {interval.upper()}\n"
            f"\n"
            f"<i>This is for informational purposes only. Not a trade signal.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg, parse_mode='HTML')

    def send_startup_message(self):
        msg = """\U0001f680 <b>Crypto Signal Bot Started</b>

Connected to Binance
Scanning top 100 coins
Timeframes: 1H + 4H
Telegram alerts active

Schedule:
- 1H scan: every hour at :05
- 4H trend update: every 4 hours
- 15 min monitor: checks TP/SL

Signal tiers:
\U0001f525 <b>STRONG</b> = 4H + 1H confirmed
\U0001f50a <b>STANDARD</b> = 1H only

Cornix auto-trading format enabled.

Bot is live and watching the market."""
        self.send_message(msg)
