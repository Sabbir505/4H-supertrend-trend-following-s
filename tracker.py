"""
Signal Tracker
- Saves every signal to signals.json
- Monitors price every 5 min to check if TP/SL was hit
- Sends outcome alert to Telegram when a trade closes
"""

import json
import os
import time
import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

SIGNALS_FILE = "signals.json"
DATA_DIR = "data/signals"

# TP Position Closing Percentages (must sum to 100%)
# 4-TP system: Close 40% at TP1, 30% at TP2, 20% at TP3, 10% at TP4
TP_CLOSE_PERCENTAGES = {
    'tp1': 0.40,
    'tp2': 0.30,
    'tp3': 0.20,
    'tp4': 0.10,
}

# Cumulative percentages for RR calculation
TP_RR_WEIGHTS = {
    'tp1': 0.40,                    # 40% at TP1
    'tp2': 0.70,                   # 40% at TP1 + 30% at TP2
    'tp3': 0.90,                   # 40% + 30% + 20% = 90%
    'tp4': 1.00,                   # 100% closed
}

# Position remaining after each TP
TP_REMAINING = {
    'tp1': 0.60,   # After TP1: 60% remaining
    'tp2': 0.30,   # After TP2: 30% remaining
    'tp3': 0.10,   # After TP3: 10% remaining
    'tp4': 0.00,   # After TP4: 0% remaining
}


class SignalTracker:
    def __init__(self, config, telegram):
        self.config = config
        self.telegram = telegram
        self.base_url = config.binance_base_url
        self.signals = self._load()
        self.cooldown = {}  # {symbol: datetime} — skip scanning until this time

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
                    os.rename(SIGNALS_FILE, backup_name)
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
            if sig['symbol'] == symbol and sig['status'] in ('OPEN', 'TP1', 'TP2'):
                return True
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
            'fired_at': datetime.utcnow().isoformat(),
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
        """Called every 5 min — checks if any open signal hit TP or SL"""
        # Monitor OPEN signals and partial TP hits (waiting for next TP)
        open_signals = [s for s in self.signals if s['status'] in ('OPEN', 'TP1', 'TP2', 'TP3')]
        if not open_signals:
            return

        logger.info(f"Monitoring {len(open_signals)} open signals...")

        # Fetch all prices in a single API call
        prices = self.get_all_prices()
        if not prices:
            logger.warning("Failed to fetch prices, skipping monitor cycle")
            return

        for sig in open_signals:
            try:
                price = prices.get(sig['symbol'])
                if price is None:
                    logger.debug(f"Price not found for {sig['symbol']}")
                    continue

                self._evaluate(sig, price)

            except Exception as e:
                logger.warning(f"Monitor error for {sig['id']}: {e}")

        self._save()

    def is_on_cooldown(self, symbol: str) -> bool:
        """Check if a symbol is still in cooldown period"""
        until = self.cooldown.get(symbol)
        if until is None:
            return False
        if datetime.utcnow() >= until:
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
                total_rr += sig.get('rr2', sig['rr1'] * 1.33) * 0.30
            elif tp == 'tp3':
                total_rr += sig.get('rr3', sig['rr1'] * 1.67) * 0.20
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
            # Ensure both datetimes are naive (no timezone) for safe subtraction
            if fired_at.tzinfo is not None:
                fired_at = fired_at.replace(tzinfo=None)
            minutes_open = (datetime.utcnow() - fired_at).total_seconds() / 60
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
                sig['closed_at'] = datetime.utcnow().isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self.cooldown[sig['symbol']] = datetime.utcnow() + timedelta(hours=4)
                self._save()
                logger.info(f"{sig['symbol']}: Breakeven exit triggered at {price}")
                return
            elif direction == 'SHORT' and price >= sig['sl']:
                sig['sl_hit'] = True
                sig['status'] = 'BREAKEVEN'
                sig['outcome'] = 'BREAKEVEN'
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['closed_at'] = datetime.utcnow().isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self.cooldown[sig['symbol']] = datetime.utcnow() + timedelta(hours=4)
                self._save()
                logger.info(f"{sig['symbol']}: Breakeven exit triggered at {price}")
                return

        # Expire signals older than configured expiration (Bug #18 fix)
        if minutes_open > self.config.signal_expiration_minutes:
            sig['status'] = 'EXPIRED'
            sig['outcome'] = 'EXPIRED'
            sig['closed_at'] = datetime.utcnow().isoformat()
            self._send_outcome(sig, price)
            self.cooldown[sig['symbol']] = datetime.utcnow() + timedelta(hours=4)
            self._save()
            return

        if direction == 'LONG':
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
                sig['closed_at'] = datetime.utcnow().isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self.cooldown[sig['symbol']] = datetime.utcnow() + timedelta(hours=4)
                self._save()
                logger.info(f"{sig['symbol']}: TP4 hit at {price}")
                return

            elif not sig.get('tp3_hit') and price >= sig['tp3']:
                sig['tp3_hit'] = True
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP3'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1', 'tp2', 'tp3']
                sig['position_remaining'] = 0.10
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self._save()
                logger.info(f"{sig['symbol']} TP3 hit (20% closed), watching TP4...")

            elif not sig.get('tp2_hit') and price >= sig['tp2']:
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP2'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1', 'tp2']
                sig['position_remaining'] = 0.30
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self._save()
                logger.info(f"{sig['symbol']} TP2 hit (30% closed), watching TP3...")

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
                self._send_outcome(sig, price)
                self._save()

            elif not sig.get('sl_hit') and price <= sig['sl']:
                sig['sl_hit'] = True
                if sig.get('tp1_hit') and sig.get('sl_at_breakeven'):
                    sig['status'] = 'BREAKEVEN'
                    sig['outcome'] = 'BREAKEVEN'
                    sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                else:
                    sig['status'] = 'SL'
                    sig['outcome'] = 'LOSS'
                    sig['max_rr_hit'] = -1
                sig['closed_at'] = datetime.utcnow().isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self.cooldown[sig['symbol']] = datetime.utcnow() + timedelta(hours=4)
                self._save()

        else:  # SHORT
            if not sig.get('tp4_hit') and price <= sig['tp4']:
                sig['tp4_hit'] = True
                sig['tp3_hit'] = True
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP4'
                sig['outcome'] = 'WIN'
                sig['tps_hit'] = ['tp1', 'tp2', 'tp3', 'tp4']
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['closed_at'] = datetime.utcnow().isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self.cooldown[sig['symbol']] = datetime.utcnow() + timedelta(hours=4)
                self._save()
                logger.info(f"{sig['symbol']}: TP4 hit at {price}")
                return

            elif not sig.get('tp3_hit') and price <= sig['tp3']:
                sig['tp3_hit'] = True
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP3'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1', 'tp2', 'tp3']
                sig['position_remaining'] = 0.10
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self._save()
                logger.info(f"{sig['symbol']} TP3 hit (20% closed), watching TP4...")

            elif not sig.get('tp2_hit') and price <= sig['tp2']:
                sig['tp2_hit'] = True
                sig['tp1_hit'] = True
                sig['status'] = 'TP2'
                sig['outcome'] = 'PARTIAL'
                sig['tps_hit'] = ['tp1', 'tp2']
                sig['position_remaining'] = 0.30
                sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self._save()
                logger.info(f"{sig['symbol']} TP2 hit (30% closed), watching TP3...")

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
                self._send_outcome(sig, price)
                self._save()

            elif not sig.get('sl_hit') and price >= sig['sl']:
                sig['sl_hit'] = True
                if sig.get('tp1_hit') and sig.get('sl_at_breakeven'):
                    sig['status'] = 'BREAKEVEN'
                    sig['outcome'] = 'BREAKEVEN'
                    sig['max_rr_hit'] = self._calculate_blended_rr(sig)
                else:
                    sig['status'] = 'SL'
                    sig['outcome'] = 'LOSS'
                    sig['max_rr_hit'] = -1
                sig['closed_at'] = datetime.utcnow().isoformat()
                sig['minutes_to_close'] = round(minutes_open)
                self._send_outcome(sig, price)
                self.cooldown[sig['symbol']] = datetime.utcnow() + timedelta(hours=4)
                self._save()

    # ─── Outcome Alert ────────────────────────────────────────────────────────

    def _send_outcome(self, sig: dict, current_price: float):
        # Outcome alerts disabled - only Cornix signals are sent to Telegram
        pass
