"""
Read-only Flask dashboard for the trading agent.

Serves:
  /              — Overview: portfolio, latest cycle narrative, trades
  /positions     — Live positions table with P&L
  /history       — List of daily summaries
  /history/<date>— Rendered markdown summary for a specific day
  /cycles        — Recent analysis cycles with full Claude rationale

Mode switching: ?mode=live or ?mode=paper (default: live)
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import markdown
from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, url_for

from src.config import get_decision_logs_dir, get_logs_dir, get_summary_dir, load_settings
from src.dashboard import controls
from src.data.market_data import MarketDataClient
from src.logging_utils.anomaly_log import ANOMALY_TYPES, count_by_type, read_anomalies
from src.logging_utils.deposits import get_capital_base
from src.logging_utils.performance import PerformanceAnalyzer

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
# Simple secret for flash messages — dashboard is IP-restricted so this is fine
app.secret_key = "claude-trading-agent-dashboard"


def get_mode() -> str:
    """Get trading mode from query string, default to live."""
    mode = request.args.get("mode", "live")
    return "paper" if mode == "paper" else "live"


def load_env_for_mode(mode: str):
    """Load the appropriate .env file for the given mode."""
    env_file = f".env.{mode}"
    load_dotenv(env_file, override=True)
    return load_settings(env_file=env_file)


def load_latest_portfolio(mode: str) -> dict | None:
    """Load the most recent portfolio snapshot for the given mode."""
    portfolio_dir = get_logs_dir(mode) / "portfolio"
    if not portfolio_dir.exists():
        return None
    snapshots = sorted(portfolio_dir.glob("*.json"))
    if not snapshots:
        return None
    try:
        with open(snapshots[-1]) as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load portfolio snapshot: %s", e)
        return None


def load_latest_decision(mode: str) -> dict | None:
    """Load the most recent analysis cycle for the given mode."""
    decision_dir = get_decision_logs_dir(mode)
    if not decision_dir.exists():
        return None
    decisions = sorted(decision_dir.glob("*.json"))
    if not decisions:
        return None
    try:
        with open(decisions[-1]) as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load decision log: %s", e)
        return None


def load_benchmark(mode: str) -> dict | None:
    """
    Load the benchmark tracking file and compute live return vs start price.
    Returns a dict with start_price, current_price, and return_pct.
    """
    bf = get_logs_dir(mode) / "benchmark.json"
    if not bf.exists():
        return None
    try:
        with open(bf) as f:
            data = json.load(f)
        start_price = data.get("start_price")
        if not start_price:
            return None

        # Fetch live SPY price
        try:
            settings = load_env_for_mode(mode)
            market = MarketDataClient(settings)
            quote = market.get_latest_quote("SPY")
            current_price = quote.get("ask") or quote.get("bid") or 0
            if current_price > 0:
                return_pct = (current_price - start_price) / start_price
                return {
                    "symbol": "SPY",
                    "start_price": start_price,
                    "current_price": current_price,
                    "return_pct": return_pct,
                }
        except Exception as e:
            logger.warning("Failed to fetch SPY quote: %s", e)

        # Fallback: return what we have without live data
        return {
            "symbol": "SPY",
            "start_price": start_price,
            "current_price": start_price,
            "return_pct": 0,
        }
    except Exception:
        return None


def list_summaries(mode: str) -> list[dict]:
    """List all daily summary markdown files, newest first."""
    summary_dir = get_summary_dir(mode)
    if not summary_dir.exists():
        return []
    files = sorted(summary_dir.glob("*.md"), reverse=True)
    return [
        {
            "date": f.stem,
            "size_kb": round(f.stat().st_size / 1024, 1),
        }
        for f in files
    ]


def list_reports(mode: str) -> list[dict]:
    """List all end-of-day report markdown files, newest first."""
    reports_dir = get_logs_dir(mode) / "reports"
    if not reports_dir.exists():
        return []
    files = sorted(reports_dir.glob("*.md"), reverse=True)
    return [
        {
            "date": f.stem,
            "size_kb": round(f.stat().st_size / 1024, 1),
        }
        for f in files
    ]


def list_recent_decisions(mode: str, limit: int = 20) -> list[dict]:
    """List recent decision logs, newest first."""
    decision_dir = get_decision_logs_dir(mode)
    if not decision_dir.exists():
        return []
    files = sorted(decision_dir.glob("*.json"), reverse=True)[:limit]
    results = []
    for f in files:
        try:
            with open(f) as fh:
                data = json.load(fh)
            results.append({
                "filename": f.stem,
                "timestamp": data.get("timestamp", ""),
                "market_regime": data.get("market_regime", ""),
                "regime_confidence": data.get("regime_confidence", ""),
                "num_signals": data.get("num_signals", 0),
                "num_closes": len(data.get("positions_to_close", [])),
                "market_summary": data.get("market_summary", ""),
                "key_observations": data.get("key_observations", []),
            })
        except Exception:
            continue
    return results


def get_live_portfolio(mode: str) -> tuple[dict | None, list[dict] | None]:
    """Fetch live portfolio state from Alpaca."""
    try:
        settings = load_env_for_mode(mode)
        market = MarketDataClient(settings)
        account = market.get_account()
        positions = market.get_positions()
        return account, positions
    except Exception as e:
        logger.warning("Failed to fetch live portfolio (%s): %s", mode, e)
        return None, None


@app.template_filter("fmt_money")
def fmt_money(value):
    """Format a number as dollars."""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


@app.template_filter("fmt_pct")
def fmt_pct(value, decimals=2):
    """Format a fraction as a percentage."""
    try:
        return f"{float(value) * 100:+.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


@app.template_filter("fmt_time")
def fmt_time(iso_str):
    """Format ISO timestamp as HH:MM:SS."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S ET")
    except Exception:
        return iso_str[:19]


@app.template_filter("fmt_date")
def fmt_date(iso_str):
    if not iso_str:
        return "—"
    try:
        return iso_str[:10]
    except Exception:
        return iso_str


@app.context_processor
def inject_mode():
    return {"current_mode": get_mode()}


@app.route("/")
def overview():
    mode = get_mode()

    # Latest snapshot from disk (always works, fast)
    snapshot = load_latest_portfolio(mode)
    latest_decision = load_latest_decision(mode)
    benchmark = load_benchmark(mode)

    # Live fetch from Alpaca (fresher but slower)
    live_account, live_positions = get_live_portfolio(mode)

    # Build overview metrics — prefer live data, fall back to snapshot
    if live_account and live_positions is not None:
        total_pl = sum(p["unrealized_pl"] for p in live_positions)
        total_value = sum(abs(p["market_value"]) for p in live_positions)
        if mode == "paper":
            settings = load_env_for_mode("paper")
            equity = get_capital_base(settings) + total_pl
            cash = equity - total_value
        else:
            equity = live_account["equity"]
            cash = live_account["cash"]
        exposure = total_value / equity if equity > 0 else 0
        num_positions = len(live_positions)
        data_source = "live (Alpaca)"
    elif snapshot:
        equity = snapshot.get("equity", 0)
        cash = snapshot.get("cash", 0)
        exposure = snapshot.get("exposure_pct", 0)
        total_pl = snapshot.get("unrealized_pl", 0)
        num_positions = snapshot.get("num_positions", 0)
        data_source = "snapshot (last cycle)"
    else:
        equity = cash = exposure = total_pl = num_positions = 0
        data_source = "no data"

    # Capital base (starting capital + net deposits) for return calculation
    try:
        settings = load_env_for_mode(mode)
        capital_base = get_capital_base(settings)
        starting_capital = settings.starting_capital
    except Exception:
        capital_base = equity
        starting_capital = equity

    total_return_pct = (equity - capital_base) / capital_base if capital_base > 0 else 0

    # Alpha vs SPY
    alpha = None
    if benchmark:
        alpha = total_return_pct - benchmark.get("return_pct", 0)

    return render_template(
        "overview.html",
        mode=mode,
        equity=equity,
        cash=cash,
        exposure=exposure,
        total_pl=total_pl,
        total_return_pct=total_return_pct,
        num_positions=num_positions,
        starting_capital=starting_capital,
        capital_base=capital_base,
        benchmark=benchmark,
        alpha=alpha,
        latest_decision=latest_decision,
        data_source=data_source,
    )


@app.route("/positions")
def positions():
    mode = get_mode()
    live_account, live_positions = get_live_portfolio(mode)

    if live_positions is None:
        return render_template("positions.html", mode=mode, positions=[], error="Could not fetch positions from Alpaca")

    # Sort by market value descending
    live_positions.sort(key=lambda p: abs(p.get("market_value", 0)), reverse=True)

    return render_template(
        "positions.html",
        mode=mode,
        positions=live_positions,
        total_value=sum(abs(p["market_value"]) for p in live_positions),
        total_pl=sum(p["unrealized_pl"] for p in live_positions),
    )


@app.route("/history")
def history():
    mode = get_mode()
    summaries = list_summaries(mode)
    return render_template("history.html", mode=mode, summaries=summaries)


@app.route("/history/<date>")
def history_day(date: str):
    mode = get_mode()
    summary_file = get_summary_dir(mode) / f"{date}.md"
    if not summary_file.exists():
        abort(404)

    try:
        content = summary_file.read_text(encoding="utf-8")
        html = markdown.markdown(content, extensions=["tables", "fenced_code"])
    except Exception as e:
        html = f"<p>Error reading summary: {e}</p>"

    return render_template("summary.html", mode=mode, date=date, html=html)


@app.route("/reports")
def reports():
    mode = get_mode()
    reports_list = list_reports(mode)
    return render_template("reports.html", mode=mode, reports=reports_list)


@app.route("/reports/<date>")
def report_day(date: str):
    mode = get_mode()
    report_file = get_logs_dir(mode) / "reports" / f"{date}.md"
    if not report_file.exists():
        abort(404)

    try:
        content = report_file.read_text(encoding="utf-8")
        html = markdown.markdown(content, extensions=["tables", "fenced_code"])
    except Exception as e:
        html = f"<p>Error reading report: {e}</p>"

    return render_template("report.html", mode=mode, date=date, html=html)


@app.route("/cycles")
def cycles():
    mode = get_mode()
    decisions = list_recent_decisions(mode)
    return render_template("cycles.html", mode=mode, decisions=decisions)


@app.route("/cycles/<filename>")
def cycle_detail(filename: str):
    mode = get_mode()
    file = get_decision_logs_dir(mode) / f"{filename}.json"
    if not file.exists():
        abort(404)
    try:
        with open(file) as f:
            data = json.load(f)
    except Exception as e:
        abort(500)

    return render_template("cycle_detail.html", mode=mode, data=data, filename=filename)


@app.route("/performance")
def performance():
    mode = get_mode()
    settings = load_env_for_mode(mode)
    analyzer = PerformanceAnalyzer(settings)

    stats = analyzer.get_combined_stats()
    curve = analyzer.get_equity_curve()

    # Pre-compute chart data in a format easy for Chart.js
    chart_data = {
        "labels": [p["date"] for p in curve],
        "equity": [round(p["equity"], 2) for p in curve],
        "drawdown": [round(p["drawdown_pct"] * 100, 2) for p in curve],
    }

    return render_template(
        "performance.html",
        mode=mode,
        stats=stats,
        curve=curve,
        chart_data=chart_data,
    )


@app.route("/diagnostics")
def diagnostics():
    mode = get_mode()
    filter_type = request.args.get("type", "") or None
    since_days = int(request.args.get("days", "7"))
    min_severity = request.args.get("severity", "info")

    anomalies = read_anomalies(
        mode,
        limit=200,
        since_days=since_days,
        filter_type=filter_type,
        min_severity=min_severity,
    )
    counts = count_by_type(mode, since_days=since_days)

    return render_template(
        "diagnostics.html",
        mode=mode,
        anomalies=anomalies,
        counts=counts,
        anomaly_types=ANOMALY_TYPES,
        selected_type=filter_type or "",
        selected_days=since_days,
        selected_severity=min_severity,
    )


@app.route("/diagnostics/export")
def diagnostics_export():
    """Export recent anomalies as markdown for pasting into a chat."""
    mode = get_mode()
    since_days = int(request.args.get("days", "7"))

    anomalies = read_anomalies(mode, limit=500, since_days=since_days)
    counts = count_by_type(mode, since_days=since_days)

    # Build markdown ready to paste
    from datetime import datetime as _dt
    lines = []
    lines.append(f"# Anomaly Report — {mode.upper()} — last {since_days} days")
    lines.append(f"Generated: {_dt.now().isoformat()}")
    lines.append("")

    if not anomalies:
        lines.append("_No anomalies recorded._")
    else:
        lines.append(f"## Summary ({len(anomalies)} entries)")
        lines.append("")
        for atype, count in sorted(counts.items(), key=lambda x: -x[1]):
            desc = ANOMALY_TYPES.get(atype, atype)
            lines.append(f"- **{atype}** ({count}): {desc}")
        lines.append("")
        lines.append("## Entries (newest first)")
        lines.append("")
        for a in anomalies:
            ts = a.get("timestamp", "")[:19]
            sev = a.get("severity", "info").upper()
            atype = a.get("type", "")
            sym = a.get("symbol") or ""
            msg = a.get("message", "")
            ctx = a.get("context", {})

            header = f"### {ts} · {sev} · {atype}"
            if sym:
                header += f" · {sym}"
            lines.append(header)
            lines.append("")
            lines.append(msg)
            if ctx:
                lines.append("```json")
                lines.append(json.dumps(ctx, indent=2, default=str))
                lines.append("```")
            lines.append("")

    from flask import Response
    return Response(
        "\n".join(lines),
        mimetype="text/markdown",
        headers={"Content-Disposition": f"inline; filename=anomalies-{mode}-{since_days}d.md"},
    )


@app.route("/controls")
def controls_page():
    mode = get_mode()

    # Get status of all services
    services = [
        controls.get_service_status("trading-agent-live"),
        controls.get_service_status("trading-agent-paper"),
        controls.get_service_status("trading-dashboard"),
    ]

    health = controls.get_server_health()
    audit = controls.read_recent_audit(lines=15)

    # Optional: view logs for a specific service
    log_service = request.args.get("logs", "")
    log_output = None
    if log_service in ("trading-agent-live", "trading-agent-paper", "trading-dashboard"):
        log_output = {
            "service": log_service,
            "content": controls.get_logs(log_service, lines=50),
        }

    return render_template(
        "controls.html",
        mode=mode,
        services=services,
        health=health,
        audit=audit,
        log_output=log_output,
    )


@app.route("/controls/restart/<service>", methods=["POST"])
def controls_restart(service: str):
    result = controls.restart_service(service)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("controls_page", mode=get_mode()))


@app.route("/controls/start/<service>", methods=["POST"])
def controls_start(service: str):
    result = controls.start_service(service)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("controls_page", mode=get_mode()))


@app.route("/controls/stop/<service>", methods=["POST"])
def controls_stop(service: str):
    result = controls.stop_service(service)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("controls_page", mode=get_mode()))


@app.route("/controls/pull", methods=["POST"])
def controls_pull():
    result = controls.git_pull()
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("controls_page", mode=get_mode()))


@app.route("/controls/deps", methods=["POST"])
def controls_deps():
    result = controls.refresh_dependencies()
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("controls_page", mode=get_mode()))


@app.route("/controls/cycle/<mode_param>", methods=["POST"])
def controls_cycle(mode_param: str):
    # Only dry-run cycles from the dashboard — real cycles happen on schedule
    result = controls.trigger_manual_cycle(mode_param, dry_run=True)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("controls_page", mode=get_mode()))


def main():
    import os
    port = int(os.environ.get("DASHBOARD_PORT", "8080"))
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    logging.basicConfig(level=logging.INFO)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
