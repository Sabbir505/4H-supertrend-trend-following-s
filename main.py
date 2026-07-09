"""
Supertrend Signal Scanner Bot
Scans top 100 coins by volume and volatility for Supertrend (ATR 12, mult 3.5)
flips on 4H timeframe, filtered by 200 EMA, RSI(14), and ATR% volatility range.
Sends alerts to Telegram.
"""

import schedule
import time
import logging
import subprocess
import sys
import os
import importlib.util
import atexit
from pathlib import Path
from scanner import CryptoScanner
from telegram_bot import TelegramBot
from signal_tracker import SignalTracker
from config import Config

# Process lock to prevent duplicate instances
LOCK_FILE = "bot.lock"
_lock_file = None


def acquire_lock():
    """Acquire exclusive lock to prevent multiple bot instances (Windows-compatible)."""
    global _lock_file
    try:
        if os.path.exists(LOCK_FILE):
            try:
                with open(LOCK_FILE, 'r') as f:
                    pid = int(f.read().strip())
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
                                    kernel32.CloseHandle(handle)
                                    return False
                        finally:
                            kernel32.CloseHandle(handle)
                else:
                    os.kill(pid, 0)
                    return False
            except (ValueError, OSError, ProcessLookupError):
                pass

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
        except Exception:
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
telegram = TelegramBot(config, scanner)
tracker = SignalTracker(config)

# ─── Web Server Processes ────────────────────────────────────────────────────
_backend_proc = None
_frontend_proc = None


def _find_executable(name, npm_path=None):
    """Find an executable in PATH, with optional fallback path."""
    import shutil
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

    if not importlib.util.find_spec("uvicorn"):
        logger.warning("Backend not started: uvicorn package is not installed.")
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

    logger.info("Starting frontend dev server on http://localhost:3001 ...")
    cmd = [npm_exe, "run", "dev", "--", "--port", "3001"]
    try:
        _frontend_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(frontend_dir)
        )
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


def run_supertrend_scan(interval: str):
    """Run Supertrend signal scan for a given interval (default 4h)."""
    logger.info("=== %s SUPERTREND SIGNAL SCAN STARTED ===", interval.upper())

    symbols = scanner.get_combined_symbols()
    logger.info(
        f"Scanning {len(symbols)} symbols on {interval} "
        f"(ST ATR{config.supertrend_atr_period}/{config.supertrend_multiplier}, "
        f"EMA{config.ema_filter_period}, RSI{config.rsi_period})..."
    )

    signals = scanner.check_supertrend_signals(
        symbols=symbols,
        interval=interval,
        atr_period=config.supertrend_atr_period,
        multiplier=config.supertrend_multiplier,
        ema_period=config.ema_filter_period,
        rsi_period=config.rsi_period,
        rsi_long=config.rsi_long_threshold,
        rsi_short=config.rsi_short_threshold,
        min_atr_pct=config.min_atr_pct,
        max_atr_pct=config.max_atr_pct,
        rr_mult=config.rr_multiplier,
    )

    if not signals:
        logger.info("No Supertrend signals detected for %s.", interval)
        return

    logger.info(f"Signals detected on {interval}: {len(signals)}")

    alerted_count = 0
    for sig in signals:
        if alerted_count >= config.max_signals_per_scan:
            logger.info(
                f"Reached max signals per scan ({config.max_signals_per_scan}), "
                f"stopping {interval} scan"
            )
            break

        is_new = tracker.record_signal(sig)
        if is_new:
            telegram.send_signal_alert(sig)
            tracker.mark_alerted(sig['id'])
            alerted_count += 1
            time.sleep(0.5)

    logger.info("=== %s SUPERTREND SIGNAL SCAN COMPLETE ===", interval.upper())


def run_startup():
    logger.info("Scanner starting — running initial scan...")
    run_supertrend_scan(config.scan_timeframe)
    logger.info("Startup complete. Scheduler running.")


if __name__ == "__main__":
    if not acquire_lock():
        print("ERROR: Another instance of the bot is already running.")
        print("If the bot crashed, delete the bot.lock file manually.")
        exit(1)

    atexit.register(release_lock)

    logger.info("=" * 50)
    logger.info("  EMA CROSSOVER SCANNER — Starting")
    logger.info("=" * 50)
    logger.info(f"Process ID: {os.getpid()} - Lock acquired")

    if not config.validate():
        logger.error("Config validation failed. Check your .env file.")
        exit(1)

    logger.info(f"Supertrend Config: ATR{config.supertrend_atr_period} x {config.supertrend_multiplier}")
    logger.info(f"Filters: EMA{config.ema_filter_period}, RSI{config.rsi_period} (L>{config.rsi_long_threshold}/S<{config.rsi_short_threshold})")
    logger.info(f"ATR% range: {config.min_atr_pct}-{config.max_atr_pct}% | RR: {config.rr_multiplier}")
    logger.info(f"Timeframe: {config.scan_timeframe} | Cooldown: {config.signal_cooldown_hours}h")
    logger.info(f"Max per scan: {config.max_signals_per_scan}")

    backend_started = start_backend()
    frontend_started = start_frontend()
    if backend_started and frontend_started:
        logger.info("Web servers startup complete.")
    else:
        if not backend_started:
            logger.error("Backend server failed to start.")
        if not frontend_started:
            logger.error("Frontend server failed to start.")
        logger.warning("Continuing without web servers. Scanner will still run.")

    run_startup()
    telegram.send_startup_message()

    # Schedule: 4H scan every hour at :05 (overlap-safe; dedup suppresses repeats within cooldown)
    schedule.every().hour.at(":05").do(run_supertrend_scan, config.scan_timeframe)

    logger.info("Scheduler active. Watching for Supertrend signals...\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        stop_servers()
