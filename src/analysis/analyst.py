"""
Claude analysis engine — constructs prompts, calls Claude, and parses structured trade signals.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import anthropic

from src.analysis.signals import MarketAnalysis
from src.config import Settings, get_summary_dir

logger = logging.getLogger(__name__)


class ClaudeAnalyst:
    """Uses Claude to analyze market data and generate trade signals."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = anthropic.Anthropic(api_key=settings.claude.anthropic_api_key)
        self._model = settings.claude.claude_model

    def analyze_market(
        self,
        account_info: dict,
        positions: list[dict],
        watchlist_data: dict[str, dict],
        market_news: list[dict],
        symbol_news: dict[str, list[dict]],
        cycle_mode: str = "morning",
        open_stops: dict[str, dict] | None = None,
        earnings_data: dict[str, dict] | None = None,
    ) -> MarketAnalysis:
        """
        Run a full market analysis cycle.

        Args:
            account_info: Current account state (equity, cash, buying power)
            positions: Current open positions with P&L
            watchlist_data: Dict of symbol -> {bars, indicators, quote} for each watchlist symbol
            market_news: Recent general market news
            symbol_news: Dict of symbol -> news articles
            cycle_mode: "morning", "midday", or "closing"
            open_stops: Dict of symbol -> {stop_price, qty} for existing stop orders
        """
        prompt = self._build_analysis_prompt(
            account_info=account_info,
            positions=positions,
            watchlist_data=watchlist_data,
            market_news=market_news,
            symbol_news=symbol_news,
            cycle_mode=cycle_mode,
            open_stops=open_stops or {},
            earnings_data=earnings_data or {},
        )

        logger.info("Sending analysis request to Claude (%s, %s mode)", self._model, cycle_mode)

        response = self._call_with_retry(
            model=self._model,
            max_tokens=4096,
            system=self._system_prompt(cycle_mode),
            messages=[{"role": "user", "content": prompt}],
        )

        raw_response = response.content[0].text
        logger.info("Received analysis response (%d chars)", len(raw_response))

        analysis = self._parse_response(raw_response)
        return analysis

    def _call_with_retry(self, **kwargs):
        """
        Call Claude's messages API with retry on transient failures.

        Retries on:
        - 529 Overloaded (Anthropic servers at capacity)
        - 503 Service Unavailable
        - Connection errors / timeouts

        Does NOT retry on:
        - 400 Bad Request (malformed input — won't get better)
        - 401 Unauthorized (bad API key)
        - 402 Payment Required (out of credits)
        """
        import time
        max_attempts = 4
        base_delay = 15  # seconds

        for attempt in range(max_attempts):
            try:
                return self._client.messages.create(**kwargs)
            except anthropic.APIStatusError as e:
                # Check if it's retryable
                status = getattr(e, "status_code", None)
                is_overloaded = status == 529 or "overloaded" in str(e).lower()
                is_unavailable = status == 503
                is_rate_limit = status == 429
                retryable = is_overloaded or is_unavailable or is_rate_limit

                if retryable and attempt < max_attempts - 1:
                    # Exponential backoff: 15s, 30s, 60s
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Claude API %s (status=%s). Retrying in %ds (attempt %d/%d)",
                        "overloaded" if is_overloaded else "unavailable",
                        status, delay, attempt + 1, max_attempts,
                    )
                    time.sleep(delay)
                    continue
                raise
            except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
                if attempt < max_attempts - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Claude API connection error: %s. Retrying in %ds (attempt %d/%d)",
                        e, delay, attempt + 1, max_attempts,
                    )
                    time.sleep(delay)
                    continue
                raise

        # Should not reach here, but just in case
        raise RuntimeError("Claude API retry loop exhausted without success")

    def _system_prompt(self, cycle_mode: str = "morning") -> str:
        risk = self.settings.risk

        mode_instructions = {
            "morning": (
                "CYCLE MODE: MORNING — Full trading cycle.\n"
                "- Analyze market conditions and all watchlist symbols\n"
                "- Propose new entries where setups are strong\n"
                "- Review existing positions — adjust stops or close if thesis is broken\n"
                "- This is the primary decision-making cycle of the day"
            ),
            "midday": (
                "CYCLE MODE: MIDDAY — Defensive check.\n"
                "- Focus on managing existing positions (stop adjustments, exits)\n"
                "- Only propose new entries if there's a compelling catalyst (breaking news, major move)\n"
                "- Be more selective than the morning cycle"
            ),
            "closing": (
                "CYCLE MODE: CLOSING — End-of-day review and catalyst entries.\n"
                "- Review existing positions: should any be closed before overnight hold?\n"
                "- Summarize the day's market action and what to watch for tomorrow\n"
                "- Include observations that should inform tomorrow's morning analysis\n"
                "- Add a 'tomorrow_watchlist' note in key_observations for morning follow-up\n"
                "\n"
                "CATALYST ENTRIES (closing cycle only):\n"
                "- You MAY open NEW positions if there is a specific overnight catalyst:\n"
                "  earnings reports, FDA decisions, product launches, major policy announcements\n"
                "- Catalyst trades MUST set is_catalyst_trade=true and describe the catalyst\n"
                "- Max position size for catalyst trades: 5% (NOT the normal 15%)\n"
                "- Options are ideal for catalyst plays — defined risk for binary events\n"
                "- If no catalysts exist, do NOT force entries. Closing cycle without catalysts = review only.\n"
                "- Regular (non-catalyst) buy signals will be REJECTED in closing mode"
            ),
        }

        return f"""You are an autonomous trading agent managing a real portfolio. Your job is to analyze market conditions and generate actionable trade signals.

{mode_instructions.get(cycle_mode, mode_instructions["morning"])}

PORTFOLIO RULES:
- Max position size: {risk.max_position_pct:.0%} of portfolio
- Max total exposure: {risk.max_total_exposure_pct:.0%} of portfolio
- IF current exposure_pct > {risk.max_total_exposure_pct:.0%}: YOUR TOP PRIORITY is to close positions to get back under the cap. Identify the weakest positions (worst R/R, broken thesis, smallest gains, or losses) and add them to positions_to_close. Do NOT propose new buys until exposure is back under the cap. Negative cash = over-leveraged = unacceptable risk.
- Max options exposure: {risk.max_options_exposure_pct:.0%} of portfolio
- Default stop-loss: {risk.stop_loss_default_pct:.0%}
- PDT limit: {risk.max_day_trades} day trades per 5 rolling business days (NEVER propose selling a position that was opened today — this counts as a day trade)
- Max drawdown circuit breaker: {risk.max_drawdown_pct:.0%}

STRATEGY — AGGRESSIVE, CONCENTRATED, DECISIVE:
Your goal is to BEAT the S&P 500 by a meaningful margin, not match it. Matching the market is a failure. Be bold, selective, and willing to concentrate capital on your best ideas.

CORE PRINCIPLES:
1. **Quality over quantity.** Max {risk.max_total_positions} concurrent positions. Fewer, bigger bets on the strongest setups. Scatter-shot diversification is a loser's game on a small account.
2. **Conviction dictates size.** Reward certainty:
   - HIGH conviction: 15-20% of portfolio (this is how you beat the market)
   - MEDIUM conviction: 8-12% (decent setups you believe in)
   - LOW conviction: DO NOT TAKE THE TRADE. Skip it. Don't force trades you're not sure about.
3. **Relative strength only.** Every new buy must be OUTPERFORMING SPY over the last 5-10 days. If a stock is just rising with the market, it's not giving you alpha — it's giving you beta. Don't pay for beta.
4. **Rotate ruthlessly.** If a new idea is clearly stronger than one of your current positions, close the weak one and open the new one in the same cycle. Don't hold weak positions out of inertia.
5. **Take profits, don't wait for perfect exits.** See EXIT RULES below.

REGIME-DRIVEN AGGRESSION (deploy capital based on opportunity, not fear):
- **Bull regime, HIGH conviction setups exist**: 80-90% deployed in 4-6 positions. Push hard.
- **Bull regime, only MEDIUM setups**: 50-70% deployed. Be picky.
- **Sideways**: 40-60% deployed. Selective, defensive positioning.
- **Volatile**: 30-50% deployed. Smaller positions, mandatory hedges, options for defined risk.
- **Bear**: 10-30% deployed. Mostly cash. Short-term trades only, or long puts/inverse ETFs.

EXIT RULES — HARD (non-negotiable, even if your thesis still "feels right"):
- **Take 50% profit at halfway-to-target.** If entry $100, target $120, stop $92: when price hits $110 (halfway), close HALF of the position. Let the rest run with a trailing stop.
- **Close any position down 10% from entry.** No hoping, no averaging down. The thesis was wrong.
- **Close any position flat (within ±3%) after 5 days.** Capital tied up in a non-mover is wasted. Rotate.
- **Close any position that hit its initial target.** Don't get greedy waiting for more — take the win, redeploy.
- **Close any position whose thesis has broken.** News reversal, sector rotation, chart breakdown. Be decisive.

POSITION ROTATION (use this aggressively):
- Every cycle, rank your existing positions vs screener candidates. Ask: "If I had cash, would I buy this current position today?" If no, close it.
- Rotation candidates (close these first when making room): losers, flat positions, weak technicals, positions where a better opportunity exists.
- Use positions_to_close and trade_signals together — closes free up room for the new entry in the same cycle.

OPTIONS STRATEGY — USE THEM FOR LEVERAGE (Level 3 approved):
- Options should be 20-30% of portfolio, not an afterthought. Max 40%.
- **High-conviction bullish calls**: Buy calls instead of equity when you want leverage. Example: Strong bull setup on NVDA, instead of buying $400 of equity, buy a $300 call that gives you $3,000+ of exposure if NVDA moves 5%.
- **Defined-risk earnings plays**: Catalyst trades via options give you upside without overnight blowup risk.
- **Hedges**: Long puts when you're worried about a pullback but want to stay deployed.
- When proposing options: include strike_price, expiration_date (YYYY-MM-DD, 2-6 weeks out), option_type ("call" or "put").
- Prefer near-the-money strikes (within 5% of current) for directional bets. Go slightly OTM for cheaper leverage on high-conviction trades.

EARNINGS AWARENESS:
- Check the UPCOMING EARNINGS section every cycle.
- Never open a new swing position that would be held through an earnings report unless it's a deliberate catalyst trade (is_catalyst_trade=true).
- For existing positions with earnings coming: decide EXPLICITLY to exit before, or explicitly hold through with a stated rationale in your cycle summary.

DAILY POSITION LIMIT (PDT constraint):
- Max {risk.max_new_positions_per_day} NEW positions per day (equities + options combined).
- You do NOT have to use all 3 slots. Zero new positions is acceptable if nothing meets your bar. Mediocre setups waste slots.
- If you only have 1 HIGH-conviction idea, take just that one. Size it big.
- Consider ALL candidates together (equities + options). Rank by quality. Only the top 3 make the cut.
- Sells and closes don't count against this limit.

SECTOR DIVERSIFICATION:
- Max {risk.max_positions_per_sector} positions per sector (financials, technology, energy, etc.)
- 3 bank stocks = 1 concentrated bet on financials, not 3 diversified positions.
- Mix sectors to get real diversification.

OPTIONS PRICING AND SIZING (CRITICAL):
- Options contracts represent 100 shares. A contract quoted at $5 premium costs $500 total ($5 × 100).
- On-the-money (ATM) options for liquid stocks typically cost 1-3% of the underlying price. Example: NVDA at $180 → ATM calls roughly $2-6 premium = $200-600 per contract.
- The system will automatically size the number of contracts based on your position_size_pct and the live premium quote.
- If the premium is too high to afford even 1 contract at your size, the trade will be skipped.
- For small accounts, consider: slightly OTM options (cheaper), longer dated for lower time decay risk, or avoid expensive stocks where even 1 contract exceeds your sizing.
- Set position_size_pct that would allow AT LEAST 1 contract — for a $2500 account, 5-10% ($125-250) works for most liquid options.

RESPONSE FORMAT:
You must respond with valid JSON matching this schema:
{{
    "market_regime": "bull|bear|sideways|volatile",
    "regime_confidence": "low|medium|high",
    "market_summary": "2-3 sentence narrative: What is the market doing right now? What is your thought process this cycle? Why are you taking action or choosing to hold? Be specific about your reasoning.",
    "key_observations": ["observation 1", "observation 2"],
    "sector_outlook": {{"Technology": "bullish", "Energy": "neutral"}},
    "trade_signals": [
        {{
            "symbol": "AAPL",
            "action": "buy|sell|hold|buy_call|buy_put|sell_call|sell_put",
            "conviction": "low|medium|high",
            "target_price": 150.00,
            "stop_loss_price": 140.00,
            "position_size_pct": 0.10,
            "rationale": "Why this trade makes sense",
            "time_horizon": "3-5 days",
            "risk_reward_ratio": 2.5,
            "is_catalyst_trade": false,
            "catalyst": null,
            "strike_price": null,
            "expiration_date": null,
            "option_type": null
        }}
    ],
    "positions_to_close": ["SYMBOL1"],
    "stop_adjustments": {{"SYMBOL1": 145.00}}
}}

STOP-LOSS MANAGEMENT:
- Check "current_stop_loss" in each position.
- If a position shows "NONE — needs stop set", include it in stop_adjustments.
- If a position shows "FRACTIONAL POSITION", do NOT include it in stop_adjustments (the broker can't set stops on fractional shares). These require manual monitoring:
  - **REQUIRED: If a fractional position's unrealized_plpc is <= -{risk.stop_loss_default_pct:.0%}, you MUST propose a SELL signal for it in trade_signals this cycle.** This is the software equivalent of a stop-loss trigger for fractional positions.
  - Check every fractional position's P&L% each cycle and act on it. Do not let a fractional position run past the stop threshold — close it.
  - If the original buy had a specific stop_loss_price set, use that level instead of the default percentage when deciding to exit.
- You can tighten stops (raise them) on winning positions to lock in profits.
- You can adjust stops based on new support levels or changed thesis.
- stop_adjustments is a dict of symbol -> new stop price.

Be decisive but disciplined. Every trade must have a clear rationale and exit plan."""

    def _build_analysis_prompt(
        self,
        account_info: dict,
        positions: list[dict],
        watchlist_data: dict[str, dict],
        market_news: list[dict],
        symbol_news: dict[str, list[dict]],
        cycle_mode: str = "morning",
        open_stops: dict[str, dict] | None = None,
        earnings_data: dict[str, dict] | None = None,
    ) -> str:
        sections = []

        # Account overview
        sections.append("## ACCOUNT STATUS")
        sections.append(json.dumps(account_info, indent=2, default=str))

        # Current positions with stop-loss info
        sections.append("\n## CURRENT POSITIONS")
        if positions:
            import math
            for p in positions:
                sym = p["symbol"]
                qty = p.get("qty", 0)
                stop_info = open_stops.get(sym, {}) if open_stops else {}
                p_display = {**p}
                if stop_info:
                    p_display["current_stop_loss"] = stop_info.get("stop_price")
                elif math.floor(qty) < 1:
                    p_display["current_stop_loss"] = "FRACTIONAL POSITION — cannot set Alpaca stop order. You manage this position via sell signals if it needs to be exited."
                else:
                    p_display["current_stop_loss"] = "NONE — needs stop set via stop_adjustments"
                sections.append(json.dumps(p_display, indent=2, default=str))
        else:
            sections.append("No open positions.")

        # Watchlist analysis
        sections.append("\n## WATCHLIST DATA")
        for symbol, data in watchlist_data.items():
            sections.append(f"\n### {symbol}")
            if "indicators" in data:
                sections.append("Technical Indicators:")
                sections.append(json.dumps(data["indicators"], indent=2, default=str))
            if "quote" in data:
                sections.append(f"Latest Quote: {json.dumps(data['quote'], default=str)}")

        # Upcoming earnings (next 14 days) — critical for holding/exit decisions
        if earnings_data:
            sections.append("\n## UPCOMING EARNINGS (next 14 days)")
            sections.append(
                "These symbols have earnings reports coming. Earnings are binary events "
                "that can move the stock 10-20% overnight. For current HOLDINGS, decide "
                "whether to exit before the report or explicitly hold as a catalyst play. "
                "For NEW buys, avoid opening a position that would hold through earnings "
                "unless you explicitly flag it as a catalyst trade."
            )
            # Sort by days away
            sorted_earnings = sorted(earnings_data.items(), key=lambda x: x[1].get("days_away", 999))
            for sym, info in sorted_earnings:
                days = info.get("days_away", "?")
                hour = info.get("hour", "")
                hour_label = {"bmo": "before market open", "amc": "after market close", "dmh": "during market hours"}.get(hour, "time TBD")
                eps = info.get("eps_estimate")
                eps_str = f", EPS est ${eps:.2f}" if eps else ""
                is_held = any(p.get("symbol") == sym for p in positions)
                held_marker = " [CURRENTLY HELD]" if is_held else ""
                sections.append(
                    f"- **{sym}**{held_marker}: reports in {days} day(s) ({info.get('date')}, {hour_label}){eps_str}"
                )

        # News
        sections.append("\n## MARKET NEWS")
        for article in market_news[:10]:
            sections.append(f"- [{article['source']}] {article['headline']}")
            if article.get("summary"):
                sections.append(f"  {article['summary'][:200]}")

        for symbol, articles in symbol_news.items():
            if articles:
                sections.append(f"\n### {symbol} News")
                for article in articles[:5]:
                    sections.append(f"- {article['headline']}")

        # Previous context from today's earlier cycles
        prior_context = self._load_prior_context()
        if prior_context:
            sections.append("\n## PREVIOUS ANALYSIS TODAY")
            sections.append("You made the following assessments earlier today. "
                          "Stay consistent unless new data warrants a change. "
                          "Do NOT re-buy positions you already opened today.")
            sections.append(prior_context)

        sections.append(
            "\n## INSTRUCTIONS"
            "\nAnalyze the above data and provide your trading recommendations."
            "\nRespond with JSON only — no markdown, no commentary outside the JSON."
        )

        return "\n".join(sections)

    def select_option_contract(
        self,
        symbol: str,
        option_type: str,
        chain: list[dict],
        original_rationale: str,
        budget: float,
    ) -> dict | None:
        """
        Ask Claude to select the best option contract from a chain.

        Args:
            symbol: Underlying symbol
            option_type: "call" or "put"
            chain: List of contract dicts from OptionsChainClient
            original_rationale: Claude's original trade rationale
            budget: Dollar budget for this trade

        Returns:
            Dict with selected contract details, or None if no good option found.
        """
        if not chain:
            return None

        affordable = [c for c in chain if c["affordable"]]
        if not affordable:
            logger.info("No affordable contracts in chain for %s (budget $%.2f)", symbol, budget)
            return None

        prompt = f"""You proposed a {option_type} option on {symbol}. Here is your original rationale:

"{original_rationale}"

Budget: ${budget:.2f} (max you can spend on this trade)

Below is the real options chain with live quotes. Select the BEST contract considering:
1. Strike selection must align with your thesis — don't just pick the cheapest
2. Prefer strikes with good liquidity (tight bid-ask spread)
3. Balance intrinsic vs time value — pure OTM options are cheaper but riskier
4. Consider days to expiry — too short = theta decay, too long = expensive
5. The contract MUST be affordable (cost_per_contract <= ${budget:.2f})

AVAILABLE CONTRACTS (affordable ones marked with *):
"""
        for c in chain:
            marker = "* " if c["affordable"] else "  "
            prompt += (
                f"{marker}{c['occ_symbol']}: strike=${c['strike']:.2f}, "
                f"exp={c['expiration']} ({c['days_to_expiry']}d), "
                f"bid=${c['bid']:.2f}, ask=${c['ask']:.2f}, "
                f"cost/contract=${c['cost_per_contract']:.2f}, "
                f"intrinsic=${c['intrinsic_value']:.2f}, "
                f"time_value=${c['time_value']:.2f}\n"
            )

        prompt += """
Respond with ONLY valid JSON:
{
    "selected_symbol": "OCC_SYMBOL_HERE",
    "strike": 105.00,
    "expiration": "2026-05-15",
    "rationale": "Why this specific strike and expiry is best for the thesis. Be specific about why this strike over others."
}

If none of the affordable contracts are a good fit for your thesis, respond with:
{"selected_symbol": null, "rationale": "Why no contract works"}
"""

        try:
            response = self._call_with_retry(
                model=self._model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]

            data = json.loads(text.strip())

            if not data.get("selected_symbol"):
                logger.info("Claude declined options for %s: %s", symbol, data.get("rationale"))
                return None

            # Find the selected contract in the chain
            selected = next((c for c in chain if c["occ_symbol"] == data["selected_symbol"]), None)
            if not selected:
                logger.warning("Claude selected unknown contract: %s", data["selected_symbol"])
                return None

            if not selected["affordable"]:
                logger.warning("Claude selected unaffordable contract: %s ($%.2f > $%.2f)",
                    selected["occ_symbol"], selected["cost_per_contract"], budget)
                return None

            selected["selection_rationale"] = data.get("rationale", "")
            logger.info(
                "Claude selected %s (strike=$%.2f, exp=%s, cost=$%.2f): %s",
                selected["occ_symbol"], selected["strike"], selected["expiration"],
                selected["cost_per_contract"], data.get("rationale", "")[:100],
            )
            return selected

        except Exception as e:
            logger.error("Option contract selection failed for %s: %s", symbol, e)
            return None

    def _load_prior_context(self) -> str | None:
        """
        Load today's earlier analysis summaries so Claude has continuity.
        Returns the markdown content of today's summary, or None if no prior cycles.
        """
        summary_dir = get_summary_dir(self.settings.trading_mode)
        today_file = summary_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"

        if not today_file.exists():
            return None

        try:
            content = today_file.read_text(encoding="utf-8", errors="replace")
            # Keep all cycles from today so Claude remembers morning decisions
            # at the closing cycle. Limit to ~6000 chars to manage token cost
            # (3 cycles × ~1500 chars each = ~4500, with header ~5000 total)
            if len(content) > 6000:
                # Keep the header and trim the oldest observations, not whole cycles
                content = content[:6000] + "\n\n[...earlier details truncated...]\n"
            return content.strip()
        except Exception as e:
            logger.warning("Failed to load prior context: %s", e)
            return None

    def _parse_response(self, raw_response: str) -> MarketAnalysis:
        """Parse Claude's JSON response into a MarketAnalysis object."""
        # Strip any markdown code fences if present
        text = raw_response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        data = json.loads(text)
        data["raw_analysis"] = raw_response
        return MarketAnalysis(**data)
