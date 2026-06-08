"""
Backtest Runner — Directional Strategy with Market Regime Detection
Tests the strategy with BTC 4H trend as market regime filter
Uses volume-based coin selection
"""

import os
import sys
import io

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import requests
import pandas as pd
import numpy as np
from backtest import Backtester, fetch_historical
from collections import defaultdict
from config import Config

cfg = Config()
backtester = Backtester()


def get_top_symbols_by_volume(top_n: int) -> list:
    """Get top coins by volume from Binance"""
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        tickers = response.json()

        usdt_pairs = []
        for t in tickers:
            symbol = t['symbol']
            if not symbol.endswith('USDT'):
                continue
            try:
                volume = float(t['quoteVolume'])
                usdt_pairs.append((symbol, volume))
            except (ValueError, KeyError):
                continue

        usdt_pairs.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in usdt_pairs[:top_n]]

    except Exception as e:
        print(f"❌ Error fetching Binance data: {e}")
        return []


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
    # When avg_loss is 0 and avg_gain > 0, RSI = 100 (all gains)
    # When both are 0 (flat market), RSI should be 50 (neutral)
    flat_market = (avg_gain == 0) & (avg_loss == 0)
    rsi = rsi.where(~flat_market, 50)
    rsi = rsi.fillna(100)

    # ADX (using EWM for consistency with signals.py)
    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
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
    dx = 100 * abs(plus_di - minus_di) / di_sum.replace(0, np.nan)
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


def run_directional_backtest(top_n: int = 50):
    """
    Run backtest with directional strategy based on BTC 4H trend
    """
    print("=" * 80)
    print("DIRECTIONAL STRATEGY BACKTEST — Market Regime Detection")
    print("=" * 80)
    print(f"Testing top {top_n} coins by volume with BTC 4H regime filter")
    print(f"Strategy: Only trade in direction of BTC 4H trend")
    print(f"- BULL regime → LONG only")
    print(f"- BEAR regime → SHORT only")
    print(f"- NEUTRAL regime → SKIP ENTIRELY (no trades)\n")

    # Get symbols
    symbols = get_top_symbols_by_volume(top_n)
    exclude = ['UUSDT', 'TRXUSDT', 'PORTALUSDT', 'ASTERUSDT', 'SOLUSDT', 'DOGEUSDT', 'XRPUSDT']
    symbols = [s for s in symbols if s not in exclude]

    print(f"Testing {len(symbols)} symbols (after exclusions)")

    # Fetch BTC 4H data for regime detection
    print("\n📡 Fetching BTC 4H data for regime detection...")
    btc_4h = fetch_historical('BTCUSDT', '4h', months=3)
    if btc_4h is None or len(btc_4h) < 60:
        print("❌ Failed to fetch BTC data!")
        return

    print(f"✅ BTC 4H data loaded: {len(btc_4h)} candles")

    # Detect regime for each 4H candle
    print("\n🔍 Detecting market regimes...")
    regimes = []
    for i in range(59, len(btc_4h)):
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

    # Now backtest each symbol with regime filtering
    print(f"\n{'─' * 80}")
    print("Running backtests with regime filtering...")
    print(f"{'─' * 80}\n")

    all_results = []
    regime_stats = {'BULL': [], 'BEAR': [], 'NEUTRAL': []}

    for symbol in symbols:
        # Run backtest with regime awareness
        result = run_symbol_with_regime(symbol, btc_4h, regimes)

        if result and result['total_trades'] > 0:
            all_results.append(result)

            # Categorize by regime
            for reg in ['BULL', 'BEAR', 'NEUTRAL']:
                if result.get(reg):
                    regime_stats[reg].append(result[reg])

            print(f"  ✓ {symbol}: {result['total_trades']} trades, "
                  f"BULL: {result.get('BULL', {}).get('wr', 0):.1f}% "
                  f"BEAR: {result.get('BEAR', {}).get('wr', 0):.1f}% "
                  f"NEUTRAL: {result.get('NEUTRAL', {}).get('wr', 0):.1f}%")

    if not all_results:
        print("\n❌ No trades found!")
        return

    # Aggregate results
    print(f"\n{'─' * 80}")
    print(f"TOTAL RESULTS")
    print(f"{'─' * 80}\n")

    # Overall stats
    total_trades = sum(r['total_trades'] for r in all_results)
    total_wins = sum(r['wins'] for r in all_results)
    overall_wr = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0

    print("📊 OVERALL PERFORMANCE (Directional Strategy)")
    print("=" * 80)
    print(f"Total Trades:   {total_trades}")
    print(f"Win Rate:       {overall_wr}%")
    print(f"=" * 80)

    # Regime breakdown
    print("\n📊 PERFORMANCE BY MARKET REGIME")
    print("=" * 80)

    for reg in ['BULL', 'BEAR', 'NEUTRAL']:
        stats = regime_stats[reg]
        if not stats:
            continue

        reg_trades = sum(s['trades'] for s in stats)
        reg_wins = sum(s['wins'] for s in stats)
        reg_wr = round(reg_wins / reg_trades * 100, 1) if reg_trades > 0 else 0
        reg_tp2 = sum(s['tp2_hits'] for s in stats)
        reg_tp2_rate = round(reg_tp2 / reg_trades * 100, 1) if reg_trades > 0 else 0
        reg_total_rr = round(sum(s['total_rr'] for s in stats), 2)

        print(f"\n{reg} REGIME:")
        print(f"  Trades:     {reg_trades}")
        print(f"  Win Rate:   {reg_wr}%")
        print(f"  TP2 Rate:   {reg_tp2_rate}%")
        print(f"  Total RR:   {reg_total_rr}")

    print("\n" + "=" * 80)

    # Compare to non-directional (baseline)
    print("\n📈 COMPARISON: Directional vs Baseline")
    print("─" * 80)
    print("Running baseline backtest (no regime filter)...")

    baseline_trades = 0
    baseline_wins = 0
    baseline_rr = 0.0

    for symbol in symbols[:20]:  # Sample for speed
        result = backtester.run(symbol, months=3)
        if result and result.total_trades > 0:
            baseline_trades += result.total_trades
            baseline_wins += result.wins
            baseline_rr += result.total_rr

    baseline_wr = round(baseline_wins / baseline_trades * 100, 1) if baseline_trades > 0 else 0

    print(f"\nDirectional: {overall_wr}% WR, Total RR: {sum(r['total_rr'] for r in all_results):.1f}")
    print(f"Baseline:      {baseline_wr}% WR, Total RR: {baseline_rr:.1f}")

    if overall_wr > baseline_wr:
        print(f"\n✅ Directional strategy performs {round(overall_wr - baseline_wr, 1)}% better!")
    else:
        print(f"\n⚠️  Baseline performs {round(baseline_wr - overall_wr, 1)}% better")

    print("=" * 80 + "\n")


def run_symbol_with_regime(symbol: str, btc_4h: pd.DataFrame, regimes: list) -> dict:
    """
    Run backtest for a single symbol with regime filtering
    """
    # Fetch 1H data
    df_1h = fetch_historical(symbol, '1h', months=3)
    if df_1h is None or len(df_1h) < 100:
        return None

    # Compute indicators
    df_1h = backtester.compute_indicators(df_1h)

    trades = []
    regime_breakdown = {'BULL': {'trades': 0, 'wins': 0, 'tp2_hits': 0, 'total_rr': 0},
                        'BEAR': {'trades': 0, 'wins': 0, 'tp2_hits': 0, 'total_rr': 0},
                        'NEUTRAL': {'trades': 0, 'wins': 0, 'tp2_hits': 0, 'total_rr': 0}}

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

                # Update regime breakdown
                rb = regime_breakdown[current_regime]
                rb['trades'] += 1
                if trade.outcome in ('TP1', 'TP2', 'TP3', 'TP4', 'BREAKEVEN'):
                    rb['wins'] += 1
                if trade.outcome == 'TP2':
                    rb['tp2_hits'] += 1
                if trade.rr_achieved:
                    rb['total_rr'] += trade.rr_achieved

            bars_held = trade.bars_held or 1
            i += bars_held + 12  # Cooldown
        else:
            i += 1

    # Calculate result
    if not trades:
        return None

    valid = [t for t in trades if t.outcome != 'EXPIRED']
    wins = [t for t in valid if t.outcome in ('TP1', 'TP2', 'TP3', 'TP4')]

    result = {
        'symbol': symbol,
        'total_trades': len(valid),
        'wins': len(wins),
        'wr': round(len(wins) / len(valid) * 100, 1) if valid else 0,
        'total_rr': round(sum(t.rr_achieved for t in valid if t.rr_achieved), 2),
        'BULL': regime_breakdown['BULL'],
        'BEAR': regime_breakdown['BEAR'],
        'NEUTRAL': regime_breakdown['NEUTRAL']
    }

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=50, help='Top N coins by volume')
    args = parser.parse_args()

    run_directional_backtest(args.top)
