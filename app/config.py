from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Profile Intelligence Service"
    debug: bool = False
    database_url: str


@lru_cache()
def get_settings() -> Settings:
    """Get application settings."""
    return Settings()