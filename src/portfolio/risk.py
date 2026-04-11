"""
Risk management engine — hard-coded guardrails that Claude cannot bypass.
Validates trade signals against portfolio risk rules before execution.
"""

import logging
from dataclasses import dataclass

from src.analysis.signals import TradeAction, TradeSignal
from src.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    """Result of a risk validation check."""

    approved: bool
    signal: TradeSignal
    reason: str = ""
    adjusted_size_pct: float | None = None  # If we reduced the position size


class RiskManager:
    """
    Validates trade signals against hard risk limits.
    This is the safety net — Claude proposes, risk manager disposes.
    """

    def __init__(self, settings: Settings):
        self.risk = settings.risk

    def validate_signal(
        self, signal: TradeSignal, portfolio_state: dict
    ) -> RiskCheckResult:
        """
        Run all risk checks on a trade signal.
        Returns approved/rejected with reason.
        """
        checks = [
            self._check_drawdown_circuit_breaker,
            self._check_catalyst_size,
            self._check_position_size,
            self._check_total_exposure,
            self._check_options_exposure,
            self._check_pdt_limit,
            self._check_has_stop_loss,
        ]

        adjusted_size = None
        for check in checks:
            result = check(signal, portfolio_state)
            if not result.approved:
                logger.warning(
                    "RISK REJECTED: %s %s — %s",
                    signal.action.value,
                    signal.symbol,
                    result.reason,
                )
                return result

            # Track the tightest size adjustment across all checks
            if result.adjusted_size_pct is not None:
                if adjusted_size is None or result.adjusted_size_pct < adjusted_size:
                    adjusted_size = result.adjusted_size_pct

        logger.info(
            "RISK APPROVED: %s %s (size: %.1f%%)",
            signal.action.value,
            signal.symbol,
            (adjusted_size or signal.position_size_pct) * 100,
        )
        return RiskCheckResult(approved=True, signal=signal, adjusted_size_pct=adjusted_size)

    def _check_drawdown_circuit_breaker(
        self, signal: TradeSignal, state: dict
    ) -> RiskCheckResult:
        """Halt all new trades if drawdown exceeds threshold."""
        # Always allow exits — must be able to close positions during a drawdown
        sell_actions = {TradeAction.SELL, TradeAction.SELL_CALL, TradeAction.SELL_PUT}
        if signal.action in sell_actions:
            return RiskCheckResult(approved=True, signal=signal)

        drawdown = state.get("drawdown_pct", 0)
        if drawdown >= self.risk.max_drawdown_pct:
            return RiskCheckResult(
                approved=False,
                signal=signal,
                reason=f"Circuit breaker: drawdown {drawdown:.1%} >= {self.risk.max_drawdown_pct:.1%} limit. No new positions.",
            )
        return RiskCheckResult(approved=True, signal=signal)

    def _check_catalyst_size(
        self, signal: TradeSignal, state: dict
    ) -> RiskCheckResult:
        """
        Enforce tighter position size for catalyst/overnight trades.
        Catalyst trades are capped at max_catalyst_position_pct (5%) instead of the
        normal max_position_pct (15%) because overnight events carry gap risk.
        """
        if not signal.is_catalyst_trade:
            return RiskCheckResult(approved=True, signal=signal)

        if signal.action in (TradeAction.SELL, TradeAction.HOLD):
            return RiskCheckResult(approved=True, signal=signal)

        if not signal.catalyst:
            return RiskCheckResult(
                approved=False,
                signal=signal,
                reason="Catalyst trade must specify the catalyst (e.g., 'earnings after close').",
            )

        max_pct = self.risk.max_catalyst_position_pct
        if signal.position_size_pct > max_pct:
            logger.info(
                "Clamping catalyst trade %s from %.1f%% to %.1f%% (catalyst limit)",
                signal.symbol, signal.position_size_pct * 100, max_pct * 100,
            )
            return RiskCheckResult(
                approved=True,
                signal=signal,
                adjusted_size_pct=max_pct,
            )

        return RiskCheckResult(approved=True, signal=signal)

    def _check_position_size(
        self, signal: TradeSignal, state: dict
    ) -> RiskCheckResult:
        """Ensure no single position exceeds max size."""
        if signal.action in (TradeAction.SELL, TradeAction.HOLD):
            return RiskCheckResult(approved=True, signal=signal)

        if signal.position_size_pct > self.risk.max_position_pct:
            # Clamp to max rather than reject
            logger.info(
                "Clamping position size from %.1f%% to %.1f%%",
                signal.position_size_pct * 100,
                self.risk.max_position_pct * 100,
            )
            return RiskCheckResult(
                approved=True,
                signal=signal,
                adjusted_size_pct=self.risk.max_position_pct,
            )
        return RiskCheckResult(approved=True, signal=signal)

    def _check_total_exposure(
        self, signal: TradeSignal, state: dict
    ) -> RiskCheckResult:
        """Ensure total portfolio exposure doesn't exceed limit."""
        if signal.action in (TradeAction.SELL, TradeAction.HOLD):
            return RiskCheckResult(approved=True, signal=signal)

        current_exposure = state.get("exposure_pct", 0)

        # If already over the cap, reject all new buys outright
        if current_exposure >= self.risk.max_total_exposure_pct:
            return RiskCheckResult(
                approved=False,
                signal=signal,
                reason=(
                    f"Already over-exposed at {current_exposure:.1%} "
                    f"(cap {self.risk.max_total_exposure_pct:.1%}). "
                    f"Close positions before adding new ones."
                ),
            )

        new_exposure = current_exposure + signal.position_size_pct

        if new_exposure > self.risk.max_total_exposure_pct:
            remaining = max(0, self.risk.max_total_exposure_pct - current_exposure)
            if remaining < 0.02:  # Less than 2% room — reject
                return RiskCheckResult(
                    approved=False,
                    signal=signal,
                    reason=f"Total exposure {current_exposure:.1%} + {signal.position_size_pct:.1%} would exceed {self.risk.max_total_exposure_pct:.1%} limit.",
                )
            # Clamp to remaining room
            return RiskCheckResult(
                approved=True,
                signal=signal,
                adjusted_size_pct=remaining,
            )
        return RiskCheckResult(approved=True, signal=signal)

    def _check_options_exposure(
        self, signal: TradeSignal, state: dict
    ) -> RiskCheckResult:
        """Ensure options exposure doesn't exceed limit."""
        is_options_trade = signal.action in (
            TradeAction.BUY_CALL, TradeAction.BUY_PUT,
            TradeAction.SELL_CALL, TradeAction.SELL_PUT,
        )
        if not is_options_trade:
            return RiskCheckResult(approved=True, signal=signal)

        equity = state.get("equity", 0)
        if equity <= 0:
            return RiskCheckResult(
                approved=False,
                signal=signal,
                reason="Cannot open options position with zero or negative equity.",
            )
        current_options = state.get("options_exposure", 0)
        options_pct = current_options / equity
        new_options_pct = options_pct + signal.position_size_pct

        if new_options_pct > self.risk.max_options_exposure_pct:
            return RiskCheckResult(
                approved=False,
                signal=signal,
                reason=f"Options exposure {options_pct:.1%} + {signal.position_size_pct:.1%} would exceed {self.risk.max_options_exposure_pct:.1%} limit.",
            )
        return RiskCheckResult(approved=True, signal=signal)

    def _check_pdt_limit(
        self, signal: TradeSignal, state: dict
    ) -> RiskCheckResult:
        """Track day trades to avoid PDT violation."""
        # We don't do day trades by design, but track just in case
        day_trades = state.get("day_trade_count", 0)
        if day_trades >= self.risk.max_day_trades:
            # Only block if this would be a day trade (bought and sold same day)
            # For now, log a warning — actual day trade detection happens at execution
            logger.warning("Day trade count at %d — close to PDT limit", day_trades)
        return RiskCheckResult(approved=True, signal=signal)

    def _check_has_stop_loss(
        self, signal: TradeSignal, state: dict
    ) -> RiskCheckResult:
        """
        Ensure buy signals have a stop-loss defined.
        Exception: long options (buy_call, buy_put) don't require a stop-loss
        because the max loss is already defined (the premium paid).
        """
        is_long_option = signal.action in (
            TradeAction.BUY_CALL, TradeAction.BUY_PUT,
        )
        is_equity_buy = signal.action == TradeAction.BUY

        if is_equity_buy and signal.stop_loss_price is None:
            return RiskCheckResult(
                approved=False,
                signal=signal,
                reason="Buy signal rejected: no stop-loss price defined.",
            )
        return RiskCheckResult(approved=True, signal=signal)
