"""Trade simulator.

Methodology (no lookahead):
- Strategies evaluate signals on CLOSED candles only; entry is at the NEXT
  candle's open.
- SL/TP hits are checked intrabar with high/low. If both SL and TP fall inside
  the same candle, SL is assumed to hit first (conservative). A bar that gaps
  through a stop fills at that bar's open, never at the better stop price.
- Costs: 0.05% taker fee per side + 0.03% slippage per side = 0.16% round trip.
- Per-trade accounting: each trade risks a fixed fraction of equity (default
  1%) -> equity impact = risk_frac * R. Trades are pooled across symbols and
  compounded in close-time order (concurrent positions approximated).
- Trailing stop: chandelier style — long stop ratchets up to
  (highest close since entry - trail_mult * ATR_entry); mirrored for shorts.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

FEE_PCT = 0.0005      # taker fee per side
SLIP_PCT = 0.0003     # slippage per side
COST_RT = 2 * (FEE_PCT + SLIP_PCT)   # 0.0016 round trip


@dataclass
class TradePlan:
    """One entry candidate emitted by a strategy (all prices relative).

    partials: list of (r_multiple, fraction) — scale out fractions of the
    position at fixed R multiples (measured on the ORIGINAL stop distance),
    remainder runs to the trail/flip/fixed exit. E.g. [(1.5, 0.5)] takes half
    off at +1.5R and trails the rest.
    """
    idx: int                 # signal candle index; entry is idx+1
    direction: int           # +1 long, -1 short
    sl_frac: float           # stop distance as fraction of entry (e.g. 0.03)
    tp_frac: float | None    # take-profit distance, None = no fixed TP
    exit_mode: str           # 'fixed' | 'trail' | 'flip'
    trail_mult: float = 3.0  # ATR multiple for 'trail' mode
    atr_entry: float = 0.0   # ATR at signal candle (for trail mode)
    time_stop_bars: int | None = None    # exit at close if trade ages this many bars
    breakeven_at_r: float | None = None  # after this much gross R, SL moves to entry
    partials: list | None = None         # [(r_mult, fraction), ...]
    atr_pct: float = 0.0                 # ATR% at signal candle (for vol-target sizing)


def simulate_symbol(df: pd.DataFrame, plans: list[TradePlan],
                    one_position: bool = True,
                    flip_dir: np.ndarray | None = None) -> list[dict]:
    """Resolve entry plans into trades.

    exit_mode:
      'fixed' — exit at sl_frac / tp_frac levels
      'trail' — chandelier ATR trail (tp_frac may be None)
      'flip'  — exit at next open after an opposite flip candle
                (requires flip_dir array of +1/-1/NaN per bar)
    """
    o = df['open'].to_numpy()
    h = df['high'].to_numpy()
    l = df['low'].to_numpy()
    c = df['close'].to_numpy()
    times = df.index
    n = len(df)

    # one-position tracking assumes chronological order
    plans = sorted(plans, key=lambda p: p.idx)

    trades = []
    busy_until = -1  # last index occupied by an open position (one_position)

    for plan in plans:
        ei = plan.idx + 1
        if ei >= n:
            continue
        if one_position and plan.idx <= busy_until:
            continue

        d = plan.direction
        entry = o[ei] * (1 + d * SLIP_PCT)
        sl_dist = plan.sl_frac
        sl = entry * (1 - d * sl_dist)
        tp = entry * (1 + d * plan.tp_frac) if plan.tp_frac else None

        trail_stop = None
        if plan.exit_mode == 'trail':
            trail_stop = entry - d * max(plan.trail_mult * plan.atr_entry,
                                         sl_dist * entry)

        # partial TP levels: (r_mult, fraction, price, filled?)
        parts = []
        for r_k, f_k in (plan.partials or []):
            parts.append([r_k, f_k, entry * (1 + d * r_k * sl_dist), False])

        be_armed = False
        exit_i = exit_px = reason = None

        def tranche_r(p):
            return (d * (p / entry - 1.0) - COST_RT) / sl_dist

        for i in range(ei, n):
            # 1) stop hit (conservative priority over everything). In trail
            #    mode the live level is the ratcheted chandelier — not the
            #    stale initial SL. A bar that GAPS through the stop fills at
            #    the bar's open (a real stop-market order fills on the gap),
            #    not at the stop price — only an intrabar pierce fills at
            #    the stop itself (matches the live PositionTracker).
            if trail_stop is not None:
                stop_lvl = max(sl, trail_stop) if d == 1 else min(sl, trail_stop)
                stop_hit = ((d == 1 and l[i] <= stop_lvl)
                            or (d == -1 and h[i] >= stop_lvl))
                stop_reason = 'trail'
            else:
                stop_lvl, stop_reason = sl, 'sl'
                stop_hit = ((d == 1 and l[i] <= sl)
                            or (d == -1 and h[i] >= sl))
            if stop_hit:
                fill = min(o[i], stop_lvl) if d == 1 else max(o[i], stop_lvl)
                exit_i, exit_px, reason = i, fill, stop_reason
                break
            # 2) partial scale-outs
            for pr in parts:
                if not pr[3] and ((d == 1 and h[i] >= pr[2]) or
                                  (d == -1 and l[i] <= pr[2])):
                    pr[3] = True
                    pr.append(tranche_r(pr[2] * (1 - d * SLIP_PCT)))
            # 3) fixed TP for the remainder
            if tp is not None and ((d == 1 and h[i] >= tp) or (d == -1 and l[i] <= tp)):
                exit_i, exit_px, reason = i, tp, 'tp'
                break
            # 4) trailing stop hit
            if trail_stop is not None and ((d == 1 and l[i] <= trail_stop) or
                                           (d == -1 and h[i] >= trail_stop)):
                exit_i, exit_px, reason = i, trail_stop, 'trail'
                break
            # 5) opposite flip exit (checked on closed candle)
            if flip_dir is not None and i > ei and flip_dir[i] == -d:
                if i + 1 < n:
                    exit_i = i + 1
                    exit_px = o[exit_i] * (1 - d * SLIP_PCT)
                else:
                    exit_i, exit_px = i, c[i]
                reason = 'flip'
                break
            # 6) time stop: exit at this bar's close
            if plan.time_stop_bars is not None and i - ei >= plan.time_stop_bars:
                exit_i, exit_px, reason = i, c[i] * (1 - d * SLIP_PCT), 'time'
                break
            # 7) advance chandelier trail from this bar's close
            if trail_stop is not None and plan.atr_entry > 0:
                candidate = c[i] - d * plan.trail_mult * plan.atr_entry
                trail_stop = max(trail_stop, candidate) if d == 1 \
                    else min(trail_stop, candidate)
            # 8) arm break-even once gross profit reaches breakeven_at_r * risk
            if plan.breakeven_at_r is not None and not be_armed:
                moved = d * (c[i] / entry - 1.0)
                if moved >= plan.breakeven_at_r * sl_dist:
                    sl = entry
                    be_armed = True

        if exit_i is None:
            exit_i, exit_px, reason = n - 1, c[-1], 'eod'
            if exit_i == ei:
                continue

        # aggregate: partial fills + remainder at the final exit
        net_r = 0.0
        taken = 0.0
        for pr in parts:
            if pr[3]:
                net_r += pr[1] * pr[4]
                taken += pr[1]
        rest = 1.0 - taken
        if rest > 1e-9:
            net_r += rest * tranche_r(exit_px)

        gross = d * (exit_px / entry - 1.0)
        trades.append({
            'symbol': df.attrs.get('symbol', '?'),
            'entry_time': times[ei],
            'exit_time': times[exit_i],
            'direction': 'LONG' if d == 1 else 'SHORT',
            'entry': entry,
            'exit': exit_px,
            'exit_reason': reason,
            'bars_held': exit_i - ei,
            'gross_r': gross / sl_dist,
            'net_r': net_r,
            'atr_pct': plan.atr_pct * 100,
        })
        busy_until = max(busy_until, exit_i)

    return trades
