"""
Signal Tracker
- Saves every signal to signals.json
- Monitors price every 5 min to check if TP/SL was hit
- Sends outcome alert to Telegram when a trade closes
"""

import json
import os
import time
import asyncio
import threading
import requests
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SIGNALS_FILE = "signals.json"
DATA_DIR = "data/signals"

class SignalTracker:
    def __init__(self, config, telegram, trader=None):
        self.config = config
        self.telegram = telegram
        self.trader = trader
        self.tp_close_pct = {
            'tp1': getattr(config, 'tp1_close_pct', 0.40),
            'tp2': getattr(config, 'tp2_close_pct', 0.30),
            'tp3': getattr(config, 'tp3_close_pct', 0.20),
            'tp4': getattr(config, 'tp4_close_pct', 0.10),
        }
        self.base_url = config.binance_base_url
        self.signals = self._load()
        self.cooldown = {}  # {symbol: datetime} — skip scanning until this time

        # WebSocket state
        self._price_cache = {}  # {symbol: price} from WebSocket ticks
        self._ws_lock = threading.Lock()
        self._ws_thread = None
        self._ws_running = False
        self._ws_connected = False
        self._last_ws_message = 0  # timestamp of last WebSocket message received
        self._last_tick_log = 0  # timestamp of last aggregated tick log
        self._last_eval_log = 0  # timestamp of last evaluation log

    # ─── WebSocket Price Monitor ──────────────────────────────────────────────

    def start_ws_monitor(self):
        """Start WebSocket price monitoring in a background thread."""
        if self._ws_running:
            logger.warning("WebSocket monitor already running")
            return
        self._ws_running = True
        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._ws_thread.start()
        # Start watchdog thread to detect stuck connections
        self._ws_watchdog_thread = threading.Thread(target=self._ws_watchdog, daemon=True)
        self._ws_watchdog_thread.start()
        logger.info("WebSocket monitor started")

    def stop_ws_monitor(self):
        """Stop the WebSocket monitor."""
        self._ws_running = False
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
        if hasattr(self, '_ws_watchdog_thread') and self._ws_watchdog_thread:
            self._ws_watchdog_thread.join(timeout=5)
        logger.info("WebSocket monitor stopped")

    def _ws_watchdog(self):
        """Watchdog that detects stuck WebSocket connections and forces reconnection."""
        last_heartbeat_log = 0
        while self._ws_running:
            time.sleep(30)
            if not self._ws_running:
                break
            # If connected but no message in 90 seconds, force reconnection
            if self._ws_connected and time.time() - self._last_ws_message > 90:
                logger.warning("WebSocket watchdog: no message in 90s, forcing reconnection")
                self._ws_connected = False
                # Trigger REST fallback to evaluate signals while reconnecting
                try:
                    self.check_open_signals()
                except Exception as e:
                    logger.error(f"REST fallback after WebSocket timeout failed: {e}")

            # Log heartbeat every 5 minutes when connected
            if self._ws_connected and time.time() - last_heartbeat_log > 300:
                cache_size = len(self._price_cache)
                open_count = len([s for s in self.signals if s['status'] in ('OPEN', 'TP1', 'TP2', 'TP3')])
                logger.info(f"WebSocket heartbeat: connected, {cache_size} prices cached, {open_count} open signals")
                last_heartbeat_log = time.time()

    def _ws_loop(self):
        """WebSocket event loop with reconnect and dynamic symbol subscriptions."""
        import websockets

        async def run_forever():
            backoff = 1
            while self._ws_running:
                try:
                    # Subscribe to all USDT ticker streams via combined endpoint
                    # Use 50 common crypto symbols as baseline — Binance limits
                    # combined stream to ~200 streams. We'll get all tickers
                    # via individual subscriptions to active trade symbols.
                    ws = await self._connect_with_symbols()
                    if ws is None:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 30)
                        continue

                    async with ws:
                        self._ws_connected = True
                        self._last_ws_message = time.time()
                        logger.info("WebSocket connected — receiving live prices")
                        backoff = 1  # Reset backoff on success

                        # Periodically re-check which symbols we need
                        last_sub_check = time.time()

                        while self._ws_running and self._ws_connected:
                            try:
                                # Wait for next message with 60s timeout
                                message = await asyncio.wait_for(ws.recv(), timeout=60.0)
                                self._last_ws_message = time.time()
                                self._on_ws_message_text(message)
                            except asyncio.TimeoutError:
                                logger.warning("WebSocket recv timeout — no message in 60s, reconnecting")
                                self._ws_connected = False
                                break
                            except websockets.exceptions.ConnectionClosed:
                                logger.warning("WebSocket connection closed")
                                self._ws_connected = False
                                break

                            # Every 30s, check if we need different subscriptions
                            now = time.time()
                            if now - last_sub_check > 30:
                                last_sub_check = now
                                # Check if any new symbols have been added since last subscription
                                with self._ws_lock:
                                    current_symbols = set(
                                        s['symbol'].lower()
                                        for s in self.signals
                                        if s['status'] in ('OPEN', 'TP1', 'TP2', 'TP3')
                                    )
                                # Get currently subscribed symbols from price cache (normalize to lowercase)
                                with self._ws_lock:
                                    subscribed_symbols = set(
                                        sym.lower() for sym in self._price_cache
                                    )
                                # If there are symbols we should be tracking but aren't, force reconnection
                                new_symbols = current_symbols - subscribed_symbols
                                if new_symbols:
                                    logger.info(f"New symbols detected: {[s.upper() for s in new_symbols]}, forcing WebSocket reconnection")
                                    self._ws_connected = False
                                    break
                                # Also check if any old symbols should be unsubscribed
                                removed_symbols = subscribed_symbols - current_symbols
                                if removed_symbols and subscribed_symbols - removed_symbols:
                                    logger.info(f"Symbols closed, removing from cache: {[s.upper() for s in removed_symbols]}")
                                    with self._ws_lock:
                                        for sym in removed_symbols:
                                            self._price_cache.pop(sym, None)
                except Exception as e:
                    self._ws_connected = False
                    logger.error(f"WebSocket error: {e}")

                if not self._ws_running:
                    break

                logger.info(f"WebSocket reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

        try:
            asyncio.run(run_forever())
        except Exception as e:
            logger.error(f"WS event loop crashed: {e}")
            self._ws_connected = False

    async def _connect_with_symbols(self):
        """Connect to WebSocket with streams for all open signal symbols."""
        import websockets

        with self._ws_lock:
            open_symbols = list(set(
                s['symbol'].lower()
                for s in self.signals
                if s['status'] in ('OPEN', 'TP1', 'TP2', 'TP3')
            ))

        if not open_symbols:
            # No open trades — subscribe to BTCUSDT as a heartbeat
            open_symbols = ['btcusdt']

        streams = '/'.join([f'{s}@ticker' for s in open_symbols[:200]])
        url = f'wss://stream.binance.com:9443/stream?streams={streams}'

        logger.info(f"WebSocket subscribing to {len(open_symbols[:200])} symbols")
        return await websockets.connect(url, ping_interval=60, ping_timeout=10)

    def _on_ws_message_text(self, message):
        """Process a ticker message from combined stream endpoint."""
        try:
            data = json.loads(message)
            # Combined stream wraps each ticker: {"stream": "...", "data": {...}}
            ticker = data.get('data')
            if ticker is None:
                logger.debug("WebSocket message missing 'data' field")
                return

            symbol = ticker.get('s', '')
            price_str = ticker.get('c', '')
            if not symbol or not price_str:
                logger.debug("WebSocket message missing symbol or price")
                return

            price = float(price_str)

            with self._ws_lock:
                self._price_cache[symbol] = price
                # Throttle verbose per-tick logs to once every 5 minutes
                now = time.time()
                if now - self._last_tick_log > 300:
                    cache_size = len(self._price_cache)
                    logger.info(f"WebSocket tick summary: {symbol} = {price} (cached {cache_size} prices)")
                    self._last_tick_log = now

                self._evaluate_open_signals_locked()
        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.error(f"WS message handler error: {e}")

    def _evaluate_open_signals_locked(self):
        """Evaluate all open signals using cached prices. Must be called with _ws_lock held.

        PF4 fix: Collect price snapshots under lock, then release lock before
        running _evaluate() which may trigger HTTP calls (close_partial,
        move_sl_to_breakeven) with 10s timeouts.
        """
        open_signals = [s for s in self.signals if s['status'] in ('OPEN', 'TP1', 'TP2', 'TP3')]
        if not open_signals:
            return

        now = time.time()
        if now - self._last_eval_log > 300:
            logger.info(f"WebSocket evaluating {len(open_signals)} open signal(s) against {len(self._price_cache)} cached prices")
            self._last_eval_log = now

        # Snapshot prices while holding lock
        price_snapshot = {sig['symbol']: self._price_cache.get(sig['symbol']) for sig in open_signals}

        # Release lock before evaluation (which may trigger HTTP calls)
        self._ws_lock.release()
        try:
            changed = False
            for sig in open_signals:
                price = price_snapshot.get(sig['symbol'])
                if price is None:
                    logger.debug(f"  No cached price for {sig['symbol']}, skipping")
                    continue
                logger.debug(f"  Checking {sig['symbol']}: current={price}, entry={sig['entry']}, SL={sig['sl']}, TP1={sig['tp1']}")
                try:
                    self._evaluate(sig, price)
                    if sig['status'] in ('SL', 'TP4', 'BREAKEVEN', 'EXPIRED', 'WIN'):
                        changed = True
                except Exception as e:
                    logger.warning(f"WS eval error for {sig.get('id')}: {e}")

            if changed:
                self._save()
        finally:
            self._ws_lock.acquire()

    def is_ws_connected(self) -> bool:
        """Check if WebSocket is currently active."""
        return self._ws_connected

    # ─── Persistence ─────────────────────────────────────────────────────────

    def _load(self) -> list:
        if os.path.exists(SIGNALS_FILE):
            try:
                with open(SIGNALS_FILE, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Corrupted signals.json: {e}")
                # Backup corrupted file (Bug #34 fix)
                backup_name = f"signals_corrupted_{int(time.time())}.json"
                try:
                    import shutil
                    shutil.copy2(SIGNALS_FILE, backup_name)
                    logger.warning(f"Corrupted file backed up to {backup_name}")
                except Exception as be:
                    logger.error(f"Could not backup corrupted file: {be}")
                return []
            except Exception as e:
                logger.error(f"Error loading signals: {e}")
                return []
        return []

    def _save(self):
        """Save signals to both legacy file and split files"""
        # Save to legacy signals.json (for backward compatibility)
        for attempt in range(3):
            try:
                with open(SIGNALS_FILE, 'w') as f:
                    json.dump(self.signals, f, indent=2)
                break
            except Exception as e:
                logger.error(f"Save attempt {attempt+1} failed: {e}")
                time.sleep(0.5 * attempt)

        # Also save to split files
        self._save_to_split_files()

    def has_open_signal(self, symbol: str) -> bool:
        """Check if a symbol already has an open signal (including partial TP hits)"""
        for sig in self.signals:
            if sig['symbol'] == symbol and sig['status'] in ('OPEN', 'TP1', 'TP2', 'TP3'):
                return True
        return False

    def has_recent_signal(self, symbol: str, minutes: int = 30) -> bool:
        """Check if a signal for this symbol was fired within the last N minutes.

        This prevents duplicate signals when startup scan and scheduled scan
        run close together (e.g., bot starts at :04, scheduler fires at :05).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        for sig in self.signals:
            if sig['symbol'] != symbol:
                continue
            fired_at = sig.get('fired_at')
            if not fired_at:
                continue
            try:
                fired_dt = datetime.fromisoformat(fired_at)
                if fired_dt >= cutoff:
                    return True
            except (ValueError, TypeError):
                continue
        return False

    def _save_to_split_files(self):
        """Save signals to year/month/week split files"""
        from collections import defaultdict

        # Group signals by year/month/week
        grouped = defaultdict(list)

        for sig in self.signals:
            fired_at = sig.get('fired_at')
            if not fired_at:
                continue

            try:
                dt = datetime.fromisoformat(fired_at)
                year = dt.year
                month = dt.month
                week = dt.isocalendar()[1]
                key = f"{year}/{month}/week_{week}"
                grouped[key].append(sig)
            except Exception:
                continue

        # Save each group
        for key, sigs in grouped.items():
            dir_path = os.path.join(DATA_DIR, *key.split('/')[:-1])
            os.makedirs(dir_path, exist_ok=True)

            file_path = os.path.join(DATA_DIR, key + '.json')
            try:
                with open(file_path, 'w') as f:
                    json.dump(sigs, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save split file {key}: {e}")

    # ─── Log New Signal ───────────────────────────────────────────────────────

    def log_signal(self, signal: dict):
        record = {
            'id': f"{signal['symbol']}_{int(time.time() * 1000)}",
            'symbol': signal['symbol'],
            'direction': signal['direction'],
            'strength': signal['strength'],
            'entry': signal['entry'],
            'sl': signal['sl'],
            'sl_original': signal['sl'],  # Keep original SL for reference
            'tp1': signal['tp1'],
            'tp2': signal['tp2'],
            'tp3': signal['tp3'],
            'tp4': signal['tp4'],
            'rr1': signal['rr1'],
            'rr2': signal['rr2'],
            'rr3': signal['rr3'],
            'rr_max': signal['rr_max'],
            'quality_score': signal['quality_score'],
            'fired_at': datetime.now(timezone.utc).isoformat(),
            'status': 'OPEN',       # OPEN | TP1 | TP2 | TP3 | TP4 | SL | BREAKEVEN | EXPIRED
            'outcome': None,        # WIN | LOSS | PARTIAL | BREAKEVEN | EXPIRED
            'closed_at': None,
            'max_rr_hit': None,
            'tp1_hit': False,
            'tp2_hit': False,
            'tp3_hit': False,
            'tp4_hit': False,
            'sl_hit': False,
            'sl_at_breakeven': False,  # Track if SL was moved to breakeven
            'minutes_to_close': None,
            # Track which TPs were hit for incremental closing
            'tps_hit': [],  # List of TP levels hit: ['tp1', 'tp2', 'tp3', 'tp4']
            'position_remaining': 1.00,  # 100% position remaining at start
            # Binance auto-trade metadata (populated when auto-trading is enabled)
            'futures_symbol': signal.get('futures_symbol'),
            'entry_quantity': signal.get('entry_quantity'),
            'binance_entry_order_id': signal.get('binance_entry_order_id'),
            'binance_sl_order_id': signal.get('binance_sl_order_id'),
        }
        self.signals.append(record)
        self._save()
        logger.info(f"Logged signal: {record['id']}")

    # ─── Price Fetch ──────────────────────────────────────────────────────────

    def get_current_price(self, symbol: str) -> float | None:
        try:
            url = f"{self.base_url}/api/v3/ticker/price"
            r = requests.get(url, params={'symbol': symbol}, timeout=5)
            r.raise_for_status()
            return float(r.json()['price'])
        except Exception as e:
            logger.debug(f"Price fetch failed {symbol}: {e}")
            return None

    def get_all_prices(self) -> dict[str, float]:
        """Fetch all ticker prices in a single API call."""
        try:
            url = f"{self.base_url}/api/v3/ticker/price"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            return {item['symbol']: float(item['price']) for item in data}
        except Exception as e:
            logger.error(f"Bulk price fetch failed: {e}")
            return {}

    # ─── Monitor Open Signals ─────────────────────────────────────────────────

    def check_open_signals(self):
        """Called every 5 min as fallback — checks if any open signal hit TP or SL"""
        open_signals = [s for s in self.signals if s['status'] in ('OPEN', 'TP1', 'TP2', 'TP3')]
        if not open_signals:
            return

        # Always run REST poll as a safety check, even if WebSocket is connected
        # This catches any signals that might have been missed by WebSocket
        prices = self.get_all_prices()
        if not prices:
            logger.warning("Failed to fetch prices, skipping monitor cycle")
            return

        with self._ws_lock:
            # Also update the price cache from REST
            self._price_cache.update(prices)
            evaluated = 0
            for sig in open_signals:
                try:
                    price = prices.get(sig['symbol'])
                    if price is None:
                        continue
                    self._evaluate(sig, price)
                    evaluated += 1
                except Exception as e:
                    logger.warning(f"Monitor error for {sig['id']}: {e}")

            self._save()
            if self._ws_connected:
                logger.debug(f"REST safety check: evaluated {evaluated} signals via REST fallback")
            else:
                logger.info(f"Fallback REST monitor: evaluated {evaluated} open signals")

    def is_on_cooldown(self, symbol: str) -> bool:
        """Check if a symbol is still in cooldown period"""
        until = self.cooldown.get(symbol)
        if until is None:
            return False
        if datetime.now(timezone.utc) >= until:
            del self.cooldown[symbol]
            return False
        return True

    def _calculate_blended_rr(self, sig: dict) -> float:
        """Calculate blended RR based on 4-TP incremental closing (40/30/20/10)"""
        tps_hit = sig.get('tps_hit', [])
        if not tps_hit:
            return 0.0

        total_rr = 0.0

        for tp in tps_hit:
            if tp == 'tp1':
                total_rr += sig['rr1'] * 0.40
            elif tp == 'tp2':
                total_rr += sig.get('rr2', 2.0) * 0.30
            elif tp == 'tp3':
                total_rr += sig.get('rr3', 3.0) * 0.20
            elif tp == 'tp4':
                total_rr += sig['rr_max'] * 0.10

        return round(total_rr, 2)

    def _evaluate(self, sig: dict, price: float):
        direction = sig.get('direction')
        if not direction:
            logger.error(f"Signal {sig.get('id')} missing direction")
            return

        # Validate required fields exist
        required = ['tp1', 'tp2', 'tp3', 'tp4', 'sl', 'entry', 'rr1', 'rr_max']
        for field in required:
            if field not in sig or sig[field] is None:
                logger.error(f"Signal {sig.get('id')} missing {field}")
                return

        try:
            fired_at = datetime.fromisoformat(sig['fired_at'])
            # Convert to UTC timezone-aware if naive
            if fired_at.tzinfo is None:
                fired_at = fired_at.replace(tzinfo=timezone.utc)
            # Get current time in UTC
            now = datetime.now(timezone.utc)
            minutes_open = (now - fired_at).total_seconds() / 60
        except (ValueError, TypeError) as e:
            logger.error(f"Signal {sig.get('id')}: Invalid fired_at timestamp: {e}")
            minutes_open = 0

        # ─── Bug Fix: Migrate legacy TP1-hit signals to breakeven format ─────────────
        if sig.get('tp1_hit') and not sig.get('sl_at_breakeven'):
            sig['sl_original'] = sig.get('sl_original', sig['sl'])
            sig['sl'] = sig['entry']
            sig['sl_at_breakeven'] = True
            logger.info(f"{sig['symbol']}: Migrated to breakeven SL format, SL now {sig['sl']}")

        # ─── Check if breakeven was already hit (price crossed below entry after TP1) ──
        if sig.get('tp1_hit') and sig.get('sl_at_breakeven') and not sig.get('sl_hit'):
            if direction == 'LONG' and price <= sig['sl']:
                sig['sl_hit'] = True
                sig['status'] = 'BREAKEVEN'
                sig['outcome'] = 'BREAKEVEN'
                # Blended RR: 50% at TP1 (rr1) + remaining at breakeven (0)
                # If TP2 was also hit: 50% at TP1 + 50% at TP2 = full win, not breakeven
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['closed_at'] = datetime.now(timezone.utc).isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self.cooldown[sig['symbol']] = datetime.now(timezone.utc) + timedelta(hours=4)
                self._save()
                logger.info(f"{sig['symbol']}: Breakeven exit triggered at {price}")
                return
            elif direction == 'SHORT' and price >= sig['sl']:
                sig['sl_hit'] = True
                sig['status'] = 'BREAKEVEN'
                sig['outcome'] = 'BREAKEVEN'
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['closed_at'] = datetime.now(timezone.utc).isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self.cooldown[sig['symbol']] = datetime.now(timezone.utc) + timedelta(hours=4)
                self._save()
                logger.info(f"{sig['symbol']}: Breakeven exit triggered at {price}")
                return

        # Expire signals older than configured expiration (Bug #18 fix)
        if minutes_open > self.config.signal_expiration_minutes:
            sig['status'] = 'EXPIRED'
            sig['outcome'] = 'EXPIRED'
            sig['closed_at'] = datetime.now(timezone.utc).isoformat()
            self._execute_full_close(sig)
            self.cooldown[sig['symbol']] = datetime.now(timezone.utc) + timedelta(hours=4)
            self._save()
            return

        if direction == 'LONG':
            # Check SL first (critical: SL must be checked before TPs)
            if not sig.get('sl_hit') and price <= sig['sl']:
                sig['sl_hit'] = True
                if sig.get('tp1_hit') and sig.get('sl_at_breakeven'):
                    sig['status'] = 'BREAKEVEN'
                    sig['outcome'] = 'BREAKEVEN'
                    sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                else:
                    sig['status'] = 'SL'
                    sig['outcome'] = 'LOSS'
                    sig['max_rr_hit'] = -1
                sig['closed_at'] = datetime.now(timezone.utc).isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self.cooldown[sig['symbol']] = datetime.now(timezone.utc) + timedelta(hours=4)
                self._save()
                return

            # Check TPs (highest first to capture best outcome)
            # 4-TP system: TP1, TP2, TP3, TP4
            if not sig.get('tp4_hit') and price >= sig['tp4']:
                sig['tp4_hit'] = True
                sig['tp3_hit'] = True
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP4'
                sig['outcome'] = 'WIN'
                sig['tps_hit'] = ['tp1', 'tp2', 'tp3', 'tp4']
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['closed_at'] = datetime.now(timezone.utc).isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self._execute_full_close(sig)
                self.cooldown[sig['symbol']] = datetime.now(timezone.utc) + timedelta(hours=4)
                self._save()
                logger.info(f"{sig['symbol']}: TP4 hit at {price}")
                return

            elif not sig.get('tp3_hit') and price >= sig['tp3']:
                tp1_skipped = not sig.get('tp1_hit')
                tp2_skipped = not sig.get('tp2_hit')
                sig['tp3_hit'] = True
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP3'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1', 'tp2', 'tp3']
                sig['position_remaining'] = 0.10
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                if tp1_skipped:
                    self._execute_tp_close(sig, 'tp1')
                if tp2_skipped:
                    self._execute_tp_close(sig, 'tp2')
                self._execute_tp_close(sig, 'tp3')
                if not sig.get('sl_at_breakeven'):
                    sig['sl'] = sig['entry']
                    sig['sl_at_breakeven'] = True
                    self._execute_sl_to_breakeven(sig)
                self._save()
                logger.info(f"{sig['symbol']} TP3 hit (90% closed), watching TP4...")

            elif not sig.get('tp2_hit') and price >= sig['tp2']:
                tp1_skipped = not sig.get('tp1_hit')
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP2'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1', 'tp2']
                sig['position_remaining'] = 0.30
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                if tp1_skipped:
                    self._execute_tp_close(sig, 'tp1')
                self._execute_tp_close(sig, 'tp2')
                if not sig.get('sl_at_breakeven'):
                    sig['sl'] = sig['entry']
                    sig['sl_at_breakeven'] = True
                    self._execute_sl_to_breakeven(sig)
                self._save()
                logger.info(f"{sig['symbol']} TP2 hit (70% closed), watching TP3...")

            elif not sig.get('tp1_hit') and price >= sig['tp1']:
                sig['tp1_hit'] = True
                sig['status'] = 'TP1'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1']
                sig['position_remaining'] = 0.60
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                # Move SL to breakeven after TP1 to protect profits
                sig['sl'] = sig['entry']
                sig['sl_at_breakeven'] = True
                logger.info(f"{sig['symbol']} TP1 hit (40% closed), SL moved to breakeven {sig['entry']}")
                self._execute_tp_close(sig, 'tp1')
                self._execute_sl_to_breakeven(sig)
                self._save()

        else:  # SHORT
            # Check SL first (critical: SL must be checked before TPs)
            if not sig.get('sl_hit') and price >= sig['sl']:
                sig['sl_hit'] = True
                if sig.get('tp1_hit') and sig.get('sl_at_breakeven'):
                    sig['status'] = 'BREAKEVEN'
                    sig['outcome'] = 'BREAKEVEN'
                    sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                else:
                    sig['status'] = 'SL'
                    sig['outcome'] = 'LOSS'
                    sig['max_rr_hit'] = -1
                sig['closed_at'] = datetime.now(timezone.utc).isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self.cooldown[sig['symbol']] = datetime.now(timezone.utc) + timedelta(hours=4)
                self._save()
                logger.info(f"{sig['symbol']}: SL hit at {price}")
                return

            # Check TPs (highest first to capture best outcome)
            if not sig.get('tp4_hit') and price <= sig['tp4']:
                sig['tp4_hit'] = True
                sig['tp3_hit'] = True
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP4'
                sig['outcome'] = 'WIN'
                sig['tps_hit'] = ['tp1', 'tp2', 'tp3', 'tp4']
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['closed_at'] = datetime.now(timezone.utc).isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self._execute_full_close(sig)
                self.cooldown[sig['symbol']] = datetime.now(timezone.utc) + timedelta(hours=4)
                self._save()
                logger.info(f"{sig['symbol']}: TP4 hit at {price}")
                return

            elif not sig.get('tp3_hit') and price <= sig['tp3']:
                tp1_skipped = not sig.get('tp1_hit')
                tp2_skipped = not sig.get('tp2_hit')
                sig['tp3_hit'] = True
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP3'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1', 'tp2', 'tp3']
                sig['position_remaining'] = 0.10
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                if tp1_skipped:
                    self._execute_tp_close(sig, 'tp1')
                if tp2_skipped:
                    self._execute_tp_close(sig, 'tp2')
                self._execute_tp_close(sig, 'tp3')
                if not sig.get('sl_at_breakeven'):
                    sig['sl'] = sig['entry']
                    sig['sl_at_breakeven'] = True
                    self._execute_sl_to_breakeven(sig)
                self._save()
                logger.info(f"{sig['symbol']} TP3 hit (90% closed), watching TP4...")

            elif not sig.get('tp2_hit') and price <= sig['tp2']:
                tp1_skipped = not sig.get('tp1_hit')
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP2'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1', 'tp2']
                sig['position_remaining'] = 0.30
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                if tp1_skipped:
                    self._execute_tp_close(sig, 'tp1')
                self._execute_tp_close(sig, 'tp2')
                if not sig.get('sl_at_breakeven'):
                    sig['sl'] = sig['entry']
                    sig['sl_at_breakeven'] = True
                    self._execute_sl_to_breakeven(sig)
                self._save()
                logger.info(f"{sig['symbol']} TP2 hit (70% closed), watching TP3...")

            elif not sig.get('tp1_hit') and price <= sig['tp1']:
                sig['tp1_hit'] = True
                sig['status'] = 'TP1'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1']
                sig['position_remaining'] = 0.60
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                sig['sl'] = sig['entry']
                sig['sl_at_breakeven'] = True
                logger.info(f"{sig['symbol']} TP1 hit (40% closed), SL moved to breakeven {sig['entry']}")
                self._execute_tp_close(sig, 'tp1')
                self._execute_sl_to_breakeven(sig)
                self._save()

    # ─── Binance Auto-Trade Helpers ──────────────────────────────────────────

    def _execute_tp_close(self, sig: dict, tp_level: str):
        """Close partial position on Binance when a TP level is hit."""
        if self.trader is None or not sig.get('futures_symbol'):
            return

        close_pct = self.tp_close_pct.get(tp_level, 0)
        entry_qty = sig.get('entry_quantity', 0)
        if not entry_qty or close_pct <= 0:
            return

        qty = entry_qty * close_pct
        futures_sym = sig['futures_symbol']
        try:
            qty = self.trader.round_quantity(futures_sym, qty)
            if qty > 0:
                self.trader.close_partial(futures_sym, qty, sig['direction'])
                logger.info(
                    f"Binance: closed {close_pct*100:.0f}% of {futures_sym} "
                    f"at {tp_level.upper()} (qty={qty})"
                )
        except Exception as e:
            logger.error(f"Binance partial close failed for {futures_sym} {tp_level}: {e}")

    def _execute_sl_to_breakeven(self, sig: dict):
        """Move SL to breakeven on Binance after any TP hit."""
        if self.trader is None or not sig.get('futures_symbol'):
            return

        futures_sym = sig['futures_symbol']
        entry_price = sig.get('actual_entry_price', sig['entry'])
        sl_order_id = sig.get('binance_sl_order_id')
        try:
            result = self.trader.move_sl_to_breakeven(
                futures_sym, entry_price, sig['direction'],
                sl_order_id=sl_order_id
            )
            if result:
                sig['binance_sl_order_id'] = result.get('orderId')
            logger.info(f"Binance: SL moved to breakeven for {futures_sym}")
        except Exception as e:
            logger.error(f"Binance SL-to-breakeven failed for {futures_sym}: {e}")

    def _execute_full_close(self, sig: dict):
        """Close any remaining position and cancel orders on Binance."""
        if self.trader is None or not sig.get('futures_symbol'):
            return

        futures_sym = sig['futures_symbol']
        try:
            self.trader.close_position(futures_sym)
            logger.info(f"Binance: full close for {futures_sym}")
        except Exception as e:
            logger.error(f"Binance full close failed for {futures_sym}: {e}")

    # ─── Symbol-Specific Statistics ─────────────────────────────────────────

    def get_symbol_stats(self, symbol: str, lookback: int = 20) -> dict:
        """Get win rate for a symbol over last N closed trades"""
        closed_statuses = ('TP4', 'TP3', 'TP2', 'TP1', 'WIN', 'SL', 'BREAKEVEN', 'EXPIRED')
        closed = [
            s for s in self.signals
            if s['symbol'] == symbol and s['status'] in closed_statuses
        ]
        recent = closed[-lookback:]

        if not recent:
            return {'wins': 0, 'total': 0, 'win_rate': 0.5}

        wins = sum(1 for s in recent if s['status'] in ('TP1', 'TP2', 'TP3', 'TP4', 'WIN'))
        losses = sum(1 for s in recent if s['status'] == 'SL')
        total = wins + losses
        return {
            'wins': wins,
            'total': total,
            'win_rate': wins / total if total > 0 else 0.5
        }

    def should_skip_symbol(self, symbol: str, min_win_rate: float = 0.40) -> bool:
        """Skip symbols with poor recent performance"""
        stats = self.get_symbol_stats(symbol, lookback=20)
        if stats['total'] >= 5 and stats['win_rate'] < min_win_rate:
            logger.warning(
                f"Skipping {symbol}: win rate {stats['win_rate']:.1%} "
                f"below threshold {min_win_rate:.1%} (last {stats['total']} trades)"
            )
            return True
        return False

    # ─── Reconciliation ───────────────────────────────────────────────────────

    def reconcile_positions(self):
        """Log comparison of tracked open signals vs actual Binance positions.

        Call on startup to detect drift after bot restart/crash.
        """
        if self.trader is None:
            logger.info("Reconciliation skipped: no trader configured")
            return

        open_statuses = ('OPEN', 'TP1', 'TP2', 'TP3')
        tracked = [
            s for s in self.signals
            if s.get('status') in open_statuses and s.get('futures_symbol')
        ]
        tracked_symbols = {s['futures_symbol'] for s in tracked}

        try:
            positions = self.trader.get_open_positions()
        except Exception as e:
            logger.error(f"Reconciliation failed: could not fetch positions: {e}")
            return

        binance_symbols = {
            p['symbol'] for p in positions
            if float(p.get('positionAmt', 0)) != 0
        }

        only_tracked = tracked_symbols - binance_symbols
        only_binance = binance_symbols - tracked_symbols

        if only_tracked:
            logger.warning(
                f"RECONCILE: tracked but NOT on Binance: {only_tracked}"
            )
        if only_binance:
            logger.warning(
                f"RECONCILE: on Binance but NOT tracked: {only_binance}"
            )
        if not only_tracked and not only_binance:
            logger.info(
                f"Reconciliation OK: {len(tracked_symbols)} positions match"
            )
