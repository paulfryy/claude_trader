# Architecture Overview

**Last Updated:** 2026-04-02

## Directory Structure

```
claude_agent/
├── docs/                          # Project documentation
│   ├── PROJECT_PLAN.md            # Implementation roadmap & status
│   ├── ARCHITECTURE.md            # This file
│   └── decisions/                 # Architecture decision records (ADRs)
│       └── 001_initial_design_choices.md
├── src/
│   ├── agent/                     # Core agent orchestration
│   │   ├── orchestrator.py        # Main agent loop + cycle mode logic
│   │   └── scheduler.py           # 3x daily scheduling (Mon-Fri)
│   ├── analysis/                  # Claude analysis engine
│   │   ├── analyst.py             # Prompt construction, API calls, response parsing
│   │   ├── prompts/               # (future) Prompt templates
│   │   └── signals.py             # TradeSignal, MarketAnalysis models
│   ├── data/                      # Market data layer
│   │   ├── market_data.py         # Alpaca: bars, quotes, account, positions
│   │   ├── indicators.py          # Technical indicators (RSI, MACD, BB, etc.)
│   │   └── news.py                # Alpaca news API client
│   ├── portfolio/                 # Portfolio & risk management
│   │   ├── portfolio.py           # Portfolio state tracking + snapshots
│   │   ├── risk.py                # Risk rules engine (6 guardrails)
│   │   └── sizing.py              # Position sizing (shares + options contracts)
│   ├── execution/                 # Order execution
│   │   └── orders.py              # Market + bracket orders via Alpaca
│   ├── logging_utils/             # Logging & analytics
│   │   ├── trade_journal.py       # Per-trade logging (executions + rejections)
│   │   ├── decision_log.py        # Per-cycle Claude analysis logging
│   │   ├── daily_summary.py       # Human-readable markdown daily summaries
│   │   └── performance.py         # Performance metrics tracking
│   └── config.py                  # Configuration (pydantic-settings from .env)
├── logs/                          # Runtime logs (mostly gitignored)
│   ├── summaries/                 # Daily markdown summaries (git-tracked)
│   ├── trades/                    # Trade journal entries (JSON)
│   ├── decisions/                 # Claude analysis logs (JSON)
│   ├── portfolio/                 # Portfolio snapshots (JSON)
│   └── errors/                    # Error logs
├── tests/                         # Test suite
├── .env                           # API keys (gitignored)
├── .env.example                   # Environment variable template
├── pyproject.toml                 # Project config & dependencies
└── .gitignore
```

## Data Flow

```
                              ┌─────────────────┐
                              │  Cycle Mode      │
                              │  morning/midday/ │
                              │  closing         │
                              └────────┬─────────┘
                                       │
Market Data (Alpaca) ──┐               │
  - OHLCV bars         │               ▼
  - Latest quotes      ├──> Claude Analysis ──> Trade Signals
  - Account info       │    (cycle-mode-aware)
News (Alpaca) ─────────┘          │
                                  │
Portfolio State ──────────────────┤
  - Positions                     │
  - Exposure                      ▼
  - Drawdown              Risk Validation
                          (6 guardrails)
                                  │
                     ┌────────────┼────────────┐
                     │            │             │
                  APPROVED    REJECTED     PDT BLOCKED
                     │            │             │
                     ▼            ▼             ▼
              Order Execution  Log reason    Log reason
              (Alpaca API)
                     │
                     ▼
              ┌──────────────┐
              │ Logging      │
              │ - Trade JSON │
              │ - Decision   │
              │ - Snapshot   │
              │ - Summary.md │
              └──────────────┘
```

## Cycle Modes

The agent runs 3 times per trading day, each with different permissions:

| Time (ET) | Mode | New Entries | Exits | Purpose |
|-----------|------|-------------|-------|---------|
| 9:45 AM | Morning | Yes | Yes | Primary decision cycle |
| 12:30 PM | Midday | Selective | Yes | Defensive check, manage positions |
| 3:45 PM | Closing | **No** | Yes | Review, log EOD, prep for tomorrow |

Claude receives different system prompts per mode. The closing cycle tells Claude to focus on position review and tomorrow's outlook rather than proposing new buys.

## Risk Management Layers

```
Layer 1: Claude's System Prompt
  └── Told the rules, asked to self-enforce

Layer 2: Risk Manager (risk.py)
  ├── Drawdown circuit breaker (>15% → halt all new trades)
  ├── Position size cap (>15% → clamp)
  ├── Total exposure cap (>90% → clamp or reject)
  ├── Options exposure cap (>30% → reject)
  ├── Stop-loss required (no stop → reject)
  └── PDT warning (at limit → warn)

Layer 3: Orchestrator PDT Check
  └── Scans trade journal for same-day buys before any sell

Layer 4: Cycle Mode Enforcement
  └── Closing cycle blocks all new entries regardless

Layer 5: Alpaca (final backstop)
  └── Rejects day trades past PDT limit
```

## Key Design Principles

1. **Separation of concerns** — Claude analyzes, risk engine validates, executor trades
2. **Claude cannot bypass risk limits** — hard-coded guardrails in the risk engine
3. **Everything is logged** — decisions, trades, errors, performance (JSON + markdown)
4. **Defense in depth** — multiple layers for PDT, risk, and mode enforcement
5. **Fail safe** — errors result in no action, not bad trades
6. **Paper-first** — all development against paper trading environment
7. **Learn from mistakes** — daily summaries + decision logs enable cross-session review

## Configuration

All settings are loaded from `.env` via pydantic-settings:

| Variable | Default | Description |
|---|---|---|
| `ALPACA_API_KEY` | — | Alpaca API key |
| `ALPACA_SECRET_KEY` | — | Alpaca secret key |
| `ALPACA_TRADING_MODE` | `paper` | `paper` or `live` |
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Model for analysis |
| `MAX_POSITION_PCT` | `0.15` | Max single position size |
| `MAX_TOTAL_EXPOSURE_PCT` | `0.90` | Max portfolio deployment |
| `MAX_OPTIONS_EXPOSURE_PCT` | `0.30` | Max options allocation |
| `MAX_DRAWDOWN_PCT` | `0.15` | Circuit breaker threshold |
| `STOP_LOSS_DEFAULT_PCT` | `0.08` | Default stop-loss distance |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Running

```bash
# Single cycle (uses current time to determine mode)
python -m src.agent.orchestrator

# Scheduled (3x daily Mon-Fri)
python -m src.agent.scheduler
```
