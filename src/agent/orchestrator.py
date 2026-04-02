"""
Main agent orchestrator — the core loop that coordinates analysis, risk, and execution.
"""

import logging
import sys
from datetime import datetime

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler

from src.analysis.analyst import ClaudeAnalyst
from src.analysis.signals import TradeAction
from src.config import load_settings
from src.data.indicators import add_all_indicators, summarize_indicators
from src.data.market_data import MarketDataClient
from src.data.news import NewsDataClient
from src.execution.orders import OrderExecutor
from src.logging_utils.daily_summary import write_daily_summary
from src.logging_utils.decision_log import DecisionLog
from src.logging_utils.trade_journal import TradeJournal
from src.portfolio.portfolio import PortfolioTracker
from src.portfolio.risk import RiskManager
from src.portfolio.sizing import calculate_shares

logger = logging.getLogger(__name__)
console = Console()

# Default watchlist — will be made configurable later
DEFAULT_WATCHLIST = [
    "SPY", "QQQ", "IWM",          # Major indices
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",  # Mega caps
    "AMD", "NFLX", "CRM",         # Growth
    "XLF", "XLE", "XLK",          # Sector ETFs
]


def setup_logging(level: str = "INFO"):
    """Configure rich logging."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def run_analysis_cycle(
    settings=None,
    watchlist: list[str] | None = None,
):
    """
    Run one complete analysis and trading cycle.

    Steps:
    1. Fetch portfolio state
    2. Fetch market data & news for watchlist
    3. Run Claude analysis
    4. Validate signals against risk rules
    5. Execute approved trades
    6. Log everything
    """
    if settings is None:
        settings = load_settings()

    watchlist = watchlist or DEFAULT_WATCHLIST

    # Initialize components
    market_data = MarketDataClient(settings)
    news_client = NewsDataClient(settings)
    analyst = ClaudeAnalyst(settings)
    portfolio_tracker = PortfolioTracker(settings)
    risk_manager = RiskManager(settings)
    executor = OrderExecutor(settings)
    trade_journal = TradeJournal()
    decision_log = DecisionLog()

    # Step 1: Check market status
    if not market_data.is_market_open():
        logger.info("Market is closed. Skipping trading cycle.")
        return

    logger.info("=== Starting analysis cycle at %s ===", datetime.now().strftime("%Y-%m-%d %H:%M"))

    # Step 2: Fetch portfolio state
    account_info = market_data.get_account()
    positions = market_data.get_positions()
    portfolio_state = portfolio_tracker.build_state(account_info, positions)
    portfolio_tracker.save_snapshot(portfolio_state)

    logger.info(
        "Portfolio: $%.2f equity, $%.2f cash, %d positions, %.1f%% exposure",
        portfolio_state["equity"],
        portfolio_state["cash"],
        portfolio_state["num_positions"],
        portfolio_state["exposure_pct"] * 100,
    )

    # Step 3: Fetch market data for watchlist
    watchlist_data = {}
    for symbol in watchlist:
        try:
            bars = market_data.get_bars(symbol, limit=100)
            if bars.empty:
                continue
            bars_with_indicators = add_all_indicators(bars)
            indicators = summarize_indicators(bars_with_indicators)
            quote = market_data.get_latest_quote(symbol)
            watchlist_data[symbol] = {
                "indicators": indicators,
                "quote": quote,
            }
        except Exception as e:
            logger.warning("Failed to fetch data for %s: %s", symbol, e)

    # Step 4: Fetch news
    market_news = news_client.get_market_news(limit=15)
    symbol_news = {}
    # Only fetch news for current positions and top watchlist items
    news_symbols = [p["symbol"] for p in positions] + watchlist[:5]
    for symbol in set(news_symbols):
        try:
            symbol_news[symbol] = news_client.get_symbol_news(symbol, limit=5)
        except Exception as e:
            logger.warning("Failed to fetch news for %s: %s", symbol, e)

    # Step 5: Run Claude analysis
    logger.info("Running Claude analysis on %d symbols...", len(watchlist_data))
    analysis = analyst.analyze_market(
        account_info=account_info,
        positions=positions,
        watchlist_data=watchlist_data,
        market_news=market_news,
        symbol_news=symbol_news,
    )

    logger.info(
        "Analysis complete: regime=%s (%s), %d signals, %d exits",
        analysis.market_regime,
        analysis.regime_confidence,
        len(analysis.trade_signals),
        len(analysis.positions_to_close),
    )

    # Step 6: Close positions Claude wants to exit
    execution_results = []
    for symbol in analysis.positions_to_close:
        result = executor.close_position(symbol)
        execution_results.append(result)
        logger.info("Closing position: %s → %s", symbol, result["status"])

    # Step 7: Validate and execute new trade signals
    rejected_signals = []
    for signal in analysis.trade_signals:
        if signal.action == TradeAction.HOLD:
            continue

        # Risk check
        risk_result = risk_manager.validate_signal(signal, portfolio_state)

        if not risk_result.approved:
            trade_journal.log_rejection(signal, risk_result.reason, portfolio_state)
            rejected_signals.append({"symbol": signal.symbol, "reason": risk_result.reason})
            continue

        # Determine position size (use adjusted size if risk clamped it)
        size_pct = risk_result.adjusted_size_pct or signal.position_size_pct

        # Get current price for sizing
        quote = watchlist_data.get(signal.symbol, {}).get("quote", {})
        current_price = quote.get("ask", 0) or quote.get("bid", 0)

        if current_price <= 0:
            logger.warning("No price available for %s, skipping", signal.symbol)
            continue

        # Calculate quantity
        qty = calculate_shares(signal, portfolio_state["equity"], current_price, size_pct)

        # Execute
        result = executor.execute_signal(signal, qty, current_price)
        execution_results.append(result)

        # Log the trade
        trade_journal.log_trade(
            signal=signal,
            execution_result=result,
            portfolio_state=portfolio_state,
            risk_result={"adjusted_size_pct": risk_result.adjusted_size_pct} if risk_result.adjusted_size_pct else None,
        )

    # Step 8: Log the complete decision cycle
    decision_log.log_analysis(
        analysis=analysis,
        portfolio_state=portfolio_state,
        execution_results=execution_results,
    )

    # Step 9: Write human-readable daily summary
    write_daily_summary(
        analysis=analysis,
        portfolio_state=portfolio_state,
        execution_results=execution_results,
        rejected_signals=rejected_signals,
    )

    logger.info(
        "=== Cycle complete: %d trades executed, %d rejected ===",
        sum(1 for r in execution_results if r.get("status") == "submitted"),
        len(rejected_signals),
    )


def main():
    """Entry point for the trading agent."""
    load_dotenv()
    settings = load_settings()
    setup_logging(settings.log_level)

    console.print("[bold green]Claude Trading Agent[/bold green]")
    console.print(f"Mode: {'PAPER' if settings.is_paper else '[bold red]LIVE[/bold red]'}")
    console.print(f"Model: {settings.claude.claude_model}")

    if not settings.is_paper:
        console.print("[bold red]⚠ LIVE TRADING MODE — Real money at risk![/bold red]")
        response = input("Type 'CONFIRM' to proceed: ")
        if response != "CONFIRM":
            console.print("Aborted.")
            sys.exit(0)

    run_analysis_cycle(settings)


if __name__ == "__main__":
    main()
