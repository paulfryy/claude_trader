"""
Order building and submission via Alpaca.
Supports notional (dollar-based) orders for fractional shares,
which is essential for a $1000 account.
"""

import logging

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from src.analysis.signals import TradeAction, TradeSignal
from src.config import Settings

logger = logging.getLogger(__name__)


class OrderExecutor:
    """Builds and submits orders to Alpaca."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = TradingClient(
            api_key=settings.alpaca.api_key,
            secret_key=settings.alpaca.secret_key,
            paper=settings.is_paper,
        )

    def execute_equity_signal(
        self,
        signal: TradeSignal,
        notional: float,
    ) -> dict:
        """
        Execute an equity trade signal using notional (dollar-based) orders.
        Alpaca handles fractional shares automatically.

        Args:
            signal: The approved trade signal
            notional: Dollar amount to invest

        Returns:
            Order result dict with order ID, status, etc.
        """
        if notional < 1.0:
            return {"status": "skipped", "reason": f"notional too small: ${notional:.2f}"}

        side = self._get_order_side(signal.action)
        if side is None:
            return {"status": "skipped", "reason": f"No order side for action {signal.action}"}

        try:
            # Use bracket order if we have both target and stop (for equity buys)
            if signal.target_price and signal.stop_loss_price and side == OrderSide.BUY:
                order = self._submit_notional_bracket_order(
                    symbol=signal.symbol,
                    notional=notional,
                    side=side,
                    take_profit=signal.target_price,
                    stop_loss=signal.stop_loss_price,
                )
            else:
                order = self._submit_notional_market_order(
                    symbol=signal.symbol,
                    notional=notional,
                    side=side,
                )

            result = {
                "status": "submitted",
                "order_id": str(order.id),
                "symbol": signal.symbol,
                "side": side.value,
                "notional": notional,
                "type": str(order.type),
                "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
            }
            logger.info(
                "Order submitted: %s $%.2f of %s (ID: %s)",
                side.value, notional, signal.symbol, order.id,
            )
            return result

        except Exception as e:
            logger.error("Order failed for %s: %s", signal.symbol, str(e))
            return {"status": "error", "symbol": signal.symbol, "error": str(e)}

    def execute_options_signal(
        self,
        signal: TradeSignal,
        contracts: int,
    ) -> dict:
        """
        Execute an options trade signal.

        Args:
            signal: The approved trade signal (must have strike_price, expiration_date)
            contracts: Number of contracts to buy

        Returns:
            Order result dict
        """
        if contracts <= 0:
            return {"status": "skipped", "reason": "0 contracts"}

        # Build the OCC options symbol
        # Format: SYMBOL + YYMMDD + C/P + strike*1000 (8 digits)
        # e.g., SPY260417C00650000
        if not signal.expiration_date or not signal.strike_price:
            return {
                "status": "skipped",
                "symbol": signal.symbol,
                "reason": "Options signal missing expiration_date or strike_price",
            }

        option_type = "C" if signal.action in (TradeAction.BUY_CALL, TradeAction.SELL_CALL) else "P"

        # Parse expiration date and format as YYMMDD
        exp = signal.expiration_date.replace("-", "")
        if len(exp) == 8:  # YYYYMMDD
            exp = exp[2:]  # -> YYMMDD

        strike_int = int(signal.strike_price * 1000)
        occ_symbol = f"{signal.symbol:<6}{exp}{option_type}{strike_int:08d}"

        side = self._get_order_side(signal.action)
        if side is None:
            return {"status": "skipped", "reason": f"No order side for action {signal.action}"}

        try:
            request = MarketOrderRequest(
                symbol=occ_symbol,
                qty=contracts,
                side=side,
                time_in_force=TimeInForce.DAY,
            )
            order = self._client.submit_order(request)

            result = {
                "status": "submitted",
                "order_id": str(order.id),
                "symbol": signal.symbol,
                "occ_symbol": occ_symbol,
                "side": side.value,
                "contracts": contracts,
                "type": str(order.type),
                "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
            }
            logger.info(
                "Options order submitted: %s %d contracts of %s (ID: %s)",
                side.value, contracts, occ_symbol, order.id,
            )
            return result

        except Exception as e:
            logger.error("Options order failed for %s: %s", occ_symbol, str(e))
            return {"status": "error", "symbol": signal.symbol, "occ_symbol": occ_symbol, "error": str(e)}

    def _submit_notional_market_order(self, symbol: str, notional: float, side: OrderSide):
        """Submit a notional (dollar-based) market order. Alpaca handles fractional shares."""
        request = MarketOrderRequest(
            symbol=symbol,
            notional=notional,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        return self._client.submit_order(request)

    def _submit_notional_bracket_order(
        self,
        symbol: str,
        notional: float,
        side: OrderSide,
        take_profit: float,
        stop_loss: float,
    ):
        """Submit a notional bracket order with take-profit and stop-loss."""
        # Note: Alpaca bracket orders with notional may not support fractional
        # shares in the leg orders. Fall back to simple market + manual stops
        # if this fails.
        try:
            request = MarketOrderRequest(
                symbol=symbol,
                notional=notional,
                side=side,
                time_in_force=TimeInForce.GTC,
                order_class="bracket",
                take_profit=TakeProfitRequest(limit_price=take_profit),
                stop_loss=StopLossRequest(stop_price=stop_loss),
            )
            return self._client.submit_order(request)
        except Exception as e:
            # Bracket orders may not work with notional — fall back to simple order
            logger.warning(
                "Bracket order failed for %s, falling back to market order: %s",
                symbol, e,
            )
            return self._submit_notional_market_order(symbol, notional, side)

    def close_position(self, symbol: str) -> dict:
        """Close an entire position for a symbol."""
        try:
            self._client.close_position(symbol)
            logger.info("Position closed: %s", symbol)
            return {"status": "closed", "symbol": symbol}
        except Exception as e:
            logger.error("Failed to close position %s: %s", symbol, str(e))
            return {"status": "error", "symbol": symbol, "error": str(e)}

    def get_orders(self, status: str = "open") -> list[dict]:
        """Get orders by status."""
        orders = self._client.get_orders(filter={"status": status})
        return [
            {
                "id": str(o.id),
                "symbol": o.symbol,
                "side": o.side,
                "qty": o.qty,
                "type": o.type,
                "status": o.status,
                "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
            }
            for o in orders
        ]

    @staticmethod
    def _get_order_side(action: TradeAction) -> OrderSide | None:
        buy_actions = {TradeAction.BUY, TradeAction.BUY_CALL, TradeAction.BUY_PUT}
        sell_actions = {TradeAction.SELL, TradeAction.SELL_CALL, TradeAction.SELL_PUT}

        if action in buy_actions:
            return OrderSide.BUY
        elif action in sell_actions:
            return OrderSide.SELL
        return None
