"""
Signal Tracker
- Persists detected Supertrend signals to signals.json
- Deduplicates alerts within a cooldown window
- Archives signals to data/signals/ by year/month/week
"""

import json
import os
import time
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

# Paths are env-overridable so the regression suite can sandbox them.
SIGNALS_FILE = os.getenv("SIGNALS_FILE", "signals.json")
DATA_DIR = os.getenv("SIGNALS_DATA_DIR", "data/signals")


class SignalTracker:
    def __init__(self, config):
        self.config = config
        self.signals = self._load()

    def _load(self) -> list:
        if os.path.exists(SIGNALS_FILE):
            try:
                with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Corrupted signals.json: {e}")
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
        """Save signals atomically (tmp file + replace, so a crash mid-write
        can never leave a truncated signals.json), then split files."""
        tmp = SIGNALS_FILE + '.tmp'
        saved = False
        for attempt in range(3):
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(self.signals, f, indent=2)
                os.replace(tmp, SIGNALS_FILE)
                saved = True
                break
            except Exception as e:
                logger.error(f"Save attempt {attempt+1} failed: {e}")
                time.sleep(0.5 * attempt)

        if not saved:
            logger.critical(f"All 3 save attempts failed for signals.json — {len(self.signals)} signals at risk")
            raise IOError(f"Failed to save signals after 3 attempts. Signals may be lost on restart.")

        self._save_to_split_files()

    def _save_to_split_files(self):
        """Save signals to year/month/week split files."""
        grouped = defaultdict(list)

        for sig in self.signals:
            detected_at = sig.get('detected_at')
            if not detected_at:
                continue
            try:
                dt = datetime.fromisoformat(detected_at)
                year = dt.year
                month = dt.month
                week = dt.isocalendar()[1]
                key = f"{year}/{month}/week_{week}"
                grouped[key].append(sig)
            except Exception:
                continue

        for key, sigs in grouped.items():
            dir_path = os.path.join(DATA_DIR, *key.split('/')[:-1])
            os.makedirs(dir_path, exist_ok=True)
            file_path = os.path.join(DATA_DIR, key + '.json')
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(sigs, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save split file {key}: {e}")

    def _parse_utc(self, iso_str: str):
        """Parse an ISO datetime string to a timezone-aware UTC datetime."""
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _is_duplicate(self, signal: dict) -> bool:
        """Check if a signal is a duplicate of an already-recorded one.

        Signals carrying a 'candle_time' (the flip candle's close time) are
        deduplicated by event: the same flip candle must never alert twice.

        Other signals are deduplicated by (symbol, direction) within the
        cooldown window.
        """
        symbol = signal['symbol']
        direction = signal['direction']

        candle_time = signal.get('candle_time')
        if candle_time:
            for sig in self.signals:
                if (
                    sig.get('symbol') == symbol
                    and sig.get('direction') == direction
                    and sig.get('candle_time') == candle_time
                ):
                    # A recorded but never-alerted signal means the Telegram
                    # send failed — allow the retry instead of suppressing it.
                    if sig.get('alerted', False):
                        logger.debug(
                            f"Dup: {symbol} {direction} — candle "
                            f"{candle_time} already alerted"
                        )
                        return True
                    logger.info(
                        f"Retry: {symbol} {direction} candle {candle_time} "
                        f"recorded but never alerted"
                    )
                    return False

        cooldown_hours = self.config.signal_cooldown_hours

        detected_at = self._parse_utc(signal.get('detected_at', ''))
        if detected_at is None:
            return False

        cutoff = detected_at - timedelta(hours=cooldown_hours)

        for sig in self.signals:
            if sig.get('symbol') != symbol:
                continue
            if sig.get('direction') != direction:
                continue
            existing_dt = self._parse_utc(sig.get('detected_at', ''))
            if existing_dt is not None and existing_dt >= cutoff:
                return True

        return False

    def record_signal(self, signal: dict) -> bool:
        """
        Record a signal. Returns True if it's new and should be alerted,
        False if it's a duplicate within the cooldown window.
        """
        # Generate deterministic ID
        try:
            detected_at = datetime.fromisoformat(signal['detected_at'])
            ts_ms = int(detected_at.timestamp() * 1000)
        except (ValueError, TypeError):
            ts_ms = int(time.time() * 1000)

        signal['id'] = f"{signal['symbol']}_{signal['interval']}_{ts_ms}"

        if self._is_duplicate(signal):
            logger.debug(
                f"Dup: {signal['symbol']} {signal['direction']} "
                f"({signal['interval']}) — within cooldown"
            )
            return False

        if 'alerted' not in signal:
            signal['alerted'] = False

        # Retry path: a recorded-but-unalerted row for the same flip candle
        # means the previous Telegram send failed. Replace it in place
        # (keeping its id, so positions referencing entry_signal_id stay
        # resolvable) instead of appending a duplicate row.
        candle_time = signal.get('candle_time')
        if candle_time:
            for i, sig in enumerate(self.signals):
                if (sig.get('symbol') == signal['symbol']
                        and sig.get('direction') == signal['direction']
                        and sig.get('candle_time') == candle_time
                        and not sig.get('alerted', False)):
                    signal['id'] = sig.get('id', signal['id'])
                    self.signals[i] = signal
                    self._save()
                    logger.info(
                        f"Retry recorded: {signal['symbol']} "
                        f"{signal['direction']} ({signal['interval']}) "
                        f"@ {signal['price']}"
                    )
                    return True

        self.signals.append(signal)
        self._save()
        logger.info(
            f"New signal: {signal['symbol']} {signal['direction']} "
            f"({signal['interval']}) @ {signal['price']}"
        )
        return True

    def mark_alerted(self, signal_id: str):
        """Mark a signal as having been alerted via Telegram."""
        for sig in self.signals:
            if sig.get('id') == signal_id:
                sig['alerted'] = True
        self._save()

    def get_recent(self, hours: int = 24) -> list:
        """Get signals from the last N hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = []
        for sig in self.signals:
            dt = self._parse_utc(sig.get('detected_at', ''))
            if dt is not None and dt >= cutoff:
                recent.append(sig)
        return recent

    def get_all(self) -> list:
        """Get all recorded signals."""
        return self.signals
