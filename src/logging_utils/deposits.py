"""
Deposits log — tracks manual cash additions and withdrawals.

The bot's "capital base" for performance tracking is computed as:
  capital_base = initial_capital + sum(deposits) - sum(withdrawals)

This lets the user add money without corrupting their performance metrics.
Total return is computed against the capital_base, not the static STARTING_CAPITAL.

File: logs/{mode}/deposits.json
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import Settings, get_logs_dir

logger = logging.getLogger(__name__)


def _deposits_file(mode: str) -> Path:
    return get_logs_dir(mode) / "deposits.json"


def load_deposits(mode: str) -> list[dict]:
    """Load all recorded deposits for a mode, oldest first."""
    f = _deposits_file(mode)
    if not f.exists():
        return []
    try:
        with open(f) as fh:
            data = json.load(fh)
        return data.get("entries", [])
    except Exception as e:
        logger.warning("Failed to read deposits log: %s", e)
        return []


def record_deposit(mode: str, amount: float, note: str = "") -> dict:
    """
    Record a cash deposit (positive) or withdrawal (negative).

    Args:
        mode: "paper" or "live"
        amount: dollars added (positive) or removed (negative)
        note: optional free-text note

    Returns:
        The entry that was recorded.
    """
    f = _deposits_file(mode)
    f.parent.mkdir(parents=True, exist_ok=True)

    entries = load_deposits(mode)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "amount": round(amount, 2),
        "note": note,
    }
    entries.append(entry)

    with open(f, "w") as fh:
        json.dump({"entries": entries}, fh, indent=2)

    logger.info("Recorded %s: $%.2f — %s", "deposit" if amount >= 0 else "withdrawal", amount, note or "(no note)")
    return entry


def total_net_deposits(mode: str) -> float:
    """Sum of all deposits minus withdrawals."""
    return sum(e.get("amount", 0) for e in load_deposits(mode))


def get_capital_base(settings: Settings) -> float:
    """
    Compute the current capital base for performance tracking.

    capital_base = STARTING_CAPITAL + sum(deposits/withdrawals)

    This is what "total return" should be measured against — it represents
    the cumulative cash you've put into the strategy.
    """
    return settings.starting_capital + total_net_deposits(settings.trading_mode)
