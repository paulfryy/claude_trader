"""
Benchmark tracker — tracks SPY return alongside portfolio for comparison.
Stores the starting SPY price on first run, then calculates relative return.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import LOGS_DIR

logger = logging.getLogger(__name__)

BENCHMARK_FILE = LOGS_DIR / "benchmark.json"
BENCHMARK_SYMBOL = "SPY"


def get_benchmark_data(current_spy_price: float) -> dict:
    """
    Get benchmark comparison data.
    On first call, records the starting SPY price.
    On subsequent calls, calculates return from start.

    Args:
        current_spy_price: Current SPY price

    Returns:
        Dict with price, start_price, return_pct
    """
    start_price = _load_start_price()

    if start_price is None:
        # First run — record starting price
        start_price = current_spy_price
        _save_start_price(start_price)
        logger.info("Benchmark start price recorded: SPY $%.2f", start_price)

    return_pct = (current_spy_price - start_price) / start_price if start_price > 0 else 0

    return {
        "symbol": BENCHMARK_SYMBOL,
        "price": current_spy_price,
        "start_price": start_price,
        "return_pct": return_pct,
    }


def _load_start_price() -> float | None:
    """Load the benchmark starting price from disk."""
    if not BENCHMARK_FILE.exists():
        return None
    try:
        with open(BENCHMARK_FILE) as f:
            data = json.load(f)
        return data.get("start_price")
    except Exception:
        return None


def _save_start_price(price: float):
    """Save the benchmark starting price."""
    BENCHMARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BENCHMARK_FILE, "w") as f:
        json.dump({
            "symbol": BENCHMARK_SYMBOL,
            "start_price": price,
            "recorded_at": datetime.now().isoformat(),
        }, f, indent=2)
