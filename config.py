"""
Configuration Management
Loads settings from .env file
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    def __init__(self):
        # Telegram
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        # Binance (no API key needed for public market data)
        self.binance_base_url = "https://api.binance.com"

        # CoinGecko (optional API key for higher rate limits)
        self.coingecko_api_key = os.getenv("COINGECKO_API_KEY", "")

        # Scanner settings
        try:
            self.top_n_coins = int(os.getenv("TOP_N_COINS", "100"))
        except ValueError:
            logger.warning("Invalid TOP_N_COINS, using default 100")
            self.top_n_coins = 100

        try:
            self.max_signals_per_scan = int(os.getenv("MAX_SIGNALS_PER_SCAN", "20"))
        except ValueError:
            logger.warning("Invalid MAX_SIGNALS_PER_SCAN, using default 20")
            self.max_signals_per_scan = 20

        self.scan_timeframe = os.getenv("SCAN_TIMEFRAME", "4h")

        # ─── Supertrend strategy parameters ───
        try:
            self.supertrend_atr_period = int(os.getenv("SUPERTREND_ATR_PERIOD", "12"))
        except ValueError:
            logger.warning("Invalid SUPERTREND_ATR_PERIOD, using default 12")
            self.supertrend_atr_period = 12

        try:
            self.supertrend_multiplier = float(os.getenv("SUPERTREND_MULTIPLIER", "3.5"))
        except ValueError:
            logger.warning("Invalid SUPERTREND_MULTIPLIER, using default 3.5")
            self.supertrend_multiplier = 3.5

        try:
            self.ema_filter_period = int(os.getenv("EMA_FILTER_PERIOD", "200"))
        except ValueError:
            logger.warning("Invalid EMA_FILTER_PERIOD, using default 200")
            self.ema_filter_period = 200

        try:
            self.rsi_period = int(os.getenv("RSI_PERIOD", "14"))
        except ValueError:
            logger.warning("Invalid RSI_PERIOD, using default 14")
            self.rsi_period = 14

        try:
            self.rsi_long_threshold = float(os.getenv("RSI_LONG_THRESHOLD", "55"))
        except ValueError:
            logger.warning("Invalid RSI_LONG_THRESHOLD, using default 55")
            self.rsi_long_threshold = 55

        try:
            self.rsi_short_threshold = float(os.getenv("RSI_SHORT_THRESHOLD", "45"))
        except ValueError:
            logger.warning("Invalid RSI_SHORT_THRESHOLD, using default 45")
            self.rsi_short_threshold = 45

        try:
            self.min_atr_pct = float(os.getenv("MIN_ATR_PCT", "0.5"))
        except ValueError:
            logger.warning("Invalid MIN_ATR_PCT, using default 0.5")
            self.min_atr_pct = 0.5

        try:
            self.max_atr_pct = float(os.getenv("MAX_ATR_PCT", "5.0"))
        except ValueError:
            logger.warning("Invalid MAX_ATR_PCT, using default 5.0")
            self.max_atr_pct = 5.0

        try:
            self.rr_multiplier = float(os.getenv("RR_MULTIPLIER", "1.5"))
        except ValueError:
            logger.warning("Invalid RR_MULTIPLIER, using default 1.5")
            self.rr_multiplier = 1.5

        try:
            self.signal_cooldown_hours = int(
                os.getenv("SIGNAL_COOLDOWN_HOURS", "4")
            )
        except ValueError:
            logger.warning("Invalid SIGNAL_COOLDOWN_HOURS, using default 4")
            self.signal_cooldown_hours = 4

        # Pairs excluded from trading (documented reasons)
        self.excluded_pairs = {
            "TRXUSDT",    # Low volatility, poor performance
            "PORTALUSDT", # Low liquidity, unreliable signals
            "SOLUSDT"     # High volatility, erratic moves, too many false signals
        }

        # Stablecoins to exclude
        self.stable_coins = {
            "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "USDD",
            "FDUSD", "PYUSD", "GUSD", "FRAX", "LUSD", "SUSD", "EURC",
            "EURS", "EURT", "XAUT", "PAXG"
        }

        # Forex/Pegged pairs to exclude (not crypto, stable/pegged assets)
        self.forex_pairs = {
            "EURUSDT",    # Euro-USD pegged pair
            "GBPUSDT",    # British Pound pegged
            "JPYUSDT",    # Japanese Yen pegged
            "AUDUSDT",    # Australian Dollar pegged
            "CADUSDT",    # Canadian Dollar pegged
            "CHFUSDT",    # Swiss Franc pegged
            "NZDUSDT",    # New Zealand Dollar pegged
            "TRYBUSD",    # Turkish Lira pegged
            "USDRUB",     # Russian Ruble pegged
            "USDZAR",     # South African Rand pegged
            "PAXGUSDT",   # Gold token (commodity, not crypto)
            "XAUTUSDT",   # Gold token (commodity, not crypto)
            "EURTUSDT",   # Euro stablecoin
            "EURSUSDT",   # Euro stablecoin
            "EURCUSDT",   # Euro stablecoin
            "USD1USDT",   # Stablecoin variants
            "USDSUSDT",
            "USDEUSDT",
            "USYCUSDT",
            "USDCUSDT",
            "USDTUSDT",
            "DAIUSDT",
            "FDUSDUSDT",
            "TUSDUSDT",
            "BUSDUSDT",
            "USDPUSDT",
            "USDDUSDT",
            "PYUSDUSDT",
            "GUSDUSDT",
            "FRAXUSDT",
            "LUSDUSDT",
            "SUSDUSDT",
            "RLUSDUSDT",
            "USDGUSDT",
            "USDYUSDT",
            "MUSDT",
            "OKBUSDT",
            "CROUSDT",
            "LEOUSDT",
            "BUIDLUSDT",
            "RAINUSDT",
            "FIGR_HELOCUSDT",
            "HYPEUSDT",
            "LABUSDT",
            "CCUSDT",
            "WBTUSDT",
        }

    def validate(self) -> bool:
        if not self.telegram_token:
            print("ERROR: Missing TELEGRAM_BOT_TOKEN in .env")
            return False
        if not self.telegram_chat_id:
            print("ERROR: Missing TELEGRAM_CHAT_ID in .env")
            return False
        print("Config validated successfully")
        return True
