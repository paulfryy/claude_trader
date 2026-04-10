"""
Trade journal — logs every trade with full context for post-hoc analysis.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.analysis.signals import TradeSignal
from src.config import TRADE_LOGS_DIR, Settings

logger = logging.getLogger(__name__)


class TradeJournal:
    """Records every trade with entry rationale, execution details, and later — outcome."""

    def __init__(self, settings: Settings | None = None):
        self._dir = settings.trade_logs_dir if settings else TRADE_LOGS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def log_trade(
        self,
        signal: TradeSignal,
        execution_result: dict,
        portfolio_state: dict,
        risk_result: dict | None = None,
    ) -> Path:
        """
        Log a trade entry to the journal.

        Records the signal, execution result, portfolio state at time of trade,
        and any risk adjustments that were made.
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "signal": signal.model_dump(),
            "execution": execution_result,
            "portfolio_state_at_trade": {
                "equity": portfolio_state.get("equity"),
                "cash": portfolio_state.get("cash"),
                "exposure_pct": portfolio_state.get("exposure_pct"),
                "drawdown_pct": portfolio_state.get("drawdown_pct"),
                "num_positions": portfolio_state.get("num_positions"),
            },
            "risk_adjustments": risk_result if risk_result else None,
        }

        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        filepath = self._dir / f"{date_str}_{signal.symbol}_{signal.action.value}_{time_str}.json"

        with open(filepath, "w") as f:
            json.dump(entry, f, indent=2, default=str)

        logger.info("Trade logged: %s %s → %s", signal.action.value, signal.symbol, filepath.name)
        return filepath

    def log_rejection(
        self,
        signal: TradeSignal,
        rejection_reason: str,
        portfolio_state: dict,
    ) -> Path:
        """Log a trade that was rejected by risk management."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "status": "rejected",
            "signal": signal.model_dump(),
            "rejection_reason": rejection_reason,
            "portfolio_state_at_rejection": {
                "equity": portfolio_state.get("equity"),
                "exposure_pct": portfolio_state.get("exposure_pct"),
                "drawdown_pct": portfolio_state.get("drawdown_pct"),
            },
        }

        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        filepath = self._dir / f"{date_str}_{signal.symbol}_REJECTED_{time_str}.json"

        with open(filepath, "w") as f:
            json.dump(entry, f, indent=2, default=str)

        logger.info("Rejection logged: %s %s — %s", signal.action.value, signal.symbol, rejection_reason)
        return filepath
