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

    def _signed(self, method: str, path: str, params: dict) -> dict:
        """Signed request to the futures API. Returns the JSON response."""
        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 10000
        query = urlencode(params, True)
        sig = hmac.new(self.config.binance_api_secret.encode("utf-8"),
                       query.encode("utf-8"), hashlib.sha256).hexdigest()
        url = f"{self.base_url}{path}?{query}&signature={sig}"
        headers = {"X-MBX-APIKEY": self.config.binance_api_key}
        resp = self._session.request(method, url, headers=headers, timeout=10)
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
                self._symbol_filters[symbol] = filters
                return filters
            logger.warning("Symbol %s not found on futures — skipping", symbol)
            self._symbol_filters[symbol] = None
            return None
        except Exception as e:
            self._alert(f"exchangeInfo({symbol})", e)
            return None

    def _qty_for_notional(self, symbol: str, price: float) -> float | None:
        """Quantity for the configured notional, rounded DOWN to the symbol's
        step size. Returns None when exchange minimums cannot be met."""
        f = self._filters(symbol)
        if f is None or price <= 0:
            return None
        notional = self.config.execution_margin_usdt * \
            self.config.execution_leverage
        step = f.get("step_size", 0.001)
        qty = int((notional / price) / step) * step
        qty = round(qty, 10)   # kill floating-point fuzz
        if qty < f.get("min_qty", 0.0):
            logger.info("Skip %s: qty %s below minQty %s at $%s notional",
                        symbol, qty, f.get("min_qty"), notional)
            return None
        if qty * price < f.get("min_notional", 5.0):
            logger.info("Skip %s: notional %.2f below minNotional %s",
                        symbol, qty * price, f.get("min_notional"))
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
        try:
            self._signed("DELETE", "/fapi/v1/allOpenOrders",
                         {"symbol": symbol})
        except BinanceFuturesError as e:
            if not _is_code(e, "-2011"):   # unknown order = nothing to cancel
                raise

    def _place_stop(self, symbol: str, close_side: str, stop_price: float):
        price = round(stop_price, 8)
        self._signed("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": close_side,
            "type": "STOP_MARKET",
            "stopPrice": price,
            "closePosition": "true",
            "workingType": "MARK_PRICE",
        })
        self._last_stop[symbol] = price
        logger.info("Stop placed: %s %s @ %s", symbol, close_side, price)

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
