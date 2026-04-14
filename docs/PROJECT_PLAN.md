# Claude Trading Agent — Project Plan

**Last Updated:** 2026-04-13

## Overview
Fully autonomous Claude-powered trading agent managing a live portfolio via Alpaca. Target: beat the S&P 500 by a meaningful margin through concentrated swing trading in equities, ETFs, and options.

**Current State:** Live trading with $2,500 real capital. Paper trading running in parallel for strategy validation. Running 24/7 on AWS EC2 with a read-only dashboard for monitoring.

## Constraints

- **PDT Rule:** Under $25k equity, limited to 3 day trades per 5 rolling business days. Strategy is swing-oriented (overnight minimum holds) plus options for leverage.
- **Capital:** $2,500 live (transferring additional $4,000 from Fidelity, landing this week)
- **Fractional shares:** Alpaca supports notional orders, but stop-loss orders require whole shares. Fractional positions are managed via cycle-based review.
- **API budget:** ~$0.03/cycle for Claude, ~$2-3/month total. Finnhub free tier (60/min) for earnings calendar.

---

## Strategy — Aggressive Tier (as of 2026-04-13)

After one week of paper trading showed us tracking SPY instead of beating it, the strategy was overhauled to be concentrated, decisive, and conviction-weighted.

### Core Rules
- **Max 6 concurrent positions** — concentrate on best ideas
- **Max 2 positions per sector** — real diversification, not stacked bets
- **Conviction-weighted sizing:**
  - HIGH conviction: 15-20% of portfolio
  - MEDIUM conviction: 8-12%
  - LOW conviction: skip entirely (no mediocre trades)
- **Relative strength requirement:** every buy must be outperforming SPY over the last 10 days
- **Max 40% options exposure** — options are the leverage lever for small accounts
- **Max 3 new positions per day** (PDT stop-loss constraint)

### Hard Exit Rules
- Take 50% profit at halfway to target
- Close any position down 10% from entry (no averaging down)
- Close any position flat (±3%) after 5 days (no dead capital)
- Close any position that hits its initial target
- Close any position whose thesis has broken

### Cycle Modes (3x daily, Mon-Fri)
- **Morning (9:45 AM ET):** Full trading cycle. New entries + exits + rotation.
- **Midday (12:30 PM ET):** Defensive review. Stop adjustments and selective entries.
- **Closing (3:45 PM ET):** Review only. Exits + tomorrow's plan + EOD report.

### Trailing Stops (automated, no Claude involvement)
- +5% gain → raise stop to breakeven
- +10% gain → trail 5% below current
- +20% gain → trail 8% below current (let it run)

---

## Implementation Phases — COMPLETE

### Phase 1: Project Setup & Infrastructure — ✅
- Python project, virtual environment, pyproject.toml
- Alpaca API client (paper + live)
- Anthropic API client with retry on 529/503/429
- Configuration via pydantic-settings from .env files

### Phase 2: Data Layer — ✅
- Market data client (Alpaca): bars, quotes, snapshots, account, positions
- Technical indicators: RSI, MACD, SMA/EMA, Bollinger Bands, ATR, OBV, VWAP, Stoch RSI
- News data pipeline (Alpaca news API)
- Trading universe (S&P 500 + 30 ETFs = 524 symbols)
- Two-tier dynamic screener (Tier 1: price/volume filter, Tier 2: signal scoring + relative strength)
- Options chain data fetcher (Alpaca options API)
- Earnings calendar (Finnhub free tier)
- Sector classification map (295 symbols across 11 sectors)

### Phase 3: Claude Analysis Engine — ✅
- Prompt engineering with cycle-mode awareness (morning/midday/closing)
- Aggressive strategy rules embedded in system prompt
- Structured JSON output parsing with retry
- Cross-cycle context (previous cycles' narratives loaded)
- Two-step options flow: Claude proposes underlying + direction, then selects specific contract from real options chain
- Earnings awareness via upcoming earnings section in prompt

### Phase 4: Portfolio & Risk Management — ✅
- Portfolio state tracker (virtual equity for paper, real for live)
- Risk rules engine with 9 layered checks:
  1. Drawdown circuit breaker (15%)
  2. Max positions cap (6)
  3. Sector concentration (2 per sector)
  4. Catalyst trade size (5% for overnight earnings plays)
  5. Max single position (20%)
  6. Max total exposure (90%)
  7. Max options exposure (40%)
  8. PDT limit warning
  9. Stop-loss required on equity buys
- Position sizing via notional orders (fractional shares)
- Options sizing using real premium data (contracts × premium × 100)
- High watermark persisted to disk
- Trailing stops (automated, tier-based)

### Phase 5: Order Execution — ✅
- Equity: notional market orders (handles fractional shares)
- Options: real contract lookup + OCC symbol order submission
- Stop-loss: automatic after buy fills, with retry on race conditions
- Close: cancels existing stops first to avoid held-quantity errors
- Bracket order fallback when fractional
- Wash trade prevention (cancels opposing stops before buys)

### Phase 6: Orchestration — ✅
- Full cycle loop with per-step error handling
- Cycle modes with different permissions
- Scheduled runs Mon-Fri (3x daily) via schedule library
- systemd services for auto-restart
- Startup connection validation with graceful 529 tolerance
- Dry-run mode for testing

### Phase 7: Logging & Analytics — ✅
- Trade journal (per-trade entry + execution + rejection records)
- Decision log (full Claude analysis per cycle)
- Portfolio snapshots (per-cycle state)
- Daily markdown summaries (appended per cycle)
- End-of-day reports (consolidated daily view with position table, thesis tracking, realized P&L)
- Anomaly log (structured JSONL for every unusual event)
- Performance analyzer (equity curve, Sharpe, win rate, expectancy, alpha)
- Benchmark tracker (SPY return from recorded start)
- Email EOD reports (Gmail SMTP, HTML styled)
- Separate logs per mode (`logs/paper/` vs `logs/live/`)

### Phase 8: Paper Trading & Validation — ✅
- One week of paper trading validated pipeline
- Exposed several bugs: options pricing, stop-loss race, wash trades, screener limit, timezone handling
- Code review surfaced 6 critical/important issues, all fixed
- Baseline performance measured: underperforming SPY by ~4.8% with scatter-shot portfolio → triggered aggressive strategy overhaul

### Phase 9: Live Trading — ✅
- Live account connected, first trades 2026-04-10
- Live runs alongside paper with separate env files, separate logs, same code
- Both services on single EC2 t4g.nano

### Phase 10: Cloud Deployment — ✅
- AWS EC2 instance (us-east-1, Amazon Linux 2023)
- systemd services: trading-agent-live, trading-agent-paper, trading-dashboard
- Auto-restart on crash, auto-start on boot
- Timezone set to America/New_York
- Git-based deployment from dashboard

### Phase 11: Monitoring Dashboard — ✅
- Flask-based read-only web UI on port 8080
- Pages: Overview, Performance, Positions, Reports, History, Cycles, Diagnostics, Controls
- Mode toggle (paper/live) via query param with separate logs
- Live portfolio data from Alpaca + persisted snapshots
- Equity curve chart (Chart.js) with starting capital reference
- Performance stats: win rate, expectancy, profit factor, Sharpe, max drawdown
- Raw alpha vs Deployed alpha (cash-drag-adjusted)
- Anomaly diagnostics with filters and markdown export
- Controls: service management (restart/start/stop), git pull, dependency refresh, manual dry-run cycles
- Self-restart (deferred subprocess to return HTTP response before dying)
- Audit log for control actions

### Phase 12: Feedback Loop — ✅
- Anomaly logger captures every unusual event (rejected signals, stop failures, parse errors, etc.)
- Structured types for easy filtering (signal_rejected, bad_stop_loss, circuit_breaker, etc.)
- Export to markdown for sharing in chat
- Startup validation tolerates transient Anthropic outages (529 retried, not fatal)
- Email alerts via EOD summary (no SMS/webhook alerts yet)

---

## Current Status (2026-04-13)

**What's running live:**
- Live account: $2,500 starting capital, 4-5 positions from week 1
- Paper account: $100k simulated, about to be liquidated for a clean restart with new strategy
- Dashboard at `http://98.94.2.153:8080`
- Email EOD reports delivered daily to paulfrydryk@gmail.com

**Recent changes (today):**
- Strategy overhaul: aggressive tier with 6-position cap, sector limits, conviction sizing, hard exit rules, relative strength filter
- Performance dashboard with equity curve and full stats
- Trailing stops automation
- Alpha calculation split into raw vs deployed

**Outstanding:**
- Paper liquidation and fresh restart (user action)
- $4k Fidelity transfer in progress (2-5 business days)
- Once funds land: update STARTING_CAPITAL to $6,500 in .env.live

---

## Risk Mitigations

1. **Paper-first validation** — every strategy change tested on paper before affecting live
2. **9-layer risk engine** — hard limits Claude cannot bypass
3. **Drawdown circuit breaker** — halt new trades if portfolio drops 15% from peak
4. **PDT protection** — 3 layers (Claude prompt, trade journal check, Alpaca backstop)
5. **Sell-first rotation** — closes processed before new buys, exposure freed in same cycle
6. **Extensive logging** — every decision, rejection, error, and anomaly persisted
7. **Dual email reports** — paper and live delivered separately for side-by-side review
8. **Cloud deployment** — auto-restart, no single point of user-machine failure
9. **Anomaly feedback loop** — structured problem log for rapid iteration
10. **Conservative options use** — premium is max loss, sizing enforced at cycle level

---

## Log Structure

| Path | Format | Purpose | Git-tracked |
|---|---|---|---|
| `logs/{mode}/summaries/*.md` | Markdown | Per-cycle narratives (appended 3x/day) | Yes |
| `logs/{mode}/reports/*.md` | Markdown | End-of-day consolidated report | Yes |
| `logs/{mode}/decisions/*.json` | JSON | Full Claude analysis with raw response | No |
| `logs/{mode}/trades/*.json` | JSON | Per-trade records (opens, closes, rejections) | No |
| `logs/{mode}/portfolio/*.json` | JSON | Per-cycle portfolio snapshots | No |
| `logs/{mode}/errors/*.log` | Log | Error tracebacks with context | No |
| `logs/{mode}/anomalies.jsonl` | JSONL | Structured unusual events | No |
| `logs/{mode}/benchmark.json` | JSON | SPY start price for alpha tracking | No |
| `logs/{mode}/high_watermark.json` | JSON | Peak equity for drawdown tracking | No |
| `logs/controls.log` | Log | Dashboard control action audit | No |
| `docs/decisions/*.md` | Markdown | Architecture decision records | Yes |

---

## Architecture Decisions

See [docs/decisions/](decisions/) for detailed ADRs.

- [001 — Initial design choices](decisions/001_initial_design_choices.md)
- [002 — Error handling and dry-run mode](decisions/002_error_handling_and_dry_run.md)
- [003 — Dynamic screener](decisions/003_dynamic_screener.md)

See [FUTURE_ROADMAP.md](FUTURE_ROADMAP.md) for next-level development ideas.
