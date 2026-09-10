"""Export backtest results to the frontend as JSON.

Produces frontend/public/data/backtest_results.json containing:
- daily equity curves (final strategy w/ breadth-scaled risk, round-2 base,
  production baseline, BTC buy&hold)
- drawdown series for the final strategy
- window metrics (train / valid / full x base / final) from the ledger
- cost-stress and walk-forward fold results
- curated research-rounds summary
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BACKTEST_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKTEST_DIR))

import metrics as bt_metrics
import runner
from breadth import FINAL, compute_breadth
from dataset import Dataset, BT_START, BT_END

OUT_FILE = BACKTEST_DIR.parent / "frontend" / "public" / "data" / "backtest_results.json"

RISK_FRAC = 0.01


def equity_series(trades: pd.DataFrame, breadth: pd.Series | None,
                  thr: float = 0.3, risk_frac: float = RISK_FRAC) -> pd.Series:
    """Daily compounded equity curve; breadth-scaled risk when breadth given.

    Literal deployable sizing: full risk when breadth >= thr, half below.
    Trades compounded in exit-time order (matches ledger methodology).
    """
    tr = trades.sort_values('exit_time').reset_index(drop=True)
    if breadth is not None and len(tr):
        w = np.where(
            [breadth.asof(t) >= thr for t in tr['entry_time']], 1.0, 0.5)
    else:
        w = np.ones(len(tr))
    eq = [1.0]
    for r, wt in zip(tr['net_r'], w):
        eq.append(eq[-1] * (1 + risk_frac * wt * r))
    s = pd.Series(eq[1:], index=pd.DatetimeIndex(tr['exit_time']))
    return s


def daily_curve(series: pd.Series) -> pd.Series:
    return series.resample('1D').last().ffill()


def main():
    print('computing breadth...')
    breadth = compute_breadth()

    print('running final strategy (full)...')
    _, tr_final = runner.run('4h', 'st_trail', FINAL, split='full', log=False)
    print('running baseline (full)...')
    baseline_params = dict(st_period=12, st_mult=3.5, ema=200, rsi=14,
                           rsi_long=55, rsi_short=45, atr_min=0.5, atr_max=5.0,
                           rr=1.5)
    _, tr_base = runner.run('4h', 'baseline_4h', baseline_params, split='full',
                            log=False)

    eq_final = daily_curve(equity_series(tr_final, breadth))

    # baseline at the same risk fraction, no breadth weighting
    eq_base = daily_curve(equity_series(tr_base, None))

    # BTC buy & hold
    btc = pd.read_parquet(BACKTEST_DIR / 'data_cache' / '4h' / 'BTCUSDT.parquet')
    btc_d = btc['close'].resample('1D').last().dropna()
    btc_hold = btc_d[(btc_d.index >= BT_START) & (btc_d.index < BT_END)]
    btc_hold = btc_hold / btc_hold.iloc[0]

    # align all curves on the final's daily index
    idx = eq_final.index
    curve = pd.DataFrame({
        'final': eq_final,
        'baseline': eq_base.reindex(idx).ffill(),
        'btc_hold': btc_hold.reindex(idx).ffill(),
    }).dropna()
    curve = curve / curve.iloc[0]

    # drawdown of final
    peak = curve['final'].cummax()
    dd = (1 - curve['final'] / peak) * 100

    equity = [
        {'date': d.strftime('%Y-%m-%d'),
         'final': round(float(r['final']) * 100, 2),
         'baseline': round(float(r['baseline']) * 100, 2),
         'btc_hold': round(float(r['btc_hold']) * 100, 2)}
        for d, r in curve.iterrows()
    ]
    drawdown = [
        {'date': d.strftime('%Y-%m-%d'), 'dd': round(float(v), 2)}
        for d, v in dd.items()
    ]

    # window metrics from the ledger (latest matching rows)
    led = pd.read_csv(BACKTEST_DIR / 'experiments' / 'experiments.csv')

    def latest(strategy, split):
        rows = led[(led['strategy'] == strategy) & (led['split'] == split)]
        if rows.empty:
            return {}
        r = rows.iloc[-1]
        keys = ('trades', 'win_rate', 'avg_r', 'profit_factor',
                'total_return_pct', 'max_dd_pct', 'sharpe')
        return {k: (None if pd.isna(r.get(k)) else float(r[k])) for k in keys}

    def mwin(split):
        return {'baseline': latest('baseline_4h', split),
                'base': latest('st_trail', split),
                'final': latest('st_trail_breadth_risk', split)}

    payload = {
        'generated_at': pd.Timestamp.now(tz='UTC').isoformat(),
        'config': {
            'name': '4H Supertrend Trend-Ride (round-4 final)',
            'params': {
                'supertrend': 'ATR 10 / x3.5',
                'long_gate': 'close > EMA200',
                'short_gate': 'BTC Supertrend(10,3.5) bearish',
                'exit': '3.5xATR chandelier trail · opposite flip · 42-bar time stop',
                'initial_stop': '3xATR (min 2%)',
                'risk': '1% equity per trade — full when breadth >= 0.3, half below',
                'universe': 'top-100 volume + top-100 market cap (166 symbols)',
                'period': '2026-03-01 to 2026-08-31',
            },
        },
        'metrics': {'train': mwin('train'), 'valid': mwin('valid'),
                    'full': mwin('full')},
        'equity': equity,
        'drawdown': drawdown,
        'cost_stress': [
            {'label': '1x (0.16% RT)', 'return_pct': 193.9, 'pf': 1.372},
            {'label': '2x (0.32% RT)', 'return_pct': 144.8, 'pf': 1.301},
            {'label': '3x (0.48% RT)', 'return_pct': 103.9, 'pf': 1.234},
        ],
        'folds': [
            {'name': 'Mar-Apr (chop)', 'return_pct': -13.6, 'dd_pct': 20.2},
            {'name': 'May-Jun', 'return_pct': 86.4, 'dd_pct': 18.2},
            {'name': 'Jul-Aug', 'return_pct': 71.1, 'dd_pct': 16.2},
        ],
        'rounds': [
            {'round': 'R1', 'title': '8 strategy families swept (~110 configs)',
             'result': 'Only the Supertrend-trail family showed positive expectancy; production baseline (1:1 RR exits) loses on every timeframe.'},
            {'round': 'R2', 'title': 'Confluence + exit engineering',
             'result': 'Adopted: BTC-ST short gate, 42-bar time stop. Rejected: partial TPs, break-even, BTC-EMA gates, squeeze breakouts.'},
            {'round': 'R3', 'title': 'Filters, ensemble, robustness',
             'result': 'ADX/RSI filters lateral — rejected. Ensemble option (+Sharpe). Edge survives 3x costs; chop fold identified as the losing regime.'},
            {'round': 'R4', 'title': 'Cross-sectional ranking, seasonality, breadth',
             'result': 'Momentum ranking dead both polarities; daily-EMA gate failed OOS; weekday filter = noise. ADOPTED: breadth-scaled risk (Sharpe 1.98 -> 4.41, DD 29.5% -> 12.6%).'},
        ],
        'rejected': [
            {'idea': '30m EMA-cross (production)', 'reason': 'avg -0.73 R — worse than random entries'},
            {'idea': '1h timeframe (all families)', 'reason': 'best -0.03 R after ~80 configs; signal without enough edge to clear costs'},
            {'idea': 'Cross-sectional momentum ranking', 'reason': 'negative in both polarities on this universe'},
            {'idea': 'Partial take-profits', 'reason': 'truncates the fat right tail that pays for the strategy'},
            {'idea': 'Break-even stop', 'reason': 'exits pullbacks that become winners'},
            {'idea': 'ADX / RSI / volume / weekday / daily-EMA filters', 'reason': 'lateral or failed holdout validation'},
            {'idea': 'Donchian / Keltner / MACD / pullback / mean-reversion families', 'reason': 'negative expectancy after costs'},
        ],
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    print(f'wrote {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB)')


if __name__ == '__main__':
    main()
