"""
One-shot repair for data/trade_history.json + data/positions.json.

Between 2026-09-01 and 2026-09-06 the exit re-simulation seeded its replay
with the persisted trail stop (ratcheted through the newest candles), so old
bars were judged against a future stop level. That logged fake stop-outs
attributed to the entry bar with negative R while the positions were, by the
strategy's own rules, still open and in profit.

This script rebuilds every recorded trade causally from its entry signal
using the FIXED PositionTracker._evaluate_position logic and live Binance
candles:
  - trades whose causal replay produces an exit get the corrected record
  - trades with no causal exit yet are re-opened as virtual positions
  - records without an entry signal (the TUSDT fixture leak, entry=exit=100)
    are dropped
  - currently open positions are left untouched

Run once with the bot STOPPED:  python repair_trade_history.py
Originals are backed up beside the files before anything is overwritten.
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import Config
from scanner import CryptoScanner
from position_tracker import PositionTracker

TRADES_FILE = Path("data/trade_history.json")
POSITIONS_FILE = Path("data/positions.json")


def load_signals_index() -> dict:
    idx = {}
    for f in sorted(Path("data/signals").rglob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, list):
            for s in data:
                if isinstance(s, dict) and s.get("id"):
                    idx[s["id"]] = s
    return idx


def rebuild_position(sig: dict, cfg: Config) -> dict:
    """Reconstruct the position dict exactly as open_position() would have
    built it from this entry signal."""
    interval = sig.get("interval", "4h")
    flip_open = pd.Timestamp(sig["flip_candle_open"])
    return {
        "symbol": sig["symbol"],
        "direction": sig["direction"],
        "entry": sig["price"],
        "atr_entry": sig["atr"],
        "entry_bar_open": (flip_open + pd.Timedelta(interval)).isoformat(),
        "entry_time": sig["detected_at"],
        "entry_signal_id": sig.get("id"),
        "interval": interval,
        "risk_level": sig.get("risk_level", "full"),
        "risk_pct": sig.get("risk_pct"),
        "breadth_at_entry": sig.get("breadth"),
        "initial_stop": sig.get("initial_stop"),
        "trail_stop": sig.get("initial_stop"),
        "strategy": sig.get("strategy", "st_trail_v2"),
        "params": {
            "st_atr_period": cfg.supertrend_atr_period,
            "st_multiplier": cfg.supertrend_multiplier,
            "trail_atr_mult": cfg.trail_atr_mult,
            "initial_stop_atr_mult": cfg.initial_stop_atr_mult,
            "time_stop_bars": cfg.time_stop_bars,
            "breadth_threshold": cfg.breadth_threshold,
        },
    }


def atomic_save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, str(path))


def main() -> None:
    cfg = Config()
    scanner = CryptoScanner(cfg)
    tracker = PositionTracker.__new__(PositionTracker)
    tracker.config = cfg  # _evaluate_position only needs config

    trades = json.loads(TRADES_FILE.read_text(encoding="utf-8"))
    positions = (
        json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
        if POSITIONS_FILE.exists() else {}
    )
    signals = load_signals_index()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for p in (TRADES_FILE, POSITIONS_FILE):
        if p.exists():
            shutil.copy2(p, f"{p}.bak_{stamp}")
    print(f"Backups written with suffix .bak_{stamp}")

    df_cache = {}
    new_history = []       # corrected + kept records, original order
    reopened = {}          # symbol -> position dict (causal replay: still open)
    dropped, kept = [], []
    n_corrected = 0

    print(f"\nRebuilding {len(trades)} trades...\n")
    for t in trades:
        sym = t["symbol"]
        sig = signals.get(t.get("entry_signal_id"))
        if sig is None:
            dropped.append(sym)
            print(f"  DROP  {sym:12s} no entry signal for "
                  f"{t.get('entry_signal_id')} (old={t['net_r']:+.2f}R)")
            continue

        pos = rebuild_position(sig, cfg)
        if sym not in df_cache:
            df = scanner.fetch_candles(sym, "4h", limit=cfg.candle_fetch_limit)
            if df is None or len(df) == 0:
                kept.append(t)
                new_history.append(t)
                print(f"  KEEP  {sym:12s} candle fetch failed; original kept")
                continue
            df_cache[sym] = CryptoScanner.compute_supertrend(
                df, cfg.supertrend_atr_period, cfg.supertrend_multiplier)

        new = tracker._evaluate_position(pos, df_cache[sym])
        if new is None:
            # causal replay: the position never legitimately exited
            reopened[sym] = pos
            print(f"  REOPEN {sym:11s} no causal exit — was {t['net_r']:+.2f}R "
                  f"at {t['exit_time']}, actually still open "
                  f"(entry {pos['entry']})")
            continue

        changed = (abs(new["net_r"] - t["net_r"]) > 1e-9
                   or new["exit_time"] != t["exit_time"])
        tag = "FIX  " if changed else "OK   "
        n_corrected += changed
        new_history.append(new)
        print(f"  {tag} {sym:12s} {t['net_r']:+.2f}R @{t['exit']} "
              f"({t['exit_reason']}, {t['exit_time']}) -> "
              f"{new['net_r']:+.2f}R @{new['exit']} ({new['exit_reason']}, "
              f"{new['exit_time']})")

    # merge re-opened positions; live positions already in the file win
    added = [s for s in reopened if s not in positions]
    positions.update({s: reopened[s] for s in added})

    atomic_save(TRADES_FILE, new_history)
    atomic_save(POSITIONS_FILE, positions)

    print(f"\nDone. corrected={n_corrected} re-opened={len(added)} "
          f"kept={len(kept)} dropped={len(dropped)}")
    print(f"trade_history.json: {len(trades)} -> {len(new_history)} records; "
          f"positions.json: {len(positions)} open")


if __name__ == "__main__":
    sys.exit(main())
