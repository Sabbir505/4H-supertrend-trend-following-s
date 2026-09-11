"""
Binance futures credential check — read-only, safe.

Verifies, in order:
  1. futures API reachability + clock sync
  2. API key / secret present in .env
  3. key validity + signature (signed balance request)
  4. permissions: canTrade on/off, and whether WITHDRAWAL is enabled
     (it should NOT be — regenerate the key if it is)
  5. available USDT futures balance

Never prints the key or secret (only first-4/last-4 of the key).
Run:  python check_binance.py
"""

import hashlib
import hmac
import time
import urllib.parse

import requests
from config import Config

BASE = "https://fapi.binance.com"


def signed_get(cfg, path, params=None):
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 10000
    q = urllib.parse.urlencode(p, True)
    sig = hmac.new(cfg.binance_api_secret.encode(), q.encode(),
                   hashlib.sha256).hexdigest()
    r = requests.get(f"{BASE}{path}?{q}&signature={sig}",
                     headers={"X-MBX-APIKEY": cfg.binance_api_key}, timeout=10)
    return r


def mask(s):
    return f"{s[:4]}...{s[-4:]} ({len(s)} chars)" if s else "(missing)"


def main():
    cfg = Config()
    ok = True

    # 1) reachability + clock
    try:
        t0 = time.time()
        server = requests.get(f"{BASE}/fapi/v1/time", timeout=10).json()["serverTime"]
        off = server - int((t0 + time.time()) / 2 * 1000)
        print(f"[PASS] futures API reachable ({BASE})")
        print(f"[{'PASS' if abs(off) < 1000 else 'WARN'}] clock offset {off:+d} ms "
              f"({'ok' if abs(off) < 1000 else 'sync your Windows clock'})")
    except Exception as e:
        print(f"[FAIL] cannot reach {BASE}: {e}")
        return 1

    # 2) keys present
    if not cfg.binance_api_key or not cfg.binance_api_secret:
        print("[FAIL] BINANCE_API_KEY / BINANCE_API_SECRET missing in .env — "
              "add both lines, then re-run this check")
        return 1
    print(f"[PASS] key present: {mask(cfg.binance_api_key)}")
    print(f"[PASS] secret present: {mask(cfg.binance_api_secret)} (never printed)")

    # 3) signed request = key valid + signature correct + futures access
    r = signed_get(cfg, "/fapi/v2/balance")
    if r.status_code == 200:
        balances = [b for b in r.json() if float(b.get("balance", 0)) != 0]
        usdt = next((b for b in r.json() if b["asset"] == "USDT"), None)
        print("[PASS] API key valid — signed futures request accepted")
        if usdt:
            avail = float(usdt.get("availableBalance", 0))
            print(f"[INFO] USDT futures balance: available {avail:.2f}")
        for b in balances:
            print(f"[INFO] {b['asset']}: balance {float(b['balance']):.4f} "
                  f"(available {float(b.get('availableBalance', 0)):.4f})")
    elif r.status_code == 401 or "-2015" in r.text or "-2014" in r.text:
        print(f"[FAIL] key rejected ({r.text[:120]})")
        print("       causes: wrong key/secret pair, key deleted, IP whitelist "
              "restriction, or futures not enabled on the key")
        return 1
    else:
        print(f"[FAIL] unexpected response {r.status_code}: {r.text[:150]}")
        return 1

    # 4) permissions
    acc = signed_get(cfg, "/fapi/v2/account")
    if acc.status_code == 200:
        a = acc.json()
        can_trade = a.get("canTrade")
        can_wd = a.get("canWithdraw")
        print(f"[{'PASS' if can_trade else 'FAIL'}] canTrade: {can_trade}")
        if can_wd:
            print("[WARN] canWithdraw is ENABLED on this key — regenerate it "
                  "and create one with ONLY 'Enable Futures' (trading) permission")
        else:
            print("[PASS] canWithdraw: false (safe)")
        positions = [p for p in a.get("positions", [])
                     if float(p.get("positionAmt", 0)) != 0]
        print(f"[INFO] open futures positions: {len(positions)}")
        for p in positions:
            print(f"       {p['symbol']}: {p['positionAmt']} @ {p.get('entryPrice')}")

    print("\nSummary: " + ("READY — set EXECUTION_MODE=live in .env when you "
                          "want real orders (dry mode first is recommended)."
                          if ok else "issues found above."))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
