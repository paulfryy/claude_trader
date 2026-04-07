"""
Order building and submission via Alpaca.
Supports notional (dollar-based) orders for fractional shares,
which is essential for a $1000 account.
"""

import logging
from datetime import datetime, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import ContractType, OrderSide, TimeInForce
from alpaca.trading.requests import (
    GetOptionContractsRequest,
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
        Looks up the real contract via Alpaca's API to get the correct OCC symbol,
        then submits the order.

        Args:
            signal: The approved trade signal (must have strike_price, expiration_date)
            contracts: Number of contracts to buy

        Returns:
            Order result dict
        """
        if contracts <= 0:
            return {"status": "skipped", "reason": "0 contracts"}

        if not signal.expiration_date or not signal.strike_price:
            return {
                "status": "skipped",
                "symbol": signal.symbol,
                "reason": "Options signal missing expiration_date or strike_price",
            }

        side = self._get_order_side(signal.action)
        if side is None:
            return {"status": "skipped", "reason": f"No order side for action {signal.action}"}

        # Look up the real contract from Alpaca
        is_call = signal.action in (TradeAction.BUY_CALL, TradeAction.SELL_CALL)
        contract_type = "call" if is_call else "put"

        occ_symbol = self._find_option_contract(
            underlying=signal.symbol,
            strike=signal.strike_price,
            expiration=signal.expiration_date,
            contract_type=contract_type,
        )

        if not occ_symbol:
            return {
                "status": "error",
                "symbol": signal.symbol,
                "error": f"No matching {contract_type} contract found for {signal.symbol} "
                         f"strike=${signal.strike_price} exp={signal.expiration_date}",
            }

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

    def _find_option_contract(
        self,
        underlying: str,
        strike: float,
        expiration: str,
        contract_type: str,
    ) -> str | None:
        """
        Look up the closest matching option contract via Alpaca's API.
        Claude may give an inexact expiration (e.g., Saturday instead of Friday),
        so we search a small date range around the requested expiry.

        Returns the OCC symbol string, or None if no match found.
        """
        try:
            # Parse Claude's expiration date
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        except ValueError:
            logger.warning("Invalid expiration date format: %s", expiration)
            return None

        ct = ContractType.CALL if contract_type == "call" else ContractType.PUT

        # Search a 3-day window around the requested expiry (Claude sometimes
        # gives Saturday/Sunday dates when the contract expires Friday)
        for offset in [0, -1, 1, -2, 2]:
            search_date = exp_date + timedelta(days=offset)
            try:
                req = GetOptionContractsRequest(
                    underlying_symbols=[underlying],
                    expiration_date=search_date.isoformat(),
                    type=ct,
                    strike_price_gte=str(strike - 1),
                    strike_price_lte=str(strike + 1),
                )
                result = self._client.get_option_contracts(req)

                if result.option_contracts:
                    # Find closest strike
                    best = min(
                        result.option_contracts,
                        key=lambda c: abs(float(c.strike_price) - strike),
                    )
                    logger.info(
                        "Found option contract: %s (strike=%s, exp=%s)",
                        best.symbol, best.strike_price, best.expiration_date,
                    )
                    return best.symbol
            except Exception as e:
                logger.debug("Contract search failed for %s offset %d: %s", underlying, offset, e)
                continue

        logger.warning(
            "No option contract found for %s %s strike=%.2f exp=%s",
            underlying, contract_type, strike, expiration,
        )
        return None

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

    def set_stop_loss(self, symbol: str, stop_price: float) -> dict:
        """
        Set a stop-loss order for an existing position.

        Alpaca doesn't support fractional qty on GTC stop orders, so we
        floor to whole shares. Positions under 1 share can't have a stop —
        they'll be managed by Claude's cycle-based review instead.

        Cancels any existing stop for this symbol first to avoid duplicates.
        """
        import math

        # Get current position qty
        try:
            position = self._client.get_open_position(symbol)
            qty = float(position.qty)
        except Exception as e:
            logger.warning("Can't set stop for %s — no position found: %s", symbol, e)
            return {"status": "skipped", "symbol": symbol, "reason": "no position"}

        whole_qty = math.floor(qty)
        if whole_qty < 1:
            logger.info(
                "Position %s has %.4f shares (< 1 whole share) — stop-loss will be "
                "managed by cycle-based review instead",
                symbol, qty,
            )
            return {
                "status": "skipped",
                "symbol": symbol,
                "reason": f"fractional only ({qty:.4f} shares), managed by cycle review",
            }

        # Cancel any existing stop orders for this symbol
        self._cancel_existing_stops(symbol)

        try:
            from alpaca.trading.requests import StopOrderRequest

            req = StopOrderRequest(
                symbol=symbol,
                qty=whole_qty,
                side=OrderSide.SELL,
                stop_price=stop_price,
                time_in_force=TimeInForce.GTC,
            )
            order = self._client.submit_order(req)
            logger.info(
                "Stop-loss set: %s — sell %d shares @ $%.2f (ID: %s)",
                symbol, whole_qty, stop_price, order.id,
            )
            return {
                "status": "submitted",
                "order_id": str(order.id),
                "symbol": symbol,
                "type": "stop_loss",
                "stop_price": stop_price,
                "qty": whole_qty,
            }
        except Exception as e:
            logger.error("Failed to set stop-loss for %s: %s", symbol, e)
            return {"status": "error", "symbol": symbol, "error": str(e)}

    def update_stop_loss(self, symbol: str, new_stop_price: float) -> dict:
        """Update stop-loss for a position — cancels old stop and sets new one."""
        return self.set_stop_loss(symbol, new_stop_price)

    def _cancel_existing_stops(self, symbol: str):
        """Cancel any existing stop orders for a symbol."""
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus

            request = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            orders = self._client.get_orders(filter=request)
            for order in orders:
                if "stop" in str(order.type).lower():
                    self._client.cancel_order_by_id(order.id)
                    logger.info("Cancelled existing stop order %s for %s", order.id, symbol)
        except Exception as e:
            logger.warning("Error cancelling existing stops for %s: %s", symbol, e)

    def get_open_stops(self) -> dict[str, dict]:
        """
        Get all open stop orders, keyed by symbol.
        Returns {symbol: {order_id, stop_price, qty}}.
        """
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus

            request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = self._client.get_orders(filter=request)
            stops = {}
            for o in orders:
                if "stop" in str(o.type).lower():
                    stops[o.symbol] = {
                        "order_id": str(o.id),
                        "stop_price": float(o.stop_price) if o.stop_price else None,
                        "qty": float(o.qty) if o.qty else None,
                    }
            return stops
        except Exception as e:
            logger.warning("Failed to get open stops: %s", e)
            return {}

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
