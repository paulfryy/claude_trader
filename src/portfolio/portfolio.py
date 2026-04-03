"""
Portfolio state tracker — tracks positions, cash, P&L, and exposure.

Uses a "virtual equity" model for paper trading: the agent sizes positions
based on starting_capital ($1000) rather than the paper account's $100k.
This ensures the agent behaves identically to how it will with real money.
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
        Build a complete portfolio state snapshot.

        Uses virtual equity based on starting_capital + unrealized P&L from
        our positions. This way the agent sizes trades based on $1000, not
        the paper account's $100k.
        """
        # Calculate position values
        total_position_value = sum(abs(p["market_value"]) for p in positions)
        total_unrealized_pl = sum(p["unrealized_pl"] for p in positions)

        # Virtual equity = starting capital + P&L from our trades
        # This is what the agent uses for all sizing and risk decisions
        virtual_equity = self._starting_capital + total_unrealized_pl
        virtual_cash = virtual_equity - total_position_value

        # Exposure calculated against virtual equity
        exposure_pct = total_position_value / virtual_equity if virtual_equity > 0 else 0

        # Options vs equity exposure
        options_value = sum(
            abs(p["market_value"]) for p in positions
            if _is_options_position(p)
        )
        equity_value = total_position_value - options_value

        # P&L
        total_return_pct = (virtual_equity - self._starting_capital) / self._starting_capital

        # Update high watermark
        if virtual_equity > self._high_watermark:
            self._high_watermark = virtual_equity

        # Drawdown from peak
        drawdown_pct = (
            (self._high_watermark - virtual_equity) / self._high_watermark
            if self._high_watermark > 0
            else 0
        )

        state = {
            "timestamp": datetime.now().isoformat(),
            # Virtual equity — what the agent uses for decisions
            "equity": virtual_equity,
            "cash": virtual_cash,
            "starting_capital": self._starting_capital,
            "total_return_pct": total_return_pct,
            # Positions and exposure
            "total_position_value": total_position_value,
            "exposure_pct": exposure_pct,
            "equity_exposure": equity_value,
            "options_exposure": options_value,
            "unrealized_pl": total_unrealized_pl,
            # Risk metrics
            "high_watermark": self._high_watermark,
            "drawdown_pct": drawdown_pct,
            "day_trade_count": account_info.get("day_trade_count", 0),
            # Positions
            "num_positions": len(positions),
            "positions": positions,
            # Raw Alpaca account (for reference/debugging)
            "alpaca_equity": account_info["equity"],
            "alpaca_cash": account_info["cash"],
            "alpaca_buying_power": account_info["buying_power"],
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
