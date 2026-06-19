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

        # Strategy settings with validation (Bug #31 fix)
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

        try:
            self.atr_sl_multiplier = float(os.getenv("ATR_SL_MULTIPLIER", "1.0"))
            self.atr_tp1_multiplier = float(os.getenv("ATR_TP1_MULTIPLIER", "1.5"))
            self.atr_tp2_multiplier = float(os.getenv("ATR_TP2_MULTIPLIER", "2.0"))
            self.atr_tp3_multiplier = float(os.getenv("ATR_TP3_MULTIPLIER", "3.0"))
            self.atr_tp4_multiplier = float(os.getenv("ATR_TP4_MULTIPLIER", "4.0"))
        except ValueError:
            logger.warning("Invalid ATR multiplier, using defaults (1.0, 1.5, 2.0, 3.0, 4.0)")
            self.atr_sl_multiplier = 1.0
            self.atr_tp1_multiplier = 1.5
            self.atr_tp2_multiplier = 2.0
            self.atr_tp3_multiplier = 3.0
            self.atr_tp4_multiplier = 4.0

        # TP Position Closing Percentages (must sum to 100%)
        # 4-TP system: Close 40% at TP1, 30% at TP2, 20% at TP3, 10% at TP4
        try:
            self.tp1_close_pct = float(os.getenv("TP1_CLOSE_PERCENT", "40.0")) / 100.0
            self.tp2_close_pct = float(os.getenv("TP2_CLOSE_PERCENT", "30.0")) / 100.0
            self.tp3_close_pct = float(os.getenv("TP3_CLOSE_PERCENT", "20.0")) / 100.0
            self.tp4_close_pct = float(os.getenv("TP4_CLOSE_PERCENT", "10.0")) / 100.0
        except ValueError:
            logger.warning("Invalid TP close percent, using defaults (40/30/20/10)")
            self.tp1_close_pct = 0.40
            self.tp2_close_pct = 0.30
            self.tp3_close_pct = 0.20
            self.tp4_close_pct = 0.10

        # Validate TP percentages sum to 100%
        tp_total = self.tp1_close_pct + self.tp2_close_pct + self.tp3_close_pct + self.tp4_close_pct
        if abs(tp_total - 1.0) > 0.001:
            logger.warning(
                f"TP close percentages sum to {tp_total*100:.1f}% (expected 100%). "
                f"Using defaults."
            )
            self.tp1_close_pct = 0.40
            self.tp2_close_pct = 0.30
            self.tp3_close_pct = 0.20
            self.tp4_close_pct = 0.10

        # Leverage setting for Telegram signals (Bug fix: was hardcoded to 10X)
        try:
            self.leverage = int(os.getenv("LEVERAGE", "10"))
        except ValueError:
            logger.warning("Invalid LEVERAGE, using default 10")
            self.leverage = 10

        # Signal expiration in minutes (Bug #18 fix) - default 7 days = 10080 minutes
        try:
            self.signal_expiration_minutes = int(os.getenv("SIGNAL_EXPIRATION_MINUTES", "10080"))
            if self.signal_expiration_minutes <= 0:
                logger.warning("SIGNAL_EXPIRATION_MINUTES must be positive, using default 10080")
                self.signal_expiration_minutes = 10080
        except ValueError:
            logger.warning("Invalid SIGNAL_EXPIRATION_MINUTES, using default 10080 (7 days)")
            self.signal_expiration_minutes = 10080

        # New trading system improvements (from AI analysis)
        try:
            self.min_quality_score = int(os.getenv("MIN_QUALITY_SCORE", "60"))
            if not (0 <= self.min_quality_score <= 100):
                logger.warning("MIN_QUALITY_SCORE must be 0-100, using default 60")
                self.min_quality_score = 60
        except ValueError:
            logger.warning("Invalid MIN_QUALITY_SCORE, using default 60")
            self.min_quality_score = 60

        try:
            self.trading_start_hour = int(os.getenv("TRADING_START_HOUR", "14"))
            self.trading_end_hour = int(os.getenv("TRADING_END_HOUR", "22"))
            if not (0 <= self.trading_start_hour <= 23):
                self.trading_start_hour = 14
            if not (0 <= self.trading_end_hour <= 23):
                self.trading_end_hour = 22
        except ValueError:
            logger.warning("Invalid trading hours, using defaults 14-22 UTC")
            self.trading_start_hour = 14
            self.trading_end_hour = 22

        try:
            self.symbol_win_rate_min = float(os.getenv("SYMBOL_WIN_RATE_MIN", "0.40"))
            if not (0.0 <= self.symbol_win_rate_min <= 1.0):
                self.symbol_win_rate_min = 0.40
        except ValueError:
            logger.warning("Invalid SYMBOL_WIN_RATE_MIN, using default 0.40")
            self.symbol_win_rate_min = 0.40

        # Adaptive TP levels
        adaptive_tp = os.getenv("ADAPTIVE_TP_ENABLED", "true").lower()
        self.adaptive_tp_enabled = adaptive_tp in ("true", "1", "yes")

        # Market regime detection parameters
        try:
            self.regime_ema_fast = int(os.getenv("REGIME_EMA_FAST", "21"))
        except ValueError:
            logger.warning("Invalid REGIME_EMA_FAST, using default 21")
            self.regime_ema_fast = 21
        try:
            self.regime_ema_slow = int(os.getenv("REGIME_EMA_SLOW", "55"))
        except ValueError:
            logger.warning("Invalid REGIME_EMA_SLOW, using default 55")
            self.regime_ema_slow = 55
        try:
            self.regime_rsi_period = int(os.getenv("REGIME_RSI_PERIOD", "14"))
        except ValueError:
            logger.warning("Invalid REGIME_RSI_PERIOD, using default 14")
            self.regime_rsi_period = 14
        try:
            self.regime_rsi_threshold = float(os.getenv("REGIME_RSI_THRESHOLD", "50"))
        except ValueError:
            logger.warning("Invalid REGIME_RSI_THRESHOLD, using default 50.0")
            self.regime_rsi_threshold = 50.0

        # Pairs excluded from trading (documented reasons)
        # Bug fix: Removed invalid/non-existent pairs (UUSDT, ASTERUSDT)
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
            "USDCUSDT",   # Already in stablecoins but double-check
            "USDTUSDT",   # Self-pair, nonsense
            "DAIUSDT",    # Already in stablecoins
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
            "RLUSDUSDT",  # Ripple USD stablecoin
            "USDGUSDT",   # Stablecoin variants
            "USDYUSDT",
            "MUSDT",      # Stablecoin-like behavior
            "OKBUSDT",    # OKB stablecoin
            "CROUSDT",    # Cronos (low volatility)
            "LEOUSDT",    # LEO token (stablecoin-like)
            "BUIDLUSDT",  # Stablecoin
            "RAINUSDT",   # Low liquidity forex-like
            "FIGR_HELOCUSDT",  # Financial product, not crypto
            "HYPEUSDT",   # Stablecoin-like
            "LABUSDT",    # Stablecoin-like
            "CCUSDT",     # Low liquidity
            "WBTUSDT",    # WhiteBit token (stablecoin-like)
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
