"""
TP System Comparison Analysis
Uses existing backtest_results_backup_20260603.json to compare 4-TP vs 2-TP systems.
Both systems use the SAME signals and outcomes - only the RR calculation differs.
"""

import json
import math
import sys
import io

# Fix encoding for Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Load existing backtest data
with open('backtest_results_backup_20260603.json', 'r') as f:
    data = json.load(f)

print("=" * 100)
print("TP SYSTEM COMPARISON ANALYSIS")
print("=" * 100)
print("Data Source: backtest_results_backup_20260603.json")
print("Method: Re-calculate RR for each trade using both systems")
print("=" * 100)

# TP System definitions
# 4-TP system: 40% at TP1, 30% at TP2, 20% at TP3, 10% at TP4
# 2-TP system: 50% at TP1, 50% at TP2, 0% at TP3, 0% at TP4

# For the 4-TP system, the RR values are already in the data
# We need to recalculate for 2-TP system

def calculate_rr_2tp(trade):
    """Calculate RR using 2-TP system (50/50)"""
    entry = trade['entry']
    sl = trade['sl_original']
    tp1 = trade['tp1']
    tp2 = trade['tp2']
    tp3 = trade.get('tp3', tp2)
    tp4 = trade.get('tp4', tp2)

    sl_dist = abs(sl - entry)
    if sl_dist == 0:
        return 0.0

    rr1 = abs(tp1 - entry) / sl_dist
    rr2 = abs(tp2 - entry) / sl_dist
    rr3 = abs(tp3 - entry) / sl_dist if tp3 else rr2
    rr4 = abs(tp4 - entry) / sl_dist if tp4 else rr2

    outcome = trade['outcome']

    if outcome == 'SL':
        return -1.0
    if outcome == 'BREAKEVEN':
        # TP1 was hit, then exited at breakeven
        # 2-TP: 50% at TP1, 50% at breakeven (0)
        return round(rr1 * 0.50, 2)
    if outcome == 'EXPIRED':
        return 0.0
    if outcome == 'TP4':
        return round(rr1 * 0.50 + rr2 * 0.50, 2)
    if outcome == 'TP3':
        return round(rr1 * 0.50 + rr2 * 0.50, 2)
    if outcome == 'TP2':
        return round(rr1 * 0.50 + rr2 * 0.50, 2)
    if outcome == 'TP1':
        return round(rr1 * 0.50, 2)

    return 0.0


def calculate_rr_4tp(trade):
    """Recalculate RR using 4-TP system (40/30/20/10)"""
    entry = trade['entry']
    sl = trade['sl_original']
    tp1 = trade['tp1']
    tp2 = trade['tp2']
    tp3 = trade.get('tp3', tp2)
    tp4 = trade.get('tp4', tp2)

    sl_dist = abs(sl - entry)
    if sl_dist == 0:
        return 0.0

    rr1 = abs(tp1 - entry) / sl_dist
    rr2 = abs(tp2 - entry) / sl_dist
    rr3 = abs(tp3 - entry) / sl_dist if tp3 else rr2
    rr4 = abs(tp4 - entry) / sl_dist if tp4 else rr2

    outcome = trade['outcome']

    if outcome == 'SL':
        return -1.0
    if outcome == 'BREAKEVEN':
        # TP1 was hit, then exited at breakeven
        # 4-TP: 40% at TP1, remaining at breakeven (0)
        return round(rr1 * 0.40, 2)
    if outcome == 'EXPIRED':
        return 0.0
    if outcome == 'TP4':
        return round(rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20 + rr4 * 0.10, 2)
    if outcome == 'TP3':
        return round(rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20, 2)
    if outcome == 'TP2':
        return round(rr1 * 0.40 + rr2 * 0.30, 2)
    if outcome == 'TP1':
        return round(rr1 * 0.40, 2)

    return 0.0


# Process each symbol
results = []
all_trades_4tp = []
all_trades_2tp = []

for symbol_data in data:
    symbol = symbol_data['symbol']
    trades = symbol_data.get('trades', [])

    if not trades:
        continue

    # Calculate for both systems
    trades_4tp = []
    trades_2tp = []

    for trade in trades:
        rr_4tp = calculate_rr_4tp(trade)
        rr_2tp = calculate_rr_2tp(trade)

        t4 = trade.copy()
        t4['rr_achieved'] = rr_4tp
        trades_4tp.append(t4)

        t2 = trade.copy()
        t2['rr_achieved'] = rr_2tp
        trades_2tp.append(t2)

    # Aggregate stats for 4-TP
    valid_4tp = [t for t in trades_4tp if t['outcome'] != 'EXPIRED']
    wins_4tp = [t for t in valid_4tp if t['outcome'] in ('TP1', 'TP2', 'TP3', 'TP4')]
    losses_4tp = [t for t in valid_4tp if t['outcome'] == 'SL']
    be_4tp = [t for t in valid_4tp if t['outcome'] == 'BREAKEVEN']
    total_rr_4tp = sum(t['rr_achieved'] for t in valid_4tp if t['rr_achieved'])

    # Aggregate stats for 2-TP
    valid_2tp = [t for t in trades_2tp if t['outcome'] != 'EXPIRED']
    wins_2tp = [t for t in valid_2tp if t['outcome'] in ('TP1', 'TP2', 'TP3', 'TP4')]
    losses_2tp = [t for t in valid_2tp if t['outcome'] == 'SL']
    be_2tp = [t for t in valid_2tp if t['outcome'] == 'BREAKEVEN']
    total_rr_2tp = sum(t['rr_achieved'] for t in valid_2tp if t['rr_achieved'])

    results.append({
        'symbol': symbol,
        'trades': len(valid_4tp),
        'wins_4tp': len(wins_4tp),
        'wins_2tp': len(wins_2tp),
        'losses': len(losses_4tp),
        'be_4tp': len(be_4tp),
        'be_2tp': len(be_2tp),
        'total_rr_4tp': round(total_rr_4tp, 2),
        'total_rr_2tp': round(total_rr_2tp, 2),
        'diff': round(total_rr_4tp - total_rr_2tp, 2),
    })

    all_trades_4tp.extend(valid_4tp)
    all_trades_2tp.extend(valid_2tp)

# Sort by total RR difference
results.sort(key=lambda x: x['diff'], reverse=True)

# Print per-symbol breakdown
print(f"\n{'SYMBOL':<14}{'TRADES':>8}{'WINS':>6}{'LOSSES':>7}{'4-TP RR':>10}{'2-TP RR':>10}{'DIFF':>10}{'WINNER':>10}")
print("-" * 100)

for r in results:
    winner = "4-TP" if r['diff'] > 0 else "2-TP" if r['diff'] < 0 else "TIE"
    print(f"{r['symbol']:<14}{r['trades']:>8}{r['wins_4tp']:>6}{r['losses']:>7}{r['total_rr_4tp']:>9.2f}R{r['total_rr_2tp']:>9.2f}R{r['diff']:>9.2f}R{winner:>10}")

# Overall totals
print("-" * 100)

total_trades = sum(r['trades'] for r in results)
total_wins_4tp = sum(r['wins_4tp'] for r in results)
total_wins_2tp = sum(r['wins_2tp'] for r in results)
total_losses = sum(r['losses'] for r in results)
total_be_4tp = sum(r['be_4tp'] for r in results)
total_be_2tp = sum(r['be_2tp'] for r in results)
total_rr_4tp = sum(r['total_rr_4tp'] for r in results)
total_rr_2tp = sum(r['total_rr_2tp'] for r in results)

print(f"{'TOTAL':<14}{total_trades:>8}{total_wins_4tp:>6}{total_losses:>7}{total_rr_4tp:>9.2f}R{total_rr_2tp:>9.2f}R{total_rr_4tp - total_rr_2tp:>9.2f}R")

# Calculate additional metrics
avg_rr_per_trade_4tp = total_rr_4tp / total_trades if total_trades > 0 else 0
avg_rr_per_trade_2tp = total_rr_2tp / total_trades if total_trades > 0 else 0

# Count how many symbols each system won
symbols_4tp_wins = sum(1 for r in results if r['diff'] > 0)
symbols_2tp_wins = sum(1 for r in results if r['diff'] < 0)
symbols_tie = sum(1 for r in results if r['diff'] == 0)

print(f"\n{'='*100}")
print("  SUMMARY")
print(f"{'='*100}")

print(f"\n  Overall Metrics:")
print(f"    Total Trades:        {total_trades}")
print(f"    Total Wins:          {total_wins_4tp} (same for both systems)")
print(f"    Total Losses:        {total_losses} (same for both systems)")
print(f"    Breakevens (4-TP):   {total_be_4tp}")
print(f"    Breakevens (2-TP):   {total_be_2tp}")

print(f"\n  Risk-Return Comparison:")
print(f"    4-TP Total RR:       {total_rr_4tp:.2f}R")
print(f"    2-TP Total RR:       {total_rr_2tp:.2f}R")
print(f"    Difference:          {total_rr_4tp - total_rr_2tp:+.2f}R")
print(f"    4-TP Avg RR/Trade:   {avg_rr_per_trade_4tp:.3f}R")
print(f"    2-TP Avg RR/Trade:   {avg_rr_per_trade_2tp:.3f}R")

print(f"\n  Per-Symbol Winners:")
print(f"    4-TP wins on:        {symbols_4tp_wins}/{len(results)} symbols")
print(f"    2-TP wins on:        {symbols_2tp_wins}/{len(results)} symbols")
print(f"    Ties:                {symbols_tie}/{len(results)} symbols")

if total_rr_4tp > total_rr_2tp:
    margin = ((total_rr_4tp - total_rr_2tp) / abs(total_rr_2tp) * 100) if total_rr_2tp != 0 else float('inf')
    print(f"\n  Winner: 4-TP SYSTEM (+{margin:.1f}% more RR)")
elif total_rr_2tp > total_rr_4tp:
    margin = ((total_rr_2tp - total_rr_4tp) / abs(total_rr_4tp) * 100) if total_rr_4tp != 0 else float('inf')
    print(f"\n  Winner: 2-TP SYSTEM (+{margin:.1f}% more RR)")
else:
    print(f"\n  Result: TIE")

print(f"\n  System Definitions:")
print(f"    4-TP: Close 40% at TP1, 30% at TP2, 20% at TP3, 10% at TP4")
print(f"    2-TP: Close 50% at TP1, 50% at TP2 (ignore TP3/TP4)")
print(f"    Both: Move SL to breakeven after TP1 hit")
print("=" * 100)

# Detailed outcome distribution
print(f"\n{'='*100}")
print("  OUTCOME DISTRIBUTION ANALYSIS")
print(f"{'='*100}")

outcomes = {}
for trade in all_trades_4tp:
    oc = trade['outcome']
    outcomes[oc] = outcomes.get(oc, 0) + 1

print(f"\n  Trade Outcomes (same for both systems):")
for oc, count in sorted(outcomes.items(), key=lambda x: -x[1]):
    pct = count / len(all_trades_4tp) * 100
    print(f"    {oc:<12}: {count:>4} trades ({pct:>5.1f}%)")

# Calculate theoretical max RR if ALL trades hit TP2
print(f"\n  Theoretical Analysis:")
all_hitting_tp2 = sum(1 for t in all_trades_4tp if t['outcome'] in ('TP2', 'TP3', 'TP4'))
all_hitting_tp1_only = sum(1 for t in all_trades_4tp if t['outcome'] == 'TP1')
all_hitting_sl = sum(1 for t in all_trades_4tp if t['outcome'] == 'SL')
all_be = sum(1 for t in all_trades_4tp if t['outcome'] == 'BREAKEVEN')

print(f"    Trades hitting TP2+: {all_hitting_tp2} ({all_hitting_tp2/len(all_trades_4tp)*100:.1f}%)")
print(f"    Trades hitting TP1 only: {all_hitting_tp1_only} ({all_hitting_tp1_only/len(all_trades_4tp)*100:.1f}%)")
print(f"    Trades hitting SL: {all_hitting_sl} ({all_hitting_sl/len(all_trades_4tp)*100:.1f}%)")
print(f"    Trades at breakeven: {all_be} ({all_be/len(all_trades_4tp)*100:.1f}%)")

print(f"\n  Key Insight:")
print(f"    When a trade hits TP2+, 4-TP captures: 40%@TP1 + 30%@TP2 = 70% of position")
print(f"    When a trade hits TP2+, 2-TP captures: 50%@TP1 + 50%@TP2 = 100% of position")
print(f"    But 2-TP gets MORE at TP2 (50% vs 30%), which is better IF TP2 hits")
print(f"    4-TP keeps 30% running for TP3/TP4 moonshots")
print("=" * 100)
