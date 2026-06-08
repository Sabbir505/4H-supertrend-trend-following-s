"""
Score-Based Performance Analysis
Analyzes backtest results broken down by quality_score ranges
"""

import os
import sys
import io

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import pandas as pd
from backtest import Backtester
from collections import defaultdict
from config import Config

cfg = Config()
backtester = Backtester()


def analyze_by_score_ranges(symbols: list, score_ranges: list = None):
    """
    Run backtest and analyze performance by quality_score ranges

    Args:
        symbols: List of trading pairs to test
        score_ranges: List of tuples defining score ranges [(min, max, label)]
                     Default: [(0, 40, 'Low'), (40, 60, 'Medium'), (60, 80, 'High'), (80, 100, 'Elite')]
    """
    if score_ranges is None:
        score_ranges = [
            (0, 40, 'Low (0-40)'),
            (40, 60, 'Medium (40-60)'),
            (60, 80, 'High (60-80)'),
            (80, 100, 'Elite (80-100)')
        ]

    print("=" * 80)
    print("SCORE-BASED PERFORMANCE ANALYSIS")
    print("=" * 80)
    print(f"\nTesting {len(symbols)} symbols...")
    print(f"Score ranges: {score_ranges}\n")

    # Collect all trades across all symbols
    all_trades = []

    for symbol in symbols:
        result = backtester.run(symbol, months=3)  # 3 months = ~90 days
        if result and result.trades:
            all_trades.extend(result.trades)
            print(f"  ✓ {symbol}: {result.total_trades} trades, WR: {result.win_rate}%")

    if not all_trades:
        print("\n❌ No trades found!")
        return

    print(f"\n{'─' * 80}")
    print(f"TOTAL TRADES COLLECTED: {len(all_trades)}")
    print(f"{'─' * 80}\n")

    # Group trades by score range
    score_groups = defaultdict(list)

    for trade in all_trades:
        score = trade['quality_score']
        for min_score, max_score, label in score_ranges:
            if min_score <= score < max_score or (min_score == score_ranges[-1][0] and score >= min_score):
                score_groups[label].append(trade)
                break

    # Calculate stats for each score range
    results_data = []

    for label in [r[2] for r in score_ranges]:
        trades = score_groups[label]
        if not trades:
            continue

        valid = [t for t in trades if t['outcome'] != 'EXPIRED']
        wins = [t for t in valid if t['outcome'] in ('TP1', 'TP2')]
        tp1_hits = [t for t in valid if t['outcome'] == 'TP1']
        tp2_hits = [t for t in valid if t['outcome'] == 'TP2']

        total = len(valid)
        win_count = len(wins)
        win_rate = round(win_count / total * 100, 1) if total > 0 else 0

        tp1_rate = round(len(tp1_hits) / total * 100, 1) if total > 0 else 0
        tp2_rate = round(len(tp2_hits) / total * 100, 1) if total > 0 else 0

        rr_values = [t['rr_achieved'] for t in valid if t['rr_achieved'] and t['rr_achieved'] > 0]
        avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0
        total_rr = round(sum(t['rr_achieved'] for t in valid if t['rr_achieved']), 2)

        avg_score = round(sum(t['quality_score'] for t in valid) / total, 1) if total > 0 else 0
        avg_adx = round(sum(t['adx_at_entry'] for t in valid) / total, 1) if total > 0 else 0

        results_data.append({
            'Score Range': label,
            'Total Trades': total,
            'Wins': win_count,
            'Losses': total - win_count,
            'Win Rate %': win_rate,
            'TP1 Hit %': tp1_rate,
            'TP2 Hit %': tp2_rate,
            'Avg RR': avg_rr,
            'Total RR': total_rr,
            'Avg Score': avg_score,
            'Avg ADX': avg_adx
        })

    # Create DataFrame for nice display
    df = pd.DataFrame(results_data)

    # Print summary table
    print("📊 PERFORMANCE BY SCORE RANGE")
    print("=" * 100)
    print(df.to_string(index=False))
    print("=" * 100)

    # Print insights
    print("\n🔍 KEY INSIGHTS:")
    print("─" * 80)

    if len(df) > 1:
        best_range = df.loc[df['Win Rate %'].idxmax()]
        worst_range = df.loc[df['Win Rate %'].idxmin()]

        print(f"✅ BEST WIN RATE: {best_range['Score Range']} → {best_range['Win Rate %']}% WR")
        print(f"   Avg RR: {best_range['Avg RR']}, TP2 hit: {best_range['TP2 Hit %']}%")
        print()
        print(f"⚠️  WORST WIN RATE: {worst_range['Score Range']} → {worst_range['Win Rate %']}% WR")
        print(f"   Avg RR: {worst_range['Avg RR']}, TP2 hit: {worst_range['TP2 Hit %']}%")
        print()

        # Find most profitable range
        most_profitable = df.loc[df['Total RR'].idxmax()]
        print(f"💰 MOST PROFITABLE: {most_profitable['Score Range']} → Total RR: {most_profitable['Total RR']}")
        print(f"   Win Rate: {most_profitable['Win Rate %']}%, Avg RR: {most_profitable['Avg RR']}")

    # Additional analysis: score correlation
    print("\n📈 SCORE VS WIN RATE CORRELATION:")
    print("─" * 80)

    # Create finer granularity (10-point bins)
    fine_bins = defaultdict(list)
    for trade in all_trades:
        if trade['outcome'] != 'EXPIRED':
            bin_key = int(trade['quality_score'] // 10) * 10
            fine_bins[bin_key].append(trade)

    fine_data = []
    for bin_start in sorted(fine_bins.keys()):
        trades = fine_bins[bin_start]
        valid = [t for t in trades if t['outcome'] != 'EXPIRED']
        wins = [t for t in valid if t['outcome'] in ('TP1', 'TP2')]

        if len(valid) >= 3:  # Only show bins with at least 3 trades
            win_rate = round(len(wins) / len(valid) * 100, 1)
            avg_rr = round(sum(t['rr_achieved'] for t in valid if t['rr_achieved']) / len(valid), 2)
            avg_score = round(sum(t['quality_score'] for t in valid) / len(valid), 1)

            fine_data.append({
                'Score Bin': f"{bin_start}-{bin_start+10}",
                'Trades': len(valid),
                'WR %': win_rate,
                'Avg RR': avg_rr,
                'Avg Score': avg_score
            })

    if fine_data:
        fine_df = pd.DataFrame(fine_data)
        print(fine_df.to_string(index=False))

    print("\n" + "=" * 80)
    print("RECOMMENDATION:")
    print("─" * 80)

    if len(df) > 0:
        # Find threshold where win rate drops significantly
        threshold_score = None
        prev_wr = None

        for idx, row in df.iterrows():
            if prev_wr is not None and row['Win Rate %'] < prev_wr - 10:
                threshold_score = row['Avg Score']
                break
            prev_wr = row['Win Rate %']

        if threshold_score:
            print(f"⚡ Consider filtering signals with score < {int(threshold_score)}")
            print(f"   Win rate drops significantly below this threshold.")
        else:
            elite_wr = df[df['Score Range'].str.contains('Elite|High')]['Win Rate %'].mean()
            overall_wr = sum([t['outcome'] in ('TP1', 'TP2') for t in all_trades if t['outcome'] != 'EXPIRED']) / len([t for t in all_trades if t['outcome'] != 'EXPIRED']) * 100

            print(f"✅ Quality scoring is working well!")
            print(f"   Elite/High scores: {round(elite_wr, 1)}% WR")
            print(f"   Overall: {round(overall_wr, 1)}% WR")
            print(f"   → Keep using current scoring system.")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    # Use exclude list from backtest.py
    exclude = ['UUSDT', 'TRXUSDT', 'PORTALUSDT', 'ASTERUSDT', 'SOLUSDT', 'DOGEUSDT', 'XRPUSDT']

    # Get all USDT pairs from Binance
    import requests
    response = requests.get("https://api.binance.com/api/v3/exchangeInfo")
    symbols = [s['symbol'] for s in response.json()['symbols']
               if s['symbol'].endswith('USDT')
               and s['status'] == 'TRADING'
               and s['symbol'] not in exclude]

    print(f"Found {len(symbols)} valid symbols (excluding {len(exclude)} dead-weight pairs)")

    # Run analysis
    analyze_by_score_ranges(symbols[:50])  # Test top 50 symbols (adjust as needed)