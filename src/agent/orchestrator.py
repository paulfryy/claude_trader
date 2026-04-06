"""
Main agent orchestrator — the core loop that coordinates analysis, risk, and execution.
"""

import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler

from src.analysis.analyst import ClaudeAnalyst
from src.analysis.signals import TradeAction
from src.config import ERROR_LOGS_DIR, load_settings
from src.data.indicators import add_all_indicators, summarize_indicators
from src.data.market_data import MarketDataClient
from src.data.news import NewsDataClient
from src.data.screener import Screener
from src.execution.orders import OrderExecutor
from src.logging_utils.benchmark import get_benchmark_data
from src.logging_utils.daily_summary import write_daily_summary
from src.logging_utils.decision_log import DecisionLog
from src.logging_utils.trade_journal import TradeJournal
from src.portfolio.portfolio import PortfolioTracker
from src.portfolio.risk import RiskManager
from src.portfolio.sizing import calculate_notional, calculate_options_contracts

logger = logging.getLogger(__name__)
console = Console()

# Fallback watchlist if screener fails
FALLBACK_WATCHLIST = [
    "SPY", "QQQ", "IWM",
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
    "AMD", "NFLX", "CRM",
    "XLF", "XLE", "XLK",
]


def setup_logging(level: str = "INFO"):
    """Configure rich logging."""
    import io
    import sys

    # Fix Windows console encoding for Unicode characters
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
        force=True,
    )


class CycleMode:
    """Controls what actions are allowed in each cycle."""

    MORNING = "morning"       # Full cycle: analyze + open + close positions
    MIDDAY = "midday"         # Defensive: analyze + close/adjust, selective new entries
    CLOSING = "closing"       # Review only: analyze + close positions, NO new entries

    @staticmethod
    def from_time(hour: int) -> str:
        """Determine cycle mode from current hour (ET)."""
        if hour < 12:
            return CycleMode.MORNING
        elif hour < 15:
            return CycleMode.MIDDAY
        else:
            return CycleMode.CLOSING


def validate_connections(settings) -> bool:
    """
    Verify API connectivity before running any cycles.
    Returns True if all connections are healthy, False otherwise.
    """
    errors = []

    # Check Alpaca
    try:
        client = MarketDataClient(settings)
        account = client.get_account()
        logger.info(
            "Alpaca OK — equity: $%s, mode: %s",
            f"{account['equity']:,.2f}",
            "PAPER" if settings.is_paper else "LIVE",
        )
    except Exception as e:
        errors.append(f"Alpaca connection failed: {e}")
        logger.error("Alpaca connection failed: %s", e)

    # Check Anthropic
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.claude.anthropic_api_key)
        resp = client.messages.create(
            model=settings.claude.claude_model,
            max_tokens=10,
            messages=[{"role": "user", "content": "Say OK"}],
        )
        logger.info("Anthropic OK — model: %s", settings.claude.claude_model)
    except Exception as e:
        errors.append(f"Anthropic connection failed: {e}")
        logger.error("Anthropic connection failed: %s", e)

    if errors:
        logger.error("Startup validation FAILED:")
        for err in errors:
            logger.error("  - %s", err)
        return False

    logger.info("All connections validated successfully.")
    return True


def _log_error(error: Exception, context: str = ""):
    """Log an error to the errors directory with full traceback."""
    ERROR_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filepath = ERROR_LOGS_DIR / f"{timestamp}_error.log"

    with open(filepath, "w") as f:
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"Context: {context}\n")
        f.write(f"Error: {type(error).__name__}: {error}\n\n")
        f.write("Traceback:\n")
        f.write(traceback.format_exc())

    logger.error("Error logged to %s", filepath)


def run_analysis_cycle(
    settings=None,
    watchlist: list[str] | None = None,
    mode: str | None = None,
    dry_run: bool = False,
):
    """
    Run one complete analysis and trading cycle.

    Args:
        settings: Application settings
        watchlist: Symbols to analyze
        mode: Cycle mode — "morning", "midday", or "closing".
              If None, determined automatically from current time.
        dry_run: If True, run the full pipeline but skip order submission.
                 Useful for testing without market hours.

    Returns:
        True if cycle completed successfully, False if it failed.
    """
    if settings is None:
        settings = load_settings()

    # Determine cycle mode
    if mode is None:
        mode = CycleMode.from_time(datetime.now().hour)

    # Initialize components
    try:
        market_data = MarketDataClient(settings)
        news_client = NewsDataClient(settings)
        analyst = ClaudeAnalyst(settings)
        portfolio_tracker = PortfolioTracker(settings)
        risk_manager = RiskManager(settings)
        executor = OrderExecutor(settings)
        screener = Screener(settings)
        trade_journal = TradeJournal()
        decision_log = DecisionLog()
    except Exception as e:
        logger.error("Failed to initialize components: %s", e)
        _log_error(e, "Component initialization")
        return False

    # Step 1: Check market status (skip in dry-run mode)
    if not dry_run:
        try:
            if not market_data.is_market_open():
                logger.info("Market is closed. Skipping trading cycle.")
                return True
        except Exception as e:
            logger.error("Failed to check market status: %s", e)
            _log_error(e, "Market status check")
            return False

    # Step 1b: Run screener to build watchlist (or use provided/fallback)
    if watchlist is None:
        try:
            watchlist = screener.screen()
            # Also include current positions so Claude always re-evaluates them
            position_symbols = [p["symbol"] for p in market_data.get_positions()]
            watchlist = list(dict.fromkeys(watchlist + position_symbols))
        except Exception as e:
            logger.warning("Screener failed, using fallback watchlist: %s", e)
            _log_error(e, "Screener")
            watchlist = FALLBACK_WATCHLIST

    run_label = "DRY-RUN " if dry_run else ""
    logger.info(
        "=== Starting %s%s analysis cycle at %s ===",
        run_label,
        mode.upper(),
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    # Step 2: Fetch portfolio state
    try:
        account_info = market_data.get_account()
        positions = market_data.get_positions()
        portfolio_state = portfolio_tracker.build_state(account_info, positions)
        portfolio_tracker.save_snapshot(portfolio_state)
    except Exception as e:
        logger.error("Failed to fetch portfolio state: %s", e)
        _log_error(e, "Portfolio state fetch")
        return False

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

    if not watchlist_data:
        logger.error("No watchlist data fetched — cannot run analysis.")
        _log_error(RuntimeError("Empty watchlist data"), "Watchlist data fetch")
        return False

    # Step 4: Fetch news (non-critical — continue even if news fails)
    market_news = []
    symbol_news = {}
    try:
        market_news = news_client.get_market_news(limit=15)
    except Exception as e:
        logger.warning("Failed to fetch market news: %s", e)

    news_symbols = [p["symbol"] for p in positions] + watchlist[:5]
    for symbol in set(news_symbols):
        try:
            symbol_news[symbol] = news_client.get_symbol_news(symbol, limit=5)
        except Exception as e:
            logger.warning("Failed to fetch news for %s: %s", symbol, e)

    # Step 4b: Get existing stop orders so Claude can see current protection
    open_stops = {}
    if not dry_run:
        try:
            open_stops = executor.get_open_stops()
            logger.info("Open stop orders: %s", list(open_stops.keys()) if open_stops else "none")
        except Exception as e:
            logger.warning("Failed to fetch open stops: %s", e)

    # Step 5: Run Claude analysis
    try:
        logger.info("Running Claude analysis on %d symbols (%s mode)...", len(watchlist_data), mode)
        analysis = analyst.analyze_market(
            account_info=account_info,
            positions=positions,
            watchlist_data=watchlist_data,
            market_news=market_news,
            symbol_news=symbol_news,
            cycle_mode=mode,
            open_stops=open_stops,
        )
    except json.JSONDecodeError as e:
        logger.error("Claude returned invalid JSON: %s", e)
        _log_error(e, "Claude JSON parsing")
        return False
    except Exception as e:
        logger.error("Claude analysis failed: %s", e)
        _log_error(e, "Claude analysis")
        return False

    logger.info(
        "Analysis complete: regime=%s (%s), %d signals, %d exits",
        analysis.market_regime,
        analysis.regime_confidence,
        len(analysis.trade_signals),
        len(analysis.positions_to_close),
    )

    # Step 6: Close positions Claude wants to exit (allowed in ALL cycle modes)
    execution_results = []
    for symbol in analysis.positions_to_close:
        # PDT protection: don't sell anything we bought today
        bought_today = _was_bought_today(symbol, positions)
        if bought_today:
            logger.warning(
                "PDT PROTECTION: Skipping close of %s — position was opened today. "
                "Selling would count as a day trade.",
                symbol,
            )
            continue

        if dry_run:
            logger.info("[DRY RUN] Would close position: %s", symbol)
            execution_results.append({"status": "dry_run", "symbol": symbol, "action": "close"})
        else:
            try:
                result = executor.close_position(symbol)
                execution_results.append(result)
                logger.info("Closing position: %s → %s", symbol, result["status"])
            except Exception as e:
                logger.error("Failed to close position %s: %s", symbol, e)
                execution_results.append({"status": "error", "symbol": symbol, "error": str(e)})

    # Step 7: Validate and execute new trade signals
    rejected_signals = []

    # In closing mode, block all new entries — analysis only
    allow_new_entries = mode != CycleMode.CLOSING

    for signal in analysis.trade_signals:
        if signal.action == TradeAction.HOLD:
            continue

        is_buy = signal.action in (
            TradeAction.BUY, TradeAction.BUY_CALL, TradeAction.BUY_PUT,
        )
        is_sell = signal.action in (
            TradeAction.SELL, TradeAction.SELL_CALL, TradeAction.SELL_PUT,
        )

        # Block new entries in closing cycle
        if is_buy and not allow_new_entries:
            reason = "Closing cycle — no new entries. Signal logged for morning review."
            logger.info("CLOSING MODE: Skipping %s %s — %s", signal.action.value, signal.symbol, reason)
            rejected_signals.append({"symbol": signal.symbol, "reason": reason})
            trade_journal.log_rejection(signal, reason, portfolio_state)
            continue

        # PDT protection: don't sell anything we bought today
        if is_sell and _was_bought_today(signal.symbol, positions):
            reason = "PDT protection: position was opened today, selling would count as a day trade."
            logger.warning("PDT PROTECTION: %s %s — %s", signal.action.value, signal.symbol, reason)
            rejected_signals.append({"symbol": signal.symbol, "reason": reason})
            trade_journal.log_rejection(signal, reason, portfolio_state)
            continue

        # Risk check
        risk_result = risk_manager.validate_signal(signal, portfolio_state)

        if not risk_result.approved:
            trade_journal.log_rejection(signal, risk_result.reason, portfolio_state)
            rejected_signals.append({"symbol": signal.symbol, "reason": risk_result.reason})
            continue

        # Determine position size (use adjusted size if risk clamped it)
        size_pct = risk_result.adjusted_size_pct or signal.position_size_pct

        # Get current price for sizing/logging
        quote = watchlist_data.get(signal.symbol, {}).get("quote", {})
        current_price = quote.get("ask", 0) or quote.get("bid", 0)

        if current_price <= 0:
            logger.warning("No price available for %s, skipping", signal.symbol)
            continue

        # Determine if this is an options or equity trade
        is_options = signal.action in (
            TradeAction.BUY_CALL, TradeAction.BUY_PUT,
            TradeAction.SELL_CALL, TradeAction.SELL_PUT,
        )

        if is_options:
            # Options: calculate contracts (can't do fractional)
            # Use the position allocation as the premium budget
            premium_budget = portfolio_state["equity"] * size_pct
            # Estimate 1 contract cost (we don't have real options chain data yet)
            # For now, skip if no strike/expiry — Claude needs to provide these
            if not signal.strike_price or not signal.expiration_date:
                logger.warning(
                    "Options signal for %s missing strike/expiry, skipping",
                    signal.symbol,
                )
                continue

            if dry_run:
                logger.info(
                    "[DRY RUN] Would execute: %s %s option on %s, strike=$%.2f, exp=%s, budget=$%.2f",
                    signal.action.value, signal.option_type or "?",
                    signal.symbol, signal.strike_price, signal.expiration_date, premium_budget,
                )
                result = {
                    "status": "dry_run",
                    "symbol": signal.symbol,
                    "side": signal.action.value,
                    "notional": premium_budget,
                    "strike": signal.strike_price,
                    "expiration": signal.expiration_date,
                }
                execution_results.append(result)
            else:
                try:
                    # Estimate 1 contract at ~$2-5 premium = $200-500 per contract
                    # With $80-150 budget on a $1000 account, usually 0-1 contracts
                    contracts = calculate_options_contracts(
                        signal, portfolio_state["equity"],
                        premium_per_contract=premium_budget,  # 1 contract = full budget
                        position_size_pct=size_pct,
                    )
                    if contracts <= 0:
                        contracts = 1  # Try at least 1 contract

                    result = executor.execute_options_signal(signal, contracts)
                    execution_results.append(result)
                except Exception as e:
                    logger.error("Options execution failed for %s: %s", signal.symbol, e)
                    result = {"status": "error", "symbol": signal.symbol, "error": str(e)}
                    execution_results.append(result)
        else:
            # Equity: use notional (dollar-based) orders for fractional shares
            notional = calculate_notional(signal, portfolio_state["equity"], current_price, size_pct)

            if dry_run:
                approx_shares = notional / current_price if current_price > 0 else 0
                logger.info(
                    "[DRY RUN] Would execute: %s $%.2f of %s (~%.2f shares @ $%.2f)",
                    signal.action.value, notional, signal.symbol, approx_shares, current_price,
                )
                result = {
                    "status": "dry_run",
                    "symbol": signal.symbol,
                    "side": signal.action.value,
                    "notional": notional,
                    "price": current_price,
                }
                execution_results.append(result)

                # Log the stop-loss we would set
                if is_buy and signal.stop_loss_price:
                    logger.info(
                        "[DRY RUN] Would set stop-loss for %s @ $%.2f",
                        signal.symbol, signal.stop_loss_price,
                    )
            else:
                try:
                    result = executor.execute_equity_signal(signal, notional)
                    execution_results.append(result)

                    # Set stop-loss after successful buy
                    if is_buy and signal.stop_loss_price and result.get("status") == "submitted":
                        stop_result = executor.set_stop_loss(signal.symbol, signal.stop_loss_price)
                        logger.info(
                            "Stop-loss for %s: %s",
                            signal.symbol, stop_result.get("status"),
                        )
                except Exception as e:
                    logger.error("Order execution failed for %s: %s", signal.symbol, e)
                    result = {"status": "error", "symbol": signal.symbol, "error": str(e)}
                    execution_results.append(result)

        # Log the trade
        trade_journal.log_trade(
            signal=signal,
            execution_result=result,
            portfolio_state=portfolio_state,
            risk_result={"adjusted_size_pct": risk_result.adjusted_size_pct} if risk_result.adjusted_size_pct else None,
        )

    # Step 7b: Execute stop-loss adjustments from Claude
    if analysis.stop_adjustments:
        for symbol, new_stop in analysis.stop_adjustments.items():
            if dry_run:
                logger.info("[DRY RUN] Would adjust stop for %s to $%.2f", symbol, new_stop)
            else:
                try:
                    stop_result = executor.update_stop_loss(symbol, new_stop)
                    logger.info(
                        "Stop adjusted: %s -> $%.2f (%s)",
                        symbol, new_stop, stop_result.get("status"),
                    )
                except Exception as e:
                    logger.error("Failed to adjust stop for %s: %s", symbol, e)

    # Step 8: Log the complete decision cycle
    decision_log.log_analysis(
        analysis=analysis,
        portfolio_state=portfolio_state,
        execution_results=execution_results,
    )

    # Step 9: Get benchmark data (SPY)
    benchmark = None
    spy_data = watchlist_data.get("SPY", {})
    spy_quote = spy_data.get("quote", {})
    spy_price = spy_quote.get("ask", 0) or spy_quote.get("bid", 0)
    if spy_price > 0:
        benchmark = get_benchmark_data(spy_price)

    # Step 10: Write human-readable daily summary
    write_daily_summary(
        analysis=analysis,
        portfolio_state=portfolio_state,
        execution_results=execution_results,
        rejected_signals=rejected_signals,
        benchmark=benchmark,
    )

    executed = sum(1 for r in execution_results if r.get("status") in ("submitted", "dry_run"))
    errored = sum(1 for r in execution_results if r.get("status") == "error")
    logger.info(
        "=== %sCycle complete: %d trades executed, %d errors, %d rejected ===",
        run_label,
        executed,
        errored,
        len(rejected_signals),
    )

    return True


def _was_bought_today(symbol: str, positions: list[dict]) -> bool:
    """
    Check if a position was opened today (same calendar day).
    If we sell it, it would count as a day trade.

    Heuristic: Alpaca doesn't directly expose the open date in positions,
    so we check our own trade journal for same-day buys.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    trade_log_dir = __import__("src.config", fromlist=["TRADE_LOGS_DIR"]).TRADE_LOGS_DIR

    if not trade_log_dir.exists():
        return False

    for filepath in trade_log_dir.glob(f"{today}_{symbol}_buy_*.json"):
        return True
    for filepath in trade_log_dir.glob(f"{today}_{symbol}_buy_call_*.json"):
        return True
    for filepath in trade_log_dir.glob(f"{today}_{symbol}_buy_put_*.json"):
        return True

    return False


def main():
    """Entry point for the trading agent."""
    load_dotenv()
    settings = load_settings()
    setup_logging(settings.log_level)

    console.print("[bold green]Claude Trading Agent[/bold green]")
    console.print(f"Mode: {'PAPER' if settings.is_paper else '[bold red]LIVE[/bold red]'}")
    console.print(f"Model: {settings.claude.claude_model}")

    if not settings.is_paper:
        console.print("[bold red]WARNING: LIVE TRADING MODE — Real money at risk![/bold red]")
        response = input("Type 'CONFIRM' to proceed: ")
        if response != "CONFIRM":
            console.print("Aborted.")
            sys.exit(0)

    # Check for --dry-run flag
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        console.print("[bold yellow]DRY RUN MODE — no orders will be submitted[/bold yellow]")

    # Validate connections before running
    if not validate_connections(settings):
        console.print("[bold red]Startup validation failed. Fix errors above and retry.[/bold red]")
        sys.exit(1)

    run_analysis_cycle(settings, dry_run=dry_run)


if __name__ == "__main__":
    main()
