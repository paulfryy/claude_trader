"""
Earnings calendar client — fetches upcoming earnings reports from Finnhub.

Free tier: 60 requests/minute, no credit card required.
Sign up: https://finnhub.io/dashboard

Used by the analyst to warn Claude about positions with upcoming earnings
so it can decide to exit before the report or explicitly hold through it
as a catalyst play.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests

from src.config import LOGS_BASE

logger = logging.getLogger(__name__)

FINNHUB_API_BASE = "https://finnhub.io/api/v1"
CACHE_DIR = LOGS_BASE / "cache"
CACHE_TTL_HOURS = 4  # Earnings schedules don't change often


class EarningsCalendarClient:
    """Fetches upcoming earnings reports from Finnhub."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("FINNHUB_API_KEY", "")
        if not self._api_key:
            logger.warning("FINNHUB_API_KEY not set — earnings calendar disabled")

    def get_upcoming_earnings(
        self,
        symbols: list[str] | None = None,
        days_ahead: int = 14,
    ) -> dict[str, dict]:
        """
        Get upcoming earnings for the next N days, optionally filtered by symbols.

        Returns:
            Dict of symbol -> {date, hour, eps_estimate, revenue_estimate}
            Only symbols with scheduled earnings in the window are returned.
        """
        if not self._api_key:
            return {}

        today = datetime.now().date()
        end = today + timedelta(days=days_ahead)

        # Check cache first
        cache_file = self._cache_file(today, end)
        cached = self._load_cache(cache_file)
        if cached is not None:
            data = cached
        else:
            data = self._fetch_from_api(today, end)
            if data is not None:
                self._save_cache(cache_file, data)

        if not data:
            return {}

        # Build symbol -> details map
        result = {}
        for item in data.get("earningsCalendar", []):
            sym = item.get("symbol", "").upper()
            if symbols and sym not in symbols:
                continue
            result[sym] = {
                "date": item.get("date"),
                "hour": item.get("hour"),  # "bmo" (before market open), "amc" (after market close), ""
                "eps_estimate": item.get("epsEstimate"),
                "revenue_estimate": item.get("revenueEstimate"),
                "days_away": self._days_between(today, item.get("date")),
            }
        return result

    def _fetch_from_api(self, from_date, to_date) -> dict | None:
        """Call the Finnhub earnings calendar API."""
        try:
            url = f"{FINNHUB_API_BASE}/calendar/earnings"
            params = {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "token": self._api_key,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("Earnings calendar fetch failed: %s", e)
            return None

    def _cache_file(self, start, end) -> Path:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / f"earnings_{start}_{end}.json"

    def _load_cache(self, cache_file: Path) -> dict | None:
        if not cache_file.exists():
            return None
        try:
            age = datetime.now().timestamp() - cache_file.stat().st_mtime
            if age > CACHE_TTL_HOURS * 3600:
                return None
            with open(cache_file) as f:
                return json.load(f)
        except Exception:
            return None

    def _save_cache(self, cache_file: Path, data: dict):
        try:
            with open(cache_file, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.debug("Failed to cache earnings: %s", e)

    @staticmethod
    def _days_between(today, date_str: str | None) -> int:
        if not date_str:
            return 0
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d").date()
            return (target - today).days
        except Exception:
            return 0
