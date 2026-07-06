from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from pydantic import AliasChoices, Field
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
    supabase_url: str
    supabase_service_role_key: str = Field(
        validation_alias=AliasChoices(
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_SERVICE_KEY",
        )
    )
    voyage_api_key: str
    voyage_embed_model: str = "voyage-3.5-lite"
    voyage_embed_dimension: int = 1024


class IngestionSettings(BaseAppSettings):
    app_env: str = "development"
    ingestion_port: int = 8000
    supabase_url: str | None = None
    supabase_service_key: str | None = None
    supabase_anon_key: str | None = None
    supabase_publishable_key: str | None = None
    voyage_api_key: str | None = None
    workspace_id: str | None = None
    google_token_path: Path = Path("secrets/club_token.json")
    drive_poll_interval_seconds: int = 300
    ingestion_api_key: str | None = None
    drive_sync_admin_user_ids: str | None = None
    slack_backfill_limit: int = 200
    slack_reconcile_cron_hour: int = 6

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
