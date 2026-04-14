"""
Anomaly logger — captures every unusual event in a single JSONL file per mode.

This is the primary feedback loop for iterating on the agent. When something
goes wrong — a rejected signal, a failed stop-loss, a parse error, a wash
trade — it gets logged here with enough context to debug without cross-
referencing multiple files.

File: logs/{mode}/anomalies.jsonl (one JSON object per line)

Each entry has:
  timestamp  — ISO timestamp
  type       — one of ANOMALY_TYPES below
  severity   — info, warning, error
  cycle_mode — morning, midday, closing, manual
  symbol     — affected symbol (if any)
  message    — human-readable one-line summary
  context    — structured dict with relevant details
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import Settings, get_logs_dir

logger = logging.getLogger(__name__)


# Known anomaly types — used for filtering in the dashboard
ANOMALY_TYPES = {
    # Risk / execution
    "signal_rejected": "Risk engine rejected a signal",
    "bad_stop_loss": "Stop-loss above entry price",
    "stop_loss_failed": "Failed to set stop-loss after retries",
    "stop_loss_skipped": "Stop-loss skipped (fractional position)",
    "order_error": "Order submission failed",
    "wash_trade_error": "Wash trade protection blocked order",
    "close_failed": "Position close failed (Alpaca rejected)",

    # Claude
    "claude_parse_error": "Failed to parse Claude's JSON response",
    "claude_bad_signal": "Claude produced an invalid signal",

    # Options
    "options_unaffordable": "No affordable options contracts for budget",
    "options_no_chain": "Options chain fetch returned empty",
    "options_contract_not_found": "Option contract lookup failed",

    # Circuit breakers and limits
    "circuit_breaker": "Drawdown circuit breaker triggered",
    "over_exposure": "Exposure cap breached",
    "pdt_block": "PDT protection blocked a trade",
    "daily_limit_hit": "Daily new position limit reached",

    # Data
    "data_fetch_error": "Market data fetch failed",
    "no_price": "No live price available for symbol",

    # Cycle
    "cycle_error": "Unhandled error during cycle",
    "duplicate_close": "Attempted to close same symbol twice",
}


SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


def log_anomaly(
    settings: Settings,
    anomaly_type: str,
    message: str,
    severity: str = "warning",
    cycle_mode: str = "unknown",
    symbol: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """
    Append an anomaly entry to the current mode's log.
    Fails silently — we never want logging to break the trading cycle.
    """
    try:
        if anomaly_type not in ANOMALY_TYPES:
            logger.debug("Unknown anomaly type: %s", anomaly_type)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": anomaly_type,
            "severity": severity,
            "cycle_mode": cycle_mode,
            "symbol": symbol,
            "message": message,
            "context": context or {},
        }

        log_file = _anomaly_file(settings.trading_mode)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        # Never let logging kill the cycle
        logger.error("Failed to write anomaly log: %s", e)


def _anomaly_file(mode: str) -> Path:
    return get_logs_dir(mode) / "anomalies.jsonl"


def read_anomalies(
    mode: str,
    limit: int | None = 200,
    since_days: int | None = None,
    filter_type: str | None = None,
    min_severity: str = "info",
) -> list[dict]:
    """
    Read recent anomalies, newest first. Returns a list of dicts.

    Args:
        mode: Trading mode (paper/live)
        limit: Max entries to return (None for all)
        since_days: Only include entries from the last N days
        filter_type: If set, only return anomalies of this type
        min_severity: Minimum severity to include
    """
    log_file = _anomaly_file(mode)
    if not log_file.exists():
        return []

    min_sev_val = SEVERITY_ORDER.get(min_severity, 0)
    cutoff = None
    if since_days is not None:
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=since_days)

    entries: list[dict] = []
    try:
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue

                # Filter by type
                if filter_type and entry.get("type") != filter_type:
                    continue

                # Filter by severity
                if SEVERITY_ORDER.get(entry.get("severity", "info"), 0) < min_sev_val:
                    continue

                # Filter by age
                if cutoff:
                    try:
                        ts = datetime.fromisoformat(entry.get("timestamp", ""))
                        if ts < cutoff:
                            continue
                    except Exception:
                        pass

                entries.append(entry)
    except Exception as e:
        logger.error("Failed to read anomaly log: %s", e)
        return []

    # Reverse so newest is first
    entries.reverse()

    if limit is not None:
        entries = entries[:limit]

    return entries


def count_by_type(mode: str, since_days: int = 7) -> dict[str, int]:
    """Count anomalies grouped by type over the last N days."""
    entries = read_anomalies(mode, limit=None, since_days=since_days)
    counts: dict[str, int] = {}
    for e in entries:
        t = e.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts
