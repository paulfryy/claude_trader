"""
Performance analytics for the trading agent.

Computes stats from the trade journals and portfolio snapshots:
- Total return, alpha vs SPY, Sharpe, max drawdown
- Win rate, avg win/loss, expectancy (per-trade stats)
- Equity curve (aggregated daily snapshots)
- Per-trade realized P&L (closed positions with entry and exit)

Read-only: analyzes existing logs without touching state.
"""

import json
import logging
import statistics
from datetime import datetime
from pathlib import Path

from src.config import Settings, get_logs_dir, get_portfolio_logs_dir, get_trade_logs_dir

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """Analyzes historical trade and portfolio data for a given mode."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.mode = settings.trading_mode
        self.starting_capital = settings.starting_capital

    def get_equity_curve(self) -> list[dict]:
        """
        Build a time-series of portfolio equity from daily snapshots.
        Takes the latest snapshot per calendar day.

        Returns list of {date, equity, spy_return, portfolio_return, alpha}
        """
        portfolio_dir = get_portfolio_logs_dir(self.mode)
        if not portfolio_dir.exists():
            return []

        # Group snapshots by date, keeping the latest per day
        daily: dict[str, dict] = {}
        for snap_file in sorted(portfolio_dir.glob("*.json")):
            try:
                with open(snap_file) as f:
                    data = json.load(f)
            except Exception:
                continue

            ts = data.get("timestamp", "")
            if not ts:
                continue
            date = ts[:10]

            # Keep the latest snapshot per day (files are sorted)
            daily[date] = data

        # Get SPY benchmark data
        spy_start = self._get_spy_start_price()

        curve = []
        for date in sorted(daily.keys()):
            snap = daily[date]
            equity = snap.get("equity", self.starting_capital)
            portfolio_return = (equity - self.starting_capital) / self.starting_capital
            curve.append({
                "date": date,
                "equity": equity,
                "portfolio_return_pct": portfolio_return,
                "exposure_pct": snap.get("exposure_pct", 0),
                "num_positions": snap.get("num_positions", 0),
                "drawdown_pct": snap.get("drawdown_pct", 0),
            })

        return curve

    def get_trade_stats(self) -> dict:
        """
        Compute per-trade statistics from closed positions in the trade journal.

        Returns:
            dict with: total_trades, wins, losses, win_rate, avg_win, avg_loss,
                      profit_factor, expectancy, best_trade, worst_trade, total_realized_pl
        """
        trade_dir = get_trade_logs_dir(self.mode)
        if not trade_dir.exists():
            return self._empty_trade_stats()

        closed_trades = []
        for f in sorted(trade_dir.glob("*.json")):
            if "REJECTED" in f.name:
                continue
            try:
                with open(f) as fh:
                    data = json.load(fh)
            except Exception:
                continue

            signal = data.get("signal", {})
            exe = data.get("execution", {})
            action = signal.get("action", "")
            status = exe.get("status", "")

            # Only count closed positions (sell signals / close_position results)
            if action in ("sell", "sell_call", "sell_put") or status == "closed":
                realized = exe.get("realized_pl")
                if realized is None:
                    continue
                closed_trades.append({
                    "symbol": signal.get("symbol", exe.get("symbol", "")),
                    "timestamp": data.get("timestamp", ""),
                    "realized_pl": realized,
                    "realized_plpc": exe.get("realized_plpc", 0),
                    "rationale": signal.get("rationale", ""),
                })

        if not closed_trades:
            return self._empty_trade_stats()

        wins = [t for t in closed_trades if t["realized_pl"] > 0]
        losses = [t for t in closed_trades if t["realized_pl"] < 0]

        total_realized = sum(t["realized_pl"] for t in closed_trades)
        win_total = sum(t["realized_pl"] for t in wins)
        loss_total = abs(sum(t["realized_pl"] for t in losses))

        stats = {
            "total_trades": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed_trades) if closed_trades else 0,
            "avg_win": statistics.mean(t["realized_pl"] for t in wins) if wins else 0,
            "avg_loss": statistics.mean(t["realized_pl"] for t in losses) if losses else 0,
            "best_trade": max(closed_trades, key=lambda t: t["realized_pl"]) if closed_trades else None,
            "worst_trade": min(closed_trades, key=lambda t: t["realized_pl"]) if closed_trades else None,
            "total_realized_pl": total_realized,
            # Profit factor = gross wins / gross losses (>1 = profitable)
            "profit_factor": (win_total / loss_total) if loss_total > 0 else float("inf") if win_total > 0 else 0,
            # Expectancy = avg P&L per trade
            "expectancy": total_realized / len(closed_trades) if closed_trades else 0,
            "closed_trades": closed_trades,
        }
        return stats

    def get_portfolio_stats(self) -> dict:
        """
        Compute portfolio-level stats from the equity curve.

        Returns:
            dict with: current_equity, total_return, max_drawdown, sharpe, days_active
        """
        curve = self.get_equity_curve()
        if not curve:
            return {
                "current_equity": self.starting_capital,
                "total_return_pct": 0,
                "max_drawdown_pct": 0,
                "sharpe": None,
                "days_active": 0,
                "peak_equity": self.starting_capital,
            }

        equities = [p["equity"] for p in curve]
        current = equities[-1]
        peak = max(equities)

        # Max drawdown from peak
        max_dd = 0
        running_peak = equities[0]
        for eq in equities:
            if eq > running_peak:
                running_peak = eq
            dd = (running_peak - eq) / running_peak if running_peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Daily returns for Sharpe calculation
        daily_returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                daily_returns.append((equities[i] - equities[i - 1]) / equities[i - 1])

        # Annualized Sharpe ratio (assuming 252 trading days)
        sharpe = None
        if len(daily_returns) >= 3:
            mean_return = statistics.mean(daily_returns)
            std_return = statistics.stdev(daily_returns)
            if std_return > 0:
                sharpe = (mean_return / std_return) * (252 ** 0.5)

        return {
            "current_equity": current,
            "total_return_pct": (current - self.starting_capital) / self.starting_capital,
            "max_drawdown_pct": max_dd,
            "peak_equity": peak,
            "sharpe": sharpe,
            "days_active": len(curve),
        }

    def get_combined_stats(self) -> dict:
        """Return portfolio + trade stats together, plus SPY benchmark."""
        portfolio = self.get_portfolio_stats()
        trades = self.get_trade_stats()
        spy = self._get_spy_comparison(portfolio["current_equity"])

        return {
            "portfolio": portfolio,
            "trades": trades,
            "spy": spy,
            "starting_capital": self.starting_capital,
            "mode": self.mode,
        }

    def _get_spy_start_price(self) -> float | None:
        """Get the recorded SPY start price from benchmark.json."""
        bf = get_logs_dir(self.mode) / "benchmark.json"
        if not bf.exists():
            return None
        try:
            with open(bf) as f:
                return json.load(f).get("start_price")
        except Exception:
            return None

    def _get_spy_comparison(self, current_equity: float) -> dict | None:
        """
        Get SPY comparison using recorded start price and a fresh live price.
        """
        start = self._get_spy_start_price()
        if not start:
            return None

        try:
            from src.data.market_data import MarketDataClient
            market = MarketDataClient(self.settings)
            quote = market.get_latest_quote("SPY")
            current_price = quote.get("ask") or quote.get("bid") or 0
            if current_price <= 0:
                return None

            spy_return = (current_price - start) / start
            portfolio_return = (current_equity - self.starting_capital) / self.starting_capital
            alpha = portfolio_return - spy_return

            return {
                "start_price": start,
                "current_price": current_price,
                "spy_return_pct": spy_return,
                "alpha": alpha,
            }
        except Exception as e:
            logger.debug("Could not fetch SPY comparison: %s", e)
            return None

    @staticmethod
    def _empty_trade_stats() -> dict:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "best_trade": None,
            "worst_trade": None,
            "total_realized_pl": 0,
            "profit_factor": 0,
            "expectancy": 0,
            "closed_trades": [],
        }
