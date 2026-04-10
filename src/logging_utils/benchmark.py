"""
Benchmark tracker — tracks SPY return alongside portfolio for comparison.
Stores the starting SPY price on first run, then calculates relative return.
Separate benchmark files for paper vs live trading.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import get_logs_dir

logger = logging.getLogger(__name__)

BENCHMARK_SYMBOL = "SPY"


def _benchmark_file(mode: str = "paper") -> Path:
    return get_logs_dir(mode) / "benchmark.json"


def get_benchmark_data(current_spy_price: float, trading_mode: str = "paper") -> dict:
    """
    Get benchmark comparison data.
    On first call, records the starting SPY price.
    On subsequent calls, calculates return from start.
    """
    bf = _benchmark_file(trading_mode)
    start_price = _load_start_price(bf)

    if start_price is None:
        start_price = current_spy_price
        _save_start_price(bf, start_price)
        logger.info("Benchmark start price recorded: SPY $%.2f", start_price)

    return_pct = (current_spy_price - start_price) / start_price if start_price > 0 else 0

    return {
        "symbol": BENCHMARK_SYMBOL,
        "price": current_spy_price,
        "start_price": start_price,
        "return_pct": return_pct,
    }


def _load_start_price(bf: Path) -> float | None:
    if not bf.exists():
        return None
    try:
        with open(bf) as f:
            data = json.load(f)
        return data.get("start_price")
    except Exception:
        return None


def _save_start_price(bf: Path, price: float):
    bf.parent.mkdir(parents=True, exist_ok=True)
    with open(bf, "w") as f:
        json.dump({
            "symbol": BENCHMARK_SYMBOL,
            "start_price": price,
            "recorded_at": datetime.now().isoformat(),
        }, f, indent=2)
