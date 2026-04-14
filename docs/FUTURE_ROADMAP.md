# Future Roadmap — Taking the Agent to the Next Level

**Last Updated:** 2026-04-13

A brain dump of ideas organized by category and honest priority. Not a commitment — a menu.

Ordering within each tier reflects my own bias toward high-impact, low-regret improvements.

---

## 🔥 Tier 1 — High Impact, Build Soon

These are the ideas I think would meaningfully move the needle on profitability or iteration speed. Each is feasible in a single session or weekend.

### 1. Backtesting Framework
**The single biggest multiplier for every future change.**

Problem: every strategy tweak today requires deploying to paper, waiting days for data, and hoping the new rule didn't break something. That's a 1-5 day feedback loop per change.

Solution: a harness that replays historical market data through the entire pipeline (screener → Claude → risk → execution simulation) and computes P&L. One hour of backtesting could test 20 prompt variations on 6 months of real market data.

**Scope:**
- Download historical bars for the entire universe from Alpaca (free)
- Replay the clock one day at a time, simulating the 3 cycles
- Stub out Alpaca order execution with a paper simulator (notional orders, simulated fills at next bar open, realistic slippage)
- Replace live Claude calls with cached responses from historical runs (or run live Claude on historical data — adds cost but gets real decisions)
- Track stats: Sharpe, drawdown, win rate, alpha vs SPY
- A/B test: run two strategies side-by-side with identical data

**Effort:** 1-2 days of focused work. Biggest ROI of anything on this list.

### 2. Weekly Performance Review (Self-Reflection)
Claude currently has no feedback loop from its own trades. It makes picks, forgets them, makes new picks. We should:

- Every Friday EOD, generate a **Weekly Review** that feeds back to Claude on Monday's morning cycle
- Contents: last week's closed trades with realized P&L, hit rate on conviction levels, which sectors worked, biggest winners and losers with Claude's original rationale
- Claude sees this at the start of Monday and can calibrate: "last week my high-conviction energy calls worked but my low-conviction financials dragged me down — this week I should be even more selective on financials"

**Effort:** ~3 hours. Low risk, consistent compounding benefit.

### 3. Partial Profit Taking (Take Half at Target 1)
Today's rule: "take 50% profit at halfway to target" is in the prompt but not enforced.

Problem: Claude follows the rule inconsistently. Sometimes it takes the profit, sometimes it holds. The outcome is up to its interpretation.

Solution: enforce it in code. When a position reaches 50% of its profit target, automatically submit a sell order for half the shares. Claude sees "position already at half size, trailing stop raised on remainder."

**Effort:** ~4 hours. Requires storing target_price per position (we already do) and a new orchestrator step.

### 4. Real-Time Alpha Tracking
Current alpha calc is point-in-time: "our return vs SPY from the benchmark start." This has the time-weighting problem we discussed.

Better: for each open position, track `position_return - SPY_return_during_holding`. Aggregate weighted by position size. True "per dollar, per day of holding" alpha.

**Effort:** ~3 hours. Requires recording SPY price at each entry. Dashboard displays a fair alpha number.

### 5. Trade History & Thesis Tracking
Every trade stores its entry rationale. We should also store:
- **Original target and stop** (for comparing to exits)
- **Days held** when closed
- **Exit reason** (hit stop, hit target, rotated out, thesis broken)
- **P&L by conviction level** (did high-conviction trades outperform?)

Then the Performance page gets a "Trade Analysis" section showing which kinds of trades actually work.

**Effort:** ~4 hours. Foundation for learning.

---

## 🛠 Tier 2 — Solid Improvements

Valuable but not game-changing. Build when you need a momentum push.

### 6. Fundamental Data Layer
Add a minimal fundamentals check before every buy:
- P/E ratio (is this absurdly expensive?)
- Market cap (avoid micro-caps unless explicit)
- Short interest (avoid meme-stock squeezes by accident)
- Recent insider selling
- Analyst rating consensus

Sources: Finnhub free tier has most of this, Yahoo Finance scraping, or Financial Modeling Prep free tier.

**Why it matters:** catches edge cases Claude's pure-technical view misses. "Stock is up 30% in 10 days with RSI 85, no earnings, short interest 45%, 3 analyst downgrades" → maybe don't buy that.

**Effort:** ~6 hours.

### 7. Sector Rotation Awareness
We have sector concentration limits but no sector **rotation** logic. In a rotation from tech to energy, we should:
- Notice XLE breaking out while XLK rolls over
- Close tech positions, open energy positions
- Shift the max_per_sector allowance dynamically (allow 3 energy when it's leading)

Requires sector ETF tracking + momentum comparison in the screener.

**Effort:** ~5 hours.

### 8. Correlation-Adjusted Sizing
"Max 2 per sector" is a blunt tool. Real correlation is subtler — AAPL and MSFT might move together even if "different sectors." Better: compute rolling 20-day correlation between candidates and existing positions. If new position correlates >0.7 with an existing one, treat it as half-size (like we already have that exposure).

**Effort:** ~6 hours. Meaningful diversification improvement.

### 9. Intraday Bar Confirmation
Today we only use daily bars. A stock that looks bullish on daily might be breaking down on 15-minute bars. Add a "confirmation" step for the morning cycle:
- Claude picks 3 candidates
- For each, check the last hour of 15-min bars
- If volume is drying up or price is rolling over intraday, downgrade conviction or skip

**Effort:** ~4 hours. Requires intraday bar API calls.

### 10. Automated Walk-Forward Testing
Once #1 (backtesting) exists, add **walk-forward testing**: train parameters on 6 months of data, test on the next month, roll forward. Prevents overfitting.

**Effort:** ~1 day (after #1).

---

## 💡 Tier 3 — Interesting Experiments

Ideas that could pay off big or teach you a lot, but are speculative.

### 11. Multi-Model Ensemble
Run 3 cycles with different Claude models (sonnet, haiku, sonnet with a different prompt) and only execute trades that 2+ models agree on.

- Pros: reduces single-model bias, increases conviction
- Cons: triples API cost, slows cycles

### 12. Sentiment Scraping
Add a social media sentiment source: Reddit r/wallstreetbets, Twitter/X financial feeds, Stocktwits. For liquid names, aggregate mentions and sentiment scores. Claude sees "TSLA: 847 mentions today, 62% bullish" alongside technicals.

- Easy source: stocktwits.com has a free API for sentiment
- Harder: pushshift/arctic_shift for Reddit, paid APIs for Twitter

**Why it matters:** retail-driven names (TSLA, NVDA, GME, meme stocks) move on sentiment more than fundamentals.

### 13. Options Spreads (Level 4)
Currently we only buy single-leg options (calls and puts). Level 4 approval unlocks:
- **Credit spreads** — defined-risk income (sell a call above the stock, buy a higher call for protection)
- **Debit spreads** — cheaper directional bets (buy a call, sell a higher call to reduce cost)
- **Iron condors** — profit from sideways markets
- **Covered calls** on existing stock positions

Requires Alpaca options approval upgrade. Adds complexity but opens strategies that work in markets where directional options lose money.

### 14. Claude Feedback Loop via Decision Log
Today, Claude's past decisions are only loaded as "prior context" for the same day. What if:
- Every week, compile Claude's last 7 days of decisions + their outcomes
- Feed that to a separate "review" prompt: "Here are your decisions and what happened. Identify 3 patterns in what worked and 3 patterns in what didn't."
- Save Claude's self-critique and inject it into future system prompts as "lessons learned"

This is meta-prompting — Claude tuning Claude based on its own performance. Risky but fascinating.

### 15. Pre-Market Movement Awareness
Add a "pre-market scan" that runs at 9:30 AM before the 9:45 morning cycle. Looks at overnight gap-ups and gap-downs on the universe, flags anything unusual. Claude's morning cycle starts with awareness of what moved overnight.

### 16. Post-Earnings Drift Strategy
Academic research shows stocks that beat earnings tend to drift up for ~30 days (PEAD — Post-Earnings Announcement Drift). We could:
- Monitor earnings results daily (Finnhub has this)
- Auto-watch any beat by >10% with revenue beat
- Claude sees a "recent earnings winners" list in the prompt

### 17. Bond ETF Rotation (Risk Regime)
In bear markets, rotating into TLT (long bonds), GLD (gold), or SHY (short-term treasuries) is a defensive play. We could:
- Add a "risk-off" mode triggered by regime=bear
- In risk-off, the screener prioritizes defensive assets
- Claude is instructed to consider bonds/gold as "cash plus yield"

---

## 🏗 Tier 4 — Infrastructure / Quality of Life

Not moving the alpha needle but making iteration faster, safer, and more pleasant.

### 18. Test Coverage
The code review flagged zero tests. Minimum viable test suite:
- Risk engine: every check has at least 2 tests (pass / fail cases)
- Position sizing: notional calculation across various scenarios
- Trailing stops: all tiers + edge cases (already have 6 unit tests!)
- Signal parsing: malformed JSON, missing fields
- Orchestrator: mock-Claude integration test for a full cycle

**Effort:** ~2 days. Ugly but critical for long-term confidence.

### 19. Alert System
Dashboard-based alerts beyond EOD emails:
- Email/SMS when drawdown exceeds 10%
- Email when a service crashes twice in an hour
- Email when a stop-loss fails to set (unprotected position warning)
- Email at open and close with current portfolio state

Use AWS SNS (free tier) or Twilio for SMS.

### 20. Live Web Logs Streaming
Dashboard page that streams journalctl output in real-time via Server-Sent Events. Watch the 9:45 cycle happen live in your browser.

### 21. Strategy Versioning
Tag git commits with strategy versions (v1-conservative, v2-aggressive, etc.). Track performance per version. When rolling back, know exactly which commit was the last good one.

### 22. Config Hot Reload
Change `.env.live` values via the Controls page without restarting. Useful for tweaking risk parameters mid-day without downtime.

### 23. Multi-Broker Support
Abstract the broker interface so Alpaca is one backend. Add Interactive Brokers for higher-volume strategies. Swap without rewriting the agent.

### 24. Strategy Templates
Pre-configured "strategy profiles" selectable via the dashboard:
- **Conservative** — 8 positions, 10% max, 60% deployed, tight stops
- **Balanced** — 6 positions, 15% max, 75% deployed
- **Aggressive** — 4 positions, 25% max, 90% deployed (current)
- **Swing + Options** — 4 equity + 2 options positions
- **Earnings Hunter** — catalyst plays only

Switch profiles with one click. Track which profile did best.

### 25. Dashboard Polish
- Real-time position P&L refresh (every 30s via JS)
- Sortable tables on all pages
- Mobile-friendly layout
- Dark/light theme toggle
- Keyboard shortcuts for power users

---

## 🎯 Tier 5 — Strategic Expansion

Longer-term ideas that require more commitment.

### 26. Interactive Brokers + $25k PDT Unlock
If the agent proves profitable, funding to $25k+ unlocks:
- Unlimited day trades (PDT rule lifts)
- Intraday strategies
- Scalping high-probability setups
- 2x buying power via portfolio margin
- Lower commission costs on IBKR vs Alpaca

This is a capital commitment, not a code change. But it dramatically increases the strategy space.

### 27. Options Flow Tracking
Institutional options flow (big unusual trades) is a leading indicator for retail. Subscribe to a feed (unusual whales, cheddar flow, etc.) and inject "smart money sentiment" into Claude's context.

Cost: ~$50-100/month for a feed. Worth it if it consistently improves win rate.

### 28. Multi-Strategy Portfolio
Run multiple strategies side-by-side with different objectives:
- **Strategy A** — swing trading (current aggressive tier)
- **Strategy B** — earnings plays (catalyst-focused)
- **Strategy C** — mean reversion (buy oversold, sell overbought)
- **Strategy D** — momentum breakouts (buy new 52-week highs)

Allocate capital across them based on recent performance. Each strategy has its own Claude system prompt.

### 29. Crypto via Alpaca
Alpaca supports crypto. Adding BTC/ETH to the universe and letting Claude allocate some capital there diversifies beyond US equities. Crypto trades 24/7 — would need a second scheduler.

### 30. Custom Fine-Tuned Model
After 6 months of cycles, you'd have thousands of decision logs with outcomes. You could fine-tune a smaller model (Claude Haiku or an open-source model) on your own trading history. A purpose-built agent trained on what works for your specific approach.

Requires: meaningful decision volume, engineering effort, and Anthropic/OpenAI fine-tuning API access.

---

## 🧘 Tier 6 — Things I'd Almost Never Do

Mentioning for completeness; I don't recommend any of these.

### 31. Margin Trading (Beyond 1x)
2x buying power sounds exciting but compounds losses just as much. Our aggressive strategy already swings ±15% monthly. Adding leverage = ±30% monthly. One bad month and you're crushed.

### 32. Short Selling
Technically possible with Alpaca, but emotionally taxing and requires much tighter risk management. Our strategy is long-biased by design.

### 33. Penny Stocks
Low liquidity, huge spreads, easy to manipulate. Stay with S&P 500 quality.

### 34. Hold-Overnight Earnings Plays Without Catalyst Sizing
Even "catalyst trades" are capped at 5% for a reason. Going bigger into earnings unmodeled = betting your account on a coin flip.

### 35. Trading Around FOMC / CPI Releases
These are high-volatility events with unpredictable direction. Better to sit them out than try to trade them with algorithmic precision.

---

## How I'd Sequence These (If I Were You)

Week 1 (after funds arrive and strategy proves working):
- **#4 Real-time alpha tracking** — we need a honest measurement tool
- **#5 Trade history & thesis tracking** — foundation for everything

Week 2-3:
- **#1 Backtesting framework** — the big investment, pays off forever

Week 4:
- **#2 Weekly review self-reflection**
- **#3 Partial profit taking**

Month 2:
- **#6 Fundamentals layer**
- **#18 Test coverage** (in parallel to other work)

Month 3+:
- Based on whatever's actually broken in production
- Plus any Tier 3 experiments that catch your interest

---

## Key Principles for Adding Features

1. **Measure before optimizing.** Don't add features to solve problems you haven't proven exist. Trust the anomaly log and the performance dashboard.
2. **One change at a time.** If you deploy 3 changes in the same day, you won't know which one caused Friday's 5% gain.
3. **Test in paper first.** Always. Every single time. Even for "small" changes.
4. **Backtesting makes everything faster.** Build it early, use it constantly.
5. **Simple rules beat complex ones.** If you can't explain why a rule exists, delete it.
6. **Trust the guardrails.** Our risk engine has saved us multiple times. Don't start bypassing it for "just this one trade."
7. **Sustainability > peak performance.** A 15% annual return you can keep earning beats a 50% year followed by -40%.
