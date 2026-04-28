from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Profile Intelligence Service"
    debug: bool = False

    database_url: str

    github_web_client_id: str
    github_web_client_secret: str
    github_cli_client_id: str
    github_cli_client_secret: str
    github_cli_callback_port: int = 51420

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 180
    refresh_token_ttl_seconds: int = 300

    backend_public_url: str
    web_app_origin: str

    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    cookie_domain: str | None = None

@lru_cache()
def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


settings = get_settings()
