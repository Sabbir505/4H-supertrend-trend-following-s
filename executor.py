"""
Binance USDT-M futures executor for the 4H Supertrend bot.

Turns the bot's virtual positions into real futures orders:

  entry   MARKET order at signal time (the scan runs 5 minutes after the
          candle closes, so this matches the backtest's next-open entry),
          then a STOP_MARKET reduce-only closePosition stop at the initial
          stop level
  trail   each scan the PositionTracker ratchets the chandelier trail; the
          exchange stop is re-placed at the new level (cancel + replace)
  exit    on tracker exit (trail/flip/time): cancel open stop + MARKET
          reduce-only close

Safety model (round-5c small-account study, REPORT §6f):
  - EXECUTION_MODE gates everything: off (default) / dry (log only) / live
  - leverage hard-capped at 5x, margin type always ISOLATED
  - hard cap on concurrent positions (EXECUTION_MAX_POSITIONS)
  - fixed margin per position (EXECUTION_MARGIN_USDT) -> notional = margin x lev
  - quantities rounded DOWN to the symbol's step size; orders below the
    exchange's minQty / minNotional are skipped with a log line (BTC's
    0.001-lot minimum cannot be met at this size — BTC entries are skipped)
  - a failed stop placement right after entry flattens the position
    immediately — the bot never leaves a naked entry
  - every failure is logged and surfaced via the Telegram error alert;
    executor methods never raise into the scan loop

No third-party exchange library: requests + HMAC, matching the codebase.
"""

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)


class BinanceFuturesError(Exception):
    pass


def _is_code(err: Exception, code: str) -> bool:
    return f'"{code}"' in str(err) or code in str(err)


class FuturesExecutor:
    def __init__(self, config, telegram=None, session=None):
        self.config = config
        self.telegram = telegram
        self.mode = config.execution_mode           # off | dry | live
        self.enabled = self.mode in ("dry", "live")
        self.base_url = config.futures_base_url
        self._session = session or requests.Session()
        self._symbol_filters = {}                   # symbol -> LOT_SIZE/NOTIONAL
        self._leverage_set = set()                  # symbols configured already
        self._last_stop = {}                        # symbol -> stop we placed
        self._time_off = 0                          # Binance server-time offset (ms)
        self._algo_place_path = None                # discovered Algo Order endpoint
        self._algo_id_by_symbol = {}                # symbol -> algoId of our stop
        self._qty_by_symbol = {}                    # symbol -> tracked qty
        self.open_count = 0                         # executor-tracked positions
        if self.mode == "live":
            logger.info("Executor LIVE: %dx leverage, $%s margin/position, "
                        "max %d positions, isolated",
                        config.execution_leverage,
                        config.execution_margin_usdt,
                        config.execution_max_positions)
        elif self.mode == "dry":
            logger.info("Executor DRY-RUN: orders will be logged, not sent "
                        "(set EXECUTION_MODE=live to trade)")

    # ── transport ────────────────────────────────────────────────────────

    def _time_offset(self) -> int:
        """Offset (ms) between Binance server time and the local clock, so a
        drifting Windows clock can't trip Binance's recvWindow checks."""
        server = self._session.get(f"{self.base_url}/fapi/v1/time",
                                   timeout=10).json()["serverTime"]
        self._time_off = server - int(time.time() * 1000)
        return self._time_off

    def _signed(self, method: str, path: str, params: dict) -> dict:
        """Signed request to the futures API. Returns the JSON response.
        Auto-resyncs the clock offset and retries once on -1021."""
        def send():
            params["timestamp"] = int(time.time() * 1000) + self._time_off
            params["recvWindow"] = 10000
            query = urlencode(params, True)
            sig = hmac.new(self.config.binance_api_secret.encode("utf-8"),
                           query.encode("utf-8"), hashlib.sha256).hexdigest()
            url = f"{self.base_url}{path}?{query}&signature={sig}"
            return self._session.request(method, url,
                                         headers={"X-MBX-APIKEY": self.config.binance_api_key},
                                         timeout=10)
        params = dict(params or {})
        resp = send()
        if resp.status_code == 400 and "-1021" in resp.text:
            self._time_off = self._time_offset()   # clock drifted: resync
            resp = send()
        if resp.status_code >= 400:
            raise BinanceFuturesError(
                f"{method} {path} -> {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def _alert(self, context: str, err: Exception):
        logger.error("Executor %s failed: %s", context, err)
        if self.telegram is not None:
            try:
                self.telegram.send_error_alert(f"executor: {context}", err)
            except Exception:
                logger.exception("Failed to send executor error alert")

    # ── symbol setup ─────────────────────────────────────────────────────

    def _filters(self, symbol: str) -> dict | None:
        """LOT_SIZE / MIN_NOTIONAL filters for a symbol (cached)."""
        if symbol in self._symbol_filters:
            return self._symbol_filters[symbol]
        try:
            info = self._signed("GET", "/fapi/v1/exchangeInfo", {})
            for s in info.get("symbols", []):
                if s.get("symbol") != symbol:
                    continue
                filters = {}
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        filters["step_size"] = float(f["stepSize"])
                        filters["min_qty"] = float(f["minQty"])
                    elif f["filterType"] == "MIN_NOTIONAL":
                        filters["min_notional"] = float(f["notional"])
                    elif f["filterType"] == "PRICE_FILTER":
                        filters["tick_size"] = float(f["tickSize"])
                self._symbol_filters[symbol] = filters
                return filters
            logger.warning("Symbol %s not found on futures — skipping", symbol)
            self._symbol_filters[symbol] = None
            return None
        except Exception as e:
            self._alert(f"exchangeInfo({symbol})", e)
            return None

    def _qty_for_notional(self, symbol: str, price: float) -> float | None:
        """Quantity for the configured notional, snapped to the symbol's step
        size. When the rounded-down quantity lands below the exchange's
        minQty / minNotional (common when the planned notional is close to
        the $5 floor), it is bumped UP to the smallest tradable quantity —
        otherwise almost every signal would be untradeable. Returns None
        only when even that cannot satisfy the filters (e.g. BTC's 0.001
        lot = ~$78)."""
        f = self._filters(symbol)
        if f is None or price <= 0:
            return None
        notional = self.config.execution_margin_usdt * \
            self.config.execution_leverage
        step = f.get("step_size", 0.001)
        min_qty = f.get("min_qty", 0.0)
        min_notional = f.get("min_notional", 5.0)

        raw = notional / price
        qty = round(int(raw / step) * step, 10)
        if qty < min_qty or qty * price < min_notional:
            qty = round((int(raw / step) + 1) * step, 10)   # bump up one step
            if qty < min_qty:
                qty = round(min_qty, 10)
        if qty < min_qty or qty * price < min_notional:
            logger.info("Skip %s: smallest tradable qty %s = $%.2f, below "
                        "minimums (minQty %s, minNotional %s)",
                        symbol, qty, qty * price, min_qty, min_notional)
            return None
        return qty

    def _setup_symbol(self, symbol: str):
        """One-time leverage + isolated margin per symbol."""
        if symbol in self._leverage_set:
            return
        self._signed("POST", "/fapi/v1/leverage",
                     {"symbol": symbol,
                      "leverage": self.config.execution_leverage})
        try:
            self._signed("POST", "/fapi/v1/marginType",
                         {"symbol": symbol, "marginType": "ISOLATED"})
        except BinanceFuturesError as e:
            if not _is_code(e, "-4046"):   # "No need to change margin type"
                raise
        self._leverage_set.add(symbol)
        logger.info("Symbol %s set: %dx leverage, isolated",
                    symbol, self.config.execution_leverage)

    # ── order actions ────────────────────────────────────────────────────

    def _cancel_symbol_orders(self, symbol: str):
        """Cancel every working order for the symbol: legacy open orders AND
        Algo Service conditional orders (the 2025-12-09 migration moved
        STOP_MARKET to the Algo API — see REPORT.md / error -4120)."""
        try:
            self._signed("DELETE", "/fapi/v1/allOpenOrders",
                         {"symbol": symbol})
        except BinanceFuturesError as e:
            if not _is_code(e, "-2011"):
                raise
        try:
            algo = self._signed("GET", "/fapi/v1/openAlgoOrders",
                                {"symbol": symbol})
            for o in algo if isinstance(algo, list) else algo.get("orders", []):
                try:
                    self._signed("DELETE", "/fapi/v1/algoOrder",
                                 {"symbol": symbol,
                                  "algoId": o.get("algoId")})
                except BinanceFuturesError as e:
                    if not _is_code(e, "-2011") and not _is_code(e, "-2013"):
                        raise
        except BinanceFuturesError as e:
            if not _is_code(e, "-2011"):
                logger.warning("Algo order cancel probe failed for %s: %s",
                               symbol, e)

    def _snap_price(self, symbol: str, price: float) -> float:
        """Snap a trigger price to the symbol's tick size (the Algo API
        rejects over-precision prices)."""
        f = self._filters(symbol) or {}
        tick = f.get("tick_size")
        if not tick:
            return round(price, 8)
        return round(round(price / tick) * tick, 10)

    def _place_stop(self, symbol: str, close_side: str, stop_price: float):
        """Place the protective stop as an Algo Service CONDITIONAL
        STOP_MARKET (legacy /fapi/v1/order returns -4120 since 2025-12-09).
        The exact place path is discovered once by probing the known
        candidates, then cached."""
        price = self._snap_price(symbol, stop_price)
        payload = {
            "symbol": symbol,
            "side": close_side,
            "algoType": "CONDITIONAL",
            "type": "STOP_MARKET",
            "triggerPrice": price,
            "closePosition": "true",
            "workingType": "MARK_PRICE",
        }
        if self._algo_place_path is None:
            candidates = ["/fapi/v1/algoOrder", "/fapi/v1/algo/order",
                          "/fapi/v1/conditional/order"]
            for path in candidates:
                try:
                    r = self._signed("POST", path, payload)
                    self._algo_place_path = path
                    self._algo_id_by_symbol[symbol] = r.get("algoId")
                    self._last_stop[symbol] = price
                    logger.info("Stop placed (algo %s): %s %s @ %s [algoId %s]",
                                path, symbol, close_side, price,
                                r.get("algoId"))
                    return
                except BinanceFuturesError as e:
                    if "404" in str(e) or "-1100" in str(e) or "-1120" in str(e):
                        continue          # wrong path, probe the next one
                    raise
            raise BinanceFuturesError(
                "no working Algo Order place endpoint found")
        r = self._signed("POST", self._algo_place_path, payload)
        self._algo_id_by_symbol[symbol] = r.get("algoId")
        self._last_stop[symbol] = price
        logger.info("Stop placed: %s %s @ %s [algoId %s]",
                    symbol, close_side, price, r.get("algoId"))

    def _market_close(self, symbol: str, direction: str):
        """MARKET reduce-only close of the tracked quantity."""
        qty = self._qty_by_symbol.pop(symbol, None)
        if qty is None:
            logger.warning("Close %s: no tracked quantity — the position "
                           "may have been opened outside this executor; "
                           "not sending a blind order", symbol)
            return
        close_side = "SELL" if direction == "BUY" else "BUY"
        try:
            self._signed("POST", "/fapi/v1/order", {
                "symbol": symbol, "side": close_side, "type": "MARKET",
                "quantity": qty, "reduceOnly": "true",
            })
            logger.info("Close order sent: %s %s %s", symbol, close_side, qty)
        except BinanceFuturesError as e:
            if _is_code(e, "-2022"):   # ReduceOnly rejected = already flat
                logger.info("Close %s: position already flat on exchange", symbol)
            else:
                raise

    def open_position(self, pos: dict) -> bool:
        """Enter from a virtual-position dict: MARKET entry + exchange stop.
        Returns True when the executor now holds (or simulated holding) it."""
        if not self.enabled:
            return False
        if self.open_count >= self.config.execution_max_positions:
            logger.warning("Executor cap %d reached — not trading %s",
                           self.config.execution_max_positions,
                           pos["symbol"])
            return False
        symbol, direction = pos["symbol"], pos["direction"]
        stop = pos.get("initial_stop")
        try:
            qty = self._qty_for_notional(symbol, pos["entry"])
            if qty is None:
                return False

            if self.mode == "dry":
                self.open_count += 1
                self._qty_by_symbol[symbol] = qty
                self._last_stop[symbol] = round(stop, 8) if stop else None
                logger.info("DRY entry: %s %s %s @ ~%s (stop %s)",
                            direction, symbol, qty, pos["entry"], stop)
                return True

            self._setup_symbol(symbol)
            side = "BUY" if direction == "BUY" else "SELL"
            self._signed("POST", "/fapi/v1/order", {
                "symbol": symbol, "side": side,
                "type": "MARKET", "quantity": qty,
            })
            self._qty_by_symbol[symbol] = qty
            # the entry is live from here — never leave it without a stop
            try:
                stop_side = "SELL" if direction == "BUY" else "BUY"
                self._place_stop(symbol, stop_side, stop)
            except Exception as e:
                self._alert(f"stop({symbol})", e)
                logger.error("Stop failed after entry — flattening %s", symbol)
                try:
                    self._market_close(symbol, direction)
                except Exception as e2:
                    self._alert(f"flatten({symbol})", e2)
                return False
            self.open_count += 1
            logger.info("EXECUTED entry: %s %s %s @ ~%s (stop %s)",
                        direction, symbol, qty, pos["entry"], stop)
            return True
        except Exception as e:
            self._alert(f"open({symbol} {direction})", e)
            return False

    def sync_stop(self, pos: dict):
        """Re-place the exchange stop at the ratcheted trail after a scan.
        No-ops in dry mode, when no stop was placed by the executor, or when
        the trail hasn't moved."""
        if self.mode != "live":
            return
        symbol = pos["symbol"]
        desired = pos.get("trail_stop")
        if desired is None or symbol not in self._last_stop:
            return
        if self._last_stop[symbol] == round(desired, 8):
            return
        direction = 1 if pos["direction"] == "BUY" else -1
        try:
            self._cancel_symbol_orders(symbol)
            stop_side = "SELL" if direction == 1 else "BUY"
            self._place_stop(symbol, stop_side, desired)
        except Exception as e:
            self._alert(f"sync_stop({symbol})", e)

    def close_position(self, pos: dict, reason: str = ""):
        """Flatten a tracked position: cancel its stop, MARKET reduce-only."""
        if not self.enabled:
            return
        symbol, direction = pos["symbol"], pos["direction"]
        if self.mode == "dry":
            logger.info("DRY close: %s %s (%s)", symbol, direction, reason)
        else:
            try:
                self._cancel_symbol_orders(symbol)
                self._market_close(symbol, direction)
            except Exception as e:
                self._alert(f"close({symbol})", e)
        self.open_count = max(0, self.open_count - 1)
        self._last_stop.pop(symbol, None)
        self._qty_by_symbol.pop(symbol, None)
        logger.info("Executor position closed: %s %s (%s)",
                    symbol, direction, reason)

    def reconcile(self, positions: list):
        """On startup: cancel stray open orders for managed symbols and
        re-place stops at each virtual position's current trail, so a restart
        never leaves a position without its protective stop."""
        if not self.enabled:
            return
        self.open_count = 0
        for pos in positions:
            symbol = pos["symbol"]
            self.open_count += 1
            self._qty_by_symbol.setdefault(symbol, None)
            if self.mode != "live":
                continue
            try:
                self._cancel_symbol_orders(symbol)
                direction = 1 if pos["direction"] == "BUY" else -1
                stop = pos.get("trail_stop") or pos.get("initial_stop")
                if stop:
                    stop_side = "SELL" if direction == 1 else "BUY"
                    self._place_stop(symbol, stop_side, stop)
            except Exception as e:
                self._alert(f"reconcile({symbol})", e)
        logger.info("Reconciled %d virtual position(s) with the exchange",
                    len(positions))
