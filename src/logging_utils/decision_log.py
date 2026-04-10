"""
Decision log — records every Claude analysis with full prompt and response.
Critical for learning and iterating on the agent's strategy.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.analysis.signals import MarketAnalysis
from src.config import DECISION_LOGS_DIR, Settings

logger = logging.getLogger(__name__)


class DecisionLog:
    """Records every Claude analysis cycle for review and learning."""

    def __init__(self, settings: Settings | None = None):
        self._dir = settings.decision_logs_dir if settings else DECISION_LOGS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def log_analysis(
        self,
        analysis: MarketAnalysis,
        portfolio_state: dict,
        execution_results: list[dict] | None = None,
    ) -> Path:
        """
        Log a complete analysis cycle.

        Records Claude's analysis, what the portfolio looked like when the
        decision was made, and what actions were actually taken.
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "market_regime": analysis.market_regime,
            "regime_confidence": analysis.regime_confidence,
            "key_observations": analysis.key_observations,
            "sector_outlook": analysis.sector_outlook,
            "num_signals": len(analysis.trade_signals),
            "signals": [s.model_dump() for s in analysis.trade_signals],
            "positions_to_close": analysis.positions_to_close,
            "portfolio_state": {
                "equity": portfolio_state.get("equity"),
                "cash": portfolio_state.get("cash"),
                "exposure_pct": portfolio_state.get("exposure_pct"),
                "drawdown_pct": portfolio_state.get("drawdown_pct"),
                "num_positions": portfolio_state.get("num_positions"),
            },
            "execution_results": execution_results or [],
            "raw_claude_response": analysis.raw_analysis,
        }

        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        filepath = self._dir / f"{date_str}_{time_str}_analysis.json"

        with open(filepath, "w") as f:
            json.dump(entry, f, indent=2, default=str)

        logger.info(
            "Decision logged: regime=%s, signals=%d, path=%s",
            analysis.market_regime,
            len(analysis.trade_signals),
            filepath.name,
        )
        return filepath
