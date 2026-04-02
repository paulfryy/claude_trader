# Claude Trading Agent — Project Plan

**Last Updated:** 2026-04-02

## Overview
Fully autonomous Claude-powered trading agent managing a $1000 portfolio via Alpaca.
Target: beat the S&P 500 benchmark through swing trading equities/ETFs and short-term options.

## Constraints
- **PDT Rule**: Under $25k, limited to 3 day trades per 5 rolling business days. Strategy must be swing-oriented (hold overnight minimum) or use options.
- **Capital**: $1000 starting — position sizing must account for small account dynamics
- **Options**: Alpaca options support — must verify tier/approval level
- **API Budget**: ~$10 Anthropic credits — each cycle costs ~$0.02-0.05

---

## Implementation Phases

### Phase 1: Project Setup & Infrastructure — COMPLETE
- [x] Define project goals and constraints
- [x] Initialize Python project (pyproject.toml, virtual environment)
- [x] Set up directory structure
- [x] Configure Alpaca API (paper trading)
- [x] Set up Anthropic API client
- [x] Create configuration management (env vars, pydantic-settings)
- [x] Initialize git repo

### Phase 2: Data Layer — COMPLETE
- [x] Market data client (Alpaca market data API)
  - [x] Historical OHLCV bars (daily, up to 1yr lookback)
  - [x] Latest quotes (bid/ask)
  - [x] Account info and positions
  - [ ] Options chain data (deferred — needs options approval)
- [x] Technical indicators module (RSI, MACD, SMA/EMA, Bollinger Bands, ATR, OBV, VWAP, Stoch RSI)
- [x] News/sentiment data pipeline (Alpaca news API — market-wide and per-symbol)
- [ ] Fundamental data (earnings, financials) — deferred to Phase 10
- [ ] Data caching to minimize API calls — deferred, not needed yet at 3 cycles/day

### Phase 3: Claude Analysis Engine — COMPLETE
- [x] Prompt engineering for market analysis
  - [x] Market regime detection (bull/bear/sideways/volatile)
  - [x] Individual stock/ETF analysis with technical indicators
  - [ ] Options opportunity identification (deferred — needs options chain data)
- [x] Structured JSON output parsing (trade signals with confidence scores)
- [x] Context management — feeds Claude indicators + news + portfolio state
- [x] Cycle-aware prompting (morning/midday/closing modes)
- [x] Decision documentation — every analysis logged with full rationale

### Phase 4: Portfolio & Risk Management — COMPLETE
- [x] Portfolio state tracker (positions, cash, P&L, exposure)
- [x] Risk rules engine (6 hard guardrails):
  - [x] Max position size (15% of portfolio)
  - [x] Max total exposure (90%)
  - [x] Stop-loss required on all buys
  - [x] Max options exposure (30%)
  - [x] PDT day trade protection (3 layers: Claude prompt, trade journal check, Alpaca backstop)
  - [x] Max drawdown circuit breaker (15%)
- [x] Position sizing calculator (fixed fractional for equities and options)

### Phase 5: Order Execution — COMPLETE (equities)
- [x] Market orders via Alpaca
- [x] Bracket orders (take-profit + stop-loss)
- [x] Position closing
- [x] Order status reporting
- [ ] Options order builder — deferred until options approval
- [ ] Order monitoring (fills, partial fills) — future enhancement
- [ ] Retry/fallback logic for failed orders — future enhancement

### Phase 6: Agent Orchestration — COMPLETE
- [x] Main agent loop (orchestrator.py):
  1. Check market status
  2. Fetch portfolio state + snapshot
  3. Fetch market data + indicators for watchlist
  4. Fetch news (market-wide + per-symbol)
  5. Run Claude analysis (cycle-mode-aware)
  6. Close positions Claude wants to exit (with PDT check)
  7. Validate new signals against risk rules
  8. Execute approved trades
  9. Log everything (JSON + markdown summary)
- [x] Cycle modes:
  - Morning (9:45 AM ET): Full trading — new entries + exits
  - Midday (12:30 PM ET): Defensive — manage positions, selective entries
  - Closing (3:45 PM ET): Review only — exits + analysis, NO new entries
- [x] Scheduler (3x daily Mon-Fri)
- [ ] Error handling and graceful degradation — basic, needs hardening

### Phase 7: Logging & Analytics — MOSTLY COMPLETE
- [x] Trade journal (every trade with signal, execution result, portfolio state)
- [x] Trade rejection log (rejected signals with reasons)
- [x] Decision log (every Claude analysis with full response)
- [x] Daily portfolio snapshots (JSON)
- [x] Human-readable daily markdown summaries (git-tracked)
- [ ] Performance metrics (Sharpe ratio, max drawdown, win rate, avg win/loss)
- [ ] Benchmark comparison (portfolio vs SPY)
- [ ] Mistake tracker (trades that lost money — what went wrong)

### Phase 8: Paper Trading & Validation — IN PROGRESS
- [x] Alpaca paper account connected ($100k paper money)
- [x] Full pipeline tested end-to-end (data → analysis → risk → logging)
- [ ] **Run scheduled agent during market hours** ← NEXT STEP
- [ ] Run for 2+ weeks collecting data
- [ ] Daily performance review
- [ ] Tune risk parameters and watchlist based on results
- [ ] Tune Claude prompts based on decision quality
- [ ] Validate logging captures everything needed for analysis

### Phase 9: Go Live
- [ ] Switch to live Alpaca account with $1000
- [ ] Adjust risk limits for real money (likely tighter initially)
- [ ] Daily monitoring and review
- [ ] Iterative improvement based on trade journal analysis

### Phase 10: Enhancements (Future)
- [ ] Options trading (needs Alpaca options approval + chain data)
- [ ] Fundamental data integration (earnings, revenue, analyst ratings)
- [ ] Sector rotation strategy
- [ ] Earnings calendar awareness (avoid holding through earnings)
- [ ] Data caching layer
- [ ] Backtesting framework (replay historical data through the agent)
- [ ] Performance dashboard (web UI or CLI report)
- [ ] Cross-session learning (feed past trade outcomes into Claude's context)
- [ ] Alert system (email/SMS on significant events)
- [ ] Multi-timeframe analysis (daily + hourly charts)

---

## Current Status (2026-04-02)

**Where we are:** Phases 1-7 are built. The full pipeline has been tested end-to-end after market hours — data fetching, indicator calculation, news, Claude analysis, risk validation, and logging all work. Claude generated 3 trade signals (QQQ, NVDA, MSFT) that all passed risk checks.

**What's next:** Run the scheduler during market hours tomorrow (2026-04-03) for the first live paper trading test. This will be the first time the agent actually executes orders.

**Key concern:** We're using $100k paper money but the real account will be $1000. Position sizing logic works on percentages so it should scale, but we should watch for any issues with minimum order sizes or fractional shares.

---

## Architecture Decisions

See [docs/decisions/](decisions/) for full ADRs.

### Why Python?
- Best library ecosystem for finance (pandas, numpy, ta)
- Alpaca and Anthropic both have first-party Python SDKs
- Rapid iteration

### Why Alpaca?
- Commission-free equities and options
- Clean REST + WebSocket API
- Paper trading environment for safe testing
- Options support

### Why Swing Trading + Options?
- PDT rule prevents frequent day trading under $25k
- Swing trades (multi-day holds) avoid PDT entirely
- Options allow leveraged exposure with defined risk on small capital
- Options premiums can generate income even in sideways markets

### Fully Autonomous Design
- Claude makes all trading decisions — no human approval loop
- Risk management rules act as guardrails (hard limits Claude cannot override)
- Every decision is logged so we can review and refine

### Cycle Modes
- Three cycles per trading day with different permissions
- Closing cycle is analysis-only — prevents opening positions near market close
- PDT protection at multiple layers (prompt, code, Alpaca)

---

## Key Risk Mitigations
1. **Paper trade first** — validate everything before real money
2. **Hard risk limits** — 6 coded constraints Claude cannot bypass
3. **Circuit breaker** — halt trading if drawdown exceeds 15%
4. **PDT protection** — 3 layers prevent accidental day trades
5. **Cycle modes** — closing cycle blocks new entries
6. **Extensive logging** — full audit trail for every decision in JSON + markdown
7. **Small position sizes** — no single position > 15% of portfolio

---

## Log Structure

| Location | Format | Purpose | Git Tracked |
|---|---|---|---|
| `logs/summaries/` | Markdown | Human-readable daily summaries | Yes |
| `logs/decisions/` | JSON | Full Claude analyses + raw responses | No |
| `logs/trades/` | JSON | Individual trade records | No |
| `logs/portfolio/` | JSON | Portfolio snapshots per cycle | No |
| `logs/errors/` | Log | Error logs | No |
| `docs/decisions/` | Markdown | Architecture decision records | Yes |
