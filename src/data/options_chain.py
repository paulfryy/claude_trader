"""
Options chain data fetcher — gets available contracts and live quotes
for Claude to make informed strike selection decisions.
"""

import logging
from datetime import datetime, timedelta

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest

from src.config import Settings

logger = logging.getLogger(__name__)


class OptionsChainClient:
    """Fetches options chain data for intelligent strike selection."""

    def __init__(self, settings: Settings):
        self._trading_client = TradingClient(
            api_key=settings.alpaca.api_key,
            secret_key=settings.alpaca.secret_key,
            paper=settings.is_paper,
        )
        self._data_client = OptionHistoricalDataClient(
            api_key=settings.alpaca.api_key,
            secret_key=settings.alpaca.secret_key,
        )

    def get_chain_for_analysis(
        self,
        symbol: str,
        option_type: str,
        current_price: float,
        budget: float,
        min_expiry_days: int = 14,
        max_expiry_days: int = 45,
        strike_range_pct: float = 0.10,
    ) -> list[dict]:
        """
        Fetch an options chain suitable for Claude to analyze and pick from.

        Args:
            symbol: Underlying stock symbol
            option_type: "call" or "put"
            current_price: Current stock price
            budget: Dollar budget for this trade
            min_expiry_days: Minimum days to expiration
            max_expiry_days: Maximum days to expiration
            strike_range_pct: How far from current price to search (0.10 = +/-10%)

        Returns:
            List of dicts with contract details + live quotes, sorted by strike.
            Each dict has: symbol, strike, expiry, bid, ask, mid_price,
            cost_per_contract, affordable, intrinsic_value, time_value
        """
        now = datetime.now()
        exp_start = (now + timedelta(days=min_expiry_days)).strftime("%Y-%m-%d")
        exp_end = (now + timedelta(days=max_expiry_days)).strftime("%Y-%m-%d")

        strike_low = current_price * (1 - strike_range_pct)
        strike_high = current_price * (1 + strike_range_pct)

        # Fetch contracts
        try:
            req = GetOptionContractsRequest(
                underlying_symbols=[symbol],
                expiration_date_gte=exp_start,
                expiration_date_lte=exp_end,
                type=option_type,
                strike_price_gte=str(int(strike_low)),
                strike_price_lte=str(int(strike_high) + 1),
            )
            result = self._trading_client.get_option_contracts(req)
            contracts = result.option_contracts
        except Exception as e:
            logger.warning("Failed to fetch options chain for %s: %s", symbol, e)
            return []

        if not contracts:
            logger.info("No options contracts found for %s %s", symbol, option_type)
            return []

        # Get live quotes for all contracts
        occ_symbols = [c.symbol for c in contracts]

        # Batch in groups of 100 (API limit)
        quotes = {}
        for i in range(0, len(occ_symbols), 100):
            chunk = occ_symbols[i:i + 100]
            try:
                quote_req = OptionLatestQuoteRequest(symbol_or_symbols=chunk)
                batch_quotes = self._data_client.get_option_latest_quote(quote_req)
                quotes.update(batch_quotes)
            except Exception as e:
                logger.warning("Failed to fetch option quotes batch %d: %s", i, e)

        # Build the chain data for Claude
        chain = []
        for c in contracts:
            q = quotes.get(c.symbol)
            if not q or (q.bid_price == 0 and q.ask_price == 0):
                continue  # Skip contracts with no market

            bid = q.bid_price
            ask = q.ask_price
            mid = (bid + ask) / 2 if bid and ask else ask or bid
            cost = ask * 100  # Cost per contract at the ask

            strike = float(c.strike_price)

            # Calculate intrinsic and time value
            if option_type == "call":
                intrinsic = max(0, current_price - strike)
            else:
                intrinsic = max(0, strike - current_price)
            time_value = mid - intrinsic

            chain.append({
                "occ_symbol": c.symbol,
                "strike": strike,
                "expiration": str(c.expiration_date),
                "bid": bid,
                "ask": ask,
                "mid_price": round(mid, 2),
                "cost_per_contract": round(cost, 2),
                "affordable": cost <= budget,
                "intrinsic_value": round(intrinsic, 2),
                "time_value": round(max(0, time_value), 2),
                "days_to_expiry": (c.expiration_date - now.date()).days,
            })

        # Sort by expiry then strike
        chain.sort(key=lambda x: (x["expiration"], x["strike"]))

        logger.info(
            "Options chain for %s %s: %d contracts (%d affordable within $%.2f budget)",
            symbol, option_type, len(chain),
            sum(1 for c in chain if c["affordable"]),
            budget,
        )

        return chain
