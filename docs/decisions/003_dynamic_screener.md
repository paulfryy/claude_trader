# ADR-003: Dynamic Stock Screener

**Date:** 2026-04-03
**Status:** Accepted

## Context
The initial implementation used a hardcoded 16-symbol watchlist. This was fine for testing but misses opportunities in the broader market. With $1000 capital and a swing trading strategy, we need to find the best setups across a wide universe, not just watch the same mega-caps every day.

## Decision

### Two-Tier Screening Architecture

**Universe:** S&P 500 components + 30 major ETFs = 524 symbols (in `universe.py`).

**Tier 1 — Quick Filter (all 524 symbols, <1 second):**
- Fetch batch snapshots from Alpaca (price + volume in one call per 100 symbols)
- Filter: price between $5-$500, daily volume > 500,000
- Result: ~76 symbols typically pass

**Tier 2 — Signal Scoring (~76 symbols, ~2-3 seconds):**
- Fetch 60 days of daily bars in batches
- Compute full technical indicators (RSI, MACD, SMA, Bollinger Bands)
- Score each symbol on signal strength:
  - RSI oversold (<30) or overbought (>70): +2-3 points
  - SMA 20-day crossover: +2-2.5 points
  - MACD crossover: +2-2.5 points
  - Volume spike (>2x average): +2 points
  - Bollinger Band breakout: +1.5-2 points
- Take top 30 by score

**Always Included:**
- Anchor symbols (SPY, QQQ, IWM) — market context
- Current positions — always re-evaluated

**Fallback:** If the screener fails for any reason, use the original 16-symbol static watchlist.

### Why This Approach?
- Batch snapshots make Tier 1 nearly free (<1s for 524 symbols)
- Tier 2 only pays the cost of bars + indicators for ~76 symbols
- Claude only sees the ~30 most actionable candidates — focused prompt, lower token cost
- Signal scoring is objective — Claude decides what to trade, but the screener decides what's worth looking at

### Screening Criteria Rationale
- **Price $5-$500:** Avoids penny stocks (wide spreads, manipulation risk) and stocks too expensive for meaningful position sizing with $1000 capital
- **Volume >500k:** Ensures liquidity — we can enter and exit without moving the price
- **RSI extremes:** Mean reversion opportunities (oversold bounce, overbought pullback)
- **SMA/MACD crossovers:** Trend change signals — core of swing trading
- **Volume spikes:** Unusual activity often precedes big moves
- **BB breakouts:** Volatility expansion signals

## Consequences
- The agent now scans the full S&P 500 every cycle instead of 16 fixed symbols
- More diverse opportunities — won't miss sector rotations or individual stock catalysts
- Slightly higher data cost per cycle (~3-4 seconds of API calls) — negligible
- Claude receives a more focused, higher-quality watchlist with built-in signal rationale
- Universe will need periodic updates as S&P 500 composition changes (quarterly)
