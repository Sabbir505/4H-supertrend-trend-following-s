"""
Crypto Signal Bot - Main Entry Point
Scans top 100 Binance coins on 1H and 4H timeframes
Sends Telegram alerts with dual-tier signals
"""

import schedule
import time
import logging
import subprocess
import sys
import os
import shutil
import importlib.util
import atexit
from datetime import datetime, timezone
from pathlib import Path
from scanner import CryptoScanner
from signals import SignalEngine
from telegram_bot import TelegramBot
from tracker import SignalTracker
from reporter import PerformanceReporter
from config import Config

# Optional win predictor import
try:
    from win_predictor import WinPredictor
    WIN_PREDICTOR_AVAILABLE = True
except ImportError:
    WIN_PREDICTOR_AVAILABLE = False

# Process lock to prevent duplicate instances
LOCK_FILE = "bot.lock"
_lock_file = None


def acquire_lock():
    """Acquire exclusive lock to prevent multiple bot instances (Windows-compatible)."""
    global _lock_file
    try:
        # Check if lock file exists with a running process
        if os.path.exists(LOCK_FILE):
            try:
                with open(LOCK_FILE, 'r') as f:
                    pid = int(f.read().strip())
                # Check if that process is still running
                if sys.platform == 'win32':
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    STILL_ACTIVE = 259
                    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                    if handle:
                        try:
                            exit_code = ctypes.c_ulong()
                            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                                if exit_code.value == STILL_ACTIVE:
                                    # Process is still running
                                    kernel32.CloseHandle(handle)
                                    return False
                        finally:
                            kernel32.CloseHandle(handle)
                else:
                    # Unix: check if process exists
                    os.kill(pid, 0)  # Raises OSError if process doesn't exist
                    return False  # Process exists, lock is held
            except (ValueError, OSError, ProcessLookupError):
                pass  # Process not running, safe to take lock

        # Create/overwrite lock file
        _lock_file = open(LOCK_FILE, 'w')
        _lock_file.write(f"{os.getpid()}\n")
        _lock_file.flush()
        return True
    except Exception as e:
        logger.error(f"Failed to acquire lock: {e}")
        return False


def release_lock():
    """Release the process lock on exit."""
    global _lock_file
    if _lock_file:
        try:
            _lock_file.close()
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except:
            pass

# Fix for Windows UTF-8 encoding issues in logging
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

config = Config()
scanner = CryptoScanner(config)
signal_engine = SignalEngine()
telegram = TelegramBot(config, scanner)
tracker = SignalTracker(config, telegram)
reporter = PerformanceReporter(telegram)

# Shared state: 4H trend bias per symbol + BTC market regime
trend_bias = {}  # { 'BTCUSDT': 'LONG' | 'SHORT' | 'NEUTRAL' }
market_regime = 'NEUTRAL'  # Global regime: 'BULL' | 'BEAR' | 'NEUTRAL'
win_predictor = None  # Optional WinPredictor instance

# ─── Web Server Processes ────────────────────────────────────────────────────
_backend_proc = None
_frontend_proc = None


def _find_executable(name, npm_path=None):
    """Find an executable in PATH, with optional fallback path."""
    exe_path = shutil.which(name)
    if exe_path:
        return exe_path
    if npm_path and os.path.exists(npm_path):
        return npm_path
    return None


def start_backend():
    """Start the FastAPI backend server in a background process."""
    global _backend_proc
    if _backend_proc is not None:
        logger.info("Backend already running (PID: %s)", _backend_proc.pid)
        return _backend_proc

    # Check uvicorn is importable before trying to launch
    if not importlib.util.find_spec("uvicorn"):
        logger.warning("Backend not started: uvicorn package is not installed. Install with: pip install uvicorn")
        return None

    logger.info("Starting backend server on http://localhost:8001 ...")
    cmd = [
        sys.executable, "-m", "uvicorn",
        "api_server:app",
        "--host", "0.0.0.0",
        "--port", "8001",
        "--reload"
    ]
    try:
        _backend_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(Path(__file__).parent)
        )
    except FileNotFoundError:
        logger.error("Backend failed to start: Python executable not found at '%s'", sys.executable)
        return None
    except Exception as e:
        logger.error("Backend failed to start: %s", e)
        return None

    logger.info("Backend started (PID: %s)", _backend_proc.pid)
    time.sleep(2)
    return _backend_proc


def start_frontend():
    """Start the Next.js frontend dev server in a background process."""
    global _frontend_proc
    if _frontend_proc is not None:
        logger.info("Frontend already running (PID: %s)", _frontend_proc.pid)
        return _frontend_proc

    frontend_dir = Path(__file__).parent / "frontend"
    if not (frontend_dir / "package.json").exists():
        logger.warning("Frontend directory not found, skipping frontend start.")
        return None

    npm_exe = _find_executable("npm")
    if not npm_exe:
        logger.warning("Frontend not started: npm is not installed or not in PATH.")
        return None

    logger.info("Starting frontend dev server on http://localhost:3000 ...")
    cmd = [npm_exe, "run", "dev"]
    try:
        _frontend_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(frontend_dir)
        )
    except FileNotFoundError:
        logger.error("Frontend failed to start: npm not found at '%s'", npm_exe)
        return None
    except Exception as e:
        logger.error("Frontend failed to start: %s", e)
        return None

    logger.info("Frontend started (PID: %s)", _frontend_proc.pid)
    time.sleep(5)
    return _frontend_proc


def stop_servers():
    """Gracefully terminate backend and frontend processes."""
    global _backend_proc, _frontend_proc
    for name, proc in [("backend", _backend_proc), ("frontend", _frontend_proc)]:
        if proc is not None:
            logger.info("Stopping %s (PID: %s)...", name, proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            logger.info("%s stopped.", name.capitalize())
    _backend_proc = None
    _frontend_proc = None


def detect_market_regime_from_btc():
    """
    Detect global market regime based on BTC 4H trend
    Returns: 'BULL' | 'BEAR' | 'NEUTRAL'
    """
    try:
        df = scanner.fetch_candles('BTCUSDT', '4h', limit=100)
        if df is None or len(df) < 60:
            logger.warning("Could not fetch BTC 4H data for regime detection")
            return 'NEUTRAL'

        # Calculate indicators using SignalEngine for consistency
        close = df['close']

        # EMAs using config values
        ema21 = close.ewm(span=config.regime_ema_fast, adjust=False).mean().iloc[-1]
        ema55 = close.ewm(span=config.regime_ema_slow, adjust=False).mean().iloc[-1]

        # RSI using SignalEngine (Bug #10 fix - consistent with signals.py)
        engine = SignalEngine()
        rsi_series = engine.rsi(close, config.regime_rsi_period)
        rsi = rsi_series.iloc[-1]

        # Determine regime
        ema_bullish = ema21 > ema55
        ema_bearish = ema21 < ema55
        rsi_bullish = rsi > config.regime_rsi_threshold
        rsi_bearish = rsi < config.regime_rsi_threshold

        if ema_bullish and rsi_bullish:
            regime = 'BULL'
        elif ema_bearish and rsi_bearish:
            regime = 'BEAR'
        else:
            regime = 'NEUTRAL'

        logger.info(f"BTC 4H Regime: {regime} (EMA21={ema21:.0f}, EMA55={ema55:.0f}, RSI={rsi:.1f})")
        return regime

    except Exception as e:
        logger.error(f"Error detecting market regime: {e}")
        return 'NEUTRAL'


def is_good_trading_hour(config) -> bool:
    """
    Check if current UTC hour is within the trading window.
    Returns True if trading is allowed, False otherwise.
    """
    try:
        # Get current UTC hour
        current_hour = datetime.now(timezone.utc).hour

        # Get trading hours from config (default: 8-20 UTC)
        start_hour = getattr(config, 'trading_start_hour', 8)
        end_hour = getattr(config, 'trading_end_hour', 20)

        # Check if within trading window
        if start_hour <= end_hour:
            # Normal range (e.g., 8-20)
            return start_hour <= current_hour < end_hour
        else:
            # Overnight range (e.g., 22-6)
            return current_hour >= start_hour or current_hour < end_hour

    except Exception as e:
        logger.error(f"Error checking trading hour: {e}")
        return True  # Default to allowing trades on error


def get_market_regime(scanner, signal_engine) -> str:
    """
    Fetch BTC 4H candles and use signal_engine.get_trend_bias() to detect regime.
    Returns: 'BULL' | 'BEAR' | 'NEUTRAL'
    """
    try:
        df = scanner.fetch_candles('BTCUSDT', '4h', limit=100)
        if df is None or len(df) < 60:
            logger.warning("Could not fetch BTC 4H data for regime detection")
            return 'NEUTRAL'

        # Use SignalEngine's get_trend_bias for regime detection
        bias = signal_engine.get_trend_bias(df)
        return bias

    except Exception as e:
        logger.error(f"Error getting market regime: {e}")
        return 'NEUTRAL'


def run_4h_scan():
    """Runs every 4H — updates trend bias for all coins + BTC regime"""
    logger.info("=== 4H TREND SCAN STARTED ===")

    # First: Detect BTC market regime
    global market_regime
    market_regime = detect_market_regime_from_btc()

    symbols = scanner.get_top_100_symbols()
    logger.info(f"Scanning {len(symbols)} symbols on 4H...")

    updated = 0
    for symbol in symbols:
        try:
            df = scanner.fetch_candles(symbol, '4h', limit=100)
            if df is None or len(df) < 60:
                continue
            bias = signal_engine.get_trend_bias(df)
            trend_bias[symbol] = bias
            updated += 1
            time.sleep(0.1)
        except Exception as e:
            logger.warning(f"4H scan error for {symbol}: {e}")

    logger.info(f"4H trend bias updated for {updated} symbols")


def run_1h_scan():
    """Runs every 1H — checks 1H signals with all filters applied"""
    global market_regime  # Only market_regime is assigned, win_predictor is read-only

    # ── TRADING HOURS FILTER ─────────────────────────────────────────────
    if not is_good_trading_hour(config):
        logger.info("=== 1H SCAN SKIPPED — Outside trading hours ===")
        return

    logger.info("=== 1H SIGNAL SCAN STARTED ===")

    # ── MARKET REGIME FILTER ─────────────────────────────────────────────
    market_regime = get_market_regime(scanner, signal_engine)
    logger.info(f"Market Regime: {market_regime} (BULL=LONGs only, BEAR=SHORTs only, NEUTRAL=skip)")

    symbols = scanner.get_top_100_symbols()

    strong_signals = []
    standard_signals = []

    # Get filter thresholds from config
    min_quality_score = getattr(config, 'min_quality_score', 50)
    min_win_probability = getattr(config, 'min_win_probability', 0.55)

    for symbol in symbols:
        try:
            # Skip forex/stablecoin pairs (not crypto)
            if symbol in config.forex_pairs:
                logger.debug(f"Skipping {symbol} — forex/stablecoin pair")
                continue

            # Skip excluded pairs (known losers from backtesting)
            if symbol in config.excluded_pairs:
                logger.debug(f"Skipping {symbol} — excluded pair (known loser)")
                continue

            # Skip if symbol already has an OPEN signal (avoid duplicates)
            if tracker.has_open_signal(symbol):
                logger.debug(f"Skipping {symbol} — already has open signal")
                continue

            # Skip if signal was recently fired (prevents startup + scheduled scan duplicates)
            if tracker.has_recent_signal(symbol, minutes=30):
                logger.debug(f"Skipping {symbol} — signal fired within last 30 minutes")
                continue

            # Skip if symbol is on cooldown
            if tracker.is_on_cooldown(symbol):
                logger.debug(f"Skipping {symbol} — on cooldown")
                continue

            # ── SYMBOL WIN RATE FILTER ─────────────────────────────────────
            # Skip if symbol has poor historical performance
            if hasattr(tracker, 'should_skip_symbol') and tracker.should_skip_symbol(symbol):
                logger.debug(f"Skipping {symbol} — poor symbol win rate")
                continue

            df = scanner.fetch_candles(symbol, '1h', limit=100)
            if df is None or len(df) < 60:
                continue

            signal = signal_engine.generate_signal(df, symbol)
            if signal is None:
                time.sleep(0.08)
                continue

            # ── REGIME FILTER: Apply BTC regime ─────────────────────────────
            # Skip signals that don't align with market regime
            if market_regime == 'BULL' and signal['direction'] != 'LONG':
                logger.debug(f"Skipping {symbol} {signal['direction']} — BULL regime only allows LONGs")
                continue
            if market_regime == 'BEAR' and signal['direction'] != 'SHORT':
                logger.debug(f"Skipping {symbol} {signal['direction']} — BEAR regime only allows SHORTs")
                continue
            if market_regime == 'NEUTRAL':
                logger.debug(f"Skipping {symbol} — NEUTRAL regime, no trades allowed")
                continue

            # ── QUALITY SCORE FILTER (DISABLED) ────────────────────────────
            # Temporarily disabled to allow more signals through
            # if signal['quality_score'] < min_quality_score:
            #     logger.debug(f"Skipping {symbol} — quality score {signal['quality_score']} < {min_quality_score}")
            #     continue

            # ── WIN PROBABILITY FILTER ─────────────────────────────────────
            predicted_win_prob = None
            if win_predictor is not None:
                try:
                    predicted_win_prob = win_predictor.predict(signal)
                    if predicted_win_prob < min_win_probability:
                        logger.debug(f"Skipping {symbol} — win probability {predicted_win_prob:.2f} < {min_win_probability}")
                        continue
                except Exception as e:
                    logger.warning(f"Win predictor error for {symbol}: {e}")
                    # Continue without win probability on error

            # ── ADD METADATA TO SIGNAL ─────────────────────────────────────
            signal['regime'] = market_regime
            if predicted_win_prob is not None:
                signal['predicted_win_probability'] = round(predicted_win_prob, 3)

            # Signal passed all filters — proceed with 4H confirmation
            four_h_bias = trend_bias.get(symbol, 'NEUTRAL')

            if four_h_bias == signal['direction']:
                signal['strength'] = 'STRONG'
                signal['four_h_confirmed'] = True
                strong_signals.append(signal)
                logger.info(f"STRONG signal: {symbol} {signal['direction']} (quality={signal['quality_score']}, win_prob={predicted_win_prob})")
            else:
                signal['strength'] = 'STANDARD'
                signal['four_h_confirmed'] = False
                standard_signals.append(signal)
                logger.info(f"STANDARD signal: {symbol} {signal['direction']} (quality={signal['quality_score']}, win_prob={predicted_win_prob})")

            time.sleep(0.08)

        except Exception as e:
            logger.warning(f"1H scan error for {symbol}: {e}")

    strong_signals.sort(key=lambda x: x['quality_score'], reverse=True)
    standard_signals.sort(key=lambda x: x['quality_score'], reverse=True)

    total = len(strong_signals) + len(standard_signals)
    logger.info(f"Signals — Strong: {len(strong_signals)}, Standard: {len(standard_signals)}")

    if total == 0:
        logger.info("No signals this hour.")
        return

    # Send + log strong signals first
    max_per_tier = config.max_signals_per_scan // 2
    for sig in strong_signals[:max_per_tier]:
        try:
            telegram.send_signal(sig)
            tracker.log_signal(sig)
            time.sleep(1)
        except Exception as e:
            logger.error(f"Signal send error: {e}")

    for sig in standard_signals[:max_per_tier]:
        try:
            telegram.send_signal(sig)
            tracker.log_signal(sig)
            time.sleep(1)
        except Exception as e:
            logger.error(f"Signal send error: {e}")

    logger.info("=== 1H SCAN COMPLETE ===")


def run_monitor():
    """Runs every 15 min — checks if open signals hit TP or SL"""
    tracker.check_open_signals()


def run_startup():
    logger.info("Bot starting — running initial scans...")
    run_4h_scan()
    run_1h_scan()
    logger.info("Startup complete. Scheduler running.")


if __name__ == "__main__":
    # Prevent duplicate bot instances
    if not acquire_lock():
        print("ERROR: Another instance of the bot is already running.")
        print("If the bot crashed, delete the bot.lock file manually.")
        exit(1)

    # Register lock release on exit
    atexit.register(release_lock)

    logger.info("=" * 50)
    logger.info("  CRYPTO SIGNAL BOT v2.0 — Starting")
    logger.info("=" * 50)
    logger.info(f"Process ID: {os.getpid()} - Lock acquired")

    if not config.validate():
        logger.error("Config validation failed. Check your .env file.")
        exit(1)

    # ── INITIALIZE WIN PREDICTOR ─────────────────────────────────────────
    # win_predictor is a module-level variable, no global declaration needed
    if WIN_PREDICTOR_AVAILABLE:
        try:
            win_predictor = WinPredictor()
            logger.info("Win Predictor initialized successfully")
        except Exception as e:
            logger.warning(f"Win Predictor initialization failed: {e}")
            win_predictor = None
    else:
        logger.info("Win Predictor not available (win_predictor.py not found)")

    # ── LOG FILTER CONFIGURATION ───────────────────────────────────────
    min_quality = getattr(config, 'min_quality_score', 50)
    min_win_prob = getattr(config, 'min_win_probability', 0.55)
    logger.info(f"Filter Configuration:")
    logger.info(f"  - Min Quality Score: {min_quality}")
    logger.info(f"  - Min Win Probability: {min_win_prob}")
    logger.info(f"  - Trading Hours Filter: Enabled")
    logger.info(f"  - Market Regime Filter: Enabled")
    logger.info(f"  - Symbol Win Rate Filter: {'Enabled' if hasattr(tracker, 'should_skip_symbol') else 'Disabled (method not found)'}")
    logger.info(f"  - Win Predictor: {'Enabled' if win_predictor else 'Disabled'}")

    # Start web servers before trading logic
    backend_started = start_backend()
    frontend_started = start_frontend()
    if backend_started and frontend_started:
        logger.info("Web servers startup complete.")
    else:
        if not backend_started:
            logger.error("Backend server failed to start.")
        if not frontend_started:
            logger.error("Frontend server failed to start.")
        logger.warning("Continuing without web servers. Trading logic will still run.")

    run_startup()
    telegram.send_startup_message()

    # 1H signal scan (delayed to avoid race with 4H scan)
    # Run at minute 05 to give 4H scan time to complete (runs at minute 02)
    schedule.every().hour.at(":05").do(run_1h_scan)

    # 4H trend update
    for hour in [0, 4, 8, 12, 16, 20]:
        schedule.every().day.at(f"{hour:02d}:02").do(run_4h_scan)

    # Price monitor every 5 min (fallback when WebSocket disconnects)
    schedule.every(5).minutes.do(run_monitor)

    # Start real-time WebSocket price monitor
    tracker.start_ws_monitor()

    # Daily report at midnight UTC
    schedule.every().day.at("00:05").do(reporter.send_daily_report)

    # Weekly report every Monday
    schedule.every().monday.at("00:10").do(reporter.send_weekly_report)

    logger.info("Scheduler active. Watching the market...\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        stop_servers()