"""One-off orphan cleanup (2026-09-29).

Removes virtual positions whose symbol has fallen out of the scan universe
for >= ORPHAN_ALERT_DAYS (no exit checks possible — the bot cannot trail,
flip-exit or time-stop them). Any REAL exchange position behind an orphan is
flattened at market and its resting stop cancelled, using the production
executor's own hardened paths.

Run ONLY while the bot is stopped (the running tracker would overwrite
positions.json from memory).

Usage:  python cleanup_orphans.py [--dry-run]
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from config import Config
from executor import FuturesExecutor

STALE_DAYS = 3


def main():
    dry = "--dry-run" in sys.argv
    cfg = Config()
    ex = FuturesExecutor(cfg)

    pos_path = ROOT / "data" / "positions.json"
    positions = json.loads(pos_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)

    orphans = []
    for sym, pos in positions.items():
        asof = pos.get("trail_stop_asof")
        if not asof:
            continue
        t = datetime.fromisoformat(asof)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        stale_days = (now - t).total_seconds() / 86400.0
        if stale_days >= STALE_DAYS:
            orphans.append((sym, pos, stale_days))

    print(f"orphan candidates (trail stale >= {STALE_DAYS}d): "
          f"{[s for s, _, _ in orphans]}")
    if not orphans:
        return

    live = {}
    if cfg.execution_mode == "live":
        rows = ex._signed("GET", "/fapi/v2/positionRisk", {})
        live = {r["symbol"]: r for r in rows
                if abs(float(r.get("positionAmt", 0) or 0)) > 0}
        print(f"exchange positions: {sorted(live)}")

    for sym, pos, days in orphans:
        print(f"\n--- {sym} (stale {days:.1f}d, entry {pos.get('entry')}, "
              f"last trail {pos.get('trail_stop')})")
        if sym not in live:
            print("    no exchange position (stop already fired / never "
                  "executed) — removing virtual record only")
            continue
        row = live[sym]
        amt = float(row["positionAmt"])
        upnl = row.get("unRealizedProfit")
        print(f"    exchange position {amt} @ entry {row.get('entryPrice')} "
              f"(unrealized PnL {upnl})")
        if dry:
            print("    dry-run: would cancel orders + market close")
            continue
        ex._qty_by_symbol[sym] = abs(amt)
        direction = pos.get("direction", "BUY")
        try:
            ok = ex._market_close(sym, direction)
            if ok:
                ex._cancel_symbol_orders(sym)
                print(f"    closed at market ({abs(amt)} contracts) and "
                      f"cancelled resting orders")
        except Exception as e:
            print(f"    CLOSE FAILED: {e} — virtual record KEPT, handle "
                  f"manually")
            continue

    if dry:
        print("\ndry-run: positions.json untouched")
        return
    removed = {s for s, _, _ in orphans
               if s not in live or True}   # remove record unless close failed
    # recompute: keep any orphan whose close raised (tracked in _qty_by_symbol)
    failed = {s for s in ex._qty_by_symbol}
    keep = {s: p for s, p in positions.items()
            if s not in removed or s in failed}
    pos_path.write_text(json.dumps(keep, indent=2), encoding="utf-8")
    print(f"\npositions.json: {len(positions)} -> {len(keep)} "
          f"(removed {sorted(set(removed) - failed)})")


if __name__ == "__main__":
    main()
