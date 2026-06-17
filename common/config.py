from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class SlackSettings(BaseAppSettings):
    app_env: str = "development"
    slack_bot_token: str
    slack_app_token: str
    slack_token_verification_enabled: bool = False


class IngestionSettings(BaseAppSettings):
    app_env: str = "development"
    ingestion_port: int = 8000
    supabase_url: str | None = None
    supabase_anon_key: str | None = None


@lru_cache
def get_slack_settings() -> SlackSettings:
    return SlackSettings()


@lru_cache
def get_ingestion_settings() -> IngestionSettings:
    return IngestionSettings()
