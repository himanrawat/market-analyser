"""Central configuration loaded from .env — single source of truth."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Data providers
    fmp_api_key: str = Field(default="", alias="FMP_API_KEY")
    fred_api_key: str = Field(default="", alias="FRED_API_KEY")
    newsapi_key: str = Field(default="", alias="NEWSAPI_KEY")
    kite_api_key: str = Field(default="", alias="KITE_API_KEY")
    kite_api_secret: str = Field(default="", alias="KITE_API_SECRET")

    # Notifications
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # Database
    database_url: str = Field(
        default=f"sqlite:///{REPO_ROOT}/data/market.db",
        alias="DATABASE_URL",
    )

    # Paths
    data_dir: Path = Field(default=REPO_ROOT / "data", alias="DATA_DIR")
    log_dir: Path = Field(default=REPO_ROOT / "logs", alias="LOG_DIR")

    # Runtime
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
