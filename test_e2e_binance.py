"""
End-to-end live test: proves the signal pipeline reaches Binance.

Uses the production FuturesExecutor (same code path as the bot) to:
  1. place a real MARKET entry (~$5 notional, isolated 5x)
  2. place the protective STOP_MARKET
  3. verify the position + stop exist on the exchange
  4. flatten (reduce-only close) and verify flat again

REAL MONEY: ~$5 notional, ~3% stop -> worst case ~$0.15 + fees.
Requires BINANCE_API_KEY and BINANCE_API_SECRET in .env.
Run:  python test_e2e_binance.py [SYMBOL]     (default DOGEUSDT)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import requests
from config import Config
from executor import FuturesExecutor

BASE = "https://fapi.binance.com"
SYMBOL = (sys.argv[1] if len(sys.argv) > 1 else "DOGEUSDT").upper()


def mask(s):
    return f"{s[:4]}...{s[-4:]}" if s else "(missing)"


def main():
    cfg = Config()
    cfg.execution_mode = "live"          # this test is explicitly live
    if not cfg.binance_api_key or not cfg.binance_api_secret:
        print("FAIL: BINANCE_API_KEY / BINANCE_API_SECRET missing in .env")
        return 1
    print(f"key: {mask(cfg.binance_api_key)}  mode: {cfg.execution_mode}")

    # current market price
    px = requests.get(f"{BASE}/fapi/v1/ticker/price",
                      params={"symbol": SYMBOL}, timeout=10).json()
    price = float(px["price"])
    print(f"[1] {SYMBOL} market price: {price}")

    # production executor, real orders
    ex = FuturesExecutor(cfg)
    pos = {"symbol": SYMBOL, "direction": "BUY", "entry": price,
           "initial_stop": round(price * 0.97, 8),   # stop 3% below
           "risk_pct": cfg.risk_pct_full}
    qty, sizing = ex._qty_for_position(SYMBOL, pos)
    if qty is None:
        print(f"FAIL: {SYMBOL} cannot be traded at this size ({sizing}) — "
              f"try another symbol")
        return 1
    print(f"[2] sizing: {sizing}")
    print(f"    quantity: {qty} (~${qty * price:.2f} notional @ "
          f"{cfg.execution_leverage}x)")

    print("[3] placing MARKET entry + protective stop ...")
    if not ex.open_position(pos):
        print("FAIL: executor could not open the position (see log above)")
        return 1

    time.sleep(3)

    # verify on the exchange: position + stop order
    pr = ex._signed("GET", "/fapi/v2/positionRisk", {"symbol": SYMBOL})
    live = [p for p in pr if float(p.get("positionAmt", 0)) != 0]
    if live:
        p = live[0]
        print(f"[4] VERIFIED on exchange: {p['symbol']} positionAmt="
              f"{p['positionAmt']} entry={p['entryPrice']} "
              f"leverage={p['leverage']}x marginType={p['marginType']} "
              f"uPnL={p.get('unRealizedProfit')}")
    else:
        print("WARN: no live position found on exchange (may have filled "
              "and instantly stopped?)")

    algo = ex._signed("GET", "/fapi/v1/openAlgoOrders", {"symbol": SYMBOL})
    if isinstance(algo, dict):
        algo = algo.get("orders", [])
    stops = [o for o in algo if o.get("orderType") == "STOP_MARKET"]
    print(f"[5] protective algo stop orders on exchange: {len(stops)}")
    for o in stops:
        print(f"    {o.get('orderType')} {o.get('side')} "
              f"stopPrice={o.get('stopPrice')} algoId={o.get('algoId')}")

    print("[6] flattening (cancel stop + reduce-only close) ...")
    ex.close_position(pos, reason="e2e test")
    time.sleep(3)

    pr2 = ex._signed("GET", "/fapi/v2/positionRisk", {"symbol": SYMBOL})
    live2 = [p for p in pr2 if float(p.get("positionAmt", 0)) != 0]
    algo2 = ex._signed("GET", "/fapi/v1/openAlgoOrders", {"symbol": SYMBOL})
    if isinstance(algo2, dict):
        algo2 = algo2.get("orders", [])
    if not live2 and not algo2:
        print("[7] VERIFIED: position flat, no open orders remain — "
              "END-TO-END OK")
        return 0
    print(f"WARN: residue — positions: {len(live2)}, open orders: {len(oo2)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
