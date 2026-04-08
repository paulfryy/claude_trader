"""
Configuration management for the trading agent.
Loads settings from environment variables with sensible defaults.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Logs directories
LOGS_DIR = PROJECT_ROOT / "logs"
TRADE_LOGS_DIR = LOGS_DIR / "trades"
DECISION_LOGS_DIR = LOGS_DIR / "decisions"
PORTFOLIO_LOGS_DIR = LOGS_DIR / "portfolio"
ERROR_LOGS_DIR = LOGS_DIR / "errors"


_ENV_FILE = PROJECT_ROOT / ".env"
_ENV_COMMON = {"env_file": _ENV_FILE, "env_file_encoding": "utf-8", "extra": "ignore"}


class AlpacaSettings(BaseSettings):
    model_config = {**_ENV_COMMON, "env_prefix": "ALPACA_"}

    api_key: str = ""
    secret_key: str = ""
    trading_mode: str = "paper"  # "paper" or "live"

    @property
    def base_url(self) -> str:
        if self.trading_mode == "live":
            return "https://api.alpaca.markets"
        return "https://paper-api.alpaca.markets"

    @property
    def data_url(self) -> str:
        return "https://data.alpaca.markets"


class ClaudeSettings(BaseSettings):
    model_config = {**_ENV_COMMON, "env_prefix": ""}

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"


class RiskSettings(BaseSettings):
    model_config = {**_ENV_COMMON, "env_prefix": ""}

    max_position_pct: float = Field(default=0.15, description="Max % of portfolio in one position")
    max_catalyst_position_pct: float = Field(default=0.05, description="Max % for catalyst/overnight trades")
    max_total_exposure_pct: float = Field(default=0.90, description="Max % of portfolio deployed")
    max_options_exposure_pct: float = Field(default=0.30, description="Max % in options")
    max_drawdown_pct: float = Field(default=0.15, description="Halt if portfolio drops this %")
    stop_loss_default_pct: float = Field(default=0.08, description="Default stop-loss %")
    max_day_trades: int = Field(default=3, description="PDT limit per 5 rolling business days")


class Settings(BaseSettings):
    model_config = {**_ENV_COMMON}

    log_level: str = "INFO"
    starting_capital: float = 1000.0

    alpaca: AlpacaSettings = Field(default_factory=AlpacaSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)

    @property
    def is_paper(self) -> bool:
        return self.alpaca.trading_mode == "paper"


def load_settings() -> Settings:
    """Load and return application settings."""
    return Settings()
