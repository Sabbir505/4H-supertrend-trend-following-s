"""
Supertrend Trend-Ride Signal Bot
Scans top 100 coins by volume and market cap for 4H Supertrend flip entries
(longs above EMA200, shorts gated by BTC's Supertrend regime), manages virtual
positions with a chandelier ATR trail, flip exits and a 7-day time stop, and
scales position risk by market breadth. Sends alerts to Telegram.
"""

import schedule
import time
import logging
import subprocess
import sys
import os
import json
import threading
import importlib.util
import atexit
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timezone
from scanner import CryptoScanner
from telegram_bot import TelegramBot
from signal_tracker import SignalTracker
from position_tracker import PositionTracker
from executor import FuturesExecutor
from config import Config

LAST_RUN_FILE = Path(__file__).parent / "data" / "scanner_last_run.json"


def _write_last_run(scan_type: str):
    """Write last run timestamp for a scan type to a shared file."""
    try:
        LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if LAST_RUN_FILE.exists():
            try:
                with open(LAST_RUN_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
        data[scan_type] = datetime.now(timezone.utc).isoformat()
        with open(LAST_RUN_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write last run heartbeat: {e}")


def _read_last_run(scan_type: str):
    """Read the last run timestamp for a scan type, or None."""
    try:
        with open(LAST_RUN_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f).get(scan_type)
        return datetime.fromisoformat(raw) if raw else None
    except Exception:
        return None

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
        RotatingFileHandler('bot.log', encoding='utf-8',
                            maxBytes=5_000_000, backupCount=3),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

config = Config()
scanner = CryptoScanner(config)
signal_tracker = SignalTracker(config)
position_tracker = PositionTracker(config)
# The weekly digest lists open positions, so the tracker must be passed
# explicitly — the scanner doesn't own it.
telegram = TelegramBot(config, scanner, position_tracker=position_tracker)
# Live execution (off/dry/live — see EXECUTION_MODE in .env). Methods are
# safe no-ops when the mode is off; never raise into the scan loop.
executor = FuturesExecutor(config, telegram=telegram)

# ─── Web Server Processes ────────────────────────────────────────────────────
_backend_proc = None
_frontend_proc = None
# Child process output must not go to DEVNULL: uvicorn access logs and Next
# errors are the only visibility into these servers (bot.log only has the
# scanner). Files are opened append-only and closed in stop_servers().
_proc_log_handles = []


def _open_proc_log(name: str):
    """Open an append-only log file for a child process's stdout/stderr."""
    path = Path(__file__).parent / name
    handle = open(path, "ab")
    _proc_log_handles.append(handle)
    return handle


def _close_proc_logs():
    while _proc_log_handles:
        try:
            _proc_log_handles.pop().close()
        except Exception:
            pass


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

    logger.info("Starting backend server on http://%s:%s ...",
                config.api_host, config.api_port)
    cmd = [
        sys.executable, "-m", "uvicorn",
        "api_server:app",
        "--host", config.api_host,
        "--port", str(config.api_port),
        # no --reload: this is a long-running service, not a dev session
    ]
    try:
        _backend_proc = subprocess.Popen(
            cmd,
            stdout=_open_proc_log("backend_api.log"),
            stderr=subprocess.STDOUT,
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

    # next.config.ts uses output: "export" + distDir: "dist", so a production
    # build is a STATIC EXPORT in frontend/dist — `next start` cannot serve it.
    # Serve the export with Python's static server (trailingSlash config means
    # directory URLs resolve to index.html). NEXT_PUBLIC_API_URL is inlined at
    # build time (frontend/.env.local points it at the local API); without an
    # export we fall back to the dev server, which inlines the env var below.
    if (frontend_dir / "dist" / "index.html").exists():
        logger.info("Serving frontend static export on http://localhost:3001 ...")
        cmd = [sys.executable, "-m", "http.server", "3001",
               "--bind", "127.0.0.1", "--directory", str(frontend_dir / "dist")]
        env = None
    else:
        logger.info("No static export found — starting frontend dev server "
                    "on http://localhost:3001 ...")
        cmd = [npm_exe, "run", "dev", "--", "--port", "3001"]
        # The frontend is a static export with no server-side proxy, so the
        # browser calls the API origin directly. NEXT_PUBLIC_ vars are inlined
        # by Next at compile time, so it must be in the env before the dev
        # server starts, not just at request time.
        env = os.environ.copy()
        env.setdefault("NEXT_PUBLIC_API_URL", f"http://localhost:{config.api_port}")
    try:
        _frontend_proc = subprocess.Popen(
            cmd,
            stdout=_open_proc_log("frontend_web.log"),
            stderr=subprocess.STDOUT,
            cwd=str(frontend_dir),
            env=env,
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
            if sys.platform == 'win32':
                # terminate() only kills the launcher shell (npm.cmd/uvicorn),
                # orphaning the node/uvicorn children. Kill the whole tree.
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True
                )
            else:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            logger.info("%s stopped.", name.capitalize())
    _backend_proc = None
    _frontend_proc = None
    _close_proc_logs()


def run_scan():
    """Full 4H scan: exits first, then entries — both on closed candles."""
    logger.info("=== 4H SUPERTREND TREND-RIDE SCAN STARTED ===")

    symbols = scanner.get_combined_symbols()
    market_data = scanner.prepare_market_data(symbols, config.scan_timeframe)
    total = len(market_data['symbols'])
    if total == 0:
        logger.warning("No market data prepared — skipping scan")
        return
    logger.info(
        "Scanning %d symbols on %s (ST ATR%d/%s, EMA%d longs, BTC-ST shorts, "
        "trail %sxATR, time stop %d bars) breadth=%.2f risk=%s",
        total, config.scan_timeframe, config.supertrend_atr_period,
        config.supertrend_multiplier, config.ema_filter_period,
        config.trail_atr_mult, config.time_stop_bars,
        market_data['breadth'],
        'full' if market_data['breadth'] >= config.breadth_threshold else 'half',
    )

    # 1) manage open virtual positions (trail / flip / time-stop exits)
    exits, orphan_alerts = position_tracker.process_exits(market_data)
    for trade in exits:
        telegram.send_exit_alert(trade)
        executor.close_position(trade, reason=trade['exit_reason'])
        time.sleep(0.5)
    for orphan in orphan_alerts:
        telegram.send_orphan_alert(orphan)
        time.sleep(0.5)

    # protective stops follow each scan's ratcheted trail
    for pos in position_tracker.get_open_positions():
        executor.sync_stop(pos)

    # 2) new entries on the just-closed candle
    volume_list = scanner.get_top_100_symbols()
    marketcap_list = scanner.get_top_100_by_market_cap()
    signals = scanner.check_entries(market_data, volume_list, marketcap_list)

    if not signals:
        logger.info("No new 4H entries detected.")
        _write_last_run("scan_4h_4h")
        return

    logger.info("Entries detected: %d", len(signals))
    # Deterministic order, best quality first, so the per-scan cap drops
    # the weakest signals rather than whichever sorts first alphabetically.
    _quality_rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    signals.sort(key=lambda s: (_quality_rank.get(s.get("quality", "C"), 2),
                                s['symbol']))
    alerted = 0
    for sig in signals:
        if alerted >= config.max_signals_per_scan:
            logger.info(
                "Reached max signals per scan (%s), stopping",
                config.max_signals_per_scan,
            )
            break
        is_new = signal_tracker.record_signal(sig)
        if not is_new:
            continue

        # Telegram alerts are informational and must fire for every new
        # signal; virtual-position capacity only decides whether the bot
        # also tracks it.
        at_cap = (len(position_tracker.get_open_positions())
                  >= config.max_open_positions)
        vp_note = None
        pos = None
        if at_cap:
            vp_note = (f"not opened — max {config.max_open_positions} "
                       f"positions reached")
        else:
            pos = position_tracker.open_position(sig)
            if pos is None:
                vp_note = "not opened — position already open"
            else:
                executor.open_position(pos)
        sent = telegram.send_entry_alert(sig, vp_note=vp_note)
        if sent:
            # Only mark alerted on success: an unalerted signal is retried
            # on the next scan (SignalTracker dedup ignores unalerted rows).
            signal_tracker.mark_alerted(sig['id'])
        else:
            logger.warning(
                "Telegram send failed for %s %s — will retry next scan",
                sig['symbol'], sig['direction'],
            )
        alerted += 1
        time.sleep(0.5)

        if at_cap:
            logger.warning(
                "Max open positions (%s) reached — %s %s alerted but no "
                "virtual position opened",
                config.max_open_positions, sig['symbol'], sig['direction'],
            )

    logger.info("=== 4H SUPERTREND TREND-RIDE SCAN COMPLETE ===")
    _write_last_run("scan_4h_4h")


def safe_run_scan():
    """Job wrapper: a failing scan must never kill the scheduler loop."""
    try:
        run_scan()
    except Exception as e:
        logger.exception("Scheduled 4H scan failed")
        try:
            telegram.send_error_alert("4H scan", e)
        except Exception:
            logger.exception("Failed to send Telegram error alert")


def run_weekly_digest():
    try:
        telegram.send_weekly_digest(position_tracker.get_trade_history())
    except Exception as e:
        logger.exception("Weekly digest failed")
        try:
            telegram.send_error_alert("weekly digest", e)
        except Exception:
            logger.exception("Failed to send Telegram error alert")


# ─── Watchdog ────────────────────────────────────────────────────────────────
# In-process guard against a hung scheduler: alerts when the 4H heartbeat
# goes stale. (A fully dead process needs an external monitor — see
# /api/health in api_server.py.)

WATCHDOG_CHECK_SECONDS = 600
WATCHDOG_STALE_HOURS = 8      # 2× the 4H scan interval
WATCHDOG_REALERT_HOURS = 4


def _watchdog_loop():
    last_alert = 0.0
    while True:
        try:
            last = _read_last_run("scan_4h_4h")
            if last is not None:
                hours_stale = (
                    datetime.now(timezone.utc) - last
                ).total_seconds() / 3600.0
                due = time.time() - last_alert >= WATCHDOG_REALERT_HOURS * 3600
                if hours_stale >= WATCHDOG_STALE_HOURS and due:
                    telegram.send_watchdog_alert(hours_stale)
                    last_alert = time.time()
        except Exception:
            logger.exception("Watchdog check failed")
        time.sleep(WATCHDOG_CHECK_SECONDS)


def run_startup():
    logger.info("Scanner starting — running initial scan...")
    safe_run_scan()
    logger.info("Startup complete. Scheduler running.")


if __name__ == "__main__":
    if not acquire_lock():
        print("ERROR: Another instance of the bot is already running.")
        print("If the bot crashed, delete the bot.lock file manually.")
        exit(1)

    atexit.register(release_lock)

    logger.info("=" * 50)
    logger.info("  4H SUPERTREND TREND-RIDE SCANNER — Starting")
    logger.info("=" * 50)
    logger.info(f"Process ID: {os.getpid()} - Lock acquired")

    if not config.validate():
        logger.error("Config validation failed. Check your .env file.")
        exit(1)

    logger.info(f"Strategy: ST ATR{config.supertrend_atr_period}/{config.supertrend_multiplier} "
                f"trail {config.trail_atr_mult}x, initial stop {config.initial_stop_atr_mult}x, "
                f"time stop {config.time_stop_bars} bars")
    logger.info(f"Gates: longs EMA{config.ema_filter_period}, shorts BTC-ST; "
                f"breadth risk at {config.breadth_threshold}")
    logger.info(f"Timeframe: {config.scan_timeframe} | Max per scan: {config.max_signals_per_scan}")

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
    _write_last_run("scan_4h_4h")
    # restore protective stops for positions the bot reopened from disk
    executor.reconcile(position_tracker.get_open_positions())

    # 4H scan: fixed UTC times — 4H candles close at 00/04/08/12/16/20 UTC,
    # so scan 5 minutes after each close. Pinned to UTC because `schedule`
    # uses host-local time by default, and `every(4).hours.at(":05")` would
    # anchor the grid to the process start hour instead of candle closes.
    for at in ("00:05", "04:05", "08:05", "12:05", "16:05", "20:05"):
        schedule.every().day.at(at, "UTC").do(safe_run_scan)
    # Weekly performance digest over closed virtual trades
    schedule.every().monday.at("09:00", "UTC").do(run_weekly_digest)

    watchdog = threading.Thread(
        target=_watchdog_loop, name="watchdog", daemon=True
    )
    watchdog.start()

    logger.info("Scheduler active. Watching for signals...\n")
    logger.info("  4H scan: 00:05/04:05/08:05/12:05/16:05/20:05 UTC")
    logger.info("  Weekly digest: Mondays 09:00 UTC")
    logger.info("  Watchdog: alerts if no scan for %dh\n", WATCHDOG_STALE_HOURS)

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        stop_servers()
