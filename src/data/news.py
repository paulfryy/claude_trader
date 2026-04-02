"""
News and sentiment data pipeline.
Fetches news from Alpaca's news API for use in Claude's analysis.
"""

from datetime import datetime, timedelta

from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

from src.config import Settings


class NewsDataClient:
    """Fetches news articles from Alpaca for market sentiment analysis."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = NewsClient(
            api_key=settings.alpaca.api_key,
            secret_key=settings.alpaca.secret_key,
        )

    def get_news(
        self,
        symbols: list[str] | None = None,
        start: datetime | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """
        Fetch recent news articles, optionally filtered by symbols.
        Returns a list of dicts with headline, summary, source, and timestamp.
        """
        if start is None:
            start = datetime.now() - timedelta(days=3)

        request = NewsRequest(
            symbols=symbols,
            start=start,
            limit=limit,
            sort="desc",
        )
        news = self._client.get_news(request)

        return [
            {
                "headline": article.headline,
                "summary": article.summary,
                "source": article.source,
                "symbols": article.symbols,
                "created_at": article.created_at.isoformat(),
                "url": article.url,
            }
            for article in news.news
        ]

    def get_market_news(self, limit: int = 15) -> list[dict]:
        """Fetch general market news (not symbol-specific)."""
        return self.get_news(symbols=None, limit=limit)

    def get_symbol_news(self, symbol: str, limit: int = 10) -> list[dict]:
        """Fetch news for a specific symbol."""
        return self.get_news(symbols=[symbol], limit=limit)
