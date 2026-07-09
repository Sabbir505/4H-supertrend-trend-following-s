"""
Telegram Bot - Sends Supertrend signal alerts
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
        self.scanner = scanner

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

    def send_signal_alert(self, alert: dict) -> bool:
        """Send Supertrend signal alert (informational only)."""
        symbol = alert['symbol']
        direction = alert['direction']
        entry = alert['price']
        sl = alert['sl']
        tp = alert['tp']
        rr = alert['rr']
        ema200 = alert['ema200']
        rsi = alert['rsi']
        atr = alert['atr']
        atr_pct = alert['atr_pct']
        st_val = alert['supertrend_value']
        interval = alert.get('interval', '4h')
        source = alert.get('source', 'unknown')
        detected_at = alert.get('detected_at', '')

        if direction == 'BUY':
            emoji = '\U0001f7e2'  # Green circle
            label = 'BUY SIGNAL'
        else:
            emoji = '\U0001f534'  # Red circle
            label = 'SELL SIGNAL'

        try:
            from datetime import datetime
            dt = datetime.fromisoformat(detected_at)
            display_time = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            display_time = detected_at

        msg = (
            f"<b>{emoji} Supertrend Signal Alert</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"<b>{symbol}</b> | {label}\n"
            f"Supertrend flip on {interval.upper()} (ATR{self.config.supertrend_atr_period}/{self.config.supertrend_multiplier})\n"
            f"\n"
            f"<b>Trade Plan</b>\n"
            f"Entry: <code>{entry}</code>\n"
            f"Stop Loss: <code>{sl}</code>\n"
            f"Take Profit: <code>{tp}</code>\n"
            f"R:R: <code>{rr}</code>\n"
            f"\n"
            f"<b>Filters</b>\n"
            f"EMA{self.config.ema_filter_period}: <code>{ema200}</code>\n"
            f"RSI{self.config.rsi_period}: <code>{rsi}</code>\n"
            f"ATR: <code>{atr}</code> ({atr_pct}%)\n"
            f"Supertrend: <code>{st_val}</code>\n"
            f"Source: {source}\n"
            f"\n"
            f"Detected: {display_time}\n"
            f"\n"
            f"<i>This is for informational purposes only. Not a trade signal.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg, parse_mode='HTML')

    def send_startup_message(self):
        msg = """\U0001f680 <b>Supertrend Scanner Started</b>

Connected to Binance
Scanning top 100 by volume + top 100 by volatility
Timeframe: 4H
Strategy: Supertrend 12/3.5 + 200 EMA + RSI(14)
Telegram alerts active

Schedule:
- 4H scan: every hour at :05

Alerts are informational only — not trade signals."""
        self.send_message(msg)
