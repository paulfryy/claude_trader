"""
Configuration management for the trading agent.
Loads settings from environment variables with sensible defaults.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Base logs directory — paper and live have separate subdirectories
LOGS_BASE = PROJECT_ROOT / "logs"


def get_logs_dir(mode: str = "paper") -> Path:
    """Get the logs directory for a given trading mode."""
    return LOGS_BASE / mode


def get_trade_logs_dir(mode: str = "paper") -> Path:
    return get_logs_dir(mode) / "trades"


def get_decision_logs_dir(mode: str = "paper") -> Path:
    return get_logs_dir(mode) / "decisions"


def get_portfolio_logs_dir(mode: str = "paper") -> Path:
    return get_logs_dir(mode) / "portfolio"


def get_error_logs_dir(mode: str = "paper") -> Path:
    return get_logs_dir(mode) / "errors"


def get_summary_dir(mode: str = "paper") -> Path:
    return get_logs_dir(mode) / "summaries"


# Legacy constants — point to paper by default for backwards compatibility
LOGS_DIR = get_logs_dir("paper")
TRADE_LOGS_DIR = get_trade_logs_dir("paper")
DECISION_LOGS_DIR = get_decision_logs_dir("paper")
PORTFOLIO_LOGS_DIR = get_portfolio_logs_dir("paper")
ERROR_LOGS_DIR = get_error_logs_dir("paper")


_ENV_FILE = PROJECT_ROOT / ".env"
_ENV_COMMON = {"env_file": _ENV_FILE, "env_file_encoding": "utf-8", "extra": "ignore"}

# Can be overridden by load_settings(env_file=...) for paper/live separation
_active_env_file = _ENV_FILE


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
    finnhub_api_key: str = ""  # Optional — for earnings calendar


class RiskSettings(BaseSettings):
    model_config = {**_ENV_COMMON, "env_prefix": ""}

    max_position_pct: float = Field(default=0.20, description="Max % of portfolio in one position (high conviction)")
    max_catalyst_position_pct: float = Field(default=0.05, description="Max % for catalyst/overnight trades")
    max_total_exposure_pct: float = Field(default=0.90, description="Max % of portfolio deployed")
    max_options_exposure_pct: float = Field(default=0.40, description="Max % in options")
    max_drawdown_pct: float = Field(default=0.15, description="Halt if portfolio drops this %")
    stop_loss_default_pct: float = Field(default=0.08, description="Default stop-loss %")
    max_day_trades: int = Field(default=3, description="PDT limit per 5 rolling business days")
    max_new_positions_per_day: int = Field(default=3, description="Max new positions opened per day — ensures every position gets a stop-loss")
    max_total_positions: int = Field(default=6, description="Max concurrent positions — concentrate on best setups")
    max_positions_per_sector: int = Field(default=2, description="Max positions in a single sector to avoid concentration")


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

    @property
    def trading_mode(self) -> str:
        return self.alpaca.trading_mode

    @property
    def logs_dir(self) -> Path:
        return get_logs_dir(self.trading_mode)

    @property
    def trade_logs_dir(self) -> Path:
        return get_trade_logs_dir(self.trading_mode)

    @property
    def decision_logs_dir(self) -> Path:
        return get_decision_logs_dir(self.trading_mode)

    @property
    def portfolio_logs_dir(self) -> Path:
        return get_portfolio_logs_dir(self.trading_mode)

    @property
    def error_logs_dir(self) -> Path:
        return get_error_logs_dir(self.trading_mode)

    @property
    def summary_dir(self) -> Path:
        return get_summary_dir(self.trading_mode)


def load_settings(env_file: str | Path | None = None) -> Settings:
    """
    Load and return application settings.

    Args:
        env_file: Path to .env file. If None, uses default .env.
                  Use .env.paper or .env.live for simultaneous operation.
    """
    if env_file is not None:
        env_path = Path(env_file) if not isinstance(env_file, Path) else env_file
        if not env_path.is_absolute():
            env_path = PROJECT_ROOT / env_path

        # Override the env file for all sub-settings
        global _active_env_file
        _active_env_file = env_path

        # Reload settings classes with the new env file
        common = {"env_file": env_path, "env_file_encoding": "utf-8", "extra": "ignore"}

        class _Alpaca(AlpacaSettings):
            model_config = {**common, "env_prefix": "ALPACA_"}

        class _Claude(ClaudeSettings):
            model_config = {**common, "env_prefix": ""}

        class _Risk(RiskSettings):
            model_config = {**common, "env_prefix": ""}

        class _Settings(Settings):
            model_config = {**common}
            alpaca: AlpacaSettings = Field(default_factory=_Alpaca)
            claude: ClaudeSettings = Field(default_factory=_Claude)
            risk: RiskSettings = Field(default_factory=_Risk)

        return _Settings()

    return Settings()
