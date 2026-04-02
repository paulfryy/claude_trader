# Claude Trading Agent — Project Plan

## Overview
Fully autonomous Claude-powered trading agent managing a $1000 portfolio via Alpaca.
Target: beat the S&P 500 benchmark through swing trading equities/ETFs and short-term options.

## Constraints
- **PDT Rule**: Under $25k, limited to 3 day trades per 5 rolling business days. Strategy must be swing-oriented (hold overnight minimum) or use options.
- **Capital**: $1000 starting — position sizing must account for small account dynamics
- **Options**: Alpaca options support — must verify tier/approval level

---

## Implementation Phases

### Phase 1: Project Setup & Infrastructure
- [x] Define project goals and constraints
- [ ] Initialize Python project (pyproject.toml, virtual environment)
- [ ] Set up directory structure
- [ ] Configure Alpaca API (paper trading first)
- [ ] Set up Anthropic API client
- [ ] Create configuration management (env vars, settings)
- [ ] Initialize git repo

### Phase 2: Data Layer
- [ ] Market data client (Alpaca market data API)
  - Real-time and historical price data
  - Options chain data
- [ ] Technical indicators module (RSI, MACD, moving averages, volume analysis)
- [ ] News/sentiment data pipeline (Alpaca news API or alternative)
- [ ] Fundamental data (earnings, financials) where available
- [ ] Data caching to minimize API calls

### Phase 3: Claude Analysis Engine
- [ ] Prompt engineering for market analysis
  - Market regime detection (bull/bear/sideways/volatile)
  - Individual stock/ETF analysis
  - Options opportunity identification
- [ ] Structured output parsing (trade signals with confidence scores)
- [ ] Context management — feed Claude relevant data without exceeding limits
- [ ] Decision documentation — every analysis logged with full rationale

### Phase 4: Portfolio & Risk Management
- [ ] Portfolio state tracker (positions, cash, P&L, Greeks for options)
- [ ] Risk rules engine:
  - Max position size (% of portfolio)
  - Max total exposure
  - Stop-loss / take-profit levels
  - Max options exposure
  - PDT day trade counter
  - Max drawdown circuit breaker
- [ ] Position sizing calculator (Kelly criterion or fixed fractional)

### Phase 5: Order Execution
- [ ] Order builder (market, limit, stop, bracket orders)
- [ ] Options order builder (single legs to start, spreads later)
- [ ] Order submission and confirmation via Alpaca
- [ ] Order monitoring (fills, partial fills, rejections)
- [ ] Retry/fallback logic for failed orders

### Phase 6: Agent Orchestration
- [ ] Main agent loop:
  1. Fetch portfolio state
  2. Fetch market data & news
  3. Run Claude analysis
  4. Generate trade proposals
  5. Validate against risk rules
  6. Execute approved trades
  7. Log everything
- [ ] Scheduling (run at configurable intervals — e.g., pre-market, mid-day, post-market)
- [ ] Error handling and graceful degradation

### Phase 7: Logging & Analytics
- [ ] Trade journal (every trade with entry/exit, rationale, outcome)
- [ ] Decision log (every Claude analysis with full prompt/response)
- [ ] Daily portfolio snapshot (NAV, positions, cash, benchmark comparison)
- [ ] Performance metrics (Sharpe ratio, max drawdown, win rate, avg win/loss)
- [ ] Mistake tracker (trades that lost money — what went wrong)

### Phase 8: Paper Trading & Validation
- [ ] Run on Alpaca paper trading for 2+ weeks
- [ ] Daily performance review
- [ ] Tune risk parameters based on results
- [ ] Validate logging captures everything needed for analysis

### Phase 9: Go Live
- [ ] Switch to live Alpaca account with $1000
- [ ] Tighter risk limits initially
- [ ] Daily monitoring and review
- [ ] Iterative improvement based on trade journal analysis

---

## Architecture Decisions

### Why Python?
- Best library ecosystem for finance (pandas, numpy, ta-lib)
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

---

## Key Risk Mitigations
1. **Paper trade first** — validate everything before real money
2. **Hard risk limits** — coded constraints Claude cannot bypass
3. **Circuit breaker** — halt trading if drawdown exceeds threshold
4. **PDT tracking** — automated day trade counter prevents violations
5. **Extensive logging** — full audit trail for every decision
6. **Small position sizes** — no single position > X% of portfolio
