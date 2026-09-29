"""Exit-engineering research lab (round 6).

Question (post Sep-28 stop-outs): the deployed system exits on a wick through
the 3xATR chandelier even while the Supertrend stays bullish. Would any of
these do better?

  V0 prod          deployed exits: wick stop (3xATR initial, 3.5xATR ratcheting
                   trail from ATR frozen at entry), flip exit, 42-bar time stop
  V1 flip_only     no stop — exit on opposite flip or 42-bar time stop
  V1b flip_pure    no stop, no time stop — literally "ride the ST flip"
  V2 flip_only_d6  no trail, only a static 6xATR disaster stop + flip/time
  V3 close_stop    stops evaluated on bar CLOSES (wick-tolerant), fill at the
                   trigger close — executable live as a scan-time market close
  V4 half_stop     first stop hit scales out 50%; remainder runs with the same
                   ratcheting stop (recovers on wick-and-reclaim, worst case -1R)
  V5 reentry_imm   deployed exits + immediate re-entry at next open after a
                   stop-out while the Supertrend still agrees (max 2)
  V6 reentry_brk   deployed exits + re-entry once a bar CLOSES above the
                   stop-exit bar's high while ST still agrees (max 2, 12 bars)
  V7 trail_roll    deployed but the chandelier ratchets from CURRENT ATR
                   (rolling) instead of ATR frozen at entry
  V8/V9            close_stop / half_stop combined with reentry_imm

Methodology mirrors engine.py exactly in prod mode (validated bar-for-bar
against engine.simulate_symbol before any variant runs): same entry plans
(st_trail + deployed entry filters), next-open entries, gap-through fills,
costs, one position per symbol, eod censoring. Portfolio math mirrors lab_eval
(breadth-scaled risk 0.5%/0.25%, exit-time compounding).

Usage:  python lab_x.py           # full run: validation + all variants
        python lab_x.py validate  # only the engine-parity check
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BT = Path(__file__).parent
sys.path.insert(0, str(BT))
sys.path.insert(0, str(BT.parent))

import indicators as ind
import engine
import strategies

CACHE = BT / "data_cache" / "4h"

# Evaluation window: the 3-year OOS of round 5b/5d, extended to today.
EVAL_START = pd.Timestamp("2023-10-01", tz="UTC")
TRAIN_END = pd.Timestamp("2025-04-01", tz="UTC")   # round-5d train/holdout split
RECENT_START = pd.Timestamp("2026-07-01", tz="UTC")

# Deployed live parameters (.env / config.py)
INIT_MULT = 3.0
INIT_FLOOR = 0.02
TRAIL_MULT = 3.5
TIME_STOP = 42
ATR_MIN, ATR_MAX = 0.5, 5.0          # ATR% entry band (live parity)
BREADTH_GATE = 0.15
RISK_FULL = 0.005                    # deployed full risk; half = 0.5x weight
BREADTH_THRESHOLD = 0.3

# Re-entry knobs
MAX_REENTRIES = 2
REENTRY_WINDOW = 12                  # bars to wait for a breakout re-entry
RECLAIM_WINDOW = 6                   # bars to wait for a reclaim re-entry

COST_RT = engine.COST_RT
SLIP = engine.SLIP_PCT

VARIANTS = (
    ("prod",         {}),
    ("flip_only",    {"stop_mode": "none"}),
    ("flip_pure",    {"stop_mode": "none", "time_stop": None}),
    ("flip_only_d6", {"stop_mode": "disaster", "disaster_mult": 6.0}),
    # live-feasible flips: at 5x isolated leverage liquidation hits ~-20%,
    # so the disaster stop distance is capped at 12% of entry
    ("flip_d6c12",   {"stop_mode": "disaster", "disaster_mult": 6.0,
                      "disaster_cap": 0.12}),
    ("close_stop",   {"stop_mode": "close"}),
    # live-feasible close-stop: no resting order while waiting for the close,
    # so a 12%-capped disaster stop guards against intrabar liquidation
    ("close_stop_d", {"stop_mode": "close_disaster", "disaster_mult": 6.0,
                      "disaster_cap": 0.12}),
    ("close_stop_roll", {"stop_mode": "close", "trail_atr": "rolling"}),
    ("half_stop",    {"stop_mode": "half"}),
    ("reentry_imm",  {"reentry": "immediate"}),
    ("reentry_brk",  {"reentry": "breakout"}),
    ("reentry_recl", {"reentry": "reclaim"}),
    ("trail_roll",   {"trail_atr": "rolling"}),
    ("close_stop_re", {"stop_mode": "close", "reentry": "immediate"}),
    ("half_stop_re",  {"stop_mode": "half", "reentry": "immediate"}),
)


# ── shared context: breadth + BTC regime (causal, lab_eval convention) ──────

def breadth_series() -> pd.Series:
    closes, above = {}, {}
    for f in sorted(CACHE.glob("*.parquet")):
        df = pd.read_parquet(f, columns=["close"])
        e = ind.ema(df["close"], 200)
        closes[f.stem] = df["close"]
        above[f.stem] = (df["close"] > e).astype(float)
    above_df = pd.DataFrame(above)
    n = above_df.notna().sum(axis=1)
    raw = above_df.sum(axis=1) / n.replace(0, np.nan)
    return raw.shift(1).dropna()


def btc_st_series() -> pd.DataFrame:
    """BTC Supertrend(10,3.5) direction keyed by close_time (dataset.py
    convention: a bar's known BTC direction is the last CLOSED btc candle)."""
    b = pd.read_parquet(CACHE / "BTCUSDT.parquet")
    _, d = ind.supertrend(b, 10, 3.5)
    return pd.DataFrame({"close_time": b["close_time"].to_numpy(),
                         "dir": d}).sort_values("close_time")


# ── entry plans (st_trail + deployed entry filters) ─────────────────────────

def build_plans(df: pd.DataFrame, btc_dir: np.ndarray,
                breadth_known: np.ndarray, deployed_filters: bool = True):
    """Entry set: ST flip; longs close>EMA200; shorts BTC-ST bearish; ATR%
    band; Sunday flip-candle skip. With deployed_filters=True (production
    parity) also applies the breadth gate and quality tiers A/B. Returns
    (plans, supertrend_dir); plans carry the entry breadth for risk weighting."""
    st, dirv = ind.supertrend(df, 10, 3.5)
    prev = dirv.shift(1)
    flip_long = (prev == -1) & (dirv == 1)
    flip_short = (prev == 1) & (dirv == -1)

    a = ind.atr(df, 14)
    atr_pct = a / df["close"] * 100
    ema200 = ind.ema(df["close"], 200)

    band = (atr_pct >= ATR_MIN) & (atr_pct <= ATR_MAX)
    longs = flip_long & band & (df["close"] > ema200)
    shorts = flip_short & band & (btc_dir == -1)

    # Sunday flip-candle skip: always on (deployed via SKIP_SUNDAY_ENTRIES;
    # the engine parity run applies the same rule through its `days` param)
    sunday = df.index.dayofweek == 6
    longs &= ~sunday
    shorts &= ~sunday

    if deployed_filters:
        # breadth gate (deployed, causal series)
        gate = pd.Series(breadth_known, index=df.index) >= BREADTH_GATE
        longs &= gate
        shorts &= gate

    plans = []
    for i in np.flatnonzero(longs.to_numpy()):
        af = a.iat[i] / df["close"].iat[i]
        if np.isnan(af) or af <= 0:
            continue
        b = breadth_known[i]
        if deployed_filters and \
                (not np.isfinite(b) or b < BREADTH_THRESHOLD):   # quality A
            continue
        plans.append({"idx": int(i), "direction": 1,
                      "sl_frac": max(INIT_MULT * af, INIT_FLOOR),
                      "atr_entry": float(a.iat[i]),
                      "breadth": float(b) if np.isfinite(b) else 0.3})
    for i in np.flatnonzero(shorts.to_numpy()):
        af = a.iat[i] / df["close"].iat[i]
        if np.isnan(af) or af <= 0:
            continue
        b = breadth_known[i]
        if deployed_filters and not (np.isfinite(b) and
                                     (b < BREADTH_THRESHOLD or b >= 0.5)):
            continue                                      # quality B
        plans.append({"idx": int(i), "direction": -1,
                      "sl_frac": max(INIT_MULT * af, INIT_FLOOR),
                      "atr_entry": float(a.iat[i]),
                      "breadth": float(b) if np.isfinite(b) else 0.3})
    plans.sort(key=lambda p: p["idx"])
    return plans, dirv.to_numpy()


# ── simulator (engine.py parity + variant modes) ────────────────────────────

def simulate(df: pd.DataFrame, plans: list, dirv: np.ndarray,
             stop_mode: str = "wick", disaster_mult: float = 6.0,
             disaster_cap: float | None = None, trail_atr: str = "frozen",
             reentry: str = "none", time_stop: int | None = TIME_STOP,
             atr_arr: np.ndarray | None = None) -> list[dict]:
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    times = df.index
    n = len(df)
    atr_arr = atr_arr if atr_arr is not None else ind.atr(df, 14).to_numpy()

    trades = []
    busy_until = -1

    def run_leg(entry_i: int, direction: int, sl_frac: float,
                atr_entry: float, reentry_no: int, orig_idx: int):
        """One position leg. Entry fills at bar entry_i's open. Returns
        (trade|None, exit_i, reason). None = eod on the entry bar (skipped,
        engine parity)."""
        nonlocal busy_until
        d = direction
        entry = o[entry_i] * (1 + d * SLIP)
        sl = entry * (1 - d * sl_frac)
        trail_stop = entry - d * max(TRAIL_MULT * atr_entry, sl_frac * entry)

        half_r = None
        exit_i = exit_px = reason = None
        exit_lvl = None
        disaster = None
        if stop_mode in ("disaster", "close_disaster"):
            dist = disaster_mult * atr_entry
            if disaster_cap:
                dist = min(dist, disaster_cap * entry)
            disaster = entry - d * dist

        def chand_now():
            if stop_mode in ("none", "disaster"):
                return None
            return max(sl, trail_stop) if d == 1 else min(sl, trail_stop)

        i = entry_i
        while i < n:
            # 1) disaster wick guard (flip_d6c12 / close_stop_d): a static
            #    stop that fires before the ~20% liquidation at 5x leverage
            if disaster is not None and \
                    ((d == 1 and l[i] <= disaster) or
                     (d == -1 and h[i] >= disaster)):
                exit_i = i
                exit_px = min(o[i], disaster) if d == 1 else max(o[i], disaster)
                reason, exit_lvl = "stop", disaster
                break
            lvl = chand_now()
            # 2) chandelier stop: wick modes fire intrabar (engine parity),
            #    close modes only on a committed close (scan-time market close)
            if lvl is not None and stop_mode in ("wick", "half") and \
                    ((d == 1 and l[i] <= lvl) or (d == -1 and h[i] >= lvl)):
                fill = min(o[i], lvl) if d == 1 else max(o[i], lvl)
                if stop_mode == "half" and half_r is None:
                    # scale out half at the stop; the remainder keeps running
                    # with the same ratcheting stop (may re-trigger later)
                    half_r = (d * (fill / entry - 1.0) - COST_RT) / sl_frac
                    exit_lvl = lvl
                else:
                    exit_i, exit_px, reason, exit_lvl = i, fill, "stop", lvl
                    break
            elif lvl is not None and stop_mode in ("close", "close_disaster") \
                    and ((d == 1 and c[i] <= lvl) or (d == -1 and c[i] >= lvl)):
                exit_i = i
                exit_px = c[i] * (1 - d * SLIP)
                reason, exit_lvl = "stop_close", lvl
                break
            # 3) opposite flip on a closed candle -> exit at next open
            if i > entry_i and dirv[i] == -d:
                if i + 1 < n:
                    exit_i = i + 1
                    exit_px = o[i + 1] * (1 - d * SLIP)
                else:
                    exit_i, exit_px = i, c[i] * (1 - d * SLIP)
                reason = "flip"
                break
            # 4) time stop
            if time_stop is not None and i - entry_i >= time_stop:
                exit_i, exit_px = i, c[i] * (1 - d * SLIP)
                reason = "time"
                break
            # 5) ratchet the chandelier from this bar's close
            if trail_atr == "rolling":
                atr_i = atr_arr[i]
                if np.isfinite(atr_i) and atr_i > 0:
                    cand = c[i] - d * TRAIL_MULT * atr_i
                    trail_stop = max(trail_stop, cand) if d == 1 \
                        else min(trail_stop, cand)
            else:
                cand = c[i] - d * TRAIL_MULT * atr_entry
                trail_stop = max(trail_stop, cand) if d == 1 \
                    else min(trail_stop, cand)
            i += 1

        if exit_i is None:
            exit_i = n - 1
            exit_px = c[-1]                     # engine parity: eod, no slip
            reason = "eod"
            if exit_i == entry_i:
                return None, exit_i, reason, exit_lvl

        gross = d * (exit_px / entry - 1.0)
        net_r = (gross - COST_RT) / sl_frac
        if half_r is not None:
            # half booked at the stop; remainder at the final exit
            net_r = 0.5 * half_r + 0.5 * net_r

        tr = {"entry_time": times[entry_i], "exit_time": times[exit_i],
              "direction": "LONG" if d == 1 else "SHORT",
              "entry": entry, "exit": exit_px, "exit_reason": reason,
              "exit_lvl": exit_lvl, "bars_held": exit_i - entry_i,
              "gross_r": gross / sl_frac, "net_r": net_r,
              "reentry_no": reentry_no, "orig_idx": orig_idx}
        busy_until = max(busy_until, exit_i)
        return tr, exit_i, reason, exit_lvl

    for plan in plans:
        ei = plan["idx"] + 1
        if ei >= n:
            continue
        if plan["idx"] <= busy_until:
            continue
        d = plan["direction"]
        re_no = 0
        cur_entry, cur_sl_frac, cur_atr = ei, plan["sl_frac"], plan["atr_entry"]
        first_entry = ei
        while True:
            tr, exit_i, reason, exit_lvl = run_leg(
                cur_entry, d, cur_sl_frac, cur_atr, re_no, plan["idx"])
            if tr is not None:
                trades.append(tr)
            if reason not in ("stop", "stop_close") or reentry == "none" \
                    or re_no >= MAX_REENTRIES:
                break
            if exit_i >= n - 1 or dirv[exit_i] != d:
                break                           # trend no longer agrees
            if reentry == "immediate":
                nxt = exit_i + 1
            elif reentry == "reclaim":
                # re-enter only after a bar CLOSES back through the stop
                # level that knocked us out (trend-line reclaimed)
                k = None
                for kk in range(exit_i + 1,
                                min(exit_i + 1 + RECLAIM_WINDOW, n)):
                    if dirv[kk] == -d:
                        break
                    back = c[kk] > exit_lvl if d == 1 else c[kk] < exit_lvl
                    if back:
                        k = kk
                        break
                if k is None or k + 1 >= n or dirv[k] != d:
                    break
                nxt = k + 1
            else:                               # breakout re-entry
                k = None
                for kk in range(exit_i + 1,
                                min(exit_i + 1 + REENTRY_WINDOW, n)):
                    if dirv[kk] == -d:
                        break
                    if c[kk] > h[exit_i]:
                        k = kk
                        break
                if k is None or k + 1 >= n or dirv[k] != d:
                    break
                nxt = k + 1
            if nxt <= busy_until or nxt >= n:
                break
            # re-anchor risk to the re-entry signal bar (fresh ATR, same rules
            # as a fresh entry: vol band must pass)
            sig = nxt - 1
            af = atr_arr[sig] / c[sig] if c[sig] > 0 else np.nan
            if not np.isfinite(af) or af <= 0:
                break
            if not (ATR_MIN <= af * 100 <= ATR_MAX):
                break
            re_no += 1
            cur_entry = nxt
            cur_sl_frac = max(INIT_MULT * af, INIT_FLOOR)
            cur_atr = float(atr_arr[sig])

    return trades


# ── portfolio math (lab_eval parity) ────────────────────────────────────────

def portfolio(trades: pd.DataFrame, weights: np.ndarray, risk: float) -> dict:
    if trades.empty:
        return {"trades": 0, "ret": 0.0, "dd": 0.0, "sharpe": 0.0,
                "avg_r": 0.0, "pf": 0.0, "win": 0.0}
    order = np.argsort(pd.DatetimeIndex(trades["exit_time"]).to_numpy(),
                       kind="stable")
    t = trades.iloc[order].reset_index(drop=True)
    w = np.asarray(weights)[order]
    eq = [1.0]
    for r, rf in zip(t["net_r"], w):
        eq.append(eq[-1] * (1.0 + risk * rf * r))
    eq = np.array(eq)
    peak = np.maximum.accumulate(eq)
    dd = float((1.0 - eq / peak).max())
    s = pd.Series(eq[1:], index=pd.DatetimeIndex(t["exit_time"]))
    daily = s.resample("1D").last().ffill()
    dr = daily.pct_change().dropna()
    sharpe = float(dr.mean() / dr.std() * np.sqrt(365)) if dr.std() > 0 else 0.0
    wins = t["net_r"] > 0
    gw, gl = t.loc[wins, "net_r"].sum(), -t.loc[~wins, "net_r"].sum()
    return {"trades": int(len(t)), "ret": round((eq[-1] - 1) * 100, 1),
            "dd": round(dd * 100, 1), "sharpe": round(sharpe, 2),
            "avg_r": round(float(t["net_r"].mean()), 4),
            "pf": round(float(gw / gl), 2) if gl > 0 else float("inf"),
            "win": round(float(wins.mean()) * 100, 1)}


# ── driver ──────────────────────────────────────────────────────────────────

def load_symbol(sym: str, breadth: pd.Series, btc: pd.DataFrame):
    df = pd.read_parquet(CACHE / f"{sym}.parquet")
    d = df.reset_index().sort_values("close_time")
    merged = pd.merge_asof(d, btc, left_on="close_time",
                           right_on="close_time", direction="backward")
    btc_dir = merged["dir"].to_numpy()
    bk = breadth.reindex(df.index, method="ffill").to_numpy()
    df.attrs["symbol"] = sym
    return df, btc_dir, bk


def validate_engine_parity(symbols: list[str], breadth, btc) -> bool:
    """lab_x.simulate in prod mode must equal engine.simulate_symbol exactly."""
    params = dict(st_period=10, st_mult=3.5, trail_mult=TRAIL_MULT, ema=200,
                  short_mode="btc_st", time_stop_bars=TIME_STOP,
                  atr_min=ATR_MIN, atr_max=ATR_MAX, init_mult=INIT_MULT,
                  init_floor=INIT_FLOOR, days=[0, 1, 2, 3, 4, 5])
    bad = 0
    for sym in symbols:
        df, btc_dir, bk = load_symbol(sym, breadth, btc)
        plans_x, _ = build_plans(df, btc_dir, bk, deployed_filters=False)
        dfe = df.copy()
        dfe["btc_st_dir"] = btc_dir      # Dataset attaches this for the engine
        plans_e, dirv_e = strategies.st_trail(dfe, params)
        if len(plans_x) != len(plans_e):
            print(f"  {sym}: PLAN COUNT lab_x={len(plans_x)} "
                  f"engine={len(plans_e)}")
            bad += 1
            continue
        tr_x = simulate(df, plans_x, dirv_e)
        tp = [engine.TradePlan(idx=p["idx"], direction=p["direction"],
                               sl_frac=p["sl_frac"], tp_frac=None,
                               exit_mode="trail", trail_mult=TRAIL_MULT,
                               atr_entry=p["atr_entry"],
                               time_stop_bars=TIME_STOP) for p in plans_x]
        tr_e = engine.simulate_symbol(df, tp, flip_dir=dirv_e)
        if len(tr_x) != len(tr_e):
            print(f"  {sym}: TRADE COUNT lab_x={len(tr_x)} "
                  f"engine={len(tr_e)}")
            bad += 1
            continue
        for tx, te in zip(tr_x, tr_e):
            for key in ("entry_time", "exit_time"):
                if pd.Timestamp(tx[key]) != pd.Timestamp(te[key]):
                    print(f"  {sym}: {key} {tx[key]} vs {te[key]}")
                    bad += 1
            for key in ("entry", "exit", "net_r", "bars_held"):
                if abs(float(tx[key]) - float(te[key])) > 1e-9:
                    print(f"  {sym}: {key} {tx[key]} vs {te[key]}")
                    bad += 1
    print(f"parity check: {'PASS' if bad == 0 else f'{bad} MISMATCHES'} "
          f"({len(symbols)} symbols)")
    return bad == 0


def main():
    do_validate = "validate" in sys.argv
    t0 = time.time()
    breadth = breadth_series()
    btc = btc_st_series()
    print(f"context ready in {time.time()-t0:.0f}s ({len(breadth)} breadth bars)")

    symbols = sorted(p.stem for p in CACHE.glob("*.parquet"))

    if do_validate:
        sys.exit(0 if validate_engine_parity(symbols[:25], breadth, btc) else 1)

    data = {}
    t0 = time.time()
    for sym in symbols:
        df, btc_dir, bk = load_symbol(sym, breadth, btc)
        plans, dirv = build_plans(df, btc_dir, bk)
        atr_arr = ind.atr(df, 14).to_numpy()
        data[sym] = (df, plans, dirv, atr_arr)
    bmap = {}
    for sym, (_, plans, _, _) in data.items():
        for p in plans:
            bmap[(sym, p["idx"])] = p["breadth"]
    print(f"loaded {len(data)} symbols, {sum(len(v[1]) for v in data.values())} "
          f"plans in {time.time()-t0:.0f}s")

    all_rows, cohort_rows, reasons = [], [], {}
    cohort_syms = {"ETHFIUSDT", "SYRUPUSDT", "JTOUSDT"}

    for name, cfg in VARIANTS:
        trades = []
        t0 = time.time()
        for sym, (df, plans, dirv, atr_arr) in data.items():
            for tr in simulate(df, plans, dirv, atr_arr=atr_arr, **cfg):
                tr["symbol"] = sym
                trades.append(tr)
        tdf = pd.DataFrame(trades)
        if tdf.empty:
            continue
        b = np.array([bmap.get((s, int(oi)), 0.3)
                      for s, oi in zip(tdf["symbol"], tdf["orig_idx"])])
        w = np.where(b >= BREADTH_THRESHOLD, 1.0, 0.5)
        et = pd.DatetimeIndex(tdf["entry_time"])
        # cohort = all legs whose ORIGINAL entry falls on Sep 26-27
        orig_et = pd.DatetimeIndex(
            tdf["entry_time"] - pd.to_timedelta(0, unit="h"))
        is_coh = tdf["symbol"].isin(cohort_syms) & \
            (tdf["reentry_no"] == 0) & (et >= pd.Timestamp("2026-09-26", tz="UTC")) \
            & (et < pd.Timestamp("2026-09-28", tz="UTC"))
        coh_keys = set(zip(tdf.loc[is_coh, "symbol"],
                           tdf.loc[is_coh, "orig_idx"]))
        coh_mask = [((s, oi) in coh_keys)
                    for s, oi in zip(tdf["symbol"], tdf["orig_idx"])]
        for _, t in tdf[coh_mask].iterrows():
            cohort_rows.append({
                "variant": name, "symbol": t["symbol"],
                "dir": t["direction"], "re": t["reentry_no"],
                "entry": round(float(t["entry"]), 5),
                "exit": round(float(t["exit"]), 5),
                "reason": t["exit_reason"],
                "entry_time": str(t["entry_time"])[:16],
                "exit_time": str(t["exit_time"])[:16],
                "net_r": round(float(t["net_r"]), 3)})
        for wname, mask in (("full", np.ones(len(tdf), bool)),
                            ("train", et < TRAIN_END),
                            ("holdout", et >= TRAIN_END),
                            ("recent", et >= RECENT_START)):
            m = portfolio(tdf[mask].reset_index(drop=True), w[mask], RISK_FULL)
            all_rows.append({"variant": name, "window": wname, **m})
        reasons[name] = tdf["exit_reason"].value_counts().to_dict()
        print(f"[{name}] {len(tdf)} trades in {time.time()-t0:.0f}s")

    res = pd.DataFrame(all_rows)
    res.to_csv(BT / "results" / "lab_x_summary.csv", index=False)
    print("\n=== full / train / holdout / recent : ret% / dd% / sharpe ===")
    for name, _ in VARIANTS:
        row = res[res["variant"] == name].set_index("window")
        cells = []
        for wname in ("full", "train", "holdout", "recent"):
            r = row.loc[wname]
            cells.append(f"{wname} {r['ret']:+.0f}/{r['dd']:.0f}/"
                         f"{r['sharpe']:.2f} n={int(r['trades'])} "
                         f"avgR={r['avg_r']:+.3f} pf={r['pf']}")
        print(f"{name:14s} " + " | ".join(cells))
    print("\n=== exit reasons (full window) ===")
    for name, vc in reasons.items():
        print(f"{name:14s} {vc}")
    cdf = pd.DataFrame(cohort_rows)
    cdf.to_csv(BT / "results" / "lab_x_cohort.csv", index=False)
    print("\n=== Sep-26 cohort (ETHFI/SYRUP/JTO) under each variant ===")
    print(cdf.to_string(index=False))


if __name__ == "__main__":
    main()
