from functools import lru_cache
from typing import TypeVar

from pydantic_settings import BaseSettings, SettingsConfigDict

T = TypeVar("T")


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
    supabase_url: str | None = None
    supabase_service_key: str | None = None
    voyage_api_key: str | None = None
    workspace_id: str | None = None
    slack_backfill_limit: int = 200

    def require(self, value: T | None, environment_name: str) -> T:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise RuntimeError(f"{environment_name} must be configured")
        return value

    @property
    def required_supabase_url(self) -> str:
        return self.require(self.supabase_url, "SUPABASE_URL")

    @property
    def required_supabase_service_key(self) -> str:
        return self.require(self.supabase_service_key, "SUPABASE_SERVICE_KEY")

    @property
    def required_voyage_api_key(self) -> str:
        return self.require(self.voyage_api_key, "VOYAGE_API_KEY")

    @property
    def required_workspace_id(self) -> str:
        return self.require(self.workspace_id, "WORKSPACE_ID")


class IngestionSettings(BaseAppSettings):
    app_env: str = "development"
    ingestion_port: int = 8000
    supabase_url: str | None = None
    supabase_service_key: str | None = None
    supabase_anon_key: str | None = None
    voyage_api_key: str | None = None
    workspace_id: str | None = None
    slack_backfill_limit: int = 200

    def require(self, value: T | None, environment_name: str) -> T:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise RuntimeError(f"{environment_name} must be configured")
        return value

    @property
    def required_supabase_url(self) -> str:
        return self.require(self.supabase_url, "SUPABASE_URL")

    @property
    def required_supabase_service_key(self) -> str:
        return self.require(self.supabase_service_key, "SUPABASE_SERVICE_KEY")

    @property
    def required_voyage_api_key(self) -> str:
        return self.require(self.voyage_api_key, "VOYAGE_API_KEY")

    @property
    def required_workspace_id(self) -> str:
        return self.require(self.workspace_id, "WORKSPACE_ID")


@lru_cache
def get_slack_settings() -> SlackSettings:
    return SlackSettings()


@lru_cache
def get_ingestion_settings() -> IngestionSettings:
    return IngestionSettings()
