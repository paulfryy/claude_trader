"""
Market data client — fetches price data, options chains, and account info from Alpaca.
"""

from datetime import datetime

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient

from src.config import Settings


class MarketDataClient:
    """Fetches market data from Alpaca APIs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._data_client = StockHistoricalDataClient(
            api_key=settings.alpaca.api_key,
            secret_key=settings.alpaca.secret_key,
        )
        self._trading_client = TradingClient(
            api_key=settings.alpaca.api_key,
            secret_key=settings.alpaca.secret_key,
            paper=settings.is_paper,
        )

    def get_bars(
        self,
        symbol: str,
        timeframe: TimeFrame = TimeFrame.Day,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars for a symbol."""
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=limit,
        )
        bars = self._data_client.get_stock_bars(request)
        return bars.df

    def get_latest_quote(self, symbol: str) -> dict:
        """Get the latest quote (bid/ask) for a symbol."""
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quote = self._data_client.get_stock_latest_quote(request)
        q = quote[symbol]
        return {
            "symbol": symbol,
            "bid": q.bid_price,
            "ask": q.ask_price,
            "bid_size": q.bid_size,
            "ask_size": q.ask_size,
            "timestamp": q.timestamp,
        }

    def get_account(self) -> dict:
        """Get current account info (buying power, equity, etc.)."""
        account = self._trading_client.get_account()
        return {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "day_trade_count": account.daytrade_count,
        }

    def get_positions(self) -> list[dict]:
        """Get all current positions."""
        positions = self._trading_client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": p.side,
                "market_value": float(p.market_value),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in positions
        ]

    def is_market_open(self) -> bool:
        """Check if the market is currently open."""
        clock = self._trading_client.get_clock()
        return clock.is_open
