"""
Backtest: Trading Hours Filter Impact Analysis
Runs the same strategy twice (with and without trading_hours filter)
on top 50 coins, last 3 months, using live Binance data.

Usage:
    python backtest_trading_hours.py
"""

import os
import sys
import io
import argparse
import requests
import pandas as pd
import numpy as np
import time
import json
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from signals import SignalEngine
from config import Config

logger = logging.getLogger(__name__)
BINANCE_URL = "https://api.binance.com"
cfg = Config()


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class Trade:
    symbol: str
    direction: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    tp4: float
    sl_distance: float
    entry_time: str
    sl_original: float = 0.0
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None
    rr_achieved: Optional[float] = None
    bars_held: Optional[int] = None
    quality_score: float = 0.0
    adx_at_entry: float = 0.0
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    tp4_hit: bool = False
    sl_at_breakeven: bool = False
    max_rr_hit: float = 0.0


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    period_months: int
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    win_rate: float = 0.0
    avg_rr: float = 0.0
    max_rr: float = 0.0
    total_rr: float = 0.0
    max_drawdown: float = 0.0
    avg_bars_held: float = 0.0
    long_trades: int = 0
    short_trades: int = 0
    long_win_rate: float = 0.0
    short_win_rate: float = 0.0
    tp1_rate: float = 0.0
    tp2_rate: float = 0.0
    tp3_rate: float = 0.0
    tp4_rate: float = 0.0
    breakeven_rate: float = 0.0
    any_tp_rate: float = 0.0
    trades: list = field(default_factory=list)


# ─── Data Fetching ────────────────────────────────────────────────────────────

def fetch_historical(symbol: str, interval: str, months: int) -> pd.DataFrame:
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=months * 30)).timestamp() * 1000)

    all_candles = []
    current_start = start_ms

    while current_start < end_ms:
        try:
            r = requests.get(
                f"{BINANCE_URL}/api/v3/klines",
                params={'symbol': symbol, 'interval': interval,
                        'startTime': current_start, 'endTime': end_ms, 'limit': 1000},
                timeout=15
            )
            r.raise_for_status()
            data = r.json()
            if not data:
                break
            all_candles.extend(data)
            last_ts = data[-1][0]
            if last_ts >= end_ms or len(data) < 1000:
                break
            current_start = last_ts + 1
            time.sleep(0.1)
        except Exception as e:
            logger.warning(f"Fetch error {symbol}: {e}")
            break

    if not all_candles:
        return None

    df = pd.DataFrame(all_candles, columns=[
        'timestamp','open','high','low','close','volume',
        'close_time','quote_volume','trades',
        'taker_buy_base','taker_buy_quote','ignore'
    ])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    for col in ['open','high','low','close','volume']:
        df[col] = df[col].astype(float)
    df.set_index('timestamp', inplace=True)
    return df[['open','high','low','close','volume']]


def get_top_symbols(n: int = 50) -> list:
    print(f"📡 Fetching top {n} coins by volume...")
    try:
        r = requests.get(f"{BINANCE_URL}/api/v3/ticker/24hr", timeout=15)
        r.raise_for_status()
        stables = {"USDT","USDC","BUSD","DAI","TUSD","USDP","USDD",
                   "FDUSD","PYUSD","GUSD","FRAX","USD1"}
        excluded = cfg.excluded_pairs
        forex = cfg.forex_pairs
        pairs = []
        for t in r.json():
            sym = t['symbol']
            if not sym.endswith('USDT'): continue
            if sym in excluded: continue
            if sym in forex: continue
            base = sym.replace('USDT','')
            if base in stables: continue
            try: pairs.append((sym, float(t['quoteVolume'])))
            except Exception: continue
        pairs.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in pairs[:n]]
    except Exception as e:
        print(f"⚠️  Could not fetch symbols: {e}")
        return ["BTCUSDT","ETHUSDT","BNBUSDT","XRPUSDT","NEARUSDT"]


# ─── Core Backtester ────────────────────────────────────────────────────────────

class Backtester:
    def __init__(self):
        self.engine = SignalEngine()
        self.cfg = Config()

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df['close']
        d = df.copy()
        d['ema21'] = self.engine.ema(close, 21)
        d['ema55'] = self.engine.ema(close, 55)
        d['rsi'] = self.engine.rsi(close, 14)
        _, _, d['macd_hist'] = self.engine.macd(close)
        d['atr'] = self.engine.atr(df, 14)
        d['vol_ma'] = self.engine.volume_ma(df['volume'], 20)
        d['adx'] = self.engine.adx(df, 14)
        return d.dropna()

    def detect_signal(self, row) -> Optional[str]:
        if row['adx'] < 25:
            return None
        if row['volume'] <= row['vol_ma'] * 1.2:
            return None

        ema_bull = row['ema21'] > row['ema55']
        ema_bear = row['ema21'] < row['ema55']

        macd_bullish = row['macd_hist'] > 0
        macd_bearish = row['macd_hist'] < 0

        hist_min = row['atr'] * 0.1
        if macd_bullish and row['macd_hist'] < hist_min:
            macd_bullish = False
        if macd_bearish and abs(row['macd_hist']) < hist_min:
            macd_bearish = False

        if ema_bull and 50 < row['rsi'] < 75 and macd_bullish:
            return 'LONG'
        if ema_bear and 25 < row['rsi'] < 50 and macd_bearish:
            return 'SHORT'
        return None

    def calculate_quality_score(self, row, direction: str, vol_ratio: float) -> float:
        score = 0
        if direction == 'LONG':
            rsi_optimal = 62.5
            rsi_dist = abs(row['rsi'] - rsi_optimal)
            score += max(0, 25 - rsi_dist * 1.5)
        else:
            rsi_optimal = 37.5
            rsi_dist = abs(row['rsi'] - rsi_optimal)
            score += max(0, 25 - rsi_dist * 1.5)

        hist_strength = min(abs(row['macd_hist']) / row['atr'] * 10, 30)
        score += hist_strength
        score += min(vol_ratio * 15, 30)

        if 25 <= row['adx'] <= 35:
            score += 20
        elif 35 < row['adx'] <= 45:
            score += 10

        return round(score, 1)

    def simulate_trade(self, signal_row, future_df: pd.DataFrame,
                       direction: str, symbol: str, quality_score: float = 0.0) -> Trade:
        entry = signal_row['close']
        atr = signal_row['atr']
        sl_dist = atr * 1.0

        cfg = self.cfg
        if direction == 'LONG':
            sl = entry - sl_dist
            tp1 = entry + sl_dist * cfg.atr_tp1_multiplier
            tp2 = entry + sl_dist * cfg.atr_tp2_multiplier
            tp3 = entry + sl_dist * cfg.atr_tp3_multiplier
            tp4 = entry + sl_dist * cfg.atr_tp4_multiplier
        else:
            sl = entry + sl_dist
            tp1 = entry - sl_dist * cfg.atr_tp1_multiplier
            tp2 = entry - sl_dist * cfg.atr_tp2_multiplier
            tp3 = entry - sl_dist * cfg.atr_tp3_multiplier
            tp4 = entry - sl_dist * cfg.atr_tp4_multiplier

        trade = Trade(
            symbol=symbol, direction=direction,
            entry=entry, sl=sl, sl_original=sl, tp1=tp1, tp2=tp2, tp3=tp3, tp4=tp4,
            sl_distance=sl_dist, entry_time=str(signal_row.name),
            adx_at_entry=round(signal_row['adx'], 1),
            quality_score=quality_score
        )

        tps_hit = []
        current_sl = sl

        for i, (ts, candle) in enumerate(future_df.iterrows()):
            high = candle['high']
            low = candle['low']

            if direction == 'LONG':
                if low <= current_sl:
                    trade.outcome = 'BREAKEVEN' if tps_hit else 'SL'
                    trade.exit_price = current_sl
                    trade.rr_achieved = self._calculate_incremental_rr(tps_hit, entry, sl, tp1, tp2, tp3, tp4)
                    trade.bars_held = i + 1
                    break

                if high >= tp4 and 'tp4' not in tps_hit:
                    tps_hit = ['tp1', 'tp2', 'tp3', 'tp4']
                    trade.outcome = 'TP4'
                    trade.exit_price = tp4
                    trade.rr_achieved = self._calculate_incremental_rr(tps_hit, entry, sl, tp1, tp2, tp3, tp4)
                    trade.bars_held = i + 1
                    trade.tp1_hit = True
                    trade.tp2_hit = True
                    trade.tp3_hit = True
                    break

                if high >= tp3 and 'tp3' not in tps_hit:
                    tps_hit = ['tp1', 'tp2', 'tp3']
                    trade.tp3_hit = True
                    trade.sl_at_breakeven = True
                    current_sl = entry

                if high >= tp2 and 'tp2' not in tps_hit:
                    tps_hit = ['tp1', 'tp2']
                    trade.tp2_hit = True
                    trade.sl_at_breakeven = True
                    current_sl = entry

                if high >= tp1 and 'tp1' not in tps_hit:
                    tps_hit.append('tp1')
                    trade.tp1_hit = True
                    trade.sl_at_breakeven = True
                    current_sl = entry

            else:  # SHORT
                if high >= current_sl:
                    trade.outcome = 'BREAKEVEN' if tps_hit else 'SL'
                    trade.exit_price = current_sl
                    trade.rr_achieved = self._calculate_incremental_rr(tps_hit, entry, sl, tp1, tp2, tp3, tp4)
                    trade.bars_held = i + 1
                    break

                if low <= tp4 and 'tp4' not in tps_hit:
                    tps_hit = ['tp1', 'tp2', 'tp3', 'tp4']
                    trade.outcome = 'TP4'
                    trade.exit_price = tp4
                    trade.rr_achieved = self._calculate_incremental_rr(tps_hit, entry, sl, tp1, tp2, tp3, tp4)
                    trade.bars_held = i + 1
                    trade.tp1_hit = True
                    trade.tp2_hit = True
                    trade.tp3_hit = True
                    break

                if low <= tp3 and 'tp3' not in tps_hit:
                    tps_hit = ['tp1', 'tp2', 'tp3']
                    trade.tp3_hit = True
                    trade.sl_at_breakeven = True
                    current_sl = entry

                if low <= tp2 and 'tp2' not in tps_hit:
                    tps_hit = ['tp1', 'tp2']
                    trade.tp2_hit = True
                    trade.sl_at_breakeven = True
                    current_sl = entry

                if low <= tp1 and 'tp1' not in tps_hit:
                    tps_hit.append('tp1')
                    trade.tp1_hit = True
                    trade.sl_at_breakeven = True
                    current_sl = entry

            trade.bars_held = i + 1

        if trade.outcome is None:
            trade.outcome = 'EXPIRED'
            trade.exit_price = future_df.iloc[-1]['close'] if len(future_df) > 0 else signal_row['close']
            trade.rr_achieved = 0.0
            trade.max_rr_hit = 0.0

        if trade.bars_held is None:
            trade.bars_held = len(future_df) if len(future_df) > 0 else 1

        if len(future_df) > 0 and trade.bars_held > 0:
            exit_idx = min(trade.bars_held - 1, len(future_df) - 1)
            trade.exit_time = str(future_df.index[exit_idx])
        else:
            trade.exit_time = str(signal_row.name) if signal_row.name else 'UNKNOWN'

        return trade

    def _calculate_incremental_rr(self, tps_hit: list, entry: float, sl: float,
                                   tp1: float, tp2: float, tp3: float, tp4: float) -> float:
        sl_dist = abs(sl - entry)
        if sl_dist == 0:
            return 0.0
        if not tps_hit:
            return -1.0

        rr1 = round(abs(tp1 - entry) / sl_dist, 2)
        rr2 = round(abs(tp2 - entry) / sl_dist, 2)
        rr3 = round(abs(tp3 - entry) / sl_dist, 2)
        rr4 = round(abs(tp4 - entry) / sl_dist, 2)

        total_rr = 0.0
        for tp in tps_hit:
            if tp == 'tp1': total_rr += rr1 * 0.40
            elif tp == 'tp2': total_rr += rr2 * 0.30
            elif tp == 'tp3': total_rr += rr3 * 0.20
            elif tp == 'tp4': total_rr += rr4 * 0.10
        return round(total_rr, 2)

    def run(self, symbol: str, interval: str = '1h', months: int = 3,
            trading_hours_filter: bool = False,
            start_hour: int = 14, end_hour: int = 22) -> BacktestResult:
        result = BacktestResult(symbol=symbol, timeframe=interval, period_months=months)

        df = fetch_historical(symbol, interval, months)
        if df is None or len(df) < 100:
            return result

        df = self.compute_indicators(df)

        trades = []
        i = 60
        current_trade_end = 0
        cooldown_until = 0
        running_rr = 0.0
        peak_rr = 0.0
        breaker_until = 0

        while i < len(df) - 1:
            if i < current_trade_end:
                i += 1
                continue
            if i < cooldown_until:
                i += 1
                continue
            if i < breaker_until:
                i += 1
                continue

            # ── TRADING HOURS FILTER ──────────────────────────────────────
            if trading_hours_filter:
                candle_hour = df.index[i].hour
                if start_hour <= end_hour:
                    if not (start_hour <= candle_hour < end_hour):
                        i += 1
                        continue
                else:
                    if not (candle_hour >= start_hour or candle_hour < end_hour):
                        i += 1
                        continue

            row = df.iloc[i]
            direction = self.detect_signal(row)

            if direction:
                future = df.iloc[i+1: i+200]
                if len(future) < 5:
                    break
                vol_ratio = row['volume'] / row['vol_ma'] if row['vol_ma'] > 0 else 1.0
                quality_score = self.calculate_quality_score(row, direction, vol_ratio)
                trade = self.simulate_trade(row, future, direction, symbol, quality_score)
                trades.append(trade)
                bars_held = trade.bars_held or 1
                current_trade_end = i + bars_held
                cooldown_until = current_trade_end + 12

                running_rr += trade.rr_achieved or 0
                if running_rr > peak_rr:
                    peak_rr = running_rr
                dd = peak_rr - running_rr
                if dd >= 4.0:
                    breaker_until = current_trade_end + 50

            i += 1

        # ─── Aggregate ────────────────────────────────────────────────────
        valid = [t for t in trades if t.outcome != 'EXPIRED']
        result.total_trades = len(valid)
        if result.total_trades == 0:
            return result

        wins = [t for t in valid if t.outcome in ('TP1','TP2','TP3','TP4')]
        losses = [t for t in valid if t.outcome == 'SL']
        breakevens = [t for t in valid if t.outcome == 'BREAKEVEN']

        result.wins = len(wins)
        result.losses = len(losses)
        result.breakevens = len(breakevens)
        result.win_rate = round(len(wins) / (len(wins) + len(losses)) * 100, 1) if (len(wins) + len(losses)) > 0 else 0.0

        result.tp1_rate = round(sum(1 for t in valid if t.outcome == 'TP1') / result.total_trades * 100, 1)
        result.tp2_rate = round(sum(1 for t in valid if t.outcome == 'TP2') / result.total_trades * 100, 1)
        result.tp3_rate = round(sum(1 for t in valid if t.outcome == 'TP3') / result.total_trades * 100, 1)
        result.tp4_rate = round(sum(1 for t in valid if t.outcome == 'TP4') / result.total_trades * 100, 1)
        result.any_tp_rate = round(sum(1 for t in valid if t.outcome in ('TP1','TP2','TP3','TP4')) / result.total_trades * 100, 1)
        result.breakeven_rate = round(len(breakevens) / result.total_trades * 100, 1)

        rr_pos = [t.rr_achieved for t in valid if t.rr_achieved and t.rr_achieved > 0]
        result.avg_rr = round(sum(rr_pos)/len(rr_pos), 2) if rr_pos else 0
        result.max_rr = round(max(rr_pos), 2) if rr_pos else 0
        result.total_rr = round(sum(t.rr_achieved for t in valid if t.rr_achieved), 2)

        bars = [t.bars_held for t in valid if t.bars_held]
        result.avg_bars_held = round(sum(bars)/len(bars), 1) if bars else 0

        longs = [t for t in valid if t.direction == 'LONG']
        shorts = [t for t in valid if t.direction == 'SHORT']
        result.long_trades = len(longs)
        result.short_trades = len(shorts)
        long_wins = len([t for t in longs if t.outcome in ('TP1','TP2','TP3','TP4')])
        long_losses = len([t for t in longs if t.outcome == 'SL'])
        short_wins = len([t for t in shorts if t.outcome in ('TP1','TP2','TP3','TP4')])
        short_losses = len([t for t in shorts if t.outcome == 'SL'])
        result.long_win_rate = round(long_wins / (long_wins + long_losses) * 100, 1) if (long_wins + long_losses) > 0 else 0
        result.short_win_rate = round(short_wins / (short_wins + short_losses) * 100, 1) if (short_wins + short_losses) > 0 else 0

        equity = peak = max_dd = 0.0
        for t in valid:
            equity += t.rr_achieved or 0
            if equity > peak: peak = equity
            dd = peak - equity
            if dd > max_dd: max_dd = dd
        result.max_drawdown = round(max_dd, 2)

        result.trades = [asdict(t) for t in valid]
        return result


# ─── Report Printer ───────────────────────────────────────────────────────────

def print_comparison(results_without: list, results_with: list, months: int, start_hour: int, end_hour: int):
    print("\n")
    print("=" * 90)
    print("  TRADING HOURS FILTER IMPACT ANALYSIS")
    print(f"  Period: {months} months | TF: 1H | Top 50 coins by volume")
    print(f"  Trading Hours Filter: {start_hour:02d}:00 - {end_hour:02d}:00 UTC")
    print("=" * 90)

    def aggregate(results):
        valid = [r for r in results if r.total_trades > 0]
        if not valid:
            return None
        total = sum(r.total_trades for r in valid)
        wins = sum(r.wins for r in valid)
        losses = sum(r.losses for r in valid)
        be = sum(r.breakevens for r in valid)
        wr = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0
        total_rr = sum(r.total_rr for r in valid)
        avg_rr = round(sum(r.avg_rr for r in valid) / len(valid), 2)
        max_dd = round(sum(r.max_drawdown for r in valid) / len(valid), 2)
        longs = sum(r.long_trades for r in valid)
        shorts = sum(r.short_trades for r in valid)
        return {
            'total': total, 'wins': wins, 'losses': losses, 'be': be,
            'wr': wr, 'total_rr': total_rr, 'avg_rr': avg_rr, 'max_dd': max_dd,
            'longs': longs, 'shorts': shorts, 'symbols': len(valid)
        }

    agg_without = aggregate(results_without)
    agg_with = aggregate(results_with)

    if not agg_without or not agg_with:
        print("  No results to compare.")
        return

    print(f"\n{'METRIC':<30}{'WITHOUT FILTER':>20}{'WITH FILTER':>20}{'DELTA':>15}")
    print("-" * 85)

    def row(label, a, b, fmt="{}", pct=False):
        va = fmt.format(a)
        vb = fmt.format(b)
        if pct and isinstance(a, (int, float)) and isinstance(b, (int, float)) and b != 0:
            delta = round(((a - b) / b) * 100, 1)
            d_str = f"{delta:+.1f}%"
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta = a - b
            d_str = f"{delta:+.1f}"
        else:
            d_str = "-"
        print(f"{label:<30}{va:>20}{vb:>20}{d_str:>15}")

    row("Total Trades", agg_without['total'], agg_with['total'])
    row("Wins", agg_without['wins'], agg_with['wins'])
    row("Losses", agg_without['losses'], agg_with['losses'])
    row("Breakevens", agg_without['be'], agg_with['be'])
    row("Win Rate", agg_without['wr'], agg_with['wr'], fmt="{:.1f}%", pct=False)
    row("Total RR", agg_without['total_rr'], agg_with['total_rr'], fmt="{:.1f}R")
    row("Avg RR per trade", agg_without['avg_rr'], agg_with['avg_rr'], fmt="{:.2f}x")
    row("Max Drawdown", agg_without['max_dd'], agg_with['max_dd'], fmt="{:.1f}R")
    row("LONG trades", agg_without['longs'], agg_with['longs'])
    row("SHORT trades", agg_without['shorts'], agg_with['shorts'])
    row("Symbols tested", agg_without['symbols'], agg_with['symbols'])

    # Per-symbol comparison table
    print(f"\n{'─'*85}")
    print("  PER-SYMBOL COMPARISON (Top 20 by total trades)")
    print(f"{'─'*85}")
    print(f"{'SYMBOL':<12}{'WITHOUT':>10}{'W/R':>8}{'RR':>10}{'WITH':>10}{'W/R':>8}{'RR':>10}{'DELTA RR':>10}")
    print("-" * 85)

    # Build lookup
    with_lookup = {r.symbol: r for r in results_with}
    combined = []
    for r in results_without:
        if r.total_trades > 0:
            rw = with_lookup.get(r.symbol)
            if rw and rw.total_trades > 0:
                combined.append((r, rw))

    combined.sort(key=lambda x: x[0].total_trades, reverse=True)
    for r_wo, r_w in combined[:20]:
        wr_wo = f"{r_wo.win_rate:.0f}%" if r_wo.total_trades > 0 else "-"
        wr_w = f"{r_w.win_rate:.0f}%" if r_w.total_trades > 0 else "-"
        delta = r_wo.total_rr - r_w.total_rr
        print(f"{r_wo.symbol:<12}{r_wo.total_trades:>10}{wr_wo:>8}{r_wo.total_rr:>9.1f}R{r_w.total_trades:>10}{wr_w:>8}{r_w.total_rr:>9.1f}R{delta:>+9.1f}R")

    print(f"\n{'='*85}")
    print("  VERDICT")
    print(f"{'='*85}")

    rr_delta = agg_without['total_rr'] - agg_with['total_rr']
    wr_delta = agg_without['wr'] - agg_with['wr']

    if rr_delta > 5 and wr_delta >= 0:
        verdict = "❌  FILTER IS HURTING — Removing it improves RR and maintains or improves WR"
    elif rr_delta > 0 and wr_delta >= -3:
        verdict = "⚠️   FILTER IS MILDLY HURTING — Slight RR gain, small WR cost"
    elif rr_delta < -5 and wr_delta <= 0:
        verdict = "✅  FILTER IS HELPING — Keeping it improves both RR and WR"
    elif abs(rr_delta) < 5 and abs(wr_delta) < 3:
        verdict = "🟡  FILTER IS NEUTRAL — No meaningful impact, keep or remove based on preference"
    else:
        verdict = "🟡  MIXED RESULTS — Review per-symbol breakdown"

    print(f"  {verdict}")
    print(f"  RR delta (without - with): {rr_delta:+.1f}R")
    print(f"  WR delta (without - with): {wr_delta:+.1f}%")
    print(f"  Trades lost to filter: {agg_without['total'] - agg_with['total']}")
    print("=" * 85)
    print()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trading Hours Filter Impact Analysis")
    parser.add_argument('--months', type=int, default=3, help='Months of history')
    parser.add_argument('--top', type=int, default=50, help='Top N coins by volume')
    parser.add_argument('--start-hour', type=int, default=14, help='Trading start hour UTC')
    parser.add_argument('--end-hour', type=int, default=22, help='Trading end hour UTC')
    parser.add_argument('--save', action='store_true', help='Save results to JSON')
    args = parser.parse_args()

    symbols = get_top_symbols(args.top)
    symbols = [s for s in symbols if s not in cfg.excluded_pairs]

    print(f"\n🚀 Trading Hours Filter Backtest — {len(symbols)} coins | {args.months} months")
    print(f"   Trading window: {args.start_hour:02d}:00 - {args.end_hour:02d}:00 UTC")
    print(f"   Coins: {', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}\n")

    backtester = Backtester()
    results_without = []
    results_with = []

    for idx, sym in enumerate(symbols):
        print(f"\n[{idx+1}/{len(symbols)}] {sym}")

        print(f"  → WITHOUT trading hours filter...")
        r_wo = backtester.run(sym, '1h', args.months, trading_hours_filter=False)
        results_without.append(r_wo)
        print(f"     {r_wo.total_trades} trades | WR: {r_wo.win_rate}% | RR: {r_wo.total_rr:+.1f}R")

        print(f"  → WITH trading hours filter ({args.start_hour:02d}-{args.end_hour:02d} UTC)...")
        r_w = backtester.run(sym, '1h', args.months, trading_hours_filter=True,
                             start_hour=args.start_hour, end_hour=args.end_hour)
        results_with.append(r_w)
        print(f"     {r_w.total_trades} trades | WR: {r_w.win_rate}% | RR: {r_w.total_rr:+.1f}R")

        time.sleep(0.3)

    print_comparison(results_without, results_with, args.months, args.start_hour, args.end_hour)

    if args.save:
        data = {
            'without_filter': [asdict(r) for r in results_without],
            'with_filter': [asdict(r) for r in results_with],
            'config': {
                'months': args.months,
                'top': args.top,
                'start_hour': args.start_hour,
                'end_hour': args.end_hour,
                'symbols': symbols,
            }
        }
        with open('backtest_trading_hours_results.json', 'w') as f:
            json.dump(data, f, indent=2)
        print(f"💾 Saved to backtest_trading_hours_results.json")
