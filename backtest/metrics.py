"""Metrics and the experiment ledger (experiments/experiments.csv).

Every backtest run appends one row to the ledger so any configuration can be
compared against the production baseline at any time.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

BACKTEST_DIR = Path(__file__).parent
LEDGER = BACKTEST_DIR / "experiments" / "experiments.csv"

LEDGER_COLUMNS = [
    'run_id', 'ts', 'timeframe', 'strategy', 'params', 'split',
    'symbols', 'trades', 'win_rate', 'avg_r', 'median_r', 'profit_factor',
    'total_return_pct', 'max_dd_pct', 'sharpe', 'avg_dur_h',
    'long_trades', 'short_trades', 'long_avg_r', 'short_avg_r',
    'exit_sl', 'exit_tp', 'exit_trail', 'exit_flip',
]


def compute_metrics(trades: pd.DataFrame, risk_frac: float = 0.01,
                    bar_hours: float = 1.0,
                    vol_target_atr: float | None = None) -> dict:
    """Aggregate pooled per-trade results into portfolio metrics.

    vol_target_atr: if set (e.g. 2.0), per-trade risk is scaled by
    target_atr / trade_atr_pct, clipped to [0.4x, 2.5x] and renormalized to
    mean 1x — a volatility-targeting overlay that reduces drawdown.
    """
    if trades.empty:
        return {'trades': 0}

    trades = trades.sort_values('exit_time').reset_index(drop=True)

    # per-trade risk weights
    if vol_target_atr is not None and 'atr_pct' in trades.columns:
        w = (vol_target_atr / trades['atr_pct'].clip(lower=0.1)).clip(0.4, 2.5)
        w = w / w.mean()
        risks = (risk_frac * w).to_numpy()
    else:
        risks = np.full(len(trades), risk_frac)

    # Compounded equity curve at fixed fractional risk
    eq = [1.0]
    for r, rf in zip(trades['net_r'], risks):
        eq.append(eq[-1] * (1.0 + rf * r))
    eq = np.array(eq)

    peak = np.maximum.accumulate(eq)
    dd = 1.0 - eq / peak
    max_dd = float(dd.max())

    # Daily equity curve for Sharpe (mark equity only at trade closes)
    close_times = pd.DatetimeIndex(trades['exit_time'])
    eq_series = pd.Series(eq[1:], index=close_times)
    daily = eq_series.resample('1D').last().ffill()
    daily_ret = daily.pct_change().dropna()
    sharpe = 0.0
    if daily_ret.std() > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(365))

    wins = trades['net_r'] > 0
    gross_win = trades.loc[wins, 'net_r'].sum()
    gross_loss = -trades.loc[~wins, 'net_r'].sum()

    dur_h = trades['bars_held'].mean()
    avg_dur_h = round(float(dur_h) * bar_hours, 1)

    longs = trades[trades['direction'] == 'LONG']
    shorts = trades[trades['direction'] == 'SHORT']

    return {
        'trades': int(len(trades)),
        'win_rate': round(float(wins.mean()) * 100, 2),
        'avg_r': round(float(trades['net_r'].mean()), 4),
        'median_r': round(float(trades['net_r'].median()), 4),
        'profit_factor': round(float(gross_win / gross_loss), 3) if gross_loss > 0 else float('inf'),
        'total_return_pct': round(float(eq[-1] - 1) * 100, 2),
        'max_dd_pct': round(max_dd * 100, 2),
        'sharpe': round(sharpe, 2),
        'avg_dur_h': avg_dur_h,
        'long_trades': int(len(longs)),
        'short_trades': int(len(shorts)),
        'long_avg_r': round(float(longs['net_r'].mean()), 4) if len(longs) else None,
        'short_avg_r': round(float(shorts['net_r'].mean()), 4) if len(shorts) else None,
        'exit_sl': int((trades['exit_reason'] == 'sl').sum()),
        'exit_tp': int((trades['exit_reason'] == 'tp').sum()),
        'exit_trail': int((trades['exit_reason'] == 'trail').sum()),
        'exit_flip': int((trades['exit_reason'] == 'flip').sum()),
    }


def log_experiment(timeframe: str, strategy: str, params: dict, split: str,
                   symbols: int, metrics: dict, run_id: str | None = None,
                   notes: str = '') -> str:
    """Append one run to the ledger; returns the run_id.

    The row is always reindexed to the canonical LEDGER_COLUMNS order so a
    metrics dict with missing keys can never shift appended CSV columns.
    """
    LEDGER.parent.mkdir(exist_ok=True)
    if run_id is None:
        import datetime
        run_id = (datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '_'
                  + f"{strategy[:24]}")
    row = {
        'run_id': run_id,
        'ts': pd.Timestamp.now(tz='UTC').isoformat(),
        'timeframe': timeframe,
        'strategy': strategy,
        'params': json.dumps(params, sort_keys=True),
        'split': split,
        'symbols': symbols,
        'notes': notes,
        **metrics,
    }
    df = pd.DataFrame([{c: row.get(c) for c in LEDGER_COLUMNS}])
    if LEDGER.exists():
        # align to the existing file's columns, whatever they are
        existing_cols = pd.read_csv(LEDGER, nrows=0).columns
        df = df.reindex(columns=existing_cols, fill_value=None)
        df.to_csv(LEDGER, mode='a', header=False, index=False)
    else:
        df.to_csv(LEDGER, index=False)
    return run_id
