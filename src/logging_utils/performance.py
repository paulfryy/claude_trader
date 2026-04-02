"""
Performance tracking — calculates and logs portfolio metrics vs benchmark.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import PORTFOLIO_LOGS_DIR

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """Tracks portfolio performance metrics over time."""

    def __init__(self, starting_capital: float):
        self._starting_capital = starting_capital
        self._daily_values: list[dict] = []

    def record_daily(self, equity: float, benchmark_value: float | None = None):
        """Record end-of-day portfolio value and optional benchmark."""
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "equity": equity,
            "return_pct": (equity - self._starting_capital) / self._starting_capital,
            "benchmark_value": benchmark_value,
        }
        self._daily_values.append(entry)

    def get_metrics(self) -> dict:
        """Calculate key performance metrics from recorded daily values."""
        if not self._daily_values:
            return {"status": "no data"}

        values = [d["equity"] for d in self._daily_values]
        returns = []
        for i in range(1, len(values)):
            r = (values[i] - values[i - 1]) / values[i - 1]
            returns.append(r)

        peak = self._starting_capital
        max_drawdown = 0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_drawdown:
                max_drawdown = dd

        total_return = (values[-1] - self._starting_capital) / self._starting_capital

        # Win rate from daily returns
        wins = sum(1 for r in returns if r > 0)
        win_rate = wins / len(returns) if returns else 0

        metrics = {
            "total_return_pct": total_return,
            "current_equity": values[-1],
            "starting_capital": self._starting_capital,
            "max_drawdown_pct": max_drawdown,
            "win_rate_daily": win_rate,
            "num_trading_days": len(self._daily_values),
            "peak_equity": max(values),
            "trough_equity": min(values),
        }
        return metrics

    def save_report(self) -> Path:
        """Save a performance report to disk."""
        PORTFOLIO_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": datetime.now().isoformat(),
            "metrics": self.get_metrics(),
            "daily_values": self._daily_values,
        }
        filepath = PORTFOLIO_LOGS_DIR / f"performance_{datetime.now().strftime('%Y-%m-%d')}.json"
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Performance report saved: %s", filepath)
        return filepath
