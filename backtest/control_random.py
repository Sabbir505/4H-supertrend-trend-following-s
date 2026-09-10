"""Random-entry control: same exit engine, same costs, random signals.

Establishes the expectancy floor of the exit/cost scheme itself. A strategy
only has an edge if it beats this floor meaningfully.

Usage: python control_random.py <interval> [n_symbols]
"""

import sys

import numpy as np
import pandas as pd

import engine
import indicators as ind
import metrics
from dataset import Dataset, BT_START, BT_END

interval = sys.argv[1] if len(sys.argv) > 1 else '30m'
n_syms = int(sys.argv[2]) if len(sys.argv) > 2 else 60
bar_hours = {'4h': 4.0, '1h': 1.0, '30m': 0.5}[interval]

rng = np.random.default_rng(7)
all_trades = []
ds = Dataset(interval)
for k, (sym, df) in enumerate(ds):
    if k >= n_syms:
        break
    n = len(df)
    if n < 1000:
        continue
    atr = ind.atr(df, 14)
    idxs = np.sort(rng.choice(np.arange(300, n - 2), size=n // 20, replace=False))
    plans = []
    for i in idxs:
        t = df.index[i + 1]
        if not (BT_START <= t < BT_END):
            continue
        af = (atr / df['close']).iat[i]
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if rng.random() < 0.5 else -1,
            sl_frac=1.5 * af, tp_frac=1.5 * af, exit_mode='fixed'))
    df.attrs['symbol'] = sym
    all_trades.extend(engine.simulate_symbol(df, plans))

tr = pd.DataFrame(all_trades)
m = metrics.compute_metrics(tr, bar_hours=bar_hours)
print(f"RANDOM-ENTRY control {interval} ({n_syms} symbols, 1:1 fixed exits):")
print({k: m[k] for k in ('trades', 'win_rate', 'avg_r', 'profit_factor')})
