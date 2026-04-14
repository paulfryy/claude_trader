# Architecture Overview

**Last Updated:** 2026-04-13

## Directory Structure

```
claude_agent/
├── docs/                            # Project documentation
│   ├── PROJECT_PLAN.md              # Implementation roadmap + status
│   ├── ARCHITECTURE.md              # This file
│   ├── CLOUD_DEPLOYMENT.md          # AWS EC2 deployment guide
│   ├── FUTURE_ROADMAP.md            # Next-level development ideas
│   └── decisions/                   # Architecture decision records
├── src/
│   ├── agent/
│   │   ├── orchestrator.py          # Main trading cycle loop
│   │   └── scheduler.py             # 3x daily scheduling (Mon-Fri)
│   ├── analysis/
│   │   ├── analyst.py               # Claude prompt + API + options selection
│   │   └── signals.py               # TradeSignal, MarketAnalysis models
│   ├── data/
│   │   ├── market_data.py           # Alpaca: bars, quotes, snapshots, accounts
│   │   ├── indicators.py            # Technical indicators (RSI, MACD, BB, etc.)
│   │   ├── news.py                  # Alpaca news API client
│   │   ├── earnings_calendar.py     # Finnhub earnings calendar (free tier)
│   │   ├── universe.py              # S&P 500 + ETFs + sector classification
│   │   ├── screener.py              # Two-tier dynamic screener
│   │   └── options_chain.py         # Options chain + live quotes
│   ├── portfolio/
│   │   ├── portfolio.py             # Portfolio state tracking + snapshots
│   │   ├── risk.py                  # 9-layer risk engine
│   │   ├── sizing.py                # Notional + options contract sizing
│   │   └── trailing_stops.py        # Automated trailing stop tiers
│   ├── execution/
│   │   └── orders.py                # Equity + options order execution
│   ├── logging_utils/
│   │   ├── trade_journal.py         # Per-trade logging
│   │   ├── decision_log.py          # Per-cycle Claude analysis log
│   │   ├── daily_summary.py         # Markdown summaries (appended per cycle)
│   │   ├── eod_report.py            # End-of-day consolidated report
│   │   ├── email_report.py          # Gmail SMTP EOD delivery
│   │   ├── benchmark.py             # SPY benchmark tracker
│   │   ├── performance.py           # Stats analyzer (equity curve, Sharpe, etc.)
│   │   └── anomaly_log.py           # Structured unusual events logger
│   ├── dashboard/
│   │   ├── app.py                   # Flask routes + handlers
│   │   ├── controls.py              # Service management + git operations
│   │   ├── templates/               # Jinja2 templates (9 pages)
│   │   └── static/style.css         # Dark theme styling
│   └── config.py                    # pydantic-settings config
├── logs/                            # Runtime logs (mode-separated)
│   ├── paper/
│   │   ├── trades/                  # Trade records
│   │   ├── decisions/               # Claude analyses
│   │   ├── portfolio/               # State snapshots
│   │   ├── summaries/               # Per-cycle markdown (git-tracked)
│   │   ├── reports/                 # EOD reports (git-tracked)
│   │   ├── errors/                  # Error tracebacks
│   │   ├── anomalies.jsonl          # Structured anomaly log
│   │   ├── benchmark.json           # SPY start price
│   │   └── high_watermark.json      # Peak equity
│   └── live/                        # Same structure, isolated from paper
├── tests/                           # Test suite (minimal)
├── .env                             # Legacy single config (optional)
├── .env.paper                       # Paper mode config (gitignored)
├── .env.live                        # Live mode config (gitignored)
├── .env.example                     # Template (git-tracked)
├── pyproject.toml                   # Project config & dependencies
└── .gitignore
```

## Data Flow (per cycle)

```
                                ┌─────────────────────┐
                                │ Cycle Mode          │
                                │ morning/midday/     │
                                │ closing             │
                                └──────────┬──────────┘
                                           │
  S&P 500 + ETFs (524 symbols)             │
  ┌──────────────────────────┐             │
  │  Two-Tier Screener       │             │
  │                          │             │
  │  Tier 1: Snapshot scan   │             │
  │  - Price/volume filter   │             │
  │  - Batch API calls       │             │
  │  → ~76 symbols pass      │             │
  │                          │             │
  │  Tier 2: Signal scoring  │             │
  │  - Full indicators       │             │
  │  - RSI, MACD, SMA, BB    │             │
  │  - Relative strength vs  │             │
  │    SPY 10-day (FILTER)   │             │
  │  → top 30 by score       │             │
  └──────────┬───────────────┘             │
             │                             │
             │ + 3 anchors (SPY, QQQ, IWM) │
             │ + current positions          │
             ▼                              │
  ┌──────────────────────────┐             │
  │  Context Assembly         │             │
  │  - Watchlist data         │             │
  │  - News (Alpaca/Benzinga) │             │
  │  - Earnings calendar      │             │
  │    (Finnhub)              │             │
  │  - Open stop orders       │             │
  │  - Portfolio state        │             │
  │  - Prior cycles today     │             │
  └──────────┬───────────────┘             │
             │                              │
             ▼                              ▼
  ┌──────────────────────────────────────────────┐
  │  Trailing Stop Automation (pre-analysis)     │
  │  For each position:                          │
  │  - +5%  → raise stop to breakeven            │
  │  - +10% → trail 5% below current             │
  │  - +20% → trail 8% below current             │
  │  Updates stops BEFORE Claude sees them       │
  └──────────────────┬───────────────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────┐
  │  Claude Analysis (cycle-mode-aware)          │
  │  - Aggressive system prompt                  │
  │  - Conviction-weighted sizing rules          │
  │  - Hard exit rules                           │
  │  - Sector diversification rules              │
  │  - Retry on 529/503/429 errors               │
  │  → MarketAnalysis (JSON)                     │
  │    - market_regime, confidence               │
  │    - market_summary (narrative)              │
  │    - trade_signals (opens)                   │
  │    - positions_to_close                      │
  │    - stop_adjustments                        │
  └──────────────────┬───────────────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────┐
  │  9-Layer Risk Engine                         │
  │  1. Drawdown circuit breaker                 │
  │  2. Max positions (6 equity)                 │
  │  3. Sector concentration (2 per sector)      │
  │  4. Catalyst size cap (5% overnight)         │
  │  5. Position size cap (20%)                  │
  │  6. Total exposure (90%)                     │
  │  7. Options exposure (40%)                   │
  │  8. PDT warning                              │
  │  9. Stop-loss required (equity buys)         │
  │                                              │
  │  Daily position limit: 3 new/day             │
  │  Bad-stop check: stop < current price        │
  │  Closing cycle: catalyst-only entries        │
  └──────────────────┬───────────────────────────┘
                     │
             ┌───────┴───────┐
             │               │
          APPROVED       REJECTED
             │               │
             ▼               ▼
  ┌──────────────┐    ┌──────────────┐
  │  Execute     │    │  Log as      │
  │  via Alpaca  │    │  anomaly     │
  │              │    │  + rejection │
  │  Equity:     │    └──────────────┘
  │   notional   │
  │   market     │
  │   +stop-loss │
  │   retry      │
  │              │
  │  Options:    │
  │   chain      │
  │   lookup     │
  │   → Claude   │
  │   picks      │
  │   contract   │
  │   → OCC      │
  │   symbol     │
  │   order      │
  └──────┬───────┘
         │
         ▼
  ┌──────────────────────────────┐
  │  Logging                     │
  │  - Trade journal JSON        │
  │  - Decision log JSON         │
  │  - Portfolio snapshot JSON   │
  │  - Daily summary markdown    │
  │  - Anomaly log (on failure)  │
  │                              │
  │  Closing cycle only:         │
  │  - EOD report markdown       │
  │  - Email via Gmail SMTP      │
  └──────────────────────────────┘
```

## Cycle Modes

| Time (ET) | Mode | New Entries | Exits | Purpose |
|---|---|---|---|---|
| 9:45 AM | Morning | Yes | Yes | Primary decision cycle |
| 12:30 PM | Midday | Selective | Yes | Defensive check, manage positions |
| 3:45 PM | Closing | Catalyst only | Yes | Review, log EOD, prep for tomorrow |

Catalyst entries (closing cycle): new positions allowed only with an explicit catalyst (earnings, FDA decision, etc.) at 5% max size.

## 9-Layer Risk Engine

```
Layer 1: Claude's System Prompt
  └── Strategy rules, conviction sizing, hard exits

Layer 2: Risk Manager (src/portfolio/risk.py)
  ├── Drawdown circuit breaker     (>15% → halt new buys)
  ├── Max positions                (6 concurrent)
  ├── Sector concentration         (2 per sector)
  ├── Catalyst size limit          (5% overnight trades)
  ├── Position size cap            (20% max)
  ├── Total exposure cap           (90%)
  ├── Options exposure cap         (40%)
  ├── PDT limit check              (3 day trades / 5 days)
  └── Stop-loss required           (equity buys only)

Layer 3: Orchestrator Pre-Flight Checks
  ├── Bad stop-loss detection      (stop >= current price rejected)
  ├── Daily position limit         (3 new per day, prompt+code enforced)
  ├── PDT same-day sell check      (trade journal lookup)
  ├── Duplicate close prevention   (closed_this_cycle set)
  └── Closing cycle catalyst check (no non-catalyst buys)

Layer 4: Cycle Mode Enforcement
  └── Closing cycle blocks non-catalyst entries

Layer 5: Alpaca Broker-Side
  ├── Day trade count enforcement  (final backstop)
  ├── Buying power validation      (can't exceed cash)
  └── Wash trade protection        (we cancel stops first)
```

## Key Design Principles

1. **Separation of concerns** — Claude analyzes, risk engine validates, executor trades
2. **Defense in depth** — risk checks at multiple layers
3. **Fail safe** — errors abort cycles gracefully, never execute bad trades
4. **Paper isolation** — separate env files, separate logs, same code
5. **Everything logged** — decisions, trades, errors, anomalies (JSON + markdown)
6. **Anomaly feedback loop** — structured problem log for iterative improvement
7. **Retry transient failures** — Anthropic 529, race conditions, fractional bracket fallback
8. **Claude cannot bypass** — hard risk limits in code, prompt is advisory

## Configuration

All settings load from `.env.paper` or `.env.live` via pydantic-settings and the `--env` flag.

| Variable | Default | Purpose |
|---|---|---|
| `ALPACA_API_KEY` | — | Alpaca API key |
| `ALPACA_SECRET_KEY` | — | Alpaca secret |
| `ALPACA_TRADING_MODE` | `paper` | `paper` or `live` |
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `FINNHUB_API_KEY` | — | Earnings calendar (optional) |
| `GMAIL_EMAIL` | — | SMTP sender (optional) |
| `GMAIL_APP_PASSWORD` | — | SMTP auth (optional) |
| `NOTIFY_EMAIL` | — | EOD report recipient (optional) |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Model for analysis |
| `STARTING_CAPITAL` | `1000` | Virtual equity base for sizing |
| `MAX_POSITION_PCT` | `0.20` | Max % in single position |
| `MAX_TOTAL_EXPOSURE_PCT` | `0.90` | Max % deployed |
| `MAX_OPTIONS_EXPOSURE_PCT` | `0.40` | Max % in options |
| `MAX_DRAWDOWN_PCT` | `0.15` | Circuit breaker threshold |
| `STOP_LOSS_DEFAULT_PCT` | `0.08` | Default stop-loss distance |
| `MAX_TOTAL_POSITIONS` | `6` | Max concurrent positions |
| `MAX_POSITIONS_PER_SECTOR` | `2` | Sector concentration limit |
| `MAX_NEW_POSITIONS_PER_DAY` | `3` | PDT stop-loss constraint |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Running

```bash
# Paper trading — scheduled
python -m src.agent.scheduler --env .env.paper

# Live trading — scheduled
python -m src.agent.scheduler --env .env.live

# One-off cycle (auto-detects mode from current time)
python -m src.agent.orchestrator --env .env.paper

# Dry-run (full pipeline, no order submission, bypasses market hours)
python -m src.agent.orchestrator --env .env.paper --dry-run

# Dashboard
python -m src.dashboard.app
# Then visit http://localhost:8080
```

In production on EC2, all three run as systemd services with auto-restart.

## Dashboard

Read-only Flask web UI exposing:

| Page | Path | Purpose |
|---|---|---|
| Overview | `/` | Live portfolio + latest cycle narrative |
| Performance | `/performance` | Stats, equity curve, trade history |
| Positions | `/positions` | Current holdings with P&L |
| Reports | `/reports` | End-of-day markdown reports |
| History | `/history` | Per-cycle daily summaries |
| Cycles | `/cycles` | Recent Claude analyses with full rationale |
| Diagnostics | `/diagnostics` | Anomaly log with filters + export |
| Controls | `/controls` | Service management + git ops + logs |

Mode toggle: `?mode=paper` or `?mode=live` on any page. Separate logs per mode.

Controls page actions:
- Restart / Start / Stop each trading service
- Restart the dashboard itself (deferred 2s for HTTP response)
- Git Pull to update code
- Refresh Python dependencies
- Trigger manual dry-run cycles
- View recent journalctl logs per service
- View server health (uptime, disk, memory)
- View audit log of control actions

## Error Handling

The agent is designed to never crash from a single failure:

- **Orchestrator** — each step wrapped in try/except, failures logged to `logs/{mode}/errors/` with full traceback
- **Scheduler** — wraps each cycle in `_safe_run_cycle()`, catches all exceptions, continues to next cycle
- **Startup validation** — tolerates transient Anthropic 529/503/429 errors at boot
- **Claude retries** — exponential backoff (15s → 30s → 60s → 120s) on overloaded errors
- **Stop-loss retries** — waits for fill, retries 4 times over 8s
- **Anomaly logging** — every unusual event logged for feedback
- **Graceful shutdown** — Ctrl+C triggers clean exit with logging
