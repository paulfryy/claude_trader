"""
Daily summary writer — produces human-readable markdown summaries
of each trading day for review across sessions.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.analysis.signals import MarketAnalysis
from src.config import LOGS_DIR

logger = logging.getLogger(__name__)

SUMMARY_DIR = LOGS_DIR / "summaries"


def write_daily_summary(
    analysis: MarketAnalysis,
    portfolio_state: dict,
    execution_results: list[dict],
    rejected_signals: list[dict],
    benchmark: dict | None = None,
) -> Path:
    """
    Write a human-readable markdown summary for this analysis cycle.
    Appends to the day's summary file so multiple cycles build up a full picture.
    """
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = SUMMARY_DIR / f"{date_str}.md"

    timestamp = datetime.now().strftime("%H:%M:%S ET")
    is_new_file = not filepath.exists()

    with open(filepath, "a", encoding="utf-8") as f:
        if is_new_file:
            f.write(f"# Trading Summary — {date_str}\n\n")
            f.write(f"**Starting Equity:** ${portfolio_state.get('equity', 0):,.2f}\n")
            f.write(f"**Cash:** ${portfolio_state.get('cash', 0):,.2f}\n")
            f.write(f"**Positions:** {portfolio_state.get('num_positions', 0)}\n")
            f.write(f"**Exposure:** {portfolio_state.get('exposure_pct', 0):.1%}\n")
            f.write(f"**Drawdown from Peak:** {portfolio_state.get('drawdown_pct', 0):.1%}\n\n")
            f.write("---\n\n")

        # Cycle header
        f.write(f"## Analysis Cycle — {timestamp}\n\n")

        # Market assessment
        regime_conf = analysis.regime_confidence.value if hasattr(analysis.regime_confidence, 'value') else analysis.regime_confidence
        f.write(f"**Market Regime:** {analysis.market_regime} ")
        f.write(f"(confidence: {regime_conf})\n\n")

        f.write("### Key Observations\n")
        for obs in analysis.key_observations:
            f.write(f"- {obs}\n")
        f.write("\n")

        if analysis.sector_outlook:
            f.write("### Sector Outlook\n")
            for sector, outlook in analysis.sector_outlook.items():
                f.write(f"- **{sector}:** {outlook}\n")
            f.write("\n")

        # Trades executed
        executed = [r for r in execution_results if r.get("status") == "submitted"]
        closed = [r for r in execution_results if r.get("status") == "closed"]
        errors = [r for r in execution_results if r.get("status") == "error"]

        if executed:
            f.write("### Trades Executed\n")
            for trade in executed:
                f.write(f"- **{trade.get('side', '').upper()} {trade.get('symbol')}** — ")
                f.write(f"{trade.get('qty')} shares (Order ID: {trade.get('order_id', 'N/A')})\n")
            f.write("\n")

        if closed:
            f.write("### Positions Closed\n")
            for c in closed:
                f.write(f"- **{c.get('symbol')}** — closed\n")
            f.write("\n")

        # Trade rationales (the most important part for learning)
        if analysis.trade_signals:
            f.write("### Trade Rationales\n")
            for sig in analysis.trade_signals:
                status = "EXECUTED"
                for r in rejected_signals:
                    if r.get("symbol") == sig.symbol:
                        status = f"REJECTED — {r.get('reason', 'unknown')}"
                        break

                conviction = sig.conviction.value if hasattr(sig.conviction, 'value') else sig.conviction
                target = f"${sig.target_price:.2f}" if sig.target_price else "N/A"
                stop = f"${sig.stop_loss_price:.2f}" if sig.stop_loss_price else "N/A (long option — max loss = premium)"
                rr = f"{sig.risk_reward_ratio:.1f}" if sig.risk_reward_ratio else "N/A"

                f.write(f"\n**{sig.action.value.upper()} {sig.symbol}** [{status}]\n")
                f.write(f"- Conviction: {conviction}\n")
                f.write(f"- Size: {sig.position_size_pct:.0%} of portfolio\n")
                f.write(f"- Target: {target}\n")
                f.write(f"- Stop Loss: {stop}\n")
                f.write(f"- R/R Ratio: {rr}\n")
                f.write(f"- Time Horizon: {sig.time_horizon}\n")
                f.write(f"- Rationale: {sig.rationale}\n")
            f.write("\n")

        if errors:
            f.write("### Errors\n")
            for e in errors:
                f.write(f"- {e.get('symbol', 'unknown')}: {e.get('error', 'unknown error')}\n")
            f.write("\n")

        # Portfolio snapshot after cycle
        f.write("### Portfolio After Cycle\n")
        f.write(f"- Equity: ${portfolio_state.get('equity', 0):,.2f}\n")
        f.write(f"- Cash: ${portfolio_state.get('cash', 0):,.2f}\n")
        f.write(f"- Exposure: {portfolio_state.get('exposure_pct', 0):.1%}\n")
        f.write(f"- Positions: {portfolio_state.get('num_positions', 0)}\n")
        f.write(f"- Total Return: {portfolio_state.get('total_return_pct', 0):.2%}\n")

        if benchmark:
            f.write(f"\n### Benchmark (SPY)\n")
            f.write(f"- SPY Price: ${benchmark.get('price', 0):,.2f}\n")
            f.write(f"- SPY Return (from start): {benchmark.get('return_pct', 0):.2%}\n")
            alpha = portfolio_state.get('total_return_pct', 0) - benchmark.get('return_pct', 0)
            f.write(f"- Alpha: {alpha:+.2%}\n")
        f.write(f"- Unrealized P&L: ${portfolio_state.get('unrealized_pl', 0):,.2f}\n")
        f.write("\n---\n\n")

    logger.info("Daily summary updated: %s", filepath)
    return filepath
