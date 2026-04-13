"""
Trailing stop logic — automatically raise stop-losses on winning positions
to lock in profits without waiting for Claude to adjust them manually.

Rules (tiered):
  Tier 1: P&L% >= +5%  → raise stop to breakeven (entry price)
  Tier 2: P&L% >= +10% → trail stop 5% below current price
  Tier 3: P&L% >= +20% → trail stop 8% below current price (wider to let it run)

Only raises stops — never lowers them. Only adjusts if the new stop would be
meaningfully higher than the current one (at least 0.5% difference), to avoid
constant cancel/re-place noise.
"""

import logging
import math

logger = logging.getLogger(__name__)


# Tier thresholds: (min_gain, stop_strategy)
# strategy "breakeven" = entry price
# strategy "trailing_5pct" = 5% below current price
# strategy "trailing_8pct" = 8% below current price
TIERS = [
    (0.20, "trailing_8pct"),   # +20% → trail 8% below current
    (0.10, "trailing_5pct"),   # +10% → trail 5% below current
    (0.05, "breakeven"),       # +5% → raise to breakeven
]

# Don't bother adjusting if the new stop is within 0.5% of the current one
MIN_ADJUSTMENT_PCT = 0.005


def calculate_trailing_stop(
    symbol: str,
    current_price: float,
    entry_price: float,
    current_stop: float | None,
    pl_pct: float,
) -> float | None:
    """
    Compute the new trailing stop price for a position, or None if no change.

    Args:
        symbol: For logging
        current_price: Current market price of the stock
        entry_price: Average entry price (for breakeven calculation)
        current_stop: Current stop price (None if no stop yet)
        pl_pct: Unrealized P&L as a decimal (e.g., 0.07 = +7%)

    Returns:
        New stop price if an adjustment is warranted, None otherwise.
    """
    if current_price <= 0 or entry_price <= 0:
        return None

    # Find the applicable tier (first match wins — highest threshold first)
    target_stop = None
    tier_label = None
    for threshold, strategy in TIERS:
        if pl_pct >= threshold:
            target_stop = _compute_stop_for_strategy(strategy, current_price, entry_price)
            tier_label = strategy
            break

    if target_stop is None:
        # Below the +5% threshold — no trailing logic yet
        return None

    # Only raise stops, never lower them
    if current_stop is not None and target_stop <= current_stop:
        return None

    # Only adjust if the change is meaningful
    if current_stop is not None:
        diff_pct = (target_stop - current_stop) / current_stop
        if diff_pct < MIN_ADJUSTMENT_PCT:
            return None

    logger.info(
        "Trailing stop for %s: P&L=%.1f%% → %s strategy → $%.2f (was $%.2f)",
        symbol, pl_pct * 100, tier_label, target_stop,
        current_stop if current_stop else 0,
    )
    return round(target_stop, 2)


def _compute_stop_for_strategy(strategy: str, current_price: float, entry_price: float) -> float:
    if strategy == "breakeven":
        return entry_price
    elif strategy == "trailing_5pct":
        return current_price * 0.95
    elif strategy == "trailing_8pct":
        return current_price * 0.92
    return entry_price


def evaluate_trailing_stops(
    positions: list[dict],
    open_stops: dict[str, dict],
) -> list[tuple[str, float, str]]:
    """
    Evaluate all positions and return a list of trailing stop adjustments.

    Args:
        positions: List of position dicts from Alpaca (with qty, avg_entry_price,
                   current_price, unrealized_plpc)
        open_stops: Dict of symbol -> {stop_price, ...} for existing stops

    Returns:
        List of (symbol, new_stop_price, reason) tuples for positions that need adjustment.
        Only returns equity positions with >= 1 whole share (options and fractional
        positions are skipped — the broker can't set stops on them).
    """
    adjustments = []

    for p in positions:
        symbol = p.get("symbol", "")
        qty = p.get("qty", 0)
        current_price = p.get("current_price", 0)
        entry_price = p.get("avg_entry_price", 0)
        pl_pct = p.get("unrealized_plpc", 0)

        # Skip options (OCC symbols are long)
        if len(symbol) > 10:
            continue

        # Skip fractional positions (can't set broker-side stops)
        if math.floor(qty) < 1:
            continue

        current_stop_info = open_stops.get(symbol, {})
        current_stop = current_stop_info.get("stop_price")

        new_stop = calculate_trailing_stop(
            symbol=symbol,
            current_price=current_price,
            entry_price=entry_price,
            current_stop=current_stop,
            pl_pct=pl_pct,
        )

        if new_stop is not None:
            # Pick a reason string for the logs
            if pl_pct >= 0.20:
                reason = f"+{pl_pct*100:.0f}% — trailing 8% below current"
            elif pl_pct >= 0.10:
                reason = f"+{pl_pct*100:.0f}% — trailing 5% below current"
            else:
                reason = f"+{pl_pct*100:.0f}% — raised to breakeven"
            adjustments.append((symbol, new_stop, reason))

    return adjustments
