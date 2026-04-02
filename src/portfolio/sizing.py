"""
Position sizing calculator.
Determines how many shares/contracts to buy based on portfolio size and risk rules.
"""

import logging
import math

from src.analysis.signals import TradeAction, TradeSignal

logger = logging.getLogger(__name__)


def calculate_shares(
    signal: TradeSignal,
    equity: float,
    current_price: float,
    position_size_pct: float | None = None,
) -> int:
    """
    Calculate the number of shares to buy for an equity/ETF trade.

    Args:
        signal: The trade signal
        equity: Current portfolio equity
        current_price: Current price of the asset
        position_size_pct: Override position size (e.g., from risk clamping)

    Returns:
        Number of whole shares to buy (0 if can't afford any)
    """
    size_pct = position_size_pct or signal.position_size_pct
    target_value = equity * size_pct

    if current_price <= 0:
        return 0

    shares = math.floor(target_value / current_price)
    if shares <= 0:
        logger.warning(
            "Cannot afford even 1 share of %s at $%.2f with $%.2f allocation",
            signal.symbol,
            current_price,
            target_value,
        )
        return 0

    logger.info(
        "Position sizing: %s — %d shares @ $%.2f = $%.2f (%.1f%% of $%.2f)",
        signal.symbol,
        shares,
        current_price,
        shares * current_price,
        size_pct * 100,
        equity,
    )
    return shares


def calculate_options_contracts(
    signal: TradeSignal,
    equity: float,
    premium_per_contract: float,
    position_size_pct: float | None = None,
) -> int:
    """
    Calculate the number of options contracts to buy.
    Each contract = 100 shares.

    Args:
        signal: The trade signal
        equity: Current portfolio equity
        premium_per_contract: Cost of one contract (premium * 100)
        position_size_pct: Override position size

    Returns:
        Number of contracts (0 if can't afford any)
    """
    size_pct = position_size_pct or signal.position_size_pct
    target_value = equity * size_pct

    if premium_per_contract <= 0:
        return 0

    contracts = math.floor(target_value / premium_per_contract)
    if contracts <= 0:
        logger.warning(
            "Cannot afford even 1 contract of %s at $%.2f with $%.2f allocation",
            signal.symbol,
            premium_per_contract,
            target_value,
        )
        return 0

    logger.info(
        "Options sizing: %s — %d contracts @ $%.2f = $%.2f (%.1f%% of $%.2f)",
        signal.symbol,
        contracts,
        premium_per_contract,
        contracts * premium_per_contract,
        size_pct * 100,
        equity,
    )
    return contracts
