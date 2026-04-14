"""
Stock screener — filters the full universe down to actionable candidates for Claude.

Two-tier approach:
  Tier 1 (fast): Batch snapshots for all ~520 symbols. Filter on price + volume.
  Tier 2 (selective): Fetch full bars + indicators for ~70-80 that pass Tier 1.
         Apply signal filters (RSI, SMA cross, volume spike, MACD, BB breakout).
         Send top ~20-30 candidates to Claude for analysis.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame

from src.config import Settings
from src.data.indicators import add_all_indicators
from src.data.universe import get_anchor_symbols, get_universe

logger = logging.getLogger(__name__)

# Screening criteria
MIN_PRICE = 5.0
MAX_PRICE = 500.0
MIN_AVG_VOLUME = 500_000
VOLUME_SPIKE_MULTIPLIER = 2.0
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MAX_CANDIDATES = 30  # Max symbols to send to Claude (excluding anchors)
MIN_CANDIDATES = 10  # Minimum — backfill with top liquid symbols if screener finds fewer


class Screener:
    """Screens the full universe down to actionable candidates."""

    def __init__(self, settings: Settings):
        self._client = StockHistoricalDataClient(
            api_key=settings.alpaca.api_key,
            secret_key=settings.alpaca.secret_key,
        )

    def screen(self) -> list[str]:
        """
        Run the full screening pipeline.
        Returns a list of symbols for Claude to analyze (anchors + screened candidates).
        """
        universe = get_universe()
        anchors = get_anchor_symbols()

        # Compute SPY's 10-day return for relative strength filtering
        spy_return_10d = self._get_spy_10d_return()
        if spy_return_10d is not None:
            logger.info("SPY 10-day return: %.2f%% (used for relative strength filter)", spy_return_10d * 100)

        # Tier 1: Quick filter on price and volume
        logger.info("Tier 1: Scanning %d symbols (snapshots)...", len(universe))
        tier1_passed, tier1_by_volume = self._tier1_filter(universe)
        logger.info("Tier 1: %d symbols passed price/volume filters", len(tier1_passed))

        # Tier 2: Fetch bars + indicators, apply signal filters + relative strength
        logger.info("Tier 2: Analyzing %d symbols (bars + indicators)...", len(tier1_passed))
        scored = self._tier2_filter(tier1_passed, spy_return_10d=spy_return_10d)
        logger.info("Tier 2: %d symbols have actionable signals", len(scored))

        # Sort by score descending, take top N
        scored.sort(key=lambda x: x[1], reverse=True)
        candidates = [sym for sym, score in scored[:MAX_CANDIDATES]]

        # Backfill: if too few candidates, add the most liquid Tier 1 symbols
        if len(candidates) < MIN_CANDIDATES:
            existing = set(candidates) | set(anchors)
            backfill = [sym for sym, vol in tier1_by_volume if sym not in existing]
            need = MIN_CANDIDATES - len(candidates)
            candidates.extend(backfill[:need])
            logger.info(
                "Backfilled %d symbols from Tier 1 (by volume) to meet minimum of %d",
                min(need, len(backfill)), MIN_CANDIDATES,
            )

        # Always include anchors
        final = list(dict.fromkeys(anchors + candidates))

        logger.info(
            "Screening complete: %d symbols selected (%d anchors + %d candidates)",
            len(final), len(anchors), len(candidates),
        )
        return final

    def _tier1_filter(self, symbols: list[str]) -> tuple[list[str], list[tuple[str, float]]]:
        """
        Tier 1: Fetch snapshots in batches and filter on price + volume.
        Fast — takes ~1 second for the full universe.

        Returns:
            (passed_symbols, by_volume) where by_volume is sorted descending
            for backfilling if Tier 2 gives too few results.
        """
        passed = []
        by_volume = []
        chunk_size = 100

        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i + chunk_size]
            try:
                request = StockSnapshotRequest(symbol_or_symbols=chunk)
                snapshots = self._client.get_stock_snapshot(request)
            except Exception as e:
                logger.warning("Snapshot fetch failed for chunk %d-%d: %s", i, i + len(chunk), e)
                continue

            for sym, snap in snapshots.items():
                if not snap.daily_bar:
                    continue

                price = snap.daily_bar.close

                # Use previous day's volume for liquidity filter — today's
                # daily_bar volume is too low early in the session (at 9:45 AM
                # it may be <20k even for SPY). Previous day is the real proxy
                # for "is this stock liquid enough."
                if snap.previous_daily_bar:
                    volume = snap.previous_daily_bar.volume
                else:
                    volume = snap.daily_bar.volume

                if price < MIN_PRICE or price > MAX_PRICE:
                    continue
                if volume < MIN_AVG_VOLUME:
                    continue

                passed.append(sym)
                by_volume.append((sym, volume))

        # Sort by volume descending for backfill priority
        by_volume.sort(key=lambda x: x[1], reverse=True)
        return passed, by_volume

    def _tier2_filter(
        self, symbols: list[str], spy_return_10d: float | None = None,
    ) -> list[tuple[str, float]]:
        """
        Tier 2: Fetch bars, compute indicators, score signals, and filter by
        relative strength (only stocks outperforming SPY get through).
        """
        scored = []
        chunk_size = 50
        start_date = datetime.now() - timedelta(days=90)

        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i + chunk_size]
            try:
                request = StockBarsRequest(
                    symbol_or_symbols=chunk,
                    timeframe=TimeFrame.Day,
                    start=start_date,
                )
                bars = self._client.get_stock_bars(request)
                df = bars.df
            except Exception as e:
                logger.warning("Bar fetch failed for chunk %d-%d: %s", i, i + len(chunk), e)
                continue

            if df.empty:
                continue

            for sym in chunk:
                try:
                    if isinstance(df.index, pd.MultiIndex) and sym in df.index.get_level_values("symbol"):
                        sym_df = df.loc[sym].copy()
                    else:
                        continue

                    if len(sym_df) < 20:
                        continue

                    # Relative strength: 10-day return of this symbol vs SPY
                    # Only boost/filter when we have SPY data to compare against
                    rs_boost = 0.0
                    if spy_return_10d is not None and len(sym_df) >= 11:
                        sym_return_10d = (sym_df["close"].iloc[-1] - sym_df["close"].iloc[-11]) / sym_df["close"].iloc[-11]
                        rel_strength = sym_return_10d - spy_return_10d
                        # Skip stocks lagging SPY by more than 1% — market beta, not alpha
                        if rel_strength < -0.01:
                            continue
                        # Boost score proportionally to outperformance
                        # +2% outperformance = +2 points, +5% = +5 points
                        rs_boost = rel_strength * 100

                    sym_df = add_all_indicators(sym_df)
                    score = self._score_signals(sym_df) + rs_boost

                    if score > 0:
                        scored.append((sym, score))
                except Exception as e:
                    logger.debug("Scoring failed for %s: %s", sym, e)

        return scored

    def _get_spy_10d_return(self) -> float | None:
        """Fetch SPY's 10-day return for relative strength comparison."""
        try:
            start = datetime.now() - timedelta(days=30)
            request = StockBarsRequest(
                symbol_or_symbols="SPY",
                timeframe=TimeFrame.Day,
                start=start,
            )
            bars = self._client.get_stock_bars(request)
            df = bars.df
            if df.empty or len(df) < 11:
                return None
            if isinstance(df.index, pd.MultiIndex):
                df = df.reset_index(level="symbol", drop=True)
            return (df["close"].iloc[-1] - df["close"].iloc[-11]) / df["close"].iloc[-11]
        except Exception as e:
            logger.debug("SPY 10d return fetch failed: %s", e)
            return None

    def _score_signals(self, df: pd.DataFrame) -> float:
        """
        Score a symbol based on technical signals.
        Higher score = more interesting for trading.
        Returns 0 if no actionable signals.
        """
        if df.empty or len(df) < 2:
            return 0.0

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        score = 0.0

        # RSI extremes (oversold or overbought)
        rsi = latest.get("rsi_14")
        if rsi is not None and not pd.isna(rsi):
            if rsi < RSI_OVERSOLD:
                score += 3.0  # Oversold — potential bounce
            elif rsi > RSI_OVERBOUGHT:
                score += 2.0  # Overbought — potential reversal or momentum

        # SMA crossover (price crosses 20-day SMA)
        sma20 = latest.get("sma_20")
        prev_sma20 = prev.get("sma_20")
        if sma20 is not None and prev_sma20 is not None:
            if not pd.isna(sma20) and not pd.isna(prev_sma20):
                # Bullish cross: price was below, now above
                if prev["close"] < prev_sma20 and latest["close"] > sma20:
                    score += 2.5
                # Bearish cross: price was above, now below
                elif prev["close"] > prev_sma20 and latest["close"] < sma20:
                    score += 2.0

        # MACD crossover
        macd = latest.get("macd")
        macd_signal = latest.get("macd_signal")
        prev_macd = prev.get("macd")
        prev_macd_signal = prev.get("macd_signal")
        if all(v is not None and not pd.isna(v) for v in [macd, macd_signal, prev_macd, prev_macd_signal]):
            # Bullish MACD cross
            if prev_macd <= prev_macd_signal and macd > macd_signal:
                score += 2.5
            # Bearish MACD cross
            elif prev_macd >= prev_macd_signal and macd < macd_signal:
                score += 2.0

        # Volume spike (today's volume > 2x average)
        volume = latest.get("volume", 0)
        avg_volume = df["volume"].rolling(20).mean().iloc[-1] if len(df) >= 20 else df["volume"].mean()
        if not pd.isna(avg_volume) and avg_volume > 0:
            if volume > avg_volume * VOLUME_SPIKE_MULTIPLIER:
                score += 2.0

        # Bollinger Band breakout
        bb_upper = latest.get("bb_upper")
        bb_lower = latest.get("bb_lower")
        if bb_upper is not None and bb_lower is not None:
            if not pd.isna(bb_upper) and latest["close"] > bb_upper:
                score += 1.5  # Breaking above upper band
            elif not pd.isna(bb_lower) and latest["close"] < bb_lower:
                score += 2.0  # Breaking below lower band (potential bounce)

        return score
