"""Cross-sectional ranking strategy (momentum AND reversal polarity).

Academic motivation: crypto cross-sectional momentum inverts into reversal
beyond ~1 week (Dobrynskaya 2023; Proelss 2025) — so we test both polarities:
  polarity='mom':     long top-N by lookback return, short bottom-N
  polarity='rev':     long bottom-N, short top-N

Weekly rebalance. Entries at the first 4h bar close after rebalance time.
Exits: chandelier ATR trail + flip via own Supertrend + optional time stop.
Shorts optionally gated by BTC Supertrend direction (round-2 finding).
"""

import sys

import numpy as np
import pandas as pd

import engine
import indicators as ind
import metrics
from dataset import Dataset, CACHE_DIR, BT_START, TRAIN_END, BT_END


def build_rank_selections(interval='4h', lookback_days=7, top_n=10,
                          universe=None):
    """Returns {symbol: {rebalance_time: rank_slot}} where slot is
    'long' or 'short'."""
    ds = Dataset(interval, symbols=universe, with_htf=False)
    closes = {}
    for sym, df in ds:
        closes[sym] = df['close']
    if not closes:
        return {}, []

    all_idx = sorted(set().union(*[set(s.index) for s in closes.values()]))
    price = pd.DataFrame({s: c for s, c in closes.items()}).sort_index()

    rebal_times = pd.date_range(BT_START, BT_END, freq='7D', tz='UTC')
    sels = {s: {} for s in closes}
    for rt in rebal_times:
        # strict '<': use only bars that have CLOSED before the rebalance time
        lb_time = rt - pd.Timedelta(days=lookback_days)
        anchor = price.index[price.index < lb_time]
        cur = price.index[price.index < rt]
        if len(anchor) == 0 or len(cur) == 0:
            continue
        a_i, c_i = anchor[-1], cur[-1]
        if a_i == c_i:
            continue
        rets = (price.loc[c_i] / price.loc[a_i] - 1.0).dropna()
        rets = rets[(rets != 0) & np.isfinite(rets)]
        if len(rets) < top_n * 3:
            continue
        ranked = rets.sort_values(ascending=False)
        top = list(ranked.index[:top_n])
        bottom = list(ranked.index[-top_n:])
        for s in top:
            sels[s][c_i] = 'hi'
        for s in bottom:
            sels[s][c_i] = 'lo'
    return sels, rebal_times


def run_xsec(polarity='mom', lookback_days=7, top_n=10, interval='4h',
             trail_mult=3.5, time_stop_bars=42, btc_gate_shorts=True,
             split='full', log=True):
    sels, _ = build_rank_selections(interval, lookback_days, top_n)
    ds = Dataset(interval, with_htf=False)

    # BTC ST direction series for short gating
    btc = pd.read_parquet(CACHE_DIR / interval / 'BTCUSDT.parquet')
    _, btc_dir = ind.supertrend(btc, 10, 3.5)
    btc_dir_by_ct = pd.Series(btc_dir.to_numpy(), index=btc['close_time'])

    start, end = BT_START, BT_END
    if split == 'train':
        end = TRAIN_END
    elif split == 'valid':
        start = TRAIN_END

    all_trades = []
    n_syms = 0
    for sym, df in ds:
        sel = sels.get(sym)
        if not sel:
            continue
        n_syms += 1
        st, dirv = ind.supertrend(df, 10, 3.5)
        a = ind.atr(df, 14)
        ct = df['close_time']
        plans = []
        opens = df.index
        for i in range(2, len(df) - 1):
            slot = sel.get(opens[i])   # selection keys are bar open_times
            if slot is None:
                continue
            t = ct.iat[i]
            if not (start <= df.index[i + 1] < end):
                continue
            if polarity == 'mom':
                d = 1 if slot == 'hi' else -1
            else:  # reversal
                d = 1 if slot == 'lo' else -1
            if d == -1 and btc_gate_shorts:
                bd = btc_dir_by_ct.asof(t)
                if not (bd == -1):
                    continue
            af = (a.iat[i] / df['close'].iat[i]) if df['close'].iat[i] > 0 else np.nan
            if np.isnan(af) or af <= 0:
                continue
            plans.append(engine.TradePlan(
                idx=int(i), direction=d,
                sl_frac=max(5 * af, 0.02), tp_frac=None, exit_mode='trail',
                trail_mult=trail_mult, atr_entry=a.iat[i],
                time_stop_bars=time_stop_bars, atr_pct=af))
        if plans:
            all_trades.extend(engine.simulate_symbol(
                df, plans, flip_dir=dirv.to_numpy()))

    trades_df = pd.DataFrame(all_trades)
    m = metrics.compute_metrics(trades_df, bar_hours=4.0)
    if log:
        metrics.log_experiment(
            interval, 'xsec_rank',
            {'polarity': polarity, 'lookback_d': lookback_days,
             'top_n': top_n, 'trail': trail_mult,
             'ts_bars': time_stop_bars, 'btc_gate_shorts': btc_gate_shorts},
            split, n_syms, m)
    return m, trades_df


if __name__ == '__main__':
    pol = sys.argv[1] if len(sys.argv) > 1 else 'mom'
    lb = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    for split in ('train',):
        m, _ = run_xsec(polarity=pol, lookback_days=lb, split=split)
        print(pol, lb, split, {k: m[k] for k in
              ('trades', 'win_rate', 'avg_r', 'profit_factor',
               'total_return_pct', 'max_dd_pct')})
