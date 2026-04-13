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
from src.config import load_settings
from src.data.indicators import add_all_indicators, summarize_indicators
from src.data.market_data import MarketDataClient
from src.data.news import NewsDataClient
from src.data.options_chain import OptionsChainClient
from src.data.screener import Screener
from src.execution.orders import OrderExecutor
from src.logging_utils.anomaly_log import log_anomaly
from src.logging_utils.benchmark import get_benchmark_data
from src.logging_utils.daily_summary import write_daily_summary
from src.logging_utils.decision_log import DecisionLog
from src.logging_utils.eod_report import generate_eod_report
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


_active_trading_mode = "paper"  # Set by run_analysis_cycle at start


def _log_error(error: Exception, context: str = ""):
    """Log an error to the errors directory with full traceback."""
    from src.config import get_error_logs_dir
    error_dir = get_error_logs_dir(_active_trading_mode)
    error_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filepath = error_dir / f"{timestamp}_error.log"

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

    # Set the active trading mode for error logging
    global _active_trading_mode
    _active_trading_mode = settings.trading_mode

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
        options_chain = OptionsChainClient(settings)
        screener = Screener(settings)
        trade_journal = TradeJournal(settings)
        decision_log = DecisionLog(settings)
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
            account_info=portfolio_state,
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
        log_anomaly(settings, "claude_parse_error", f"Failed to parse Claude response: {e}",
                    severity="error", cycle_mode=mode, context={"error": str(e)})
        return False
    except Exception as e:
        logger.error("Claude analysis failed: %s", e)
        _log_error(e, "Claude analysis")
        log_anomaly(settings, "cycle_error", f"Claude analysis failed: {e}",
                    severity="error", cycle_mode=mode, context={"error": str(e)})
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
    cycle_freed_exposure_pct = 0.0  # Track exposure freed by closes for subsequent buys
    cycle_freed_options_value = 0.0
    closed_this_cycle = set()  # Track symbols already closed to prevent duplicates

    # Build lookups for exposure tracking and realized P&L on close
    position_values = {p["symbol"]: abs(p["market_value"]) for p in positions}
    position_lookup = {p["symbol"]: p for p in positions}
    equity = portfolio_state.get("equity", 1.0) or 1.0

    for symbol in analysis.positions_to_close:
        # Skip if already closed this cycle
        if symbol in closed_this_cycle:
            logger.debug("Already closed %s this cycle, skipping duplicate", symbol)
            continue

        # PDT protection: don't sell anything we bought today
        bought_today = _was_bought_today(symbol, positions)
        if bought_today:
            logger.warning(
                "PDT PROTECTION: Skipping close of %s — position was opened today. "
                "Selling would count as a day trade.",
                symbol,
            )
            continue

        closed_value = position_values.get(symbol, 0)
        pos_snapshot = position_lookup.get(symbol, {})
        pre_close_pl = pos_snapshot.get("unrealized_pl", 0)
        pre_close_plpc = pos_snapshot.get("unrealized_plpc", 0)

        if dry_run:
            logger.info("[DRY RUN] Would close position: %s (frees ~$%.2f)", symbol, closed_value)
            execution_results.append({
                "status": "dry_run", "symbol": symbol, "action": "close",
                "realized_pl": pre_close_pl, "realized_plpc": pre_close_plpc,
            })
            cycle_freed_exposure_pct += closed_value / equity
        else:
            try:
                # Cancel any stop orders first — they hold shares and block the close
                executor._cancel_existing_stops(symbol)
                result = executor.close_position(symbol)
                # Capture realized P&L — what was unrealized just became realized
                result["realized_pl"] = pre_close_pl
                result["realized_plpc"] = pre_close_plpc
                execution_results.append(result)
                logger.info(
                    "Closing position: %s → %s (frees ~$%.2f)",
                    symbol, result["status"], closed_value,
                )
                if result.get("status") == "closed":
                    closed_this_cycle.add(symbol)
                    cycle_freed_exposure_pct += closed_value / equity
                    # Check if it was an options position (long symbol = OCC)
                    if len(symbol) > 10:
                        cycle_freed_options_value += closed_value
            except Exception as e:
                logger.error("Failed to close position %s: %s", symbol, e)
                execution_results.append({"status": "error", "symbol": symbol, "error": str(e)})

    # Step 7: Validate and execute new trade signals
    rejected_signals = []

    # Track exposure and options exposure added this cycle so subsequent
    # risk checks account for trades already executed within the same cycle
    cycle_added_exposure_pct = 0.0
    cycle_added_options_value = 0.0

    # Count new positions opened today (from trade journal + this cycle)
    # PDT constraint: each new buy needs a stop-loss, which counts as a day trade
    max_new_per_day = settings.risk.max_new_positions_per_day
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_buys = len(list(settings.trade_logs_dir.glob(f"{today_str}_*_buy_*.json")))
    today_buys += len(list(settings.trade_logs_dir.glob(f"{today_str}_*_buy_call_*.json")))
    today_buys += len(list(settings.trade_logs_dir.glob(f"{today_str}_*_buy_put_*.json")))
    new_buys_this_cycle = 0
    remaining_slots = max(0, max_new_per_day - today_buys)

    if remaining_slots < max_new_per_day:
        logger.info(
            "Daily position limit: %d/%d used today, %d slots remaining",
            today_buys, max_new_per_day, remaining_slots,
        )

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

        # Block non-catalyst entries in closing cycle
        # Catalyst trades (earnings plays, etc.) are allowed with tighter size limits
        if is_buy and not allow_new_entries:
            if signal.is_catalyst_trade and signal.catalyst:
                logger.info(
                    "CLOSING MODE: Allowing catalyst entry %s %s — %s",
                    signal.action.value, signal.symbol, signal.catalyst,
                )
                # Catalyst trade — proceed to risk checks (which enforce the 5% limit)
            else:
                reason = "Closing cycle — no new entries without a catalyst. Signal logged for morning review."
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
            log_anomaly(
                settings, "pdt_block", f"{signal.symbol}: PDT — position opened today, can't sell",
                severity="info", cycle_mode=mode, symbol=signal.symbol,
                context={"action": signal.action.value},
            )
            continue

        # Sell signals: close the position directly (don't go through sizing)
        if is_sell and signal.action == TradeAction.SELL:
            if signal.symbol in closed_this_cycle:
                logger.debug("Already closed %s this cycle, skipping duplicate sell signal", signal.symbol)
                continue
            closed_value = position_values.get(signal.symbol, 0)
            pos_snapshot = position_lookup.get(signal.symbol, {})
            pre_close_pl = pos_snapshot.get("unrealized_pl", 0)
            pre_close_plpc = pos_snapshot.get("unrealized_plpc", 0)

            if dry_run:
                logger.info("[DRY RUN] Would close position: %s (frees ~$%.2f)", signal.symbol, closed_value)
                result = {
                    "status": "dry_run", "symbol": signal.symbol, "action": "close",
                    "realized_pl": pre_close_pl, "realized_plpc": pre_close_plpc,
                }
            else:
                # Cancel any existing stop orders first
                executor._cancel_existing_stops(signal.symbol)
                result = executor.close_position(signal.symbol)
                result["realized_pl"] = pre_close_pl
                result["realized_plpc"] = pre_close_plpc
            execution_results.append(result)
            trade_journal.log_trade(
                signal=signal, execution_result=result,
                portfolio_state=portfolio_state,
            )
            # Track freed exposure so later buys in this cycle can use the freed room
            if result.get("status") in ("closed", "dry_run"):
                closed_this_cycle.add(signal.symbol)
                cycle_freed_exposure_pct += closed_value / equity
                if len(signal.symbol) > 10:
                    cycle_freed_options_value += closed_value
            logger.info("Sell signal: %s -> %s", signal.symbol, result.get("status"))
            continue

        # Daily position limit — hard enforcement
        if is_buy and (remaining_slots - new_buys_this_cycle) <= 0:
            reason = f"Daily position limit reached ({max_new_per_day}/{max_new_per_day}). Signal ranked below today's top picks."
            logger.info("LIMIT: Skipping %s %s — %s", signal.action.value, signal.symbol, reason)
            rejected_signals.append({"symbol": signal.symbol, "reason": reason})
            trade_journal.log_rejection(signal, reason, portfolio_state)
            log_anomaly(
                settings, "daily_limit_hit", f"{signal.symbol}: daily position limit reached",
                severity="info", cycle_mode=mode, symbol=signal.symbol,
                context={"action": signal.action.value, "limit": max_new_per_day},
            )
            continue

        # Risk check — use updated state reflecting:
        #   - closes already made this cycle (frees exposure)
        #   - trades already executed this cycle (adds exposure)
        net_exposure = (
            portfolio_state.get("exposure_pct", 0)
            - cycle_freed_exposure_pct
            + cycle_added_exposure_pct
        )
        net_options = (
            portfolio_state.get("options_exposure", 0)
            - cycle_freed_options_value
            + cycle_added_options_value
        )
        live_state = {
            **portfolio_state,
            "exposure_pct": max(0.0, net_exposure),
            "options_exposure": max(0.0, net_options),
        }
        risk_result = risk_manager.validate_signal(signal, live_state)

        if not risk_result.approved:
            trade_journal.log_rejection(signal, risk_result.reason, portfolio_state)
            rejected_signals.append({"symbol": signal.symbol, "reason": risk_result.reason})
            # Classify the rejection reason for better filtering
            reason_lower = risk_result.reason.lower()
            if "drawdown" in reason_lower or "circuit breaker" in reason_lower:
                atype = "circuit_breaker"
            elif "exposure" in reason_lower:
                atype = "over_exposure"
            elif "pdt" in reason_lower:
                atype = "pdt_block"
            else:
                atype = "signal_rejected"
            log_anomaly(
                settings, atype, f"{signal.symbol}: {risk_result.reason}",
                severity="warning", cycle_mode=mode, symbol=signal.symbol,
                context={
                    "action": signal.action.value,
                    "reason": risk_result.reason,
                    "position_size_pct": signal.position_size_pct,
                    "rationale": signal.rationale,
                },
            )
            continue

        # Determine position size (use adjusted size if risk clamped it)
        size_pct = risk_result.adjusted_size_pct or signal.position_size_pct

        # Get current price for sizing/logging
        quote = watchlist_data.get(signal.symbol, {}).get("quote", {})
        current_price = quote.get("ask", 0) or quote.get("bid", 0)

        if current_price <= 0:
            logger.warning("No price available for %s, skipping", signal.symbol)
            continue

        # Validate stop-loss is below current price for buys (not above — that would trigger instantly)
        if is_buy and signal.stop_loss_price and signal.stop_loss_price >= current_price:
            reason = (
                f"Stop-loss ${signal.stop_loss_price:.2f} is >= current price ${current_price:.2f}. "
                f"This would trigger immediately. Rejecting."
            )
            logger.warning("BAD STOP: %s %s — %s", signal.action.value, signal.symbol, reason)
            rejected_signals.append({"symbol": signal.symbol, "reason": reason})
            trade_journal.log_rejection(signal, reason, portfolio_state)
            log_anomaly(
                settings, "bad_stop_loss",
                f"{signal.symbol}: stop ${signal.stop_loss_price:.2f} >= current ${current_price:.2f}",
                severity="warning", cycle_mode=mode, symbol=signal.symbol,
                context={
                    "stop_loss_price": signal.stop_loss_price,
                    "current_price": current_price,
                    "action": signal.action.value,
                    "rationale": signal.rationale,
                },
            )
            continue

        # Determine if this is an options or equity trade
        is_options = signal.action in (
            TradeAction.BUY_CALL, TradeAction.BUY_PUT,
            TradeAction.SELL_CALL, TradeAction.SELL_PUT,
        )

        if is_options:
            # Options: two-step flow
            # 1. Fetch the real options chain
            # 2. Let Claude pick the best contract from what's available
            premium_budget = portfolio_state["equity"] * size_pct
            contract_type = "call" if "call" in signal.action.value else "put"

            # Fetch the options chain
            chain = options_chain.get_chain_for_analysis(
                symbol=signal.symbol,
                option_type=contract_type,
                current_price=current_price,
                budget=premium_budget,
            )

            if not chain:
                logger.warning("No options chain available for %s, skipping", signal.symbol)
                log_anomaly(
                    settings, "options_no_chain",
                    f"{signal.symbol}: options chain fetch returned empty",
                    severity="warning", cycle_mode=mode, symbol=signal.symbol,
                    context={"contract_type": contract_type},
                )
                continue

            affordable_count = sum(1 for c in chain if c["affordable"])
            if affordable_count == 0:
                reason = f"No affordable {contract_type} contracts for {signal.symbol} within ${premium_budget:.2f} budget"
                logger.warning(reason)
                rejected_signals.append({"symbol": signal.symbol, "reason": reason})
                trade_journal.log_rejection(signal, reason, portfolio_state)
                log_anomaly(
                    settings, "options_unaffordable",
                    f"{signal.symbol}: no affordable {contract_type} contracts (budget ${premium_budget:.2f})",
                    severity="warning", cycle_mode=mode, symbol=signal.symbol,
                    context={
                        "contract_type": contract_type,
                        "budget": premium_budget,
                        "chain_size": len(chain),
                        "cheapest_cost": min(c["cost_per_contract"] for c in chain) if chain else None,
                    },
                )
                continue

            # Let Claude pick the best contract
            selected = analyst.select_option_contract(
                symbol=signal.symbol,
                option_type=contract_type,
                chain=chain,
                original_rationale=signal.rationale,
                budget=premium_budget,
            )

            if not selected:
                reason = f"Claude declined — no suitable {contract_type} contract for thesis"
                logger.info(reason)
                rejected_signals.append({"symbol": signal.symbol, "reason": reason})
                continue

            occ_symbol = selected["occ_symbol"]
            cost_per_contract = selected["cost_per_contract"]
            contracts = int(premium_budget // cost_per_contract)
            if contracts <= 0:
                contracts = 1  # We already verified it's affordable
            total_cost = contracts * cost_per_contract

            logger.info(
                "Options: Claude selected %s (strike=$%.2f, exp=%s) — %d contracts @ $%.2f = $%.2f",
                occ_symbol, selected["strike"], selected["expiration"],
                contracts, cost_per_contract, total_cost,
            )

            if dry_run:
                logger.info(
                    "[DRY RUN] Would execute: %s %d contracts of %s @ $%.2f/contract = $%.2f total",
                    signal.action.value, contracts, occ_symbol, cost_per_contract, total_cost,
                )
                result = {
                    "status": "dry_run",
                    "symbol": signal.symbol,
                    "occ_symbol": occ_symbol,
                    "side": signal.action.value,
                    "contracts": contracts,
                    "cost_per_contract": cost_per_contract,
                    "total_cost": total_cost,
                    "strike": selected["strike"],
                    "expiration": selected["expiration"],
                    "selection_rationale": selected.get("selection_rationale", ""),
                }
                execution_results.append(result)
            else:
                try:
                    # Update signal with Claude's selected contract details
                    signal.strike_price = selected["strike"]
                    signal.expiration_date = selected["expiration"]
                    result = executor.execute_options_signal(signal, contracts)
                    execution_results.append(result)
                except Exception as e:
                    logger.error("Options execution failed for %s: %s", signal.symbol, e)
                    result = {"status": "error", "symbol": signal.symbol, "error": str(e)}
                    execution_results.append(result)
                    log_anomaly(
                        settings, "order_error",
                        f"Options order failed for {signal.symbol}: {e}",
                        severity="error", cycle_mode=mode, symbol=signal.symbol,
                        context={"action": signal.action.value, "error": str(e)},
                    )
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
                    # Cancel existing stops before buying — Alpaca rejects buys
                    # with "wash trade" if a sell stop exists on the same symbol
                    if is_buy:
                        executor._cancel_existing_stops(signal.symbol)

                    result = executor.execute_equity_signal(signal, notional)
                    execution_results.append(result)

                    # Set stop-loss after successful buy
                    # Retry with increasing delay — order needs to fully fill first
                    if is_buy and signal.stop_loss_price and result.get("status") == "submitted":
                        import time
                        stop_result = None
                        for attempt in range(4):
                            time.sleep(2)  # 2s between attempts (total up to 8s)
                            stop_result = executor.set_stop_loss(signal.symbol, signal.stop_loss_price)
                            status = stop_result.get("status", "")
                            if status == "submitted":
                                break  # Success
                            if status == "skipped" and "fractional" in stop_result.get("reason", ""):
                                break  # Fractional position — can't set stop, that's OK
                            logger.debug("Stop-loss attempt %d for %s — waiting for fill...", attempt + 1, signal.symbol)

                        # Check final result — alert on failure
                        final_status = stop_result.get("status", "unknown") if stop_result else "unknown"
                        if final_status == "submitted":
                            logger.info("Stop-loss for %s: set @ $%.2f", signal.symbol, signal.stop_loss_price)
                        elif final_status == "skipped" and "fractional" in stop_result.get("reason", ""):
                            pass  # Expected for fractional positions
                        else:
                            err_msg = stop_result.get("error", stop_result.get("reason", "unknown"))
                            logger.error(
                                "UNPROTECTED POSITION: Failed to set stop-loss for %s after 4 attempts. "
                                "Position is LIVE with NO stop protection. Last error: %s",
                                signal.symbol, err_msg,
                            )
                            log_anomaly(
                                settings, "stop_loss_failed",
                                f"{signal.symbol}: stop-loss failed after 4 attempts — position unprotected",
                                severity="error", cycle_mode=mode, symbol=signal.symbol,
                                context={
                                    "stop_price": signal.stop_loss_price,
                                    "last_error": err_msg,
                                    "notional": notional,
                                },
                            )
                except Exception as e:
                    logger.error("Order execution failed for %s: %s", signal.symbol, e)
                    result = {"status": "error", "symbol": signal.symbol, "error": str(e)}
                    execution_results.append(result)
                    err_str = str(e).lower()
                    atype = "wash_trade_error" if "wash trade" in err_str else "order_error"
                    log_anomaly(
                        settings, atype,
                        f"Equity order failed for {signal.symbol}: {e}",
                        severity="error", cycle_mode=mode, symbol=signal.symbol,
                        context={
                            "action": signal.action.value,
                            "notional": notional,
                            "error": str(e),
                        },
                    )

        # Track exposure added this cycle for subsequent risk checks
        # (applies to both equity and options buys)
        if is_buy and result.get("status") in ("submitted", "dry_run"):
            if is_options:
                # Use the REAL total cost of the options trade
                actual_cost = result.get("total_cost", 0)
                if not actual_cost and result.get("contracts") and result.get("premium"):
                    actual_cost = result["contracts"] * result["premium"] * 100
                cycle_added_exposure_pct += actual_cost / portfolio_state["equity"] if portfolio_state["equity"] > 0 else 0
                cycle_added_options_value += actual_cost
                new_buys_this_cycle += 1
            else:
                cycle_added_exposure_pct += size_pct
                new_buys_this_cycle += 1

        # Log the trade
        trade_journal.log_trade(
            signal=signal,
            execution_result=result,
            portfolio_state=portfolio_state,
            risk_result={"adjusted_size_pct": risk_result.adjusted_size_pct} if risk_result.adjusted_size_pct else None,
        )

    # Step 7b: Execute stop-loss adjustments from Claude
    #          (skip fractional-only positions silently — Claude is told about them)
    if analysis.stop_adjustments:
        for symbol, new_stop in analysis.stop_adjustments.items():
            if dry_run:
                logger.info("[DRY RUN] Would adjust stop for %s to $%.2f", symbol, new_stop)
            else:
                try:
                    stop_result = executor.update_stop_loss(symbol, new_stop)
                    if stop_result.get("status") == "skipped":
                        continue  # Fractional position — handled by cycle review, don't log
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

    # Step 9: Re-fetch portfolio state after trades for accurate summary
    try:
        post_account = market_data.get_account()
        post_positions = market_data.get_positions()
        post_state = portfolio_tracker.build_state(post_account, post_positions)
    except Exception:
        post_state = portfolio_state  # Fall back to pre-trade state

    # Step 10: Get benchmark data (SPY)
    benchmark = None
    spy_data = watchlist_data.get("SPY", {})
    spy_quote = spy_data.get("quote", {})
    spy_price = spy_quote.get("ask", 0) or spy_quote.get("bid", 0)
    if spy_price > 0:
        benchmark = get_benchmark_data(spy_price, trading_mode=settings.trading_mode)

    # Step 11: Write human-readable daily summary (uses post-trade state)
    write_daily_summary(
        analysis=analysis,
        portfolio_state=post_state,
        execution_results=execution_results,
        rejected_signals=rejected_signals,
        benchmark=benchmark,
        trading_mode=settings.trading_mode,
    )

    # Step 12: Generate end-of-day report (closing cycle only)
    if mode == CycleMode.CLOSING:
        try:
            generate_eod_report(
                settings=settings,
                portfolio_state=post_state,
                benchmark=benchmark,
            )
        except Exception as e:
            logger.error("Failed to generate EOD report: %s", e)

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
    from src.config import get_trade_logs_dir
    trade_log_dir = get_trade_logs_dir(_active_trading_mode)

    if not trade_log_dir.exists():
        return False

    for filepath in trade_log_dir.glob(f"{today}_{symbol}_buy_*.json"):
        return True
    for filepath in trade_log_dir.glob(f"{today}_{symbol}_buy_call_*.json"):
        return True
    for filepath in trade_log_dir.glob(f"{today}_{symbol}_buy_put_*.json"):
        return True

    return False


def _get_env_file() -> str | None:
    """Parse --env flag from sys.argv."""
    for i, arg in enumerate(sys.argv):
        if arg == "--env" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith("--env="):
            return arg.split("=", 1)[1]
    return None


def main():
    """Entry point for the trading agent."""
    env_file = _get_env_file()
    if env_file:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv()
    settings = load_settings(env_file=env_file)
    setup_logging(settings.log_level)

    console.print("[bold green]Claude Trading Agent[/bold green]")
    console.print(f"Mode: {'PAPER' if settings.is_paper else '[bold red]LIVE[/bold red]'}")
    console.print(f"Model: {settings.claude.claude_model}")

    if not settings.is_paper:
        console.print("[bold red]WARNING: LIVE TRADING MODE — Real money at risk![/bold red]")
        import os
        if os.environ.get("SKIP_LIVE_CONFIRM") == "true":
            console.print("[yellow]SKIP_LIVE_CONFIRM=true — bypassing confirmation[/yellow]")
        else:
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
