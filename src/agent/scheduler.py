"""
Scheduler — runs the agent on configurable intervals.

Schedule (all times ET):
- 9:45 AM  — MORNING: Full cycle, new entries allowed
- 12:30 PM — MIDDAY: Defensive check, selective entries
- 3:45 PM  — CLOSING: Analysis + exits only, NO new entries
"""

import logging
import time

import schedule
from rich.console import Console

from src.agent.orchestrator import CycleMode, run_analysis_cycle, setup_logging
from src.config import load_settings

logger = logging.getLogger(__name__)
console = Console()

# Schedule definition: (time, mode)
SCHEDULE = [
    ("09:45", CycleMode.MORNING),
    ("12:30", CycleMode.MIDDAY),
    ("15:45", CycleMode.CLOSING),
]

TRADING_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


def start_scheduler():
    """Start the trading agent on a schedule."""
    from dotenv import load_dotenv

    load_dotenv()
    settings = load_settings()
    setup_logging(settings.log_level)

    console.print("[bold green]Claude Trading Agent — Scheduler[/bold green]")
    console.print(f"Mode: {'PAPER' if settings.is_paper else '[bold red]LIVE[/bold red]'}")

    for day in TRADING_DAYS:
        for time_str, mode in SCHEDULE:
            getattr(schedule.every(), day).at(time_str).do(
                run_analysis_cycle, settings=settings, mode=mode,
            )

    console.print("Schedule (ET):")
    for time_str, mode in SCHEDULE:
        console.print(f"  {time_str} — {mode.upper()}")
    console.print("Days: Mon-Fri")
    console.print("Waiting for next scheduled run...")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    start_scheduler()
