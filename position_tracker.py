"""
Virtual position tracker for the 4H Supertrend trend-ride strategy.

Mirrors the backtest engine's exit logic exactly (closed candles only):
  - stop: chandelier trail (initial stop INITIAL_STOP_ATR_MULT xATR at entry, ratcheting by
    close - 3.5xATR_entry), checked against each bar's low/high
  - flip: opposite Supertrend flip on a closed candle -> exit at next open
  - time: 42 bars (7 days) after entry -> exit at that bar's close

Positions survive restarts (data/positions.json); exit checks re-simulate
from the entry bar so downtime never skips an exit.
"""

import json
import os
import logging
from datetime import datetime, timezone

import pandas as pd

logger = logging.getLogger(__name__)

# Paths are env-overridable so the regression suite can sandbox them; the
# production bot never sets these vars and uses the relative defaults.
POSITIONS_FILE = os.getenv("POSITIONS_FILE", "data/positions.json")
TRADES_FILE = os.getenv("TRADES_FILE", "data/trade_history.json")

# round-trip cost assumption from the backtest (fees + slippage)
COST_RT = 0.0016


class PositionTracker:
    def __init__(self, config):
        self.config = config
        self.positions = self._load(POSITIONS_FILE, {})
        self.history = self._load(TRADES_FILE, [])

    @staticmethod
    def _load(path, default):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load {path}: {e}")
                backup = f"{path}.corrupted"
                try:
                    import shutil
                    shutil.copy2(path, backup)
                    logger.warning(f"Backed up corrupted file to {backup}")
                except Exception:
                    pass
        return default

    @staticmethod
    def _save(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)  # atomic

    # ─── entries ────────────────────────────────────────────────────────

    def open_position(self, signal: dict) -> dict | None:
        """Open a virtual position for an entry signal. One position per
        symbol. Returns the position or None if one already exists."""
        symbol = signal['symbol']
        if symbol in self.positions:
            logger.debug(f"Position already open for {symbol}, skipping entry")
            return None

        interval = signal.get('interval', '4h')
        flip_open = pd.Timestamp(signal['flip_candle_open'])
        entry_bar_open = flip_open + pd.Timedelta(interval)

        pos = {
            'symbol': symbol,
            'direction': signal['direction'],
            'entry': signal['price'],
            'atr_entry': signal['atr'],
            'entry_bar_open': entry_bar_open.isoformat(),
            'entry_time': signal['detected_at'],
            'entry_signal_id': signal.get('id'),
            'interval': interval,
            'risk_level': signal.get('risk_level', 'full'),
            'risk_pct': signal.get('risk_pct'),
            'breadth_at_entry': signal.get('breadth'),
            'initial_stop': signal.get('initial_stop'),
            'trail_stop': signal.get('initial_stop'),
            'strategy': signal.get('strategy', 'st_trail_v2'),
            # snapshot the exact config used, so later tuning never
            # contaminates attribution of historical trades
            'params': {
                'st_atr_period': self.config.supertrend_atr_period,
                'st_multiplier': self.config.supertrend_multiplier,
                'trail_atr_mult': self.config.trail_atr_mult,
                'initial_stop_atr_mult': self.config.initial_stop_atr_mult,
                'time_stop_bars': self.config.time_stop_bars,
                'breadth_threshold': self.config.breadth_threshold,
            },
        }
        self.positions[symbol] = pos
        self._save(POSITIONS_FILE, self.positions)
        logger.info("Position opened: %s %s @ %s (risk %s)",
                    symbol, signal['direction'], signal['price'], pos['risk_level'])
        return pos

    # ─── exits ──────────────────────────────────────────────────────────

    def process_exits(self, market_data: dict) -> tuple[list, list]:
        """Check every open position against the newest candle data.
        Re-simulates bar by bar from the entry bar so downtime is safe.
        The replay is causal: it starts from the initial stop and ratchets
        with each bar's close, mirroring the backtest engine — it must never
        inherit a stop level ratcheted through candles the replayed bar
        predates (that logged fake stop-outs). The entry bar itself IS
        checked against the stop (entry fills at the bar's open; the
        backtest engine does the same), and flip exits never fire on the
        entry bar (engine's `i > ei` guard).
        Returns (exit events, orphan alerts) — orphan alerts fire once per
        position whose symbol has been missing from the scan universe for
        more than `orphan_alert_days` days."""
        exits = []
        orphan_alerts = []
        now_utc = pd.Timestamp.now(tz='UTC')
        orphaned = False
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            d = market_data['symbols'].get(symbol)
            if d is None:
                if self._check_orphan(pos, symbol, now_utc):
                    orphan_alerts.append(self._orphan_alert(pos, symbol))
                    orphaned = True
                continue  # symbol no longer in universe; keep position
            pos['last_seen_universe'] = now_utc.isoformat()

            trade = self._evaluate_position(pos, d['df'])
            if trade is None:
                continue

            exits.append(trade)
            self.history.append(trade)
            del self.positions[symbol]
            logger.info("Position closed: %s %s @ %s (%s, %.2fR net)",
                        symbol, pos['direction'], trade['exit'],
                        trade['exit_reason'], trade['net_r'])

        # positions.json is saved on every scan path: exits delete entries,
        # orphan flags and last_seen stamps mutate in place.
        self._save(POSITIONS_FILE, self.positions)
        if exits:
            self._save(TRADES_FILE, self.history)
        return exits, orphan_alerts

    def _evaluate_position(self, pos: dict, df) -> dict | None:
        """Causally replay one position over closed candles (open/high/low/
        close + supertrend_dir, indexed by bar open time). Mutates `pos`:
        anchors the entry to the entry bar's open (once) and persists the
        ratcheted trail_stop / trail_stop_asof when still open. Returns the
        trade record if an exit fired, else None (position stays open).

        The replay starts from the initial stop and ratchets bar by bar so
        each bar is judged against the stop level that existed at that bar —
        never the current trail, which would inject future information.
        """
        direction = 1 if pos['direction'] == 'BUY' else -1
        trail_mult = self.config.trail_atr_mult
        init_mult = self.config.initial_stop_atr_mult
        time_stop = self.config.time_stop_bars

        entry_bar_open = pd.Timestamp(pos['entry_bar_open'])
        idx = df.index.get_indexer([entry_bar_open], method='bfill')[0]
        if idx < 0 or idx >= len(df):
            # entry bar not closed yet -> nothing to check this scan
            return None

        # Anchor the virtual fill to the entry bar's real open. The entry
        # signal only carries the flip candle's close; the engine enters
        # at the next bar's open, so the position must be re-priced the
        # first time the entry bar shows up in fetched data (once ever —
        # the flag rides along in positions.json so restarts can't
        # re-anchor a trade that already has ratcheted stops). Skipped when
        # the entry bar has fallen out of the fetch window: bar 0 would be
        # a much later candle, not the real fill.
        gap = bool(len(df) and df.index[0] > entry_bar_open)
        if not pos.get('entry_anchored') and not gap \
                and float(df['open'].iloc[idx]) > 0:
            anchored = float(df['open'].iloc[idx])
            pos['entry'] = anchored
            pos['initial_stop'] = round(
                anchored - direction
                * max(init_mult * pos['atr_entry'], 0.02 * anchored), 10)
            pos['entry_anchored'] = True

        entry = pos['entry']
        atr_entry = pos['atr_entry']
        init_dist = max(init_mult * atr_entry, 0.02 * entry)
        stop = entry - direction * init_dist

        # Where the causal replay starts. Normally the entry bar: replaying
        # from the initial stop reproduces the exact historical stop path.
        # If the entry bar has fallen out of the fetch window the early
        # bars can't be replayed — seed from the persisted stop instead,
        # but only judge bars after the one it was ratcheted through
        # (trail_stop_asof), which earlier scans already judged causally.
        if gap:
            seed = pos.get('trail_stop')
            if seed:
                stop = max(stop, seed) if direction == 1 else min(stop, seed)
            asof = pos.get('trail_stop_asof')
            if asof:
                a = df.index.get_indexer([pd.Timestamp(asof)], method='bfill')[0]
                start = a + 1 if a >= 0 else len(df) - 1
            else:
                # stop history unknown — judge only the newest candle
                start = len(df) - 1
            if start >= len(df):
                return None  # nothing new to judge this scan
            start = max(start, idx)
        else:
            start = idx

        exit_reason = None
        exit_px = None
        exit_j = None

        for j in range(start, len(df)):
            bar = df.iloc[j]
            # 1) trail/stop hit (conservative priority) — live from the
            #    entry bar, matching the backtest engine. A bar that GAPS
            #    through the stop fills at the bar's open (a real
            #    stop-market order fills on the gap), never at the better
            #    stop price.
            if (direction == 1 and bar['low'] <= stop) or \
               (direction == -1 and bar['high'] >= stop):
                fill = min(bar['open'], stop) if direction == 1 \
                    else max(bar['open'], stop)
                exit_reason, exit_px, exit_j = 'stop', fill, j
                break
            # 2) opposite flip on a closed candle -> exit at next open
            #    (never on the entry bar — engine checks i > ei)
            if j > idx and bar['supertrend_dir'] == -direction:
                if j + 1 < len(df):
                    exit_reason, exit_px, exit_j = 'flip', df['open'].iloc[j + 1], j + 1
                else:
                    exit_reason, exit_px, exit_j = 'flip', bar['close'], j
                break
            # 3) time stop
            if (j - idx) >= time_stop:
                exit_reason, exit_px, exit_j = 'time', bar['close'], j
                break
            # 4) ratchet the trail from this bar's close
            candidate = bar['close'] - direction * trail_mult * atr_entry
            stop = max(stop, candidate) if direction == 1 else min(stop, candidate)

        if exit_reason is None:
            # still open: persist the ratcheted stop and the bar it was
            # ratcheted through (the replay's causality anchor)
            pos['trail_stop'] = round(float(stop), 10)
            pos['trail_stop_asof'] = df.index[-1].isoformat()
            return None

        # Bar-open timestamps, matching the engine's entry/exit_time
        # convention (entry fills at the entry bar's open, a stop/flip/
        # time exit belongs to the bar that triggered it). bars_held is
        # relative to the first replayed bar when the entry bar has aged
        # out of the fetch window (gap case).
        entry_dt = pd.Timestamp(pos['entry_bar_open'])
        exit_dt = df.index[exit_j]
        gross = direction * (float(exit_px) / entry - 1.0)
        sl_dist = init_dist / entry
        net_r = (gross - COST_RT) / sl_dist

        return {
            'symbol': pos['symbol'],
            'direction': pos['direction'],
            'entry': entry,
            'exit': round(float(exit_px), 10),
            'exit_reason': exit_reason,
            'gross_r': round(float(gross / sl_dist), 4),
            'net_r': round(float(net_r), 4),
            'bars_held': int(exit_j - idx),
            'entry_time': entry_dt.isoformat(),
            'exit_time': exit_dt.isoformat(),
            'entry_signal_id': pos.get('entry_signal_id'),
            'risk_level': pos.get('risk_level'),
            'risk_pct': pos.get('risk_pct'),
            'strategy': pos.get('strategy'),
            'params': pos.get('params'),
        }

    def _check_orphan(self, pos: dict, symbol: str, now_utc: pd.Timestamp) -> bool:
        """True if this position has been missing from the universe for more
        than orphan_alert_days and hasn't been flagged yet."""
        if pos.get('orphan_alerted'):
            return False
        last_seen = pos.get('last_seen_universe') or pos.get('entry_time')
        try:
            last_dt = pd.Timestamp(last_seen)
            if last_dt.tzinfo is None:
                last_dt = last_dt.tz_localize('UTC')
            else:
                last_dt = last_dt.tz_convert('UTC')
        except (ValueError, TypeError):
            return False
        days_missing = (now_utc - last_dt).total_seconds() / 86400.0
        if days_missing < self.config.orphan_alert_days:
            return False
        pos['orphan_alerted'] = True
        logger.warning(
            "Orphaned position: %s %s unseen in scan universe for %.1f days "
            "(no exit checks possible until it returns)",
            symbol, pos['direction'], days_missing,
        )
        return True

    @staticmethod
    def _orphan_alert(pos: dict, symbol: str) -> dict:
        return {
            'symbol': symbol,
            'direction': pos['direction'],
            'entry': pos.get('entry'),
            'entry_time': pos.get('entry_time'),
            'last_seen_universe': pos.get('last_seen_universe'),
        }

    def get_open_positions(self) -> list:
        return list(self.positions.values())

    def get_trade_history(self) -> list:
        return self.history
