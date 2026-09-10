"""Market breadth overlay: fraction of the universe above its own 4H EMA200,
sampled at each 4h close. Used as (a) entry filter or (b) risk scaler on the
winning strategy's trades. Threshold chosen on train, checked on holdout.
"""

import numpy as np
import pandas as pd

import metrics
import runner
from dataset import Dataset, BT_START, TRAIN_END, BT_END

FINAL = dict(st_period=10, st_mult=3.5, trail_mult=3.5, ema=200,
             short_mode='btc_st', time_stop_bars=42)


def compute_breadth() -> pd.Series:
    ds = Dataset('4h', with_htf=False)
    flags = []
    for sym, df in ds:
        e = df['close'].ewm(span=200, adjust=False).mean()
        f = (df['close'] > e).astype(float)
        f.index = df['close_time']
        flags.append(f)
    mat = pd.concat(flags, axis=1).sort_index()
    breadth = mat.mean(axis=1, skipna=True)
    breadth.index.name = 'close_time'
    return breadth


def main():
    breadth = compute_breadth()
    print(f'breadth series: {len(breadth)} timestamps, mean {breadth.mean():.2f}')

    for split in ('train', 'valid'):
        m, tr = runner.run('4h', 'st_trail', FINAL, split=split, log=False)
        b_at_entry = pd.Series(
            [breadth.asof(t) for t in tr['entry_time']], index=tr.index)
        tr['breadth'] = b_at_entry

        print(f'--- {split} (n={len(tr)}) ---')
        # quintile analysis of trade quality vs breadth at entry
        tr['bq'] = pd.qcut(tr['breadth'], 4, labels=['q1', 'q2', 'q3', 'q4'])
        print(tr.groupby('bq', observed=True)['net_r'].agg(
            ['size', 'mean']).round(4).to_string())

        # candidate overlays
        for thr in (0.3, 0.4, 0.5):
            keep = tr['breadth'] >= thr
            mf = metrics.compute_metrics(tr[keep], bar_hours=4.0)
            # half-risk when breadth low
            w = np.where(keep, 1.0, 0.5)
            eq = [1.0]
            for r, wt in zip(tr['net_r'], w):
                eq.append(eq[-1] * (1 + 0.01 * wt * r))
            eq = np.array(eq)
            peak = np.maximum.accumulate(eq)
            dd = (1 - eq / peak).max() * 100
            print(f'thr={thr}: FILTER ret {mf["total_return_pct"]:+7.1f}% '
                  f'dd {mf["max_dd_pct"]:5.1f}% avgR {mf["avg_r"]:+.4f} n {mf["trades"]}'
                  f' | HALF-RISK ret {(eq[-1]-1)*100:+7.1f}% dd {dd:5.1f}%')


if __name__ == '__main__':
    main()
