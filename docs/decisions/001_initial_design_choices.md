# ADR-001: Initial Design Choices

**Date:** 2026-04-02
**Status:** Accepted

## Context
Starting a new project to build an autonomous Claude-powered trading agent with $1000 capital.

## Decisions

### Brokerage: Alpaca
- Commission-free equities and options
- Excellent API (REST + WebSocket)
- Built-in paper trading environment
- Options support for small accounts

### Strategy: Swing Trading + Short-Term Options
- PDT rule (3 day trades per 5 business days) prevents day trading under $25k
- Swing trades hold overnight minimum, avoiding PDT entirely
- Options provide leverage on small capital with defined risk
- Options can profit in sideways markets (selling premium)

### Assets: US Equities, ETFs, Options
- Equities and ETFs for swing trading core positions
- Options for leveraged plays and income generation
- Starting with single-leg options, expanding to spreads once proven

### Autonomy: Fully Autonomous
- Claude makes all trading decisions without human approval
- Risk management rules are hard-coded guardrails Claude cannot override
- Full logging enables post-hoc review and iterative improvement

### Language: Python
- Best finance library ecosystem
- First-party SDKs for both Alpaca and Anthropic
- Fast iteration speed

## Consequences
- Must build robust risk management (no human safety net)
- Must paper trade extensively before going live
- Must log everything for learning and accountability
- PDT constraint shapes strategy toward multi-day holds
- Small capital ($1000) limits position diversity — need careful sizing
