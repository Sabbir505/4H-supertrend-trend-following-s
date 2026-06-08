"""
Backtester v4 — Tests the 4-TP Incremental Closing System
4-TP system:
  - TP1 at 1.5x SL (1.5:1 RR) — close 40%
  - TP2 at 2.0x SL (2.0:1 RR) — close 30%
  - TP3 at 2.5x SL (2.5:1 RR) — close 20%
  - TP4 at 3.0x SL (3.0:1 RR) — close 10%
  - SL = 1.0x ATR
  - ADX filter 25, Volume > 1.2x MA
  - MACD histogram direction + min strength

Usage:
  python backtest.py                              # Top 20 coins, 6 months
  python backtest.py --coins BTCUSDT ETHUSDT NEARUSDT
  python backtest.py --months 3 --top 10
  python backtest.py --save
"""

import os
import sys
import io

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import argparse
import requests
import pandas as pd
import numpy as np
import time
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from signals import SignalEngine
from config import Config

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
    outcome: Optional[str] = None   # TP1 | TP2 | TP3 | TP4 | SL | BREAKEVEN | EXPIRED
    rr_achieved: Optional[float] = None
    bars_held: Optional[int] = None
    quality_score: float = 0.0
    adx_at_entry: float = 0.0
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    sl_at_breakeven: bool = False


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    period_months: int
    total_trades: int = 0
    wins: int = 0        # TP1 or TP2 — both count as win
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


# ─── Data Fetching ─────────────────────────────────────────────────────────────

def fetch_historical(symbol: str, interval: str, months: int) -> pd.DataFrame:
    end_ms = int(datetime.utcnow().timestamp() * 1000)
    start_ms = int((datetime.utcnow() - timedelta(days=months * 30)).timestamp() * 1000)

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
            print(f"  ⚠️  Fetch error {symbol}: {e}")
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


# ─── Core Backtester ──────────────────────────────────────────────────────────

class Backtester:
    def __init__(self):
        self.engine = SignalEngine()

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df['close']
        d = df.copy()
        d['ema21']          = self.engine.ema(close, 21)
        d['ema55']          = self.engine.ema(close, 55)
        d['rsi']            = self.engine.rsi(close, 14)
        _, _, d['macd_hist'] = self.engine.macd(close)
        d['atr']            = self.engine.atr(df, 14)
        d['vol_ma']         = self.engine.volume_ma(df['volume'], 20)
        d['adx']            = self.engine.adx(df, 14)
        return d.dropna()

    def detect_signal(self, row) -> Optional[str]:
        # ADX filter — 30 threshold (tightened from 25)
        if row['adx'] < 30:
            return None

        # Volume filter — must be > 1.5x average (tightened from 1.2x)
        if row['volume'] <= row['vol_ma'] * 1.5:
            return None

        ema_bull = row['ema21'] > row['ema55']
        ema_bear = row['ema21'] < row['ema55']

        # MACD histogram direction + strength (reject weak momentum)
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
        """Calculate quality score for a signal (v5 formula from signals.py)"""
        score = 0

        # RSI quality: reward optimal range proximity
        if direction == 'LONG':
            rsi_optimal = 62.5
            rsi_dist = abs(row['rsi'] - rsi_optimal)
            score += max(0, 25 - rsi_dist * 1.5)
        else:
            rsi_optimal = 37.5
            rsi_dist = abs(row['rsi'] - rsi_optimal)
            score += max(0, 25 - rsi_dist * 1.5)

        # MACD histogram strength
        hist_strength = min(abs(row['macd_hist']) / row['atr'] * 10, 30)
        score += hist_strength

        # Volume strength
        score += min(vol_ratio * 15, 30)

        # ADX trend quality
        if 25 <= row['adx'] <= 35:
            score += 20
        elif 35 < row['adx'] <= 45:
            score += 10
        else:
            score += 0

        return round(score, 1)

    def simulate_trade(self, signal_row, future_df: pd.DataFrame,
                       direction: str, symbol: str, quality_score: float = 0.0) -> Trade:
        entry   = signal_row['close']
        atr     = signal_row['atr']
        sl_dist = atr * 1.0

        # 4-TP system
        if direction == 'LONG':
            sl  = entry - sl_dist
            tp1 = entry + sl_dist * 1.5
            tp2 = entry + sl_dist * 2.0
            tp3 = entry + sl_dist * 2.5
            tp4 = entry + sl_dist * 3.0
        else:
            sl  = entry + sl_dist
            tp1 = entry - sl_dist * 1.5
            tp2 = entry - sl_dist * 2.0
            tp3 = entry - sl_dist * 2.5
            tp4 = entry - sl_dist * 3.0

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
            low  = candle['low']

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
            trade.max_rr_hit = 0.0  # Bug fix: Set max_rr_hit for consistency

        if trade.bars_held is None:
            trade.bars_held = len(future_df) if len(future_df) > 0 else 1

        # Bug #11 fix: Bounds checking for exit time
        if len(future_df) > 0 and trade.bars_held > 0:
            exit_idx = min(trade.bars_held - 1, len(future_df) - 1)
            trade.exit_time = str(future_df.index[exit_idx])
        else:
            trade.exit_time = str(signal_row.name) if signal_row.name else 'UNKNOWN'

        return trade

    def _calculate_incremental_rr(self, tps_hit: list, entry: float, sl: float,
                                   tp1: float, tp2: float, tp3: float, tp4: float) -> float:
        """Calculate blended RR based on 4-TP incremental closing (40/30/20/10)"""
        sl_dist = abs(sl - entry)
        if sl_dist == 0:
            return 0.0

        # If no TPs hit, this is an SL loss
        if not tps_hit:
            return -1.0

        rr1 = round(abs(tp1 - entry) / sl_dist, 2)
        rr2 = round(abs(tp2 - entry) / sl_dist, 2)
        rr3 = round(abs(tp3 - entry) / sl_dist, 2)
        rr4 = round(abs(tp4 - entry) / sl_dist, 2)

        total_rr = 0.0

        for tp in tps_hit:
            if tp == 'tp1':
                total_rr += rr1 * 0.40
            elif tp == 'tp2':
                total_rr += rr2 * 0.30
            elif tp == 'tp3':
                total_rr += rr3 * 0.20
            elif tp == 'tp4':
                total_rr += rr4 * 0.10

        return round(total_rr, 2)

    def run(self, symbol: str, interval: str = '1h', months: int = 6) -> BacktestResult:
        result = BacktestResult(symbol=symbol, timeframe=interval, period_months=months)

        print(f"  📥 Fetching {symbol} {interval} — {months} months...")
        df = fetch_historical(symbol, interval, months)
        if df is None or len(df) < 100:
            print(f"  ⚠️  Not enough data for {symbol}")
            return result

        print(f"  ⚙️  Running strategy on {len(df)} candles...")
        df = self.compute_indicators(df)

        trades = []
        i = 60
        current_trade_end = 0
        cooldown_until = 0  # Trade cooldown: skip bars after a closed trade
        running_rr = 0.0    # Running RR total for circuit breaker
        peak_rr = 0.0       # Peak RR for drawdown calculation
        breaker_until = 0   # Circuit breaker: pause pair when DD exceeds threshold

        while i < len(df) - 1:
            if i < current_trade_end:
                i += 1
                continue

            # Trade cooldown: skip 12 bars after a closed trade to avoid overtrading
            if i < cooldown_until:
                i += 1
                continue

            # Circuit breaker: pause pair if running drawdown exceeds -4R for 50 bars
            if i < breaker_until:
                i += 1
                continue

            row = df.iloc[i]
            direction = self.detect_signal(row)

            if direction:
                future = df.iloc[i+1: i+200]
                if len(future) < 5:
                    break
                # Calculate quality score for the signal
                vol_ratio = row['volume'] / row['vol_ma'] if row['vol_ma'] > 0 else 1.0
                quality_score = self.calculate_quality_score(row, direction, vol_ratio)
                trade = self.simulate_trade(row, future, direction, symbol, quality_score)
                trades.append(trade)
                bars_held = trade.bars_held or 1
                current_trade_end = i + bars_held
                cooldown_until = current_trade_end + 12

                # Circuit breaker: track running RR and pause if DD > 4R
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
            print(f"  ⚠️  No trades generated for {symbol}")
            return result

        # WIN = TP1, TP2, TP3, TP4 (any TP level counts)
        wins   = [t for t in valid if t.outcome in ('TP1','TP2','TP3','TP4')]
        losses = [t for t in valid if t.outcome == 'SL']
        breakevens = [t for t in valid if t.outcome == 'BREAKEVEN']

        result.wins   = len(wins)
        result.losses = len(losses)
        result.breakevens = len(breakevens)
        # Bug fix: Breakevens are not wins - report win rate as pure wins only
        result.win_rate = round(len(wins) / result.total_trades * 100, 1)

        result.tp1_rate = round(sum(1 for t in valid if t.outcome == 'TP1') / result.total_trades * 100, 1)
        result.tp2_rate = round(sum(1 for t in valid if t.outcome == 'TP2') / result.total_trades * 100, 1)
        result.tp3_rate = round(sum(1 for t in valid if t.outcome == 'TP3') / result.total_trades * 100, 1)
        result.tp4_rate = round(sum(1 for t in valid if t.outcome == 'TP4') / result.total_trades * 100, 1)
        # Combined TP rate (any TP level hit)
        result.any_tp_rate = round(sum(1 for t in valid if t.outcome in ('TP1','TP2','TP3','TP4')) / result.total_trades * 100, 1)
        # Breakeven rate
        result.breakeven_rate = round(len(breakevens) / result.total_trades * 100, 1)

        rr_pos = [t.rr_achieved for t in valid if t.rr_achieved and t.rr_achieved > 0]
        result.avg_rr   = round(sum(rr_pos)/len(rr_pos), 2) if rr_pos else 0
        result.max_rr   = round(max(rr_pos), 2) if rr_pos else 0
        result.total_rr = round(sum(t.rr_achieved for t in valid if t.rr_achieved), 2)

        bars = [t.bars_held for t in valid if t.bars_held]
        result.avg_bars_held = round(sum(bars)/len(bars), 1) if bars else 0

        longs  = [t for t in valid if t.direction == 'LONG']
        shorts = [t for t in valid if t.direction == 'SHORT']
        result.long_trades  = len(longs)
        result.short_trades = len(shorts)
        # Long/short win rate includes breakevens for consistency with overall win_rate
        result.long_win_rate  = round(sum(1 for t in longs  if t.outcome in ('TP1','TP2','TP3','TP4','BREAKEVEN')) / len(longs)  * 100, 1) if longs  else 0
        result.short_win_rate = round(sum(1 for t in shorts if t.outcome in ('TP1','TP2','TP3','TP4','BREAKEVEN')) / len(shorts) * 100, 1) if shorts else 0

        # Max drawdown
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

def print_report(results: list, months: int):
    print("\n")
    print("=" * 80)
    print("  BACKTEST RESULTS v4 — Improved Triple Confirmation System")
    print(f"  Period: {months} months  |  TF: 1H  |  WIN = TP1+TP2+BREAKEVEN")
    print("  Fixes: MACD direction | ADX>25 | Vol>1.2x | SL=1.0x/TP1=1.5x/TP2=2.0x | DD breaker=4R/50bars")
    print("  Breakeven: TP1 hit -> SL to breakeven -> exit at rr1*0.5 overall with partial")
    print("=" * 80)

    results = [r for r in results if r.total_trades > 0]
    results.sort(key=lambda r: r.win_rate, reverse=True)

    if not results:
        print("  No results to display.")
        return

    total_trades = sum(r.total_trades for r in results)
    total_wins   = sum(r.wins for r in results)
    total_losses = sum(r.losses for r in results)
    total_breakevens = sum(r.breakevens for r in results)
    total_rr     = sum(r.total_rr for r in results)

    # Calculate gross profit (sum of positive RR) and gross loss (sum of negative RR)
    gross_profit = 0.0
    gross_loss   = 0.0
    for r in results:
        for t in r.trades:
            rr = t.get('rr_achieved', 0) or 0
            if rr > 0:
                gross_profit += rr
            elif rr < 0:
                gross_loss += rr

    net_rr = gross_profit + gross_loss

    print(f"\n{'SYMBOL':<14}{'TRADES':>7}{'WINS':>6}{'BE':>5}{'LOSS':>6}{'WIN%':>7}{'AVG RR':>8}{'TOTAL RR':>10}{'TP1%':>7}{'TP2%':>7}{'MAX DD':>8}")
    print("-" * 90)

    for r in results:
        flag = " 🔥" if r.win_rate >= 60 else (" 👍" if r.win_rate >= 45 else "")
        print(
            f"{r.symbol:<14}{r.total_trades:>7}{r.wins:>6}{r.breakevens:>5}{r.losses:>6}"
            f"{r.win_rate:>6.1f}%{r.avg_rr:>7.2f}x{r.total_rr:>9.1f}R"
            f"{r.tp1_rate:>6.1f}%{r.tp2_rate:>6.1f}%"
            f"{r.max_drawdown:>7.1f}R{flag}"
        )

    print("-" * 90)
    overall_wr = round((total_wins + total_breakevens) / total_trades * 100, 1) if total_trades else 0
    print(f"{'TOTAL':<14}{total_trades:>7}{total_wins:>6}{total_breakevens:>5}{'':>6}{overall_wr:>6.1f}%{'':>8}{total_rr:>9.1f}R")

    print(f"\n{'─'*70}")
    print("  LONG vs SHORT")
    print(f"{'─'*70}")
    print(f"{'SYMBOL':<14}{'LONG':>7}{'L.WIN%':>8}{'SHORT':>7}{'S.WIN%':>8}")
    print("-" * 44)
    for r in results:
        print(f"{r.symbol:<14}{r.long_trades:>7}{r.long_win_rate:>7.1f}%{r.short_trades:>7}{r.short_win_rate:>7.1f}%")

    print(f"\n{'─'*70}")
    print("  SUMMARY")
    print(f"{'─'*70}")

    best  = max(results, key=lambda r: r.win_rate)
    worst = min(results, key=lambda r: r.win_rate)
    most  = max(results, key=lambda r: r.total_trades)

    avg_bars = round(sum(r.avg_bars_held for r in results) / len(results), 1)
    avg_rr_all = round(sum(r.avg_rr for r in results) / len(results), 2)

    print(f"  Best win rate:     {best.symbol} — {best.win_rate}%")
    print(f"  Worst win rate:    {worst.symbol} — {worst.win_rate}%")
    print(f"  Most active pair:  {most.symbol} — {most.total_trades} trades")
    print(f"  Overall win rate:  {overall_wr}%")
    print(f"  Overall avg RR:    {avg_rr_all}x")
    print(f"  Total RR earned:   {total_rr:.1f}R")
    print(f"  Avg trade length:  {avg_bars} candles ({round(avg_bars)}H)")

    # Gross/Net breakdown
    print(f"\n  {'─'*40}")
    print("  GROSS / NET BREAKDOWN")
    print(f"  {'─'*40}")
    print(f"  Trades Won:        {total_wins} / {total_trades}")
    print(f"  Trades Lost:       {total_losses} / {total_trades}")
    print(f"  Breakevens:        {total_breakevens}")
    print(f"  Gross RR Won:      +{gross_profit:.1f}R")
    print(f"  Gross RR Lost:     {gross_loss:.1f}R")
    print(f"  Net RR:            {net_rr:+.1f}R")
    if gross_loss != 0:
        profit_factor = abs(gross_profit / gross_loss)
        print(f"  Profit Factor:     {profit_factor:.2f}")
    else:
        print(f"  Profit Factor:     N/A (no losses)")

    print()
    if overall_wr >= 55:
        verdict = "✅  PROFITABLE — Strategy ready for live trading"
        note    = "    Use proper position sizing (1-2% risk per trade)"
    elif overall_wr >= 45:
        verdict = "⚠️   MARGINAL — Promising but needs more tuning"
        note    = "    Try paper trading for 2-4 weeks before going live"
    else:
        verdict = "❌  NEEDS WORK — Not ready for live trading yet"
        note    = "    Share results and I'll tune the parameters further"

    print(f"  Verdict: {verdict}")
    print(f"  {note}")
    print("=" * 70)


def get_top_symbols(n: int = 20) -> list:
    print(f"📡 Fetching top {n} coins by volume...")
    try:
        r = requests.get(f"{BINANCE_URL}/api/v3/ticker/24hr", timeout=15)
        r.raise_for_status()
        stables = {"USDT","USDC","BUSD","DAI","TUSD","USDP","USDD",
                   "FDUSD","PYUSD","GUSD","FRAX","USD1"}
        excluded = cfg.excluded_pairs
        forex = cfg.forex_pairs  # Exclude forex/stablecoin pairs
        pairs = []
        for t in r.json():
            sym = t['symbol']
            if not sym.endswith('USDT'): continue
            if sym in excluded: continue
            if sym in forex: continue  # Skip forex pairs
            base = sym.replace('USDT','')
            if base in stables: continue
            try: pairs.append((sym, float(t['quoteVolume'])))
            except Exception: continue
        pairs.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in pairs[:n]]
    except Exception as e:
        print(f"⚠️  Could not fetch symbols: {e}")
        return ["BTCUSDT","ETHUSDT","BNBUSDT","XRPUSDT","NEARUSDT"]


def detect_market_regime(btc_df: pd.DataFrame) -> dict:
    """
    Detect market regime based on BTC 4H trend
    Returns: {'regime': 'BULL'|'BEAR'|'NEUTRAL', 'adx': float, 'ema_bullish': bool}
    """
    if btc_df is None or len(btc_df) < 60:
        return {'regime': 'NEUTRAL', 'adx': 0, 'ema_bullish': False, 'rsi': 50}

    # Calculate indicators
    close = btc_df['close']
    high = btc_df['high']
    low = btc_df['low']

    # EMAs
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema55 = close.ewm(span=55, adjust=False).mean()

    # RSI (using Wilder's EWM for consistency with signals.py)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=14 - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=14 - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(100)

    # ADX (using EWM for consistency with signals.py)
    # True Range
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional movements
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=btc_df.index).ewm(com=14 - 1, adjust=False).mean()
    minus_dm_s = pd.Series(minus_dm, index=btc_df.index).ewm(com=14 - 1, adjust=False).mean()
    atr_s = tr.ewm(com=14 - 1, adjust=False).mean()

    plus_di = 100 * plus_dm_s / atr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm_s / atr_s.replace(0, np.nan)

    di_sum = plus_di + minus_di
    dx = 100 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)
    adx = dx.ewm(com=14 - 1, adjust=False).mean().fillna(0)

    # Get latest values
    last_ema21 = ema21.iloc[-1]
    last_ema55 = ema55.iloc[-1]
    last_rsi = rsi.iloc[-1]
    last_adx = adx.iloc[-1]

    # Determine regime
    ema_bullish = last_ema21 > last_ema55
    ema_bearish = last_ema21 < last_ema55
    rsi_bullish = last_rsi > 50
    rsi_bearish = last_rsi < 50

    if ema_bullish and rsi_bullish:
        regime = 'BULL'
    elif ema_bearish and rsi_bearish:
        regime = 'BEAR'
    else:
        regime = 'NEUTRAL'

    return {
        'regime': regime,
        'adx': last_adx,
        'ema_bullish': ema_bullish,
        'rsi': last_rsi
    }


def run_directional_backtest(symbols: list, months: int = 6):
    """
    Run backtest with directional strategy (BULL/BEAR regime only, skip NEUTRAL)
    """
    print(f"\n{'='*80}")
    print("DIRECTIONAL STRATEGY BACKTEST — Market Regime Detection")
    print(f"{'='*80}")
    print(f"Strategy: Trade only in BTC trend direction")
    print(f"  BULL regime → LONG only")
    print(f"  BEAR regime → SHORT only")
    print(f"  NEUTRAL regime → SKIP (no trades)")

    # Fetch BTC 4H data for regime detection
    print(f"\n📡 Fetching BTC 4H data for regime detection...")
    btc_4h = fetch_historical('BTCUSDT', '4h', months)
    if btc_4h is None or len(btc_4h) < 60:
        print("❌ Failed to fetch BTC data!")
        return

    print(f"✅ BTC 4H data loaded: {len(btc_4h)} candles")

    # Detect regime for each 4H candle
    print("\n🔍 Detecting market regimes...")
    regimes = []
    for i in range(55, len(btc_4h)):
        window = btc_4h.iloc[:i+1]
        regime = detect_market_regime(window)
        regime['timestamp'] = btc_4h.index[i]
        regimes.append(regime)

    # Count regimes
    bull_count = sum(1 for r in regimes if r['regime'] == 'BULL')
    bear_count = sum(1 for r in regimes if r['regime'] == 'BEAR')
    neutral_count = sum(1 for r in regimes if r['regime'] == 'NEUTRAL')

    print(f"\n📊 Market Regime Distribution:")
    print(f"  BULL:    {bull_count} periods ({bull_count/len(regimes)*100:.1f}%)")
    print(f"  BEAR:    {bear_count} periods ({bear_count/len(regimes)*100:.1f}%)")
    print(f"  NEUTRAL: {neutral_count} periods ({neutral_count/len(regimes)*100:.1f}%)")

    # Run backtest for each symbol with regime filtering
    print(f"\n{'─'*80}")
    print("Running backtests with regime filtering...")
    print(f"{'─'*80}\n")

    all_results = []
    regime_stats = {'BULL': {'trades': 0, 'wins': 0, 'tp2_hits': 0, 'gross_profit': 0.0, 'gross_loss': 0.0},
                   'BEAR': {'trades': 0, 'wins': 0, 'tp2_hits': 0, 'gross_profit': 0.0, 'gross_loss': 0.0}}

    backtester = Backtester()

    for symbol in symbols:
        # Fetch 1H data
        df_1h = fetch_historical(symbol, '1h', months)
        if df_1h is None or len(df_1h) < 100:
            continue

        # Compute indicators
        df_1h = backtester.compute_indicators(df_1h)

        trades = []
        symbol_regime_stats = {'BULL': {'trades': 0, 'wins': 0, 'tp2_hits': 0, 'gross_profit': 0.0, 'gross_loss': 0.0},
                               'BEAR': {'trades': 0, 'wins': 0, 'tp2_hits': 0, 'gross_profit': 0.0, 'gross_loss': 0.0}}

        # Map each 1H candle to a regime
        i = 60
        while i < len(df_1h) - 1:
            current_time = df_1h.index[i]

            # Find the regime at this time (from BTC 4H)
            current_regime = 'NEUTRAL'
            for r in regimes:
                if r['timestamp'] <= current_time:
                    current_regime = r['regime']
                else:
                    break

            row = df_1h.iloc[i]
            direction = backtester.detect_signal(row)

            if direction:
                # Apply regime filter - SKIP NEUTRAL entirely
                if current_regime == 'BULL' and direction != 'LONG':
                    i += 1
                    continue
                if current_regime == 'BEAR' and direction != 'SHORT':
                    i += 1
                    continue
                if current_regime == 'NEUTRAL':
                    i += 1  # Skip all trades in neutral market
                    continue

                # Simulate trade
                future = df_1h.iloc[i+1: i+200]
                if len(future) < 5:
                    break

                vol_ratio = row['volume'] / row['vol_ma'] if row['vol_ma'] > 0 else 1.0
                quality_score = backtester.calculate_quality_score(row, direction, vol_ratio)
                trade = backtester.simulate_trade(row, future, direction, symbol, quality_score)

                if trade.outcome and trade.outcome != 'EXPIRED':
                    trades.append(trade)

                    # Update regime stats - track gross profit/loss separately
                    rs = symbol_regime_stats[current_regime]
                    rs['trades'] += 1
                    if trade.outcome in ('TP1', 'TP2', 'BREAKEVEN'):
                        rs['wins'] += 1
                        rs['gross_profit'] += trade.rr_achieved
                    else:
                        rs['gross_loss'] += trade.rr_achieved  # This is -1.0
                    if trade.outcome == 'TP2':
                        rs['tp2_hits'] += 1

                bars_held = trade.bars_held or 1
                i += bars_held + 12  # Cooldown
            else:
                i += 1

        if trades:
            valid = [t for t in trades if t.outcome != 'EXPIRED']
            wins = [t for t in valid if t.outcome in ('TP1', 'TP2')]

            result = {
                'symbol': symbol,
                'total_trades': len(valid),
                'wins': len(wins),
                'wr': round(len(wins) / len(valid) * 100, 1) if valid else 0,
                'total_rr': round(sum(t.rr_achieved for t in valid if t.rr_achieved), 2),
                'BULL': symbol_regime_stats['BULL'],
                'BEAR': symbol_regime_stats['BEAR']
            }

            all_results.append(result)

            # Aggregate regime stats
            for reg in ['BULL', 'BEAR']:
                regime_stats[reg]['trades'] += symbol_regime_stats[reg]['trades']
                regime_stats[reg]['wins'] += symbol_regime_stats[reg]['wins']
                regime_stats[reg]['tp2_hits'] += symbol_regime_stats[reg]['tp2_hits']
                regime_stats[reg]['gross_profit'] += symbol_regime_stats[reg]['gross_profit']
                regime_stats[reg]['gross_loss'] += symbol_regime_stats[reg]['gross_loss']

            print(f"  ✓ {symbol}: {result['total_trades']} trades, "
                  f"BULL: {round(result['BULL']['wins']/result['BULL']['trades']*100,1) if result['BULL']['trades'] > 0 else 0}% "
                  f"BEAR: {round(result['BEAR']['wins']/result['BEAR']['trades']*100,1) if result['BEAR']['trades'] > 0 else 0}%")

    if not all_results:
        print("\n❌ No trades found!")
        return

    # Aggregate results
    total_trades = sum(r['total_trades'] for r in all_results)
    total_wins = sum(r['wins'] for r in all_results)
    total_losses = total_trades - total_wins
    overall_wr = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0

    # Calculate gross profit, gross loss, and net RR from regime stats
    gross_profit = sum(regime_stats[reg]['gross_profit'] for reg in ['BULL', 'BEAR'])
    gross_loss = sum(regime_stats[reg]['gross_loss'] for reg in ['BULL', 'BEAR'])
    net_rr = gross_profit + gross_loss

    print(f"\n{'─'*80}")
    print(f"TOTAL RESULTS")
    print(f"{'─'*80}\n")

    print("📊 OVERALL PERFORMANCE (Directional Strategy)")
    print("=" * 80)
    print(f"Total Trades:   {total_trades}")
    print(f"  Wins:         {total_wins}")
    print(f"  Losses:       {total_losses}")
    print(f"Win Rate:       {overall_wr}%")
    print("=" * 80)
    print(f"💰 PROFIT/LOSS BREAKDOWN")
    print("=" * 80)
    print(f"Gross Profit:   +{gross_profit:.1f}R")
    print(f"Gross Loss:     {gross_loss:.1f}R")
    print(f"Net RR:         {net_rr:+.1f}R")
    print(f"Profit Factor:  {abs(gross_profit/gross_loss):.2f}" if gross_loss != 0 else "N/A")
    print("=" * 80)

    # Regime breakdown
    print("\n📊 PERFORMANCE BY MARKET REGIME")
    print("=" * 80)

    for reg in ['BULL', 'BEAR']:
        stats = regime_stats[reg]
        if stats['trades'] == 0:
            continue

        reg_wr = round(stats['wins'] / stats['trades'] * 100, 1)
        reg_tp2_rate = round(stats['tp2_hits'] / stats['trades'] * 100, 1)
        reg_losses = stats['trades'] - stats['wins']

        print(f"\n{reg} REGIME:")
        print(f"  Trades:       {stats['trades']}")
        print(f"  Wins:         {stats['wins']}")
        print(f"  Losses:       {reg_losses}")
        print(f"  Win Rate:     {reg_wr}%")
        print(f"  TP2 Rate:     {reg_tp2_rate}%")
        print(f"  Gross Profit: +{stats['gross_profit']:.1f}R")
        print(f"  Gross Loss:   {stats['gross_loss']:.1f}R")
        print(f"  Net RR:       {stats['gross_profit'] + stats['gross_loss']:+.1f}R")

    print("\n" + "=" * 80 + "\n")


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Backtester v4")
    parser.add_argument('--coins',  nargs='+', help='Coins to test e.g. BTCUSDT ETHUSDT')
    parser.add_argument('--months', type=int, default=6,  help='Months of history')
    parser.add_argument('--top',    type=int, default=20, help='Top N coins by volume')
    parser.add_argument('--save',   action='store_true',  help='Save to backtest_results.json')
    parser.add_argument('--directional', action='store_true', help='Use directional strategy with regime detection')
    args = parser.parse_args()

    symbols = args.coins if args.coins else get_top_symbols(args.top)
    symbols = [s for s in symbols if s not in cfg.excluded_pairs]

    if args.directional:
        # Run directional backtest
        run_directional_backtest(symbols, args.months)
    else:
        # Run standard backtest
        print(f"\n🚀 Backtester v4 — {len(symbols)} coins | {args.months} months")
        print(f"   Fixes: MACD direction | ADX>25 | Vol>1.2x | SL=1.0x/TP1=1.5x/TP2=2.0x | DD breaker=4R/50bars")
        print(f"   Excluded: {', '.join(cfg.excluded_pairs)}")
        print(f"   Coins: {', '.join(symbols)}\n")

        backtester = Backtester()
        all_results = []

        for idx, sym in enumerate(symbols):
            print(f"\n[{idx+1}/{len(symbols)}] {sym}")
            result = backtester.run(sym, '1h', args.months)
            all_results.append(result)
            time.sleep(0.3)

        print_report(all_results, args.months)

        if args.save:
            with open('backtest_results.json', 'w') as f:
                json.dump([asdict(r) for r in all_results], f, indent=2)
            print(f"\n💾 Saved to backtest_results.json")