"""
Claude analysis engine — constructs prompts, calls Claude, and parses structured trade signals.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import anthropic

from src.analysis.signals import MarketAnalysis
from src.config import LOGS_DIR, Settings

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
        )

        logger.info("Sending analysis request to Claude (%s, %s mode)", self._model, cycle_mode)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=self._system_prompt(cycle_mode),
            messages=[{"role": "user", "content": prompt}],
        )

        raw_response = response.content[0].text
        logger.info("Received analysis response (%d chars)", len(raw_response))

        analysis = self._parse_response(raw_response)
        return analysis

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
- Max options exposure: {risk.max_options_exposure_pct:.0%} of portfolio
- Default stop-loss: {risk.stop_loss_default_pct:.0%}
- PDT limit: {risk.max_day_trades} day trades per 5 rolling business days (NEVER propose selling a position that was opened today — this counts as a day trade)
- Max drawdown circuit breaker: {risk.max_drawdown_pct:.0%}

STRATEGY:
- Swing trading US equities and ETFs (hold 2-14 days typically)
- Focus on high-probability setups with favorable risk/reward (>2:1)
- Preserve capital — don't force trades when conditions are unclear
- Actively look for opportunities to deploy idle cash. Having 40%+ cash is underutilized — find setups worth entering. It's better to be 70-90% deployed in good setups than sitting on cash.
- You CAN and SHOULD open new positions in symbols you don't already hold if the setup is good, even if you opened other positions earlier today.

POSITION ROTATION (important):
- If you see a better opportunity but the portfolio is near the 90% exposure cap, close a weaker position to make room for the stronger one.
- Use positions_to_close alongside trade_signals in the same response — closes are processed first, so the freed exposure is available for the new buys.
- Compare your existing positions to the screener candidates. Ask yourself: "Is my worst current position a better bet than the best new candidate?" If not, rotate.
- Rotation candidates: positions below your entry, positions with weakening technicals, positions where the original thesis is broken, positions approaching their time horizon without gains.
- Do not rotate for the sake of rotating — only swap when the new idea is clearly stronger than the existing one (higher conviction, better risk/reward, stronger technicals).

OPTIONS STRATEGY (Level 3 approved — you CAN trade options):
- Use options for 10-20% of the portfolio. Mix equity and options positions.
- Buy calls when you're bullish on a stock but want leveraged upside with defined risk
- Buy puts as hedges against portfolio downside or to profit from bearish setups
- Options are especially useful for: expensive stocks where equity positions would be too large, hedging existing positions, high-conviction directional bets
- When proposing options, you MUST include: strike_price, expiration_date (YYYY-MM-DD, pick the nearest monthly expiry), option_type ("call" or "put")
- Prefer options with 2-4 weeks to expiry and strikes near the money (within 5% of current price)
- Each options position: 5-10% of portfolio (the premium IS your max loss)

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
- If a position shows "FRACTIONAL POSITION", do NOT include it in stop_adjustments (the broker can't set stops on fractional shares). Instead, if you want to exit it, use a sell signal in trade_signals.
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

    def _load_prior_context(self) -> str | None:
        """
        Load today's earlier analysis summaries so Claude has continuity.
        Returns the markdown content of today's summary, or None if no prior cycles.
        """
        summary_dir = LOGS_DIR / "summaries"
        today_file = summary_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"

        if not today_file.exists():
            return None

        try:
            content = today_file.read_text(encoding="utf-8", errors="replace")
            # Trim if too long — keep under ~2000 chars to save tokens
            if len(content) > 3000:
                # Keep the header and the most recent cycle
                sections = content.split("---")
                # Header + last 2 sections (most recent cycle + trailing)
                if len(sections) >= 3:
                    content = sections[0] + "---" + "---".join(sections[-3:])
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
