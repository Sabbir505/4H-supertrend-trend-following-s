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
import re
import time
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

# USDT-M futures REQUEST_WEIGHT budget per minute, per IP. The executor's
# order volume is tiny; this only exists to throttle before Binance does.
_FUTURES_WEIGHT_LIMIT = 2400

_BAN_RE = re.compile(r"banned until (\d+)")


class BinanceFuturesError(Exception):
    pass


class BinanceRateLimited(BinanceFuturesError):
    """Binance has rate-limited or IP-banned us (429/418). Raised instead of
    sending anything for as long as the penalty is active: every request
    that arrives during a ban extends it."""


def _is_code(err: Exception, code: str) -> bool:
    return f'"{code}"' in str(err) or code in str(err)


def _retry_after(resp, default: float) -> float:
    """Retry-After header in seconds, clamped to [0, 60]."""
    try:
        return min(max(float(resp.headers.get("Retry-After") or default), 0.0), 60.0)
    except (TypeError, ValueError):
        return default


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
        self._pending_closes = {}                   # symbol -> direction (failed closes)
        self.open_count = 0                         # executor-tracked positions
        self._banned_until = 0.0                    # Binance IP ban expiry (ts)
        self._ban_alerted = False                   # one alert per ban window
        if self.mode == "live":
            logger.info("Executor LIVE: %dx leverage, max %d positions, "
                        "isolated, fixed $%g margin per trade",
                        config.execution_leverage,
                        config.execution_max_positions,
                        config.execution_margin_usdt)
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

    def _gate(self):
        """Refuse to send anything while a Binance IP ban is active — every
        request that arrives during a ban extends it. Raises instead."""
        if self._banned_until and time.time() < self._banned_until:
            raise BinanceRateLimited(
                f"Binance IP ban active until "
                f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._banned_until))} "
                f"— request not sent")
        if self._banned_until:               # ban expired: resume, re-arm
            self._banned_until = 0.0
            self._ban_alerted = False

    def _signed(self, method: str, path: str, params: dict) -> dict:
        """Signed request to the futures API. Returns the JSON response.
        Auto-resyncs the clock offset and retries once on -1021. Honors
        429 with one Retry-After backoff; treats 418 as an IP ban and
        pauses all requests until it expires."""
        self._gate()

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
        if resp.status_code == 429:
            wait = _retry_after(resp, default=2.0)
            logger.warning("Binance 429 on %s %s — backing off %.0fs",
                           method, path, wait)
            time.sleep(wait)
            resp = send()
        if resp.status_code == 418:
            m = _BAN_RE.search(resp.text)
            until = (int(m.group(1)) / 1000.0 if m
                     else time.time() + max(_retry_after(resp, default=60.0), 60.0))
            self._banned_until = until
            self._alert_ban(until)
            raise BinanceRateLimited(
                f"Binance IP ban until "
                f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(until))}")
        if resp.status_code == 400 and "-1021" in resp.text:
            self._time_off = self._time_offset()   # clock drifted: resync
            resp = send()
        if resp.status_code >= 400:
            raise BinanceFuturesError(
                f"{method} {path} -> {resp.status_code}: {resp.text[:200]}")
        used = resp.headers.get("X-MBX-USED-WEIGHT-1M", "")
        if used.isdigit() and int(used) > _FUTURES_WEIGHT_LIMIT * 0.9:
            logger.warning("Binance request weight %s/%d — throttling 2s",
                           used, _FUTURES_WEIGHT_LIMIT)
            time.sleep(2)
        return resp.json()

    def _alert_ban(self, until: float):
        """One Telegram alert per ban window (repeats would spam every scan)."""
        if self._ban_alerted:
            return
        self._ban_alerted = True
        resume = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(until))
        logger.error("Binance IP ban until %s — executor requests are paused "
                     "until then (every request sent while banned extends "
                     "the ban). Shared proxy/VPN exit IPs are a common "
                     "cause; consider a dedicated node for fapi.binance.com",
                     resume)
        if self.telegram is not None:
            try:
                self.telegram.send_error_alert(
                    "executor: Binance IP ban",
                    BinanceRateLimited(
                        f"IP banned until {resume} — requests paused "
                        f"(trading resumes automatically)"))
            except Exception:
                logger.exception("Failed to send ban alert")

    def _alert(self, context: str, err: Exception):
        if isinstance(err, BinanceRateLimited):
            # The ban itself was alerted once when it began; per-symbol
            # repeats during the same ban must not spam.
            logger.warning("Executor %s skipped: %s", context, err)
            return
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
                    elif f["filterType"] in ("MIN_NOTIONAL", "MINNOTIONAL"):
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

    def _qty_for_notional(self, symbol: str, price: float,
                          notional: float | None = None) -> float | None:
        """Quantity for the given notional (default: configured margin x
        leverage), snapped DOWN to the symbol's step size. A below-floor
        quantity is raised to the smallest tradable size — without the bump
        almost every signal is untradeable when the plan sits near the $5
        floor. Returns None when not even the smallest size satisfies the
        filters (e.g. BTC's 0.001 lot = ~$78)."""
        f = self._filters(symbol)
        if f is None or price <= 0:
            return None
        if notional is None:
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

    def _live_price(self, symbol: str) -> float | None:
        """Current market price — sizing against this instead of the signal
        candle price keeps the order's real notional above the floor even
        when price moved during the 5-minute scan delay."""
        try:
            r = self._session.get(f"{self.base_url}/fapi/v1/ticker/price",
                                  params={"symbol": symbol}, timeout=10).json()
            p = float(r["price"])
            return p if p > 0 else None
        except Exception as e:
            logger.warning("Live price fetch failed for %s (%s) — sizing "
                           "with the signal price", symbol, e)
            return None

    def _margin_for(self, pos: dict) -> float:
        """Margin per position, scaled by the signal's breadth risk tier —
        live parity with the backtested breadth-scaled risk (full when
        breadth >= threshold, half below; REPORT §6c/§6f). Positions opened
        before the tier existed default to full."""
        margin = self.config.execution_margin_usdt
        if pos.get("risk_level") == "half":
            margin *= 0.5
        return margin

    def _qty_for_position(self, symbol: str, pos: dict) -> tuple[float | None, str]:
        """Quantity for a new position: fixed EXECUTION_MARGIN_USDT margin
        (halved for half-breadth-risk signals), notional = margin x leverage,
        plus a label for logs."""
        price = float(pos.get("entry") or 0)
        stop = pos.get("initial_stop")
        margin = self._margin_for(pos)
        price = self._live_price(symbol) or price   # size vs. the real fill price
        sl_dist = (abs(price - float(stop)) / price
                   if (stop and price > 0) else None)

        qty = self._qty_for_notional(symbol, price, margin * self.config.execution_leverage)
        if qty is None:
            return None, "not-tradable"
        risk_usd = qty * price * sl_dist if sl_dist else None
        label = (f"fixed ${margin:g} margin -> "
                 f"${qty * price:.2f} notional"
                 + (" [half-risk]" if margin < self.config.execution_margin_usdt else "")
                 + (f", risk ${risk_usd:.2f}" if risk_usd else ""))
        return qty, label

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
        STOP_MARKET to the Algo API — see REPORT.md / error -4120). Both are
        batch endpoints, so this is exactly two requests however many orders
        are working."""
        for path in ("/fapi/v1/allOpenOrders", "/fapi/v1/algoOpenOrders"):
            try:
                self._signed("DELETE", path, {"symbol": symbol})
            except BinanceFuturesError as e:
                # -2011 "Unknown order sent" / -2013 "Order does not exist"
                # = nothing to cancel
                if not _is_code(e, "-2011") and not _is_code(e, "-2013"):
                    raise

    def _snap_price(self, symbol: str, price: float) -> float:
        """Snap a trigger price to the symbol's tick size (the Algo API
        rejects over-precision prices)."""
        f = self._filters(symbol) or {}
        tick = f.get("tick_size")
        if not tick:
            return round(price, 8)
        return round(round(price / tick) * tick, 10)

    def _algo_post(self, symbol: str, payload: dict) -> dict:
        """POST to the Algo Order place endpoint. The exact path is
        discovered once by probing the known candidates, then cached."""
        if self._algo_place_path:
            return self._signed("POST", self._algo_place_path, payload)
        last: Exception | None = None
        for path in ("/fapi/v1/algoOrder", "/fapi/v1/algo/order",
                     "/fapi/v1/conditional/order"):
            try:
                r = self._signed("POST", path, payload)
                self._algo_place_path = path
                return r
            except BinanceFuturesError as e:
                if "404" in str(e) or "-1100" in str(e) or "-1120" in str(e):
                    last = e            # wrong path, probe the next one
                    continue
                raise
        raise last or BinanceFuturesError(
            "no working Algo Order place endpoint found")

    def _working_close_stop(self, symbol: str, close_side: str):
        """The exchange's working closePosition conditional in this
        direction as (algoId, triggerPrice), or None. Binance allows only
        one such order per direction — it rejects a second with -4130."""
        algo = self._signed("GET", "/fapi/v1/openAlgoOrders",
                            {"symbol": symbol})
        for o in (algo if isinstance(algo, list) else algo.get("orders", [])):
            if str(o.get("side", "")).upper() != close_side:
                continue
            cp = o.get("closePosition")
            if cp is not True and str(cp).lower() != "true":
                continue
            if str(o.get("algoStatus", o.get("status", ""))).upper() in (
                    "CANCELED", "CANCELLED", "FILLED", "EXPIRED",
                    "FINISHED", "REJECTED"):
                continue
            trigger = o.get("triggerPrice", o.get("stopPrice"))
            try:
                return o.get("algoId"), round(float(trigger), 10)
            except (TypeError, ValueError):
                continue
        return None

    def _place_stop(self, symbol: str, close_side: str, stop_price: float):
        """Ensure the protective stop sits at `stop_price` as an Algo Service
        CONDITIONAL STOP_MARKET (legacy /fapi/v1/order returns -4120 since
        2025-12-09).

        Place-first instead of cancel-then-replace: Binance allows only ONE
        closePosition conditional per direction, so a conflicting stop comes
        back as -4130. When that happens, keep the existing stop if it
        already sits at the desired trigger (self-heals after restarts and
        rate-limit outages), otherwise batch-cancel the algo orders and
        retry the placement once."""
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
        try:
            r = self._algo_post(symbol, payload)
        except BinanceFuturesError as e:
            if not _is_code(e, "-4130"):
                raise
            existing = self._working_close_stop(symbol, close_side)
            if existing and existing[1] == price:
                self._last_stop[symbol] = price
                self._algo_id_by_symbol[symbol] = existing[0]
                logger.info("Stop already in place: %s %s @ %s [algoId %s] "
                            "— kept", symbol, close_side, price, existing[0])
                return
            logger.info("Stop %s conflicts with an existing algo order "
                        "(%s) — cancelling and re-placing", symbol, existing)
            try:
                self._signed("DELETE", "/fapi/v1/algoOpenOrders",
                             {"symbol": symbol})
            except BinanceFuturesError as e2:
                if not _is_code(e2, "-2011") and not _is_code(e2, "-2013"):
                    raise
            r = self._algo_post(symbol, payload)
        self._algo_id_by_symbol[symbol] = r.get("algoId")
        self._last_stop[symbol] = price
        logger.info("Stop placed: %s %s @ %s [algoId %s]",
                    symbol, close_side, price, r.get("algoId"))

    def _market_close(self, symbol: str, direction: str) -> bool:
        """MARKET reduce-only close of the tracked quantity. Returns True when
        the position is confirmed flat (order filled, or already flat).

        The tracked quantity is only popped AFTER a confirmed close: popping
        before the send meant one network drop orphaned the real position —
        the bot forgot its own size (seen live: SYRUPUSDT close failed on an
        SSL EOF on 2026-09-28 while the tracker had already deleted the
        position). Transport errors are retried; an exchange rejection is not
        (state unknown — the caller's pending-close retry re-anchors safely
        because reduceOnly closes on a flat position just come back -2022)."""
        qty = self._qty_by_symbol.get(symbol)
        if qty is None:
            logger.warning("Close %s: no tracked quantity — the position "
                           "may have been opened outside this executor; "
                           "not sending a blind order", symbol)
            return True   # nothing tracked -> nothing this executor can close
        close_side = "SELL" if direction == "BUY" else "BUY"
        payload = {"symbol": symbol, "side": close_side, "type": "MARKET",
                   "quantity": qty, "reduceOnly": "true"}
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                self._signed("POST", "/fapi/v1/order", dict(payload))
                self._qty_by_symbol.pop(symbol, None)
                logger.info("Close order sent: %s %s %s", symbol, close_side, qty)
                return True
            except BinanceFuturesError as e:
                if _is_code(e, "-2022"):   # ReduceOnly rejected = already flat
                    self._qty_by_symbol.pop(symbol, None)
                    logger.info("Close %s: position already flat on exchange", symbol)
                    return True
                last_exc = e               # rejected: retrying is pointless
                break
            except requests.RequestException as e:
                last_exc = e               # transport: back off and retry
                time.sleep(2 * (attempt + 1))
        raise last_exc if last_exc is not None else BinanceFuturesError(
            f"close({symbol}): unknown failure")

    def _resting_stop(self, pos: dict) -> float | None:
        """The level for the RESTING exchange stop. In round-6 close-trigger
        mode the chandelier only exists at scan time, so the resting order is
        the static disaster net; in wick (legacy) mode it is the initial
        stop / ratcheted trail as before."""
        if self.config.stop_trigger_mode == 'close' and pos.get('disaster_stop'):
            return float(pos['disaster_stop'])
        return pos.get('initial_stop')

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
        stop = self._resting_stop(pos)
        try:
            qty, sizing = self._qty_for_position(symbol, pos)
            if qty is None:
                logger.info("Not opening %s %s: %s", direction, symbol, sizing)
                return False

            if self.mode == "dry":
                self.open_count += 1
                self._qty_by_symbol[symbol] = qty
                self._last_stop[symbol] = round(stop, 8) if stop else None
                logger.info("DRY entry: %s %s %s @ ~%s (stop %s) | %s",
                            direction, symbol, qty, pos["entry"], stop, sizing)
                return True

            self._setup_symbol(symbol)
            side = "BUY" if direction == "BUY" else "SELL"
            payload = {"symbol": symbol, "side": side,
                       "type": "MARKET", "quantity": qty}
            try:
                self._signed("POST", "/fapi/v1/order", payload)
            except BinanceFuturesError as e:
                if not _is_code(e, "-4164"):
                    raise
                # notional dipped under the floor between sizing and fill:
                # retry once ~5% larger (still tiny — one step of margin)
                entry_px = float(pos["entry"])
                qty = self._qty_for_notional(symbol, entry_px,
                                             qty * entry_px * 1.05)
                if qty is None:
                    raise
                payload["quantity"] = qty
                self._signed("POST", "/fapi/v1/order", payload)
                logger.info("Entry retried at +5%% notional after -4164: "
                            "%s %s %s", symbol, side, qty)
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
            logger.info("EXECUTED entry: %s %s %s @ ~%s (stop %s) | %s",
                        direction, symbol, qty, pos["entry"], stop, sizing)
            return True
        except Exception as e:
            self._alert(f"open({symbol} {direction})", e)
            return False

    def sync_stop(self, pos: dict):
        """Keep the resting exchange stop at the desired level after a scan:
        the static disaster stop in close-trigger mode (it never moves, so
        this is placement-once + self-heal after restarts — no churn), or the
        ratcheted trail in legacy wick mode. No-ops in dry mode, when no stop
        was placed by the executor, or when the level hasn't moved at the
        trigger's tick precision — _last_stop stores the tick-snapped price,
        so comparing against a snapped desired level is what prevents
        same-price cancel/replace churn on every scan (that churn was the
        bot's main source of order-API requests and rate-limit exposure)."""
        if self.mode != "live":
            return
        symbol = pos["symbol"]
        if self.config.stop_trigger_mode == 'close' and pos.get('disaster_stop'):
            desired = float(pos['disaster_stop'])
        else:
            desired = pos.get("trail_stop")
        if desired is None or symbol not in self._last_stop:
            return
        if self._last_stop[symbol] == self._snap_price(symbol, desired):
            return
        direction = 1 if pos["direction"] == "BUY" else -1
        stop_side = "SELL" if direction == 1 else "BUY"
        try:
            self._place_stop(symbol, stop_side, desired)
        except Exception as e:
            self._alert(f"sync_stop({symbol})", e)

    def close_position(self, pos: dict, reason: str = ""):
        """Flatten a tracked position: MARKET reduce-only, then cancel its
        stop. The close comes FIRST: if it fails, the protective stop is
        still in force and the position stays managed (cancel-first used to
        leave a naked position between a failed close and the next restart).
        A failed close keeps the tracked quantity and registers a pending
        retry for the next scan."""
        if not self.enabled:
            return
        symbol, direction = pos["symbol"], pos["direction"]
        if self.mode == "dry":
            logger.info("DRY close: %s %s (%s)", symbol, direction, reason)
        else:
            try:
                if self._market_close(symbol, direction):
                    self._cancel_symbol_orders(symbol)
            except Exception as e:
                self._alert(f"close({symbol})", e)
                self._pending_closes[symbol] = direction
                logger.error("Close %s failed — protective stop remains in "
                             "force, will retry next scan", symbol)
                return   # keep open_count and bookkeeping: still open there
        self.open_count = max(0, self.open_count - 1)
        self._last_stop.pop(symbol, None)
        self._qty_by_symbol.pop(symbol, None)
        self._pending_closes.pop(symbol, None)
        logger.info("Executor position closed: %s %s (%s)",
                    symbol, direction, reason)

    def retry_pending_closes(self):
        """Re-attempt closes that failed on an earlier scan (network drop /
        transient exchange error). The virtual position is already closed in
        the tracker at that point, so this is the only path that flattens the
        exchange side. Safe to call every scan; no-op when nothing pending."""
        if not self._pending_closes or self.mode != "live":
            return
        for symbol, direction in list(self._pending_closes.items()):
            try:
                if not self._market_close(symbol, direction):
                    continue
                self._cancel_symbol_orders(symbol)
            except Exception as e:
                self._alert(f"retry-close({symbol})", e)
                continue
            self._pending_closes.pop(symbol, None)
            self.open_count = max(0, self.open_count - 1)
            self._last_stop.pop(symbol, None)
            self._qty_by_symbol.pop(symbol, None)
            logger.info("Pending close completed: %s (%s)", symbol, direction)

    def reconcile(self, positions: list):
        """On startup: verify each virtual position against the exchange and
        manage only the ones that actually exist there — cancel stray orders
        and re-place the protective stop at the resting level (disaster net
        in close-trigger mode, current trail in wick mode), so a restart
        never leaves a real position unprotected. Virtual positions with no
        exchange position (paper-era records, manual closes) are logged and
        skipped: the bot must never send orders for phantom positions."""
        if not self.enabled:
            return
        live_qty = {}
        if self.mode == "live":
            try:
                for p in self._signed("GET", "/fapi/v2/positionRisk", {}):
                    amt = float(p.get("positionAmt", 0) or 0)
                    if amt:
                        live_qty[p["symbol"]] = abs(amt)
            except Exception as e:
                self._alert("reconcile(positionRisk)", e)
                logger.warning("Reconcile: cannot verify exchange positions — "
                               "no stops placed this startup (existing "
                               "exchange stops remain in force)")
                return
        self.open_count = 0
        for pos in positions:
            symbol = pos["symbol"]
            if self.mode == "live" and symbol not in live_qty:
                logger.warning(
                    "Reconcile: %s %s is tracked virtually but has no "
                    "exchange position — skipped, no orders sent",
                    symbol, pos.get("direction"))
                continue
            self.open_count += 1
            if symbol in live_qty:
                self._qty_by_symbol[symbol] = live_qty[symbol]
            if self.mode != "live":
                continue
            try:
                self._cancel_symbol_orders(symbol)
                direction = 1 if pos["direction"] == "BUY" else -1
                stop = self._resting_stop(pos)
                if stop:
                    stop_side = "SELL" if direction == 1 else "BUY"
                    self._place_stop(symbol, stop_side, stop)
            except Exception as e:
                self._alert(f"reconcile({symbol})", e)
        logger.info("Reconciled %d of %d tracked position(s) with the "
                    "exchange", self.open_count, len(positions))
        # Exchange positions with no virtual record are invisible to every
        # management path (exits, stop sync, orphan alerts). They can come
        # from a close that failed before the fix kept its qty, a crash
        # between tracker-save and close, or manual trading on this account
        # — never auto-close them, but make sure they are SEEN.
        if self.mode == "live":
            tracked = {p["symbol"] for p in positions}
            for symbol, qty in live_qty.items():
                if symbol not in tracked:
                    msg = (f"Unmanaged exchange position: {symbol} "
                           f"(qty {qty}) has no virtual record — not exit-"
                           f"checked, not stop-synced. Close manually if "
                           f"unintended.")
                    logger.error(msg)
                    if self.telegram is not None:
                        try:
                            self.telegram.send_error_alert(
                                "executor: unmanaged position",
                                RuntimeError(msg))
                        except Exception:
                            logger.exception("Failed to send unmanaged-"
                                             "position alert")
