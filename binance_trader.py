"""
Binance Futures Trader — Direct order execution on Binance Futures
Places market orders, manages SL/TP lifecycle, handles position sizing.

Order flow per signal:
1. Set leverage + margin type
2. Place MARKET entry order
3. Place STOP_MARKET for SL (closePosition=true)
4. Tracker monitors prices and calls close_partial() at each TP level
5. After TP1: cancel old SL, place new SL at entry (breakeven)
"""

import hashlib
import hmac
import time
import logging
import requests
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

FUTURES_BASE_URL = "https://fapi.binance.com"


class BinanceAPIError(Exception):
    """Binance API error with code and message."""

    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"Binance API Error {code}: {msg}")


class BinanceTrader:

    def __init__(self, config, scanner=None):
        self.config = config
        self.api_key = config.binance_api_key
        self.api_secret = config.binance_api_secret
        self.base_url = FUTURES_BASE_URL
        self.enabled = config.auto_trading_enabled
        self.scanner = scanner
        self._exchange_info_cache = {}
        self._exchange_info_time = 0

    # ─── API Request Helpers ─────────────────────────────────────────────────

    def _sign(self, params: dict) -> dict:
        """Add timestamp and HMAC-SHA256 signature."""
        params['timestamp'] = int(time.time() * 1000)
        params['recvWindow'] = 5000
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        params['signature'] = signature
        return params

    def _headers(self) -> dict:
        return {'X-MBX-APIKEY': self.api_key}

    def _request(self, method: str, endpoint: str, params: dict = None,
                 signed: bool = True) -> dict:
        """Make a request to Binance Futures API with retry logic."""
        url = f"{self.base_url}{endpoint}"
        params = params or {}

        if signed:
            params = self._sign(params)

        for attempt in range(3):
            try:
                if method == 'GET':
                    resp = requests.get(url, params=params,
                                        headers=self._headers(), timeout=10)
                elif method == 'POST':
                    resp = requests.post(url, params=params,
                                         headers=self._headers(), timeout=10)
                elif method == 'DELETE':
                    resp = requests.delete(url, params=params,
                                           headers=self._headers(), timeout=10)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.HTTPError as e:
                error_data = {}
                try:
                    error_data = e.response.json()
                except Exception:
                    pass
                code = error_data.get('code', -1)
                msg = error_data.get('msg', str(e))
                if e.response.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning(f"Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                raise BinanceAPIError(code, msg)

            except requests.exceptions.RequestException as e:
                if attempt < 2:
                    wait = 0.5 * (2 ** attempt)
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}): {e}, "
                        f"retrying in {wait}s"
                    )
                    time.sleep(wait)
                    continue
                raise BinanceAPIError(-1, f"Request failed after retries: {e}")

        raise BinanceAPIError(-1, "Request failed after all retries")

    # ─── Exchange Info ───────────────────────────────────────────────────────

    def _get_exchange_info(self) -> dict:
        """Fetch and cache futures exchange info (precision, filters)."""
        now = time.time()
        if self._exchange_info_cache and now - self._exchange_info_time < 3600:
            return self._exchange_info_cache

        data = self._request('GET', '/fapi/v1/exchangeInfo', signed=False)
        info = {}
        for s in data.get('symbols', []):
            info[s['symbol']] = {
                'quantityPrecision': s['quantityPrecision'],
                'pricePrecision': s['pricePrecision'],
                'filters': {f['filterType']: f for f in s.get('filters', [])},
                'status': s.get('status'),
            }
        self._exchange_info_cache = info
        self._exchange_info_time = now
        logger.info(f"Exchange info cached: {len(info)} symbols")
        return info

    def _get_symbol_info(self, symbol: str) -> dict:
        """Get precision and filter info for a symbol."""
        info = self._get_exchange_info()
        if symbol not in info:
            raise BinanceAPIError(-1, f"Symbol {symbol} not found in exchange info")
        return info[symbol]

    def round_quantity(self, symbol: str, quantity: float) -> float:
        """Round quantity to the symbol's step size."""
        info = self._get_symbol_info(symbol)
        precision = info['quantityPrecision']
        lot_filter = info['filters'].get('LOT_SIZE', {})
        step_size = float(lot_filter.get('stepSize', 10 ** -precision))
        min_qty = float(lot_filter.get('minQty', 0))

        if step_size > 0:
            quantity = int(quantity / step_size) * step_size
        quantity = round(quantity, precision)

        if quantity < min_qty:
            return 0.0
        return quantity

    def _round_price(self, symbol: str, price: float) -> float:
        """Round price to the symbol's tick size."""
        info = self._get_symbol_info(symbol)
        return round(price, info['pricePrecision'])

    def _get_futures_symbol(self, spot_symbol: str) -> str:
        """Convert spot symbol to futures symbol (e.g. PEPEUSDT -> 1000PEPEUSDT)."""
        if self.scanner:
            return self.scanner.get_futures_symbol(spot_symbol)
        return spot_symbol

    # ─── Account Info ────────────────────────────────────────────────────────

    def get_account_balance(self) -> float:
        """Get available USDT balance."""
        data = self._request('GET', '/fapi/v2/balance')
        for asset in data:
            if asset['asset'] == 'USDT':
                return float(asset['availableBalance'])
        return 0.0

    def get_position(self, symbol: str) -> dict | None:
        """Get current position for a symbol. Returns None if no position."""
        data = self._request('GET', '/fapi/v2/positionRisk', {'symbol': symbol})
        for pos in data:
            if pos['symbol'] == symbol and float(pos['positionAmt']) != 0:
                return {
                    'symbol': pos['symbol'],
                    'side': 'LONG' if float(pos['positionAmt']) > 0 else 'SHORT',
                    'quantity': abs(float(pos['positionAmt'])),
                    'entry_price': float(pos['entryPrice']),
                    'unrealized_pnl': float(pos['unRealizedProfit']),
                    'leverage': int(pos['leverage']),
                }
        return None

    def get_open_orders(self, symbol: str) -> list:
        """Get all open orders for a symbol."""
        return self._request('GET', '/fapi/v1/openOrders', {'symbol': symbol})

    def get_open_positions(self) -> list:
        """Return all positions from the exchange."""
        return self._request('GET', '/fapi/v2/positionRisk')

    def get_open_position_count(self) -> int:
        """Count current open positions on the exchange."""
        data = self.get_open_positions()
        return sum(1 for p in data if float(p.get('positionAmt', 0)) != 0)

    # ─── Order Management ────────────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Set leverage for a symbol."""
        return self._request('POST', '/fapi/v1/leverage', {
            'symbol': symbol,
            'leverage': leverage,
        })

    def set_margin_type(self, symbol: str, margin_type: str = 'CROSSED') -> dict:
        """Set margin type (CROSSED or ISOLATED). Ignores 'already set' errors."""
        try:
            return self._request('POST', '/fapi/v1/marginType', {
                'symbol': symbol,
                'marginType': margin_type,
            })
        except BinanceAPIError as e:
            if e.code == -4046:
                return {'msg': 'No need to change margin type.'}
            raise

    def open_position(self, signal: dict) -> dict:
        """Open a new position on Binance Futures.

        1. Maps spot symbol to futures symbol
        2. Sets leverage + margin type
        3. Places MARKET entry order
        4. Places STOP_MARKET for SL (closePosition=true)

        Returns dict with order details for storage in tracker.
        """
        if not self.enabled:
            raise BinanceAPIError(-1, "Auto-trading is disabled")

        spot_symbol = signal['symbol']
        futures_symbol = self._get_futures_symbol(spot_symbol)
        direction = signal['direction']
        entry_price = float(signal['entry'])
        sl_price = float(signal['sl'])
        leverage = self.config.leverage

        # Position sizing: fixed USDT amount * leverage / price
        trade_amount = self.config.trade_amount_usdt
        notional = trade_amount * leverage
        quantity = notional / entry_price
        quantity = self.round_quantity(futures_symbol, quantity)

        if quantity <= 0:
            raise BinanceAPIError(
                -1,
                f"Quantity too small for {futures_symbol} "
                f"(${trade_amount} x {leverage}x / {entry_price})"
            )

        # Configure leverage and margin
        self.set_leverage(futures_symbol, leverage)
        self.set_margin_type(futures_symbol, 'CROSSED')

        # Place MARKET entry order
        entry_side = 'BUY' if direction == 'LONG' else 'SELL'
        entry_order = self._request('POST', '/fapi/v1/order', {
            'symbol': futures_symbol,
            'side': entry_side,
            'type': 'MARKET',
            'quantity': quantity,
        })
        logger.info(
            f"Entry order: {futures_symbol} {entry_side} qty={quantity} "
            f"orderId={entry_order.get('orderId')}"
        )

        # Place STOP_MARKET for SL (closes entire remaining position)
        sl_side = 'SELL' if direction == 'LONG' else 'BUY'
        sl_stop_price = self._round_price(futures_symbol, sl_price)

        sl_order = self._request('POST', '/fapi/v1/order', {
            'symbol': futures_symbol,
            'side': sl_side,
            'type': 'STOP_MARKET',
            'closePosition': 'true',
            'stopPrice': sl_stop_price,
        })
        logger.info(
            f"SL order: {futures_symbol} {sl_side} stop={sl_stop_price} "
            f"orderId={sl_order.get('orderId')}"
        )

        return {
            'futures_symbol': futures_symbol,
            'entry_order_id': entry_order.get('orderId'),
            'entry_quantity': quantity,
            'actual_entry_price': float(entry_order.get('avgPrice', entry_price)),
            'sl_order_id': sl_order.get('orderId'),
            'sl_price': sl_stop_price,
        }

    def close_partial(self, symbol: str, quantity: float,
                      direction: str) -> dict | None:
        """Close a specific quantity via MARKET reduceOnly order.

        Args:
            symbol: Futures symbol
            quantity: Exact quantity to close (already rounded)
            direction: 'LONG' or 'SHORT' (position direction)
        """
        if quantity <= 0:
            logger.warning(f"Close quantity <= 0 for {symbol}, skipping")
            return None

        close_side = 'SELL' if direction == 'LONG' else 'BUY'
        order = self._request('POST', '/fapi/v1/order', {
            'symbol': symbol,
            'side': close_side,
            'type': 'MARKET',
            'quantity': quantity,
            'reduceOnly': 'true',
        })
        logger.info(
            f"Partial close: {symbol} {close_side} qty={quantity} "
            f"orderId={order.get('orderId')}"
        )
        return order

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Cancel a specific order by ID."""
        try:
            return self._request('DELETE', '/fapi/v1/order', {
                'symbol': symbol,
                'orderId': order_id,
            })
        except BinanceAPIError as e:
            logger.warning(f"Cancel order {order_id} failed for {symbol}: {e}")
            return {}

    def move_sl_to_breakeven(self, symbol: str, entry_price: float,
                             direction: str,
                             sl_order_id: int = None) -> dict:
        """Cancel existing SL and place new one at entry price (breakeven).

        PR3 fix: Prefer cancelling the specific SL order by ID instead of
        cancel_all_orders, which would also cancel user's manual orders.
        """
        if sl_order_id:
            self.cancel_order(symbol, sl_order_id)
        else:
            self._cancel_stop_orders(symbol)

        sl_side = 'SELL' if direction == 'LONG' else 'BUY'
        sl_price = self._round_price(symbol, entry_price)

        sl_order = self._request('POST', '/fapi/v1/order', {
            'symbol': symbol,
            'side': sl_side,
            'type': 'STOP_MARKET',
            'closePosition': 'true',
            'stopPrice': sl_price,
        })
        logger.info(
            f"SL moved to breakeven: {symbol} stop={sl_price} "
            f"orderId={sl_order.get('orderId')}"
        )
        return sl_order

    def _cancel_stop_orders(self, symbol: str):
        """Cancel only STOP_MARKET orders for a symbol (not user's limit orders).

        PR3 fix: Used as fallback when we don't have a specific SL order ID.
        """
        try:
            orders = self._request('GET', '/fapi/v1/openOrders',
                                   {'symbol': symbol})
            for order in orders:
                if order.get('type') in ('STOP_MARKET', 'STOP'):
                    self.cancel_order(symbol, order['orderId'])
                    logger.info(
                        f"Cancelled stop order {order['orderId']} for {symbol}"
                    )
        except BinanceAPIError as e:
            logger.warning(f"Failed to query/cancel stop orders for {symbol}: {e}")

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel all open orders for a symbol."""
        try:
            result = self._request('DELETE', '/fapi/v1/allOpenOrders',
                                   {'symbol': symbol})
            logger.info(f"All orders cancelled: {symbol}")
            return result
        except BinanceAPIError as e:
            logger.warning(f"Cancel orders failed for {symbol}: {e}")
            return {}

    def close_position(self, symbol: str) -> dict | None:
        """Emergency close: full position at market + cancel all orders."""
        position = self.get_position(symbol)
        if position is None:
            logger.info(f"No position to close for {symbol}")
            return None

        close_side = 'SELL' if position['side'] == 'LONG' else 'BUY'
        order = self._request('POST', '/fapi/v1/order', {
            'symbol': symbol,
            'side': close_side,
            'type': 'MARKET',
            'quantity': position['quantity'],
            'reduceOnly': 'true',
        })
        self.cancel_all_orders(symbol)
        logger.info(f"Position closed: {symbol} qty={position['quantity']}")
        return order

    def is_ready(self) -> bool:
        """Check if trader is configured and enabled."""
        return bool(self.api_key and self.api_secret and self.enabled)
