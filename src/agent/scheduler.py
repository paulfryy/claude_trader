"""
Scheduler — runs the agent on configurable intervals.

Schedule (all times ET):
- 9:45 AM  — MORNING: Full cycle, new entries allowed
- 12:30 PM — MIDDAY: Defensive check, selective entries
- 3:45 PM  — CLOSING: Analysis + exits only, NO new entries

Error handling:
- If a cycle fails, the error is logged and the scheduler continues.
- The scheduler never crashes from a single cycle failure.
- Startup validates all API connections before scheduling.
"""

import logging
import signal as signal_mod
import sys
import time

import schedule
from rich.console import Console

from src.agent.orchestrator import (
    CycleMode,
    _log_error,
    run_analysis_cycle,
    setup_logging,
    validate_connections,
)
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


def _safe_run_cycle(settings, mode: str):
    """
    Wrapper that catches all exceptions so the scheduler never dies.
    Logs errors and continues to the next scheduled cycle.
    """
    try:
        logger.info("--- Scheduled %s cycle triggered ---", mode.upper())
        success = run_analysis_cycle(settings=settings, mode=mode)
        if not success:
            logger.warning("Cycle completed with errors (see logs/errors/)")
    except Exception as e:
        logger.error("CYCLE CRASHED: %s — %s", type(e).__name__, e)
        _log_error(e, f"Scheduled {mode} cycle")
        logger.info("Scheduler will continue to next cycle.")


def start_scheduler():
    """Start the trading agent on a schedule."""
    from dotenv import load_dotenv

    load_dotenv()
    settings = load_settings()
    setup_logging(settings.log_level)

    console.print("[bold green]Claude Trading Agent — Scheduler[/bold green]")
    console.print(f"Mode: {'PAPER' if settings.is_paper else '[bold red]LIVE[/bold red]'}")
    console.print(f"Model: {settings.claude.claude_model}")

    # Validate connections at startup
    console.print("\nValidating API connections...")
    if not validate_connections(settings):
        console.print("[bold red]Startup validation failed. Fix errors above and retry.[/bold red]")
        sys.exit(1)

    console.print()

    # Register schedule
    for day in TRADING_DAYS:
        for time_str, mode in SCHEDULE:
            getattr(schedule.every(), day).at(time_str).do(
                _safe_run_cycle, settings=settings, mode=mode,
            )

    console.print("Schedule (ET):")
    for time_str, mode in SCHEDULE:
        console.print(f"  {time_str} — {mode.upper()}")
    console.print("Days: Mon-Fri")
    console.print()

    # Graceful shutdown handler
    def shutdown_handler(signum, frame):
        console.print("\n[bold yellow]Shutting down scheduler...[/bold yellow]")
        logger.info("Scheduler stopped by user (signal %d)", signum)
        sys.exit(0)

    signal_mod.signal(signal_mod.SIGINT, shutdown_handler)
    signal_mod.signal(signal_mod.SIGTERM, shutdown_handler)

    # Show next scheduled run
    next_run = schedule.next_run()
    if next_run:
        console.print(f"Next run: {next_run.strftime('%A %H:%M')}")
    console.print("Waiting for scheduled runs... (Ctrl+C to stop)")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    start_scheduler()
