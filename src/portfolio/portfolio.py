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

from src.config import PORTFOLIO_LOGS_DIR, Settings, get_logs_dir

logger = logging.getLogger(__name__)


class PortfolioTracker:
    """Tracks portfolio state and records daily snapshots."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._starting_capital = settings.starting_capital
        self._logs_dir = settings.logs_dir
        self._portfolio_logs_dir = settings.portfolio_logs_dir
        self._watermark_file = self._logs_dir / "high_watermark.json"
        self._high_watermark: float = self._load_watermark()

    def build_state(self, account_info: dict, positions: list[dict]) -> dict:
        """
        Build a complete portfolio state snapshot.

        Live mode: uses real Alpaca account equity directly.
        Paper mode: uses virtual equity (starting_capital + P&L) to simulate
        a smaller account on the $100k paper balance.
        """
        # Calculate position values
        total_position_value = sum(abs(p["market_value"]) for p in positions)
        total_unrealized_pl = sum(p["unrealized_pl"] for p in positions)

        if self.settings.is_paper:
            # Paper: virtual equity model — simulate smaller account
            equity = self._starting_capital + total_unrealized_pl
            cash = equity - total_position_value
        else:
            # Live: use real Alpaca numbers
            equity = account_info["equity"]
            cash = account_info["cash"]

        # Guard: if equity is zero or negative, force max exposure
        # to trigger the drawdown circuit breaker and halt all new trades
        if equity <= 0:
            logger.error(
                "EQUITY IS <= 0 ($%.2f). All new trades will be blocked.",
                equity,
            )
            equity = max(equity, 1.0)  # Prevent division by zero
            exposure_pct = 1.0  # Force circuit breaker
        else:
            exposure_pct = total_position_value / equity

        # Options vs equity exposure
        options_value = sum(
            abs(p["market_value"]) for p in positions
            if _is_options_position(p)
        )
        equity_value = total_position_value - options_value

        # P&L
        total_return_pct = (equity - self._starting_capital) / self._starting_capital

        # Update high watermark (persisted to disk so it survives restarts)
        if equity > self._high_watermark:
            self._high_watermark = equity
            self._save_watermark()

        # Drawdown from peak
        drawdown_pct = (
            (self._high_watermark - equity) / self._high_watermark
            if self._high_watermark > 0
            else 0
        )

        state = {
            "timestamp": datetime.now().isoformat(),
            # Virtual equity — what the agent uses for decisions
            "equity": equity,
            "cash": cash,
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
        self._portfolio_logs_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        filepath = self._portfolio_logs_dir / f"{date_str}_{time_str}.json"

        with open(filepath, "w") as f:
            json.dump(state, f, indent=2, default=str)

        logger.info("Portfolio snapshot saved: %s", filepath)
        return filepath


    def _load_watermark(self) -> float:
        """Load high watermark from disk, or use starting capital if none exists."""
        if self._watermark_file.exists():
            try:
                with open(self._watermark_file) as f:
                    data = json.load(f)
                saved = data.get("high_watermark", self._starting_capital)
                logger.info("Loaded high watermark: $%.2f", saved)
                return saved
            except Exception:
                pass
        return self._starting_capital

    def _save_watermark(self):
        """Persist high watermark to disk."""
        self._watermark_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._watermark_file, "w") as f:
            json.dump({
                "high_watermark": self._high_watermark,
                "updated_at": datetime.now().isoformat(),
            }, f, indent=2)


def _is_options_position(position: dict) -> bool:
    """Check if a position is an options contract (heuristic)."""
    symbol = position.get("symbol", "")
    # Alpaca options symbols are longer and contain date/strike info
    return len(symbol) > 10
