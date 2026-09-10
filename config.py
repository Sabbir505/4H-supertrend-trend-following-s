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

        # ─── 4H Supertrend trend-riding strategy (backtest round-4 final) ───
        # Entry: ST flip; longs close > EMA200; shorts only when BTC ST is bearish.
        # Management: 3.5xATR chandelier trail (initial stop 3xATR in prod), exit on
        # opposite flip or after TIME_STOP_BARS bars; breadth-scaled risk.
        try:
            self.supertrend_atr_period = int(os.getenv("SUPERTREND_ATR_PERIOD", "10"))
        except ValueError:
            logger.warning("Invalid SUPERTREND_ATR_PERIOD, using default 10")
            self.supertrend_atr_period = 10

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
            self.trail_atr_mult = float(os.getenv("TRAIL_ATR_MULT", "3.5"))
        except ValueError:
            logger.warning("Invalid TRAIL_ATR_MULT, using default 3.5")
            self.trail_atr_mult = 3.5

        try:
            self.initial_stop_atr_mult = float(os.getenv("INITIAL_STOP_ATR_MULT", "3.0"))
        except ValueError:
            logger.warning("Invalid INITIAL_STOP_ATR_MULT, using default 3.0")
            self.initial_stop_atr_mult = 3.0

        try:
            self.atr_min_pct = float(os.getenv("ATR_MIN_PCT", "0.4"))
        except ValueError:
            logger.warning("Invalid ATR_MIN_PCT, using default 0.4")
            self.atr_min_pct = 0.4

        try:
            self.atr_max_pct = float(os.getenv("ATR_MAX_PCT", "3.0"))
        except ValueError:
            logger.warning("Invalid ATR_MAX_PCT, using default 3.0")
            self.atr_max_pct = 3.0

        try:
            self.time_stop_bars = int(os.getenv("TIME_STOP_BARS", "42"))
        except ValueError:
            logger.warning("Invalid TIME_STOP_BARS, using default 42")
            self.time_stop_bars = 42

        try:
            self.breadth_threshold = float(os.getenv("BREADTH_THRESHOLD", "0.3"))
        except ValueError:
            logger.warning("Invalid BREADTH_THRESHOLD, using default 0.3")
            self.breadth_threshold = 0.3

        # ─── Round-5b entry filters (3-year OOS validation, REPORT §6f) ──
        # Skip entries whose flip candle opens on Sunday (weekend
        # liquidity; Sunday entries averaged -0.04R to -0.15R depending
        # on window, longs -0.10R over 3 years).
        self.skip_sunday = self._get_bool("SKIP_SUNDAY_ENTRIES", True)
        # Skip ALL entries while market breadth (fraction of the universe
        # above its EMA200) is below this floor. 0 disables the gate.
        self.breadth_gate = self._get_float("BREADTH_GATE", 0.15)
        # Quality tiers to actually trade (REPORT §6f study): A = confirmed
        # longs, B = flush/high-breadth shorts, C = weak sets, D = BTC
        # shorts. Comma-separated; "all" disables the filter. Default A,B —
        # the 3-year A+B variant beat the full config (+243% vs +195%, DD
        # 35.6% vs 41.9%, bear fold -1.7% vs -13.6%).
        raw_qf = os.getenv("QUALITY_FILTER", "A,B").strip()
        if raw_qf.lower() == "all":
            self.quality_tiers = {"A", "B", "C", "D"}
        else:
            tiers = {s.strip().upper() for s in raw_qf.split(",") if s.strip()}
            invalid = tiers - {"A", "B", "C", "D"}
            if invalid:
                logger.warning("Invalid QUALITY_FILTER tiers %s — using A,B",
                               ", ".join(sorted(invalid)))
                tiers = {"A", "B"}
            if not tiers:
                tiers = {"A", "B"}
            self.quality_tiers = tiers

        # ─── Live execution (Binance USDT-M futures) ─────────────────────
        # EXECUTION_MODE:
        #   off  — signal-only bot (default; no orders, no keys needed)
        #   dry  — log every order the executor *would* send (no network)
        #   live — place real orders (requires API keys with futures perms)
        # Leverage is hard-capped at 5x and margin type is always ISOLATED,
        # per the round-5c small-account study (REPORT §6f).
        self.execution_mode = os.getenv("EXECUTION_MODE", "off").strip().lower()
        if self.execution_mode not in ("off", "dry", "live"):
            logger.warning("Invalid EXECUTION_MODE %r — using 'off'",
                           self.execution_mode)
            self.execution_mode = "off"
        self.binance_api_key = os.getenv("BINANCE_API_KEY", "").strip()
        self.binance_api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
        if self.execution_mode == "live" and not (
                self.binance_api_key and self.binance_api_secret):
            logger.warning("EXECUTION_MODE=live but API keys missing — "
                           "falling back to 'dry'")
            self.execution_mode = "dry"
        self.futures_base_url = os.getenv(
            "FUTURES_BASE_URL", "https://fapi.binance.com").rstrip("/")
        # Margin committed per position in USDT; notional = margin × leverage
        # ($1 × 5x = $5 notional = the exchange minimum on most pairs).
        self.execution_margin_usdt = self._get_float("EXECUTION_MARGIN_USDT", 1.0)
        self.execution_leverage = min(5, max(1, self._get_int(
            "EXECUTION_LEVERAGE", 5)))
        self.execution_max_positions = self._get_int("EXECUTION_MAX_POSITIONS", 15)

        try:
            self.candle_fetch_limit = int(os.getenv("CANDLE_FETCH_LIMIT", "600"))
        except ValueError:
            logger.warning("Invalid CANDLE_FETCH_LIMIT, using default 600")
            self.candle_fetch_limit = 600

        try:
            self.signal_cooldown_hours = int(
                os.getenv("SIGNAL_COOLDOWN_HOURS", "4")
            )
        except ValueError:
            logger.warning("Invalid SIGNAL_COOLDOWN_HOURS, using default 4")
            self.signal_cooldown_hours = 4

        # ─── Portfolio risk caps ─────────────────────────────────────────
        # The backtest risks a fixed fraction of equity per trade (full risk
        # when breadth >= threshold, half below it). These mirror that.
        self.max_open_positions = self._get_int("MAX_OPEN_POSITIONS", 10)
        self.risk_pct_full = self._get_float("RISK_PCT_FULL", 1.0)
        self.risk_pct_half = self._get_float("RISK_PCT_HALF", 0.5)

        # ─── Operations ──────────────────────────────────────────────────
        # Alert when an open position's symbol stops appearing in the scan
        # universe (delisted / fell out of top-100) for this many days.
        self.orphan_alert_days = self._get_int("ORPHAN_ALERT_DAYS", 3)
        # Parallel Binance kline fetches during a scan (weight-safe pool size).
        self.fetch_workers = self._get_int("FETCH_WORKERS", 8)
        self.api_host = os.getenv("API_HOST", "0.0.0.0")
        self.api_port = self._get_int("API_PORT", 8001)
        # Minimum closed candles a symbol must have to be scanned. Kept at
        # the fetch window (600 ≈ EMA200 × 3) so indicator warmup never
        # leaks into signals; coins listed more recently than this are
        # excluded from entries AND breadth, by design.
        self.min_history_bars = self._get_int("MIN_HISTORY_BARS",
                                              self.candle_fetch_limit)

        # Warn about env keys nothing reads anymore (retired strategies /
        # old names). Catches typos like MIN_ATR_PCT vs ATR_MIN_PCT that
        # would otherwise silently change live behavior.
        dead_keys = [
            k for k in (
                "MIN_ATR_PCT", "MAX_ATR_PCT", "RSI_PERIOD",
                "RSI_LONG_THRESHOLD", "RSI_SHORT_THRESHOLD", "RR_MULTIPLIER",
                "EMA_FAST", "EMA_SLOW", "EMA_TREND", "HTF_EMA",
                "EMA_ATR_PERIOD",
            )
            if os.getenv(k) is not None
        ]
        if dead_keys:
            logger.warning(
                "Ignoring unrecognized/deprecated .env keys: %s — the live "
                "strategy no longer reads these. Check config.py for the "
                "current names.", ", ".join(dead_keys))

        # Pairs excluded from scanning (documented reasons). EXCLUDED_PAIRS in
        # .env adds more (comma-separated) without touching code.
        self.excluded_pairs = {
            # Stable / pegged / non-crypto
            "EURUSDT", "GBPUSDT", "JPYUSDT", "AUDUSDT", "CADUSDT", "CHFUSDT",
            "NZDUSDT", "TRYBUSD", "USDRUB", "USDZAR",
            "PAXGUSDT", "XAUTUSDT",              # gold tokens
            "USD1USDT", "USDSUSDT", "USDEUSDT", "USYCUSDT", "USDGUSDT",
            "USDYUSDT", "RLUSDUSDT", "BUIDLUSDT",
            # (stablecoins themselves are filtered via stable_coins below)
            # Exchange tokens / low-float listings with unreliable signals
            "MUSDT", "OKBUSDT", "CROUSDT", "LEOUSDT",
            "HYPEUSDT", "WBTUSDT",
            "RAINUSDT", "FIGR_HELOCUSDT", "LABUSDT", "CCUSDT",
            # Curated exclusions from live results
            "TRXUSDT",     # Low volatility, poor performance
            "PORTALUSDT",  # Low liquidity, unreliable signals
            "SOLUSDT",     # High volatility, erratic moves, too many false signals
        }
        extra = os.getenv("EXCLUDED_PAIRS", "")
        self.excluded_pairs |= {
            s.strip().upper() for s in extra.split(",") if s.strip()
        }

        # Stablecoins to exclude
        self.stable_coins = {
            "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "USDD",
            "FDUSD", "PYUSD", "GUSD", "FRAX", "LUSD", "SUSD", "EURC",
            "EURS", "EURT", "XAUT", "PAXG"
        }

    @staticmethod
    def _get_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _get_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except ValueError:
            logger.warning(f"Invalid {name}, using default {default}")
            return default

    @staticmethod
    def _get_float(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, str(default)))
        except ValueError:
            logger.warning(f"Invalid {name}, using default {default}")
            return default

    def validate(self) -> bool:
        if not self.telegram_token:
            print("ERROR: Missing TELEGRAM_BOT_TOKEN in .env")
            return False
        if not self.telegram_chat_id:
            print("ERROR: Missing TELEGRAM_CHAT_ID in .env")
            return False
        print("Config validated successfully")
        return True
