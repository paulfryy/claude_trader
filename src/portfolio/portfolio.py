"""
Portfolio state tracker — tracks positions, cash, P&L, and exposure.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import PORTFOLIO_LOGS_DIR, Settings

logger = logging.getLogger(__name__)


class PortfolioTracker:
    """Tracks portfolio state and records daily snapshots."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._starting_capital = settings.starting_capital
        self._high_watermark: float = settings.starting_capital

    def build_state(self, account_info: dict, positions: list[dict]) -> dict:
        """
        Build a complete portfolio state snapshot from live data.

        Returns a dict with portfolio metrics for analysis and logging.
        """
        equity = account_info["equity"]
        cash = account_info["cash"]
        portfolio_value = account_info["portfolio_value"]

        # Calculate exposure
        total_position_value = sum(abs(p["market_value"]) for p in positions)
        exposure_pct = total_position_value / equity if equity > 0 else 0

        # Options vs equity exposure
        options_value = sum(
            abs(p["market_value"]) for p in positions
            if _is_options_position(p)
        )
        equity_value = total_position_value - options_value

        # P&L
        total_unrealized_pl = sum(p["unrealized_pl"] for p in positions)
        total_return_pct = (equity - self._starting_capital) / self._starting_capital

        # Update high watermark
        if equity > self._high_watermark:
            self._high_watermark = equity

        # Drawdown from peak
        drawdown_pct = (
            (self._high_watermark - equity) / self._high_watermark
            if self._high_watermark > 0
            else 0
        )

        state = {
            "timestamp": datetime.now().isoformat(),
            "equity": equity,
            "cash": cash,
            "portfolio_value": portfolio_value,
            "starting_capital": self._starting_capital,
            "total_return_pct": total_return_pct,
            "total_position_value": total_position_value,
            "exposure_pct": exposure_pct,
            "equity_exposure": equity_value,
            "options_exposure": options_value,
            "unrealized_pl": total_unrealized_pl,
            "high_watermark": self._high_watermark,
            "drawdown_pct": drawdown_pct,
            "day_trade_count": account_info.get("day_trade_count", 0),
            "num_positions": len(positions),
            "positions": positions,
        }

        return state

    def save_snapshot(self, state: dict) -> Path:
        """Save a portfolio snapshot to the logs directory."""
        PORTFOLIO_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        filepath = PORTFOLIO_LOGS_DIR / f"{date_str}_{time_str}.json"

        with open(filepath, "w") as f:
            json.dump(state, f, indent=2, default=str)

        logger.info("Portfolio snapshot saved: %s", filepath)
        return filepath


def _is_options_position(position: dict) -> bool:
    """Check if a position is an options contract (heuristic)."""
    symbol = position.get("symbol", "")
    # Alpaca options symbols are longer and contain date/strike info
    return len(symbol) > 10
