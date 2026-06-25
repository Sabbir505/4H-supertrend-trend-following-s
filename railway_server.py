"""
TradeEdge Railway Server
Combined FastAPI + Bot Scheduler for Railway deployment.
Runs the trading bot scheduler alongside the FastAPI API in a single process.
"""

import os
import sys
import logging
import threading
import time
from pathlib import Path

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ─── Import Bot Components ───────────────────────────────────────────────────
from scanner import CryptoScanner
from signals import SignalEngine
from telegram_bot import TelegramBot
from tracker import SignalTracker
from reporter import PerformanceReporter
from config import Config
from binance_trader import BinanceTrader
from risk_manager import RiskManager

# Optional win predictor import
try:
    from win_predictor import WinPredictor
    WIN_PREDICTOR_AVAILABLE = True
except ImportError:
    WIN_PREDICTOR_AVAILABLE = False

import schedule
from datetime import datetime, timezone

# ─── Import FastAPI ───────────────────────────────────────────────────────────
from api_server import app as fastapi_app
import uvicorn

# ─── Global State ─────────────────────────────────────────────────────────────
config = Config()
scanner = CryptoScanner(config)
signal_engine = SignalEngine()
telegram = TelegramBot(config, scanner)

# Initialize Binance auto-trader (J4 fix: was missing entirely)
trader = None
risk_mgr = None
if config.auto_trading_enabled and config.binance_api_key:
    trader = BinanceTrader(config, scanner)
    risk_mgr = RiskManager(config, trader)
    logger.info("Binance auto-trading ENABLED (TRADE_AMOUNT=$%s, MAX_POS=%s)",
                config.trade_amount_usdt, config.max_open_positions)
else:
    logger.info("Auto-trading disabled — signals sent to Telegram only")

tracker = SignalTracker(config, telegram, trader=trader)
reporter = PerformanceReporter(telegram)

trend_bias = {}
market_regime = 'NEUTRAL'
win_predictor = None

# ─── Bot Functions ────────────────────────────────────────────────────────────

def detect_market_regime_from_btc():
    """Detect global market regime based on BTC 4H trend."""
    try:
        df = scanner.fetch_candles('BTCUSDT', '4h', limit=100)
        if df is None or len(df) < 60:
            logger.warning("Could not fetch BTC 4H data for regime detection")
            return 'NEUTRAL'

        close = df['close']
        ema21 = close.ewm(span=config.regime_ema_fast, adjust=False).mean().iloc[-1]
        ema55 = close.ewm(span=config.regime_ema_slow, adjust=False).mean().iloc[-1]

        engine = SignalEngine()
        rsi_series = engine.rsi(close, config.regime_rsi_period)
        rsi = rsi_series.iloc[-1]

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


def run_4h_scan():
    """Runs every 4H — updates trend bias for all coins + BTC regime."""
    global market_regime
    logger.info("=== 4H TREND SCAN STARTED ===")

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


def run_4h_ema_crossover_scan():
    """Runs every 4H alongside trend scan."""
    logger.info("=== 4H EMA CROSSOVER SCAN STARTED ===")

    symbols = scanner.get_top_100_by_market_cap()
    if not symbols:
        logger.warning("No market cap symbols fetched, skipping EMA crossover scan")
        return

    logger.info(f"Checking EMA crossovers for {len(symbols)} symbols...")

    crossovers = scanner.check_ema_crossovers(
        symbols=symbols,
        interval='4h',
        ema_fast=config.regime_ema_fast,
        ema_slow=config.regime_ema_slow
    )

    if not crossovers:
        logger.info("No EMA crossovers detected this scan.")
        return

    logger.info(f"EMA crossovers detected: {len(crossovers)}")

    for alert in crossovers:
        try:
            alert['ema_fast_period'] = config.regime_ema_fast
            alert['ema_slow_period'] = config.regime_ema_slow
            telegram.send_ema_crossover_alert(alert)
            logger.info(
                f"EMA Alert sent: {alert['symbol']} {alert['crossover_type']} "
                f"(price={alert['price']}, EMA{config.regime_ema_fast}={alert['ema_fast']}, "
                f"EMA{config.regime_ema_slow}={alert['ema_slow']})"
            )
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Failed to send EMA crossover alert: {e}")

    logger.info("=== 4H EMA CROSSOVER SCAN COMPLETE ===")


def _auto_trade_signal(sig: dict):
    """Execute auto-trade on Binance if enabled and risk checks pass.

    J4 fix: This was completely missing from railway_server.py — signals were
    logged and sent to Telegram but never placed on Binance.
    """
    if trader is None or risk_mgr is None:
        return

    allowed, reason = risk_mgr.can_open_trade()
    if not allowed:
        logger.info(f"Auto-trade skipped for {sig['symbol']}: {reason}")
        return

    valid, reason = risk_mgr.validate_signal(sig)
    if not valid:
        logger.warning(f"Signal validation failed for {sig['symbol']}: {reason}")
        return

    try:
        result = trader.open_position(sig)
        sig['futures_symbol'] = result['futures_symbol']
        sig['entry_quantity'] = result['entry_quantity']
        sig['binance_entry_order_id'] = result['entry_order_id']
        sig['binance_sl_order_id'] = result['sl_order_id']
        sig['actual_entry_price'] = result.get('actual_entry_price', sig['entry'])
        logger.info(
            f"Auto-trade opened: {sig['symbol']} "
            f"({result['futures_symbol']}) qty={result['entry_quantity']}"
        )
        telegram.send_message(
            f"<b>Auto-Trade Opened</b>\n"
            f"{sig['symbol']} {sig['direction']}\n"
            f"Qty: {result['entry_quantity']}\n"
            f"Entry: {sig['entry']} | SL: {sig['sl']}",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Auto-trade FAILED for {sig['symbol']}: {e}")
        telegram.send_message(
            f"Auto-trade FAILED for {sig['symbol']}: {e}",
            parse_mode=None
        )


def run_1h_scan():
    """Runs every 1H — checks 1H signals with all filters applied."""
    global market_regime

    logger.info("=== 1H SIGNAL SCAN STARTED ===")

    market_regime = detect_market_regime_from_btc()
    logger.info(f"Market Regime: {market_regime} (BULL=LONGs only, BEAR=SHORTs only, NEUTRAL=skip)")

    symbols = scanner.get_top_100_symbols()
    strong_signals = []
    standard_signals = []

    min_quality_score = getattr(config, 'min_quality_score', 50)
    min_win_probability = getattr(config, 'min_win_probability', 0.55)

    for symbol in symbols:
        try:
            if symbol in config.forex_pairs:
                continue
            if symbol in config.excluded_pairs:
                continue
            if tracker.has_open_signal(symbol):
                continue
            if tracker.has_recent_signal(symbol, minutes=30):
                continue
            if tracker.is_on_cooldown(symbol):
                continue
            if hasattr(tracker, 'should_skip_symbol') and tracker.should_skip_symbol(symbol):
                continue

            df = scanner.fetch_candles(symbol, '1h', limit=100)
            if df is None or len(df) < 60:
                continue

            signal = signal_engine.generate_signal(df, symbol)
            if signal is None:
                time.sleep(0.08)
                continue

            # Regime filter
            if market_regime == 'BULL' and signal['direction'] != 'LONG':
                continue
            if market_regime == 'BEAR' and signal['direction'] != 'SHORT':
                continue
            if market_regime == 'NEUTRAL':
                continue

            # Win probability filter
            predicted_win_prob = None
            if win_predictor is not None:
                try:
                    predicted_win_prob = win_predictor.predict_proba(signal)
                    if predicted_win_prob < min_win_probability:
                        continue
                except Exception as e:
                    logger.warning(f"Win predictor error for {symbol}: {e}")

            signal['regime'] = market_regime
            if predicted_win_prob is not None:
                signal['predicted_win_probability'] = round(predicted_win_prob, 3)

            four_h_bias = trend_bias.get(symbol, 'NEUTRAL')

            if four_h_bias == signal['direction']:
                signal['strength'] = 'STRONG'
                signal['four_h_confirmed'] = True
                strong_signals.append(signal)
            else:
                signal['strength'] = 'STANDARD'
                signal['four_h_confirmed'] = False
                standard_signals.append(signal)

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

    max_per_tier = config.max_signals_per_scan // 2
    for sig in strong_signals[:max_per_tier]:
        try:
            telegram.send_signal(sig)
            _auto_trade_signal(sig)
            tracker.log_signal(sig)
            time.sleep(1)
        except Exception as e:
            logger.error(f"Signal send error: {e}")

    for sig in standard_signals[:max_per_tier]:
        try:
            telegram.send_signal(sig)
            _auto_trade_signal(sig)
            tracker.log_signal(sig)
            time.sleep(1)
        except Exception as e:
            logger.error(f"Signal send error: {e}")

    logger.info("=== 1H SCAN COMPLETE ===")


def run_monitor():
    """Runs every 15 min — checks if open signals hit TP or SL."""
    tracker.check_open_signals()


def run_startup():
    logger.info("Bot starting — running initial scans...")
    tracker.reconcile_positions()
    run_4h_scan()
    run_4h_ema_crossover_scan()
    run_1h_scan()
    logger.info("Startup complete. Scheduler running.")


def _init_scheduler_common() -> bool:
    """Shared initialization for both scheduler modes (A3 fix: deduplicated)."""
    global win_predictor

    if not config.validate():
        logger.error("Config validation failed. Check your environment variables.")
        return False

    if WIN_PREDICTOR_AVAILABLE:
        try:
            win_predictor = WinPredictor()
            logger.info("Win Predictor initialized successfully")
        except Exception as e:
            logger.warning(f"Win Predictor initialization failed: {e}")
            win_predictor = None
    else:
        logger.info("Win Predictor not available")

    logger.info("Filter Configuration:")
    logger.info(f"  - Market Regime Filter: Enabled")
    logger.info(f"  - Symbol Win Rate Filter: {'Enabled' if hasattr(tracker, 'should_skip_symbol') else 'Disabled'}")
    logger.info(f"  - Win Predictor: {'Enabled' if win_predictor else 'Disabled'}")
    logger.info(f"  - Auto-Trading: {'Enabled' if trader else 'Disabled'}")
    if trader:
        logger.info(f"    Trade Amount: ${config.trade_amount_usdt}")
        logger.info(f"    Max Positions: {config.max_open_positions}")

    tracker.start_ws_monitor()
    run_startup()
    telegram.send_startup_message()

    schedule.every().hour.at(":05").do(run_1h_scan)
    for hour in [0, 4, 8, 12, 16, 20]:
        schedule.every().day.at(f"{hour:02d}:02").do(run_4h_scan)
        schedule.every().day.at(f"{hour:02d}:04").do(run_4h_ema_crossover_scan)
    schedule.every(5).minutes.do(run_monitor)
    schedule.every().day.at("00:05").do(reporter.send_daily_report)
    schedule.every().monday.at("00:10").do(reporter.send_weekly_report)

    logger.info("Scheduler active. Watching the market...\n")
    return True


def _scheduler_loop():
    """Run the schedule loop."""
    while True:
        try:
            schedule.run_pending()
            time.sleep(30)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            time.sleep(60)


def bot_scheduler_loop():
    """Background thread: runs the trading bot scheduler."""
    logger.info("=" * 50)
    logger.info("  CRYPTO SIGNAL BOT v2.0 — Starting on Railway")
    logger.info("=" * 50)
    if not _init_scheduler_common():
        return
    _scheduler_loop()


def run_bot_only():
    """Run the bot without FastAPI (for Railway without web server)."""
    logger.info("=" * 50)
    logger.info("  CRYPTO SIGNAL BOT v2.0 — Bot Only Mode")
    logger.info("=" * 50)
    if not _init_scheduler_common():
        return
    _scheduler_loop()


# ─── FastAPI Lifespan Event Handler ───────────────────────────────────────────

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    """Start the bot scheduler when FastAPI starts."""
    logger.info("FastAPI starting up — launching bot scheduler thread...")
    bot_thread = threading.Thread(target=bot_scheduler_loop, daemon=True)
    bot_thread.start()
    logger.info("Bot scheduler thread started successfully")
    yield
    logger.info("FastAPI shutting down...")


# Apply lifespan to the FastAPI app
fastapi_app.router.lifespan_context = lifespan


# ─── Main Entry Point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = os.getenv("PORT")
    if port is None:
        logger.info("No PORT environment variable found — running bot in standalone mode")
        run_bot_only()
    else:
        port = int(port)
        logger.info(f"PORT found — starting TradeEdge server on port {port}")
        uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
