"""Runner: execute a strategy over the cached dataset, compute metrics,
append to the experiments ledger, and optionally persist trade detail.

Split handling: trades are filtered by ENTRY time:
  'train'   -> entries in [BT_START, TRAIN_END)
  'valid'   -> entries in [TRAIN_END, BT_END)
  'full'    -> all entries in [BT_START, BT_END)
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import engine
import metrics
import strategies
from dataset import Dataset, BT_START, BT_END, TRAIN_END


def run(timeframe: str, strategy_name: str, params: dict, split: str = 'full',
        log: bool = True, symbols: list[str] | None = None,
        save_trades: bool = False):
    fn = strategies.REGISTRY[strategy_name]
    ds = Dataset(timeframe, symbols=symbols)

    start, end = BT_START, BT_END
    if split == 'train':
        end = TRAIN_END
    elif split == 'valid':
        start = TRAIN_END

    all_trades = []
    n_symbols = 0
    for sym, df in ds:
        try:
            plans, flip_dir = fn(df, params)
        except Exception as e:
            print(f"  {sym}: strategy error {e}", file=sys.stderr)
            continue
        # keep plans whose ENTRY lands inside the split window
        keep = []
        for pl in plans:
            ei = pl.idx + 1
            if ei >= len(df):
                continue
            t = df.index[ei]
            if start <= t < end:
                keep.append(pl)
        if not keep:
            continue
        trades = engine.simulate_symbol(df, keep, flip_dir=flip_dir)
        # drop eod-forced trades whose exit spills past the dataset (they are
        # valid but their exit is censored) — keep them, tagged by reason
        all_trades.extend(trades)
        n_symbols += 1

    trades_df = pd.DataFrame(all_trades)
    bar_hours = {'4h': 4.0, '1h': 1.0, '30m': 0.5}[timeframe]
    m = metrics.compute_metrics(trades_df, bar_hours=bar_hours)
    if log:
        metrics.log_experiment(timeframe, strategy_name, params, split,
                               n_symbols, m)
    if save_trades and not trades_df.empty:
        out = Path(__file__).parent / 'results' / f"{strategy_name}_{split}.csv"
        out.parent.mkdir(exist_ok=True)
        trades_df.to_csv(out, index=False)
    return m, trades_df


def sweep(timeframe: str, strategy_name: str, param_grid: dict,
          split: str = 'train'):
    """Run every combination in param_grid; returns results sorted by expectancy."""
    from itertools import product
    keys = list(param_grid.keys())
    results = []
    combos = list(product(*param_grid.values()))
    t0 = time.time()
    for k, vals in enumerate(combos):
        params = dict(zip(keys, vals))
        m, _ = run(timeframe, strategy_name, params, split=split, log=True)
        row = {**params, **{kk: m.get(kk) for kk in
                            ('trades', 'win_rate', 'avg_r', 'profit_factor',
                             'total_return_pct', 'max_dd_pct', 'sharpe')}}
        results.append(row)
        print(f"[{k+1}/{len(combos)}] {params} -> trades={m.get('trades')} "
              f"avgR={m.get('avg_r')} PF={m.get('profit_factor')} "
              f"ret={m.get('total_return_pct')}% dd={m.get('max_dd_pct')}%")
    print(f"sweep done in {time.time()-t0:.0f}s")
    return pd.DataFrame(results).sort_values('avg_r', ascending=False)


if __name__ == "__main__":
    # quick sanity run of the 4H baseline over a few symbols
    sample = Dataset('4h').symbols[:5]
    m, trades = run('4h', 'baseline_4h',
                    dict(st_period=12, st_mult=3.5, ema=200, rsi=14,
                         rsi_long=55, rsi_short=45, atr_min=0.5, atr_max=5.0,
                         rr=1.5),
                    split='full', log=False, symbols=sample, save_trades=True)
    print("sample baseline:", m)
    print(trades.head(10).to_string() if not trades.empty else "no trades")
