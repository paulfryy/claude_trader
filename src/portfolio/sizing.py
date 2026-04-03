"""
Position sizing calculator.
Returns dollar amounts (notional) for orders — Alpaca handles fractional shares.
This is essential for a $1000 account where most stocks cost more than a 15% allocation.
"""

import logging

from src.analysis.signals import TradeSignal

logger = logging.getLogger(__name__)


def calculate_notional(
    signal: TradeSignal,
    equity: float,
    current_price: float,
    position_size_pct: float | None = None,
) -> float:
    """
    Calculate the dollar amount to allocate to a trade.

    Uses notional (dollar-based) sizing so Alpaca can handle fractional shares.
    A $1000 account with 15% position size = $150 of any stock, regardless of price.

    Args:
        signal: The trade signal
        equity: Current portfolio equity (virtual, based on starting_capital)
        current_price: Current price of the asset (for logging only)
        position_size_pct: Override position size (e.g., from risk clamping)

    Returns:
        Dollar amount to invest (0.0 if too small to be meaningful)
    """
    size_pct = position_size_pct or signal.position_size_pct
    notional = round(equity * size_pct, 2)

    # Alpaca minimum notional is $1
    if notional < 1.0:
        logger.warning(
            "Notional too small for %s: $%.2f (%.1f%% of $%.2f)",
            signal.symbol, notional, size_pct * 100, equity,
        )
        return 0.0

    approx_shares = notional / current_price if current_price > 0 else 0
    logger.info(
        "Position sizing: %s — $%.2f notional (~%.2f shares @ $%.2f) = %.1f%% of $%.2f",
        signal.symbol, notional, approx_shares, current_price, size_pct * 100, equity,
    )
    return notional


def calculate_options_contracts(
    signal: TradeSignal,
    equity: float,
    premium_per_contract: float,
    position_size_pct: float | None = None,
) -> int:
    """
    Calculate the number of options contracts to buy.
    Each contract = 100 shares. Options don't support fractional — must be whole contracts.

    Args:
        signal: The trade signal
        equity: Current portfolio equity
        premium_per_contract: Cost of one contract (premium * 100)
        position_size_pct: Override position size

    Returns:
        Number of contracts (0 if can't afford any)
    """
    import math

    size_pct = position_size_pct or signal.position_size_pct
    target_value = equity * size_pct

    if premium_per_contract <= 0:
        return 0

    contracts = math.floor(target_value / premium_per_contract)
    if contracts <= 0:
        logger.warning(
            "Cannot afford even 1 contract of %s at $%.2f with $%.2f allocation",
            signal.symbol, premium_per_contract, target_value,
        )
        return 0

    logger.info(
        "Options sizing: %s — %d contracts @ $%.2f = $%.2f (%.1f%% of $%.2f)",
        signal.symbol, contracts, premium_per_contract,
        contracts * premium_per_contract, size_pct * 100, equity,
    )
    return contracts
