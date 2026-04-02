"""
Scheduler — runs the agent on configurable intervals.
"""

import logging
import time

import schedule
from rich.console import Console

from src.agent.orchestrator import run_analysis_cycle, setup_logging
from src.config import load_settings

logger = logging.getLogger(__name__)
console = Console()


def start_scheduler():
    """
    Start the trading agent on a schedule.

    Default schedule:
    - 9:45 AM ET — Morning analysis (15 min after market open, let things settle)
    - 12:30 PM ET — Midday check
    - 3:30 PM ET — Afternoon review (30 min before close)
    """
    from dotenv import load_dotenv

    load_dotenv()
    settings = load_settings()
    setup_logging(settings.log_level)

    console.print("[bold green]Claude Trading Agent — Scheduler[/bold green]")
    console.print(f"Mode: {'PAPER' if settings.is_paper else '[bold red]LIVE[/bold red]'}")

    # Schedule analysis cycles (times in ET)
    schedule.every().monday.at("09:45").do(run_analysis_cycle, settings=settings)
    schedule.every().monday.at("12:30").do(run_analysis_cycle, settings=settings)
    schedule.every().monday.at("15:30").do(run_analysis_cycle, settings=settings)

    schedule.every().tuesday.at("09:45").do(run_analysis_cycle, settings=settings)
    schedule.every().tuesday.at("12:30").do(run_analysis_cycle, settings=settings)
    schedule.every().tuesday.at("15:30").do(run_analysis_cycle, settings=settings)

    schedule.every().wednesday.at("09:45").do(run_analysis_cycle, settings=settings)
    schedule.every().wednesday.at("12:30").do(run_analysis_cycle, settings=settings)
    schedule.every().wednesday.at("15:30").do(run_analysis_cycle, settings=settings)

    schedule.every().thursday.at("09:45").do(run_analysis_cycle, settings=settings)
    schedule.every().thursday.at("12:30").do(run_analysis_cycle, settings=settings)
    schedule.every().thursday.at("15:30").do(run_analysis_cycle, settings=settings)

    schedule.every().friday.at("09:45").do(run_analysis_cycle, settings=settings)
    schedule.every().friday.at("12:30").do(run_analysis_cycle, settings=settings)
    schedule.every().friday.at("15:30").do(run_analysis_cycle, settings=settings)

    console.print("Scheduled: 9:45 AM, 12:30 PM, 3:30 PM ET (Mon-Fri)")
    console.print("Waiting for next scheduled run...")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    start_scheduler()
