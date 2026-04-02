# Architecture Overview

## Directory Structure

```
claude_agent/
├── docs/                    # Project documentation
│   ├── PROJECT_PLAN.md      # Implementation roadmap
│   ├── ARCHITECTURE.md      # This file
│   └── decisions/           # Decision logs (ADRs)
├── src/
│   ├── agent/               # Core agent orchestration
│   │   ├── orchestrator.py  # Main agent loop
│   │   └── scheduler.py     # Run scheduling
│   ├── analysis/            # Claude analysis engine
│   │   ├── analyst.py       # Claude prompt construction & parsing
│   │   ├── prompts/         # Prompt templates
│   │   └── signals.py       # Trade signal models
│   ├── data/                # Market data layer
│   │   ├── market_data.py   # Price & options data from Alpaca
│   │   ├── indicators.py    # Technical indicator calculations
│   │   └── news.py          # News & sentiment data
│   ├── portfolio/           # Portfolio & risk management
│   │   ├── portfolio.py     # Portfolio state tracking
│   │   ├── risk.py          # Risk rules engine
│   │   └── sizing.py        # Position sizing
│   ├── execution/           # Order execution
│   │   ├── orders.py        # Order building & submission
│   │   └── monitor.py       # Order monitoring
│   ├── logging/             # Logging & analytics
│   │   ├── trade_journal.py # Trade-level logging
│   │   ├── decision_log.py  # Claude analysis logging
│   │   └── performance.py   # Performance metrics & tracking
│   └── config.py            # Configuration management
├── logs/                    # Runtime logs
│   ├── trades/              # Trade journals (by date)
│   ├── decisions/           # Claude decision logs
│   ├── portfolio/           # Daily portfolio snapshots
│   └── errors/              # Error logs
├── tests/                   # Test suite
├── .env.example             # Environment variable template
├── pyproject.toml           # Project config & dependencies
└── README.md                # Project overview
```

## Data Flow

```
Market Data (Alpaca) ──┐
                       ├──> Claude Analysis ──> Trade Signals
News / Sentiment ──────┘          │
                                  │
Portfolio State ──────────────────┤
                                  ▼
                          Risk Validation
                                  │
                           ┌──────┴──────┐
                           │  APPROVED   │  REJECTED
                           ▼             ▼
                     Order Execution   Log reason
                           │
                           ▼
                     Trade Journal
                     (full audit)
```

## Key Design Principles

1. **Separation of concerns** — Claude analyzes, risk engine validates, executor trades
2. **Claude cannot bypass risk limits** — hard-coded guardrails in the risk engine
3. **Everything is logged** — decisions, trades, errors, performance
4. **Idempotent operations** — safe to re-run without duplicate trades
5. **Fail safe** — errors result in no action, not bad trades
6. **Paper-first** — all development against paper trading environment
