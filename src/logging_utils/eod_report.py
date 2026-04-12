"""
End-of-day report generator.

Produces a human-readable markdown report consolidating the entire trading day:
- Day at a glance (P&L, alpha, key numbers)
- Position table with thesis, age, vs target/stop
- Today's activity (opens, closes with realized P&L, rejected signals)
- Claude's narrative across the day's 3 cycles (condensed)
- Tomorrow's plan extracted from closing cycle

Reports are written to logs/{mode}/reports/{YYYY-MM-DD}.md
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import Settings, get_decision_logs_dir, get_logs_dir, get_trade_logs_dir

logger = logging.getLogger(__name__)


def generate_eod_report(
    settings: Settings,
    portfolio_state: dict,
    benchmark: dict | None,
) -> Path | None:
    """
    Generate an end-of-day report for today.

    Args:
        settings: Application settings
        portfolio_state: Current portfolio state (from PortfolioTracker.build_state)
        benchmark: Benchmark data with return_pct

    Returns:
        Path to the generated report, or None on error
    """
    try:
        mode = settings.trading_mode
        reports_dir = get_logs_dir(mode) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        filepath = reports_dir / f"{today}.md"

        # Gather all the data
        decisions = _load_today_decisions(mode, today)
        trades = _load_today_trades(mode, today)
        entry_dates = _build_entry_date_map(mode, today)
        theses = _build_thesis_map(mode)

        # Build the report
        content = _render_report(
            settings=settings,
            today=today,
            portfolio_state=portfolio_state,
            benchmark=benchmark,
            decisions=decisions,
            trades=trades,
            entry_dates=entry_dates,
            theses=theses,
        )

        filepath.write_text(content, encoding="utf-8")
        logger.info("EOD report written: %s", filepath)
        return filepath

    except Exception as e:
        logger.error("Failed to generate EOD report: %s", e)
        return None


def _load_today_decisions(mode: str, today: str) -> list[dict]:
    """Load all decision logs from today, sorted by timestamp."""
    decision_dir = get_decision_logs_dir(mode)
    if not decision_dir.exists():
        return []
    files = sorted(decision_dir.glob(f"{today}_*_analysis.json"))
    results = []
    for f in files:
        try:
            with open(f) as fh:
                results.append(json.load(fh))
        except Exception:
            continue
    return results


def _load_today_trades(mode: str, today: str) -> dict[str, list[dict]]:
    """
    Load all trade journal entries from today, grouped by status.

    Returns dict with keys: opened, closed, rejected
    """
    trade_dir = get_trade_logs_dir(mode)
    if not trade_dir.exists():
        return {"opened": [], "closed": [], "rejected": []}

    opened = []
    closed = []
    rejected = []

    for f in sorted(trade_dir.glob(f"{today}_*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
        except Exception:
            continue

        status = data.get("status", "")
        signal = data.get("signal", {})
        action = signal.get("action", "")

        if status == "rejected":
            rejected.append(data)
        elif action in ("buy", "buy_call", "buy_put"):
            opened.append(data)
        elif action in ("sell", "sell_call", "sell_put"):
            closed.append(data)

    return {"opened": opened, "closed": closed, "rejected": rejected}


def _build_entry_date_map(mode: str, today: str) -> dict[str, str]:
    """
    Scan all trade logs to find the earliest buy date for each symbol.
    Reads the JSON to get the real symbol (not the filename, which doesn't
    work for OCC option symbols that contain date/strike data).
    """
    trade_dir = get_trade_logs_dir(mode)
    if not trade_dir.exists():
        return {}

    entry_dates: dict[str, str] = {}
    for f in sorted(trade_dir.glob("*_buy*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
        except Exception:
            continue

        signal = data.get("signal", {})
        action = signal.get("action", "")
        if "buy" not in action:
            continue

        # Use OCC symbol for options, regular symbol for equities
        exe = data.get("execution", {})
        symbol = exe.get("occ_symbol") or signal.get("symbol", "")
        if not symbol:
            continue

        date_str = data.get("timestamp", "")[:10]
        if not date_str:
            continue

        if symbol not in entry_dates or date_str < entry_dates[symbol]:
            entry_dates[symbol] = date_str
    return entry_dates


def _build_thesis_map(mode: str) -> dict[str, str]:
    """
    Build a map of symbol -> most recent buy rationale.
    Indexed by both OCC symbol (for options) and underlying symbol (for equities).
    """
    trade_dir = get_trade_logs_dir(mode)
    if not trade_dir.exists():
        return {}

    theses: dict[str, tuple[str, str]] = {}  # symbol -> (date, rationale)
    for f in sorted(trade_dir.glob("*_buy*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
        except Exception:
            continue
        signal = data.get("signal", {})
        rationale = signal.get("rationale", "")
        date_str = data.get("timestamp", "")[:10]

        # Use OCC symbol for options, regular symbol for equities
        exe = data.get("execution", {})
        symbol = exe.get("occ_symbol") or signal.get("symbol", "")

        if not symbol or not rationale:
            continue

        existing = theses.get(symbol)
        if existing is None or date_str > existing[0]:
            theses[symbol] = (date_str, rationale)

    return {sym: rationale for sym, (_, rationale) in theses.items()}


def _days_between(start_str: str, end_str: str) -> int:
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d").date()
        end = datetime.strptime(end_str, "%Y-%m-%d").date()
        return (end - start).days
    except Exception:
        return 0


def _render_report(
    settings: Settings,
    today: str,
    portfolio_state: dict,
    benchmark: dict | None,
    decisions: list[dict],
    trades: dict,
    entry_dates: dict[str, str],
    theses: dict[str, str],
) -> str:
    """Render the markdown report."""
    lines: list[str] = []

    equity = portfolio_state.get("equity", 0)
    cash = portfolio_state.get("cash", 0)
    exposure = portfolio_state.get("exposure_pct", 0)
    positions = portfolio_state.get("positions", [])
    total_pl = portfolio_state.get("unrealized_pl", 0)
    starting_capital = settings.starting_capital
    total_return = (equity - starting_capital) / starting_capital if starting_capital > 0 else 0

    # Today's realized P&L from closed positions
    realized_pl_today = sum(
        t.get("execution", {}).get("realized_pl", 0)
        for t in trades.get("closed", [])
    )

    # ============ HEADER ============
    mode_label = "LIVE" if not settings.is_paper else "PAPER"
    lines.append(f"# Daily Report — {today} [{mode_label}]")
    lines.append("")

    # ============ DAY AT A GLANCE ============
    lines.append("## Day at a Glance")
    lines.append("")
    lines.append(f"- **Ending Equity:** ${equity:,.2f}")
    lines.append(f"- **Cash:** ${cash:,.2f}")
    lines.append(f"- **Exposure:** {exposure:.1%}")
    lines.append(f"- **Positions:** {len(positions)}")
    lines.append(f"- **Unrealized P&L:** ${total_pl:+,.2f}")
    lines.append(f"- **Realized P&L Today:** ${realized_pl_today:+,.2f}")
    lines.append(f"- **Total Return (since start):** {total_return:+.2%}")

    if benchmark:
        spy_return = benchmark.get("return_pct", 0)
        alpha = total_return - spy_return
        lines.append(f"- **SPY Return (since start):** {spy_return:+.2%}")
        lines.append(f"- **Alpha:** {alpha:+.2%}")

    opens = len(trades.get("opened", []))
    closes = len(trades.get("closed", []))
    rejects = len(trades.get("rejected", []))
    lines.append(
        f"- **Activity:** {opens} opened · {closes} closed · {rejects} rejected"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ============ POSITION TABLE ============
    lines.append("## Positions")
    lines.append("")
    if not positions:
        lines.append("_No open positions._")
    else:
        lines.append(
            "| Symbol | Qty | Entry | Current | P&L | P&L % | Days | Thesis |"
        )
        lines.append(
            "|--------|-----|-------|---------|-----|-------|------|--------|"
        )
        # Sort by P&L% descending so winners are at the top
        sorted_positions = sorted(
            positions,
            key=lambda p: p.get("unrealized_plpc", 0),
            reverse=True,
        )
        for p in sorted_positions:
            symbol = p.get("symbol", "")
            qty = p.get("qty", 0)
            avg_entry = p.get("avg_entry_price", 0)
            current = p.get("current_price", 0)
            pl = p.get("unrealized_pl", 0)
            pl_pct = p.get("unrealized_plpc", 0)
            entry_date = entry_dates.get(symbol, "?")
            days_held = _days_between(entry_date, today) if entry_date != "?" else "?"
            thesis = theses.get(symbol, "—")
            # Trim thesis for table readability
            if len(thesis) > 100:
                thesis = thesis[:97] + "..."
            lines.append(
                f"| {symbol} | {qty:.3f} | ${avg_entry:.2f} | ${current:.2f} | "
                f"${pl:+.2f} | {pl_pct:+.2%} | {days_held} | {thesis} |"
            )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ============ TODAY'S ACTIVITY ============
    lines.append("## Today's Activity")
    lines.append("")

    if trades["opened"]:
        lines.append("### Opened")
        lines.append("")
        for t in trades["opened"]:
            sig = t.get("signal", {})
            exe = t.get("execution", {})
            symbol = sig.get("symbol", "")
            action = sig.get("action", "buy")
            size_pct = (sig.get("position_size_pct") or 0) * 100
            target = sig.get("target_price")
            stop = sig.get("stop_loss_price")
            rationale = sig.get("rationale", "")
            notional = exe.get("notional")

            header = f"**{action.upper()} {symbol}**"
            if notional:
                header += f" — ${notional:.2f}"
            elif exe.get("contracts"):
                header += f" — {exe['contracts']} contract(s) @ ${exe.get('cost_per_contract', 0):.2f}"

            lines.append(f"- {header} ({size_pct:.0f}% of portfolio)")
            if target:
                lines.append(f"  - Target: ${target}, Stop: ${stop or 'N/A'}")
            lines.append(f"  - {rationale}")
        lines.append("")

    if trades["closed"]:
        lines.append("### Closed")
        lines.append("")
        for t in trades["closed"]:
            sig = t.get("signal", {})
            exe = t.get("execution", {})
            symbol = sig.get("symbol", "")
            realized = exe.get("realized_pl")
            realized_pct = exe.get("realized_plpc")
            rationale = sig.get("rationale", "") or "Position closed"

            line = f"- **{symbol}**"
            if realized is not None:
                pl_str = f"${realized:+.2f}"
                if realized_pct is not None:
                    pl_str += f" ({realized_pct:+.2%})"
                line += f" — realized {pl_str}"
            lines.append(line)
            if rationale:
                lines.append(f"  - {rationale}")
        lines.append("")

    if trades["rejected"]:
        lines.append("### Rejected Signals")
        lines.append("")
        for t in trades["rejected"]:
            sig = t.get("signal", {})
            reason = t.get("rejection_reason", "")
            symbol = sig.get("symbol", "")
            action = sig.get("action", "")
            lines.append(f"- **{action.upper()} {symbol}** — {reason}")
        lines.append("")

    if not any([trades["opened"], trades["closed"], trades["rejected"]]):
        lines.append("_No trades today._")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ============ CLAUDE'S NARRATIVE ============
    lines.append("## Claude's Thinking Through the Day")
    lines.append("")

    cycle_labels = {"morning": "Morning (9:45)", "midday": "Midday (12:30)", "closing": "Closing (3:45)"}
    # Match decisions to cycle mode by timestamp hour
    for d in decisions:
        ts = d.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            hour = dt.hour
        except Exception:
            hour = 0

        if hour < 12:
            label = cycle_labels["morning"]
        elif hour < 15:
            label = cycle_labels["midday"]
        else:
            label = cycle_labels["closing"]

        summary = d.get("market_summary", "")
        regime = d.get("market_regime", "")
        confidence = d.get("regime_confidence", "")
        time_str = ts[11:16] if len(ts) > 16 else ""

        lines.append(f"### {label} — {regime} ({confidence})")
        lines.append("")
        if summary:
            lines.append(f"> {summary}")
            lines.append("")

    lines.append("---")
    lines.append("")

    # ============ TOMORROW'S PLAN ============
    lines.append("## Tomorrow's Plan")
    lines.append("")

    # Extract tomorrow plan from the closing cycle (last decision of the day)
    tomorrow_notes = []
    if decisions:
        closing = decisions[-1]
        for obs in closing.get("key_observations", []):
            if "tomorrow" in obs.lower() or "watch" in obs.lower():
                tomorrow_notes.append(obs)

    if tomorrow_notes:
        for note in tomorrow_notes:
            lines.append(f"- {note}")
    else:
        lines.append("_No specific notes for tomorrow._")
    lines.append("")

    # ============ SECTOR OUTLOOK (from closing cycle) ============
    if decisions:
        closing = decisions[-1]
        sectors = closing.get("sector_outlook", {})
        if sectors:
            lines.append("## End-of-Day Sector Outlook")
            lines.append("")
            for sector, outlook in sectors.items():
                lines.append(f"- **{sector}:** {outlook}")
            lines.append("")

    return "\n".join(lines)
