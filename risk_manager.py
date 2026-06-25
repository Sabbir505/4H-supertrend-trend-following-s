"""
Risk Manager — Safety controls for automated trading
Validates trades before execution, enforces position limits.
"""

import logging

logger = logging.getLogger(__name__)


class RiskManager:

    def __init__(self, config, trader=None):
        self.config = config
        self.trader = trader

    def can_open_trade(self) -> tuple[bool, str]:
        """Check if a new trade is allowed.

        Returns:
            (allowed: bool, reason: str)
        """
        if not self.config.auto_trading_enabled:
            return False, "Auto-trading is disabled"

        if self.trader is None or not self.trader.is_ready():
            return False, "Trader not ready (missing API keys or disabled)"

        try:
            open_count = self.trader.get_open_position_count()
            max_positions = self.config.max_open_positions
            if open_count >= max_positions:
                return False, (
                    f"Max positions reached ({open_count}/{max_positions})"
                )
        except Exception as e:
            logger.error(f"Failed to check position count: {e}")
            return False, f"Position count check failed: {e}"

        return True, "OK"

    def validate_signal(self, signal: dict) -> tuple[bool, str]:
        """Validate signal data before execution.

        Returns:
            (valid: bool, reason: str)
        """
        required = [
            'symbol', 'direction', 'entry', 'sl',
            'tp1', 'tp2', 'tp3', 'tp4',
        ]
        for field in required:
            if field not in signal or signal[field] is None:
                return False, f"Missing field: {field}"

        if signal['direction'] not in ('LONG', 'SHORT'):
            return False, f"Invalid direction: {signal['direction']}"

        entry = float(signal['entry'])
        sl = float(signal['sl'])

        if entry <= 0 or sl <= 0:
            return False, "Invalid entry or SL price"

        if signal['direction'] == 'LONG' and sl >= entry:
            return False, f"LONG SL ({sl}) must be below entry ({entry})"
        if signal['direction'] == 'SHORT' and sl <= entry:
            return False, f"SHORT SL ({sl}) must be above entry ({entry})"

        return True, "OK"
