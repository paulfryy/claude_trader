# ADR-002: Error Handling, Startup Validation, and Dry-Run Mode

**Date:** 2026-04-03
**Status:** Accepted

## Context
Before the first live paper trading run on Monday 2026-04-06, we needed confidence that:
1. The scheduler won't crash and die silently from a single bad cycle
2. We'll know immediately at startup if API keys are wrong or services are down
3. We can test the full pipeline end-to-end without waiting for market hours

## Decisions

### Error Handling Strategy
- **Per-step try/except in orchestrator**: Each major step (portfolio fetch, data fetch, Claude analysis, order execution) is individually wrapped. A failure in one step doesn't prevent logging of what succeeded.
- **Non-critical vs critical failures**: News fetch failures log a warning and continue (analysis can work without news). Portfolio fetch or Claude analysis failures abort the cycle (can't trade without data).
- **Error logging to disk**: Every caught exception writes a full traceback to `logs/errors/` with timestamp and context. This persists even if the console output is lost.
- **Scheduler survival**: `_safe_run_cycle()` wraps every scheduled call in a blanket try/except. The scheduler will never die from a cycle failure.

### Startup Validation
- On scheduler boot, validate both Alpaca and Anthropic connections with real API calls
- If either fails, exit immediately with a clear error — don't schedule and wait
- This catches stale API keys, expired credits, network issues before they waste time

### Dry-Run Mode
- `--dry-run` flag on the orchestrator runs the full pipeline but replaces order submission with logging
- Bypasses the market-hours check so it can run anytime
- Produces the same logs and daily summary as a real run
- Allows end-to-end testing over weekends and after hours

## Consequences
- The agent is safe to leave running unattended — it won't silently die
- We can always inspect `logs/errors/` to understand what went wrong
- Dry-run mode enables testing without market dependency
- The startup check adds ~3 seconds to scheduler boot (one Anthropic API call) — acceptable tradeoff
