"""Incremental cache refresher: append new closed 4h bars to existing parquets.

The stock data_fetcher.py skips symbols whose parquet already exists, so the
cache silently goes stale as research continues. This script appends only the
missing tail (from each file's last open_time) — one request per symbol.

Usage:  python refresh_cache.py [interval]   (default 4h)
"""

import sys
import time
from pathlib import Path

import requests
import pandas as pd

CACHE = Path(__file__).parent / "data_cache"
BINANCE = "https://api.binance.com"
PAUSE = 0.12

COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore']


def fetch_tail(symbol: str, interval: str, start_ms: int):
    url = f"{BINANCE}/api/v3/klines"
    params = {'symbol': symbol, 'interval': interval,
              'startTime': start_ms, 'limit': 1000}
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code in (429, 418):
                time.sleep(30)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return None


def main():
    interval = sys.argv[1] if len(sys.argv) > 1 else "4h"
    out_dir = CACHE / interval
    files = sorted(out_dir.glob("*.parquet"))
    print(f"refreshing {len(files)} {interval} parquets ...")
    now = pd.Timestamp.now(tz="UTC")
    updated = failed = 0
    for i, f in enumerate(files, 1):
        try:
            df = pd.read_parquet(f)
            last = df.index.max()
            start_ms = int((last + pd.Timedelta(seconds=1)).timestamp() * 1000)
            if (now - last) < pd.Timedelta(hours=1):
                continue
            batch = fetch_tail(f.stem, interval, start_ms)
            if not batch:
                failed += 1
                continue
            new = pd.DataFrame(batch, columns=COLS)
            new['open_time'] = pd.to_datetime(new['open_time'], unit='ms', utc=True)
            new['close_time'] = pd.to_datetime(new['close_time'], unit='ms', utc=True)
            for c in ['open', 'high', 'low', 'close', 'volume']:
                new[c] = new[c].astype(float)
            new = new[new['close_time'] <= now]  # closed candles only
            new = new.set_index('open_time')[['open', 'high', 'low', 'close',
                                              'volume', 'close_time']]
            if new.empty:
                continue
            df = pd.concat([df, new])
            df = df[~df.index.duplicated(keep='first')].sort_index()
            df.to_parquet(f)
            updated += 1
        except Exception as e:
            failed += 1
            print(f"  {f.stem}: {e}")
        if i % 40 == 0:
            print(f"  [{i}/{len(files)}] updated={updated} failed={failed}")
        time.sleep(PAUSE)
    print(f"DONE: updated={updated} failed={failed}")


if __name__ == "__main__":
    main()
