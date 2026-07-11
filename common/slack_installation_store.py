"""Supabase-backed Bolt InstallationStore for multi-workspace OAuth installs.

Replaces the single static SLACK_BOT_TOKEN env var (issue #61): one row per
Slack team in `slack_installations`, bot tokens encrypted at rest via
common/crypto.py. Only bot-scope installs are supported (no user tokens) —
matches how every command in this app already authenticates.
"""

from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any, Optional

from slack_sdk.oauth.installation_store import InstallationStore
from slack_sdk.oauth.installation_store.models.bot import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation

from common.crypto import decrypt, encrypt


class SupabaseInstallationStore(InstallationStore):
    def __init__(self, supabase_client: Any):
        self._supabase = supabase_client
        self._logger = getLogger(__name__)

    @property
    def logger(self) -> Logger:
        return self._logger

    def save(self, installation: Installation) -> None:
        raw = installation.to_dict()
        raw["bot_token"] = encrypt(raw["bot_token"]) if raw.get("bot_token") else None
        row = {
            "team_id": installation.team_id,
            "enterprise_id": installation.enterprise_id,
            "is_enterprise_install": bool(installation.is_enterprise_install),
            "bot_token_encrypted": encrypt(installation.bot_token) if installation.bot_token else None,
            "bot_id": installation.bot_id,
            "bot_user_id": installation.bot_user_id,
            "bot_scopes": _scopes_to_str(installation.bot_scopes),
            "app_id": installation.app_id,
            "installed_by_user_id": installation.user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "raw_installation": raw,
        }
        (
            self._supabase.table("slack_installations")
            .upsert(row, on_conflict="team_id")
            .execute()
        )

    def save_bot(self, bot: Bot) -> None:
        row = {
            "team_id": bot.team_id,
            "enterprise_id": bot.enterprise_id,
            "is_enterprise_install": bool(bot.is_enterprise_install),
            "bot_token_encrypted": encrypt(bot.bot_token) if bot.bot_token else None,
            "bot_id": bot.bot_id,
            "bot_user_id": bot.bot_user_id,
            "bot_scopes": _scopes_to_str(bot.bot_scopes),
            "app_id": bot.app_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "raw_installation": bot.to_dict(),
        }
        (
            self._supabase.table("slack_installations")
            .upsert(row, on_conflict="team_id")
            .execute()
        )

    def find_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Bot]:
        row = self._find_row(team_id)
        if row is None:
            return None
        return Bot(
            app_id=row.get("app_id"),
            enterprise_id=row.get("enterprise_id"),
            team_id=row.get("team_id"),
            bot_token=decrypt(row["bot_token_encrypted"]) if row.get("bot_token_encrypted") else None,
            bot_id=row.get("bot_id"),
            bot_user_id=row.get("bot_user_id"),
            bot_scopes=row.get("bot_scopes") or "",
            is_enterprise_install=bool(row.get("is_enterprise_install")),
            installed_at=_parse_installed_at(row),
        )

    def find_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Installation]:
        row = self._find_row(team_id)
        if row is None:
            return None
        raw = dict(row.get("raw_installation") or {})
        if raw.get("bot_token"):
            raw["bot_token"] = decrypt(row["bot_token_encrypted"]) if row.get("bot_token_encrypted") else None
        raw.setdefault("user_id", row.get("installed_by_user_id") or "")
        raw.pop("bot_refresh_token", None)
        raw.pop("user_refresh_token", None)
        try:
            return Installation(**{k: v for k, v in raw.items() if k in _INSTALLATION_FIELDS})
        except TypeError:
            self._logger.exception(f"Stored raw_installation for team {team_id} could not be reconstructed")
            return None

    def delete_bot(self, *, enterprise_id: Optional[str], team_id: Optional[str]) -> None:
        self._delete(team_id)

    def delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        self._delete(team_id)

    def list_team_ids(self) -> list[str]:
        """All currently-installed team IDs -- used to iterate every active
        install (e.g. startup backfill in student-org-agent/app.py)."""
        rows = (
            self._supabase.table("slack_installations")
            .select("team_id")
            .execute()
            .data
        )
        return [row["team_id"] for row in rows]

    def _find_row(self, team_id: Optional[str]) -> Optional[dict]:
        if not team_id:
            return None
        rows = (
            self._supabase.table("slack_installations")
            .select("*")
            .eq("team_id", team_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def _delete(self, team_id: Optional[str]) -> None:
        if not team_id:
            return
        (
            self._supabase.table("slack_installations")
            .delete()
            .eq("team_id", team_id)
            .execute()
        )


_INSTALLATION_FIELDS = {
    "app_id", "enterprise_id", "enterprise_name", "enterprise_url", "team_id", "team_name",
    "bot_token", "bot_id", "bot_user_id", "bot_scopes", "bot_token_expires_in", "bot_token_expires_at",
    "user_id", "user_token", "user_scopes", "user_token_expires_in", "user_token_expires_at",
    "incoming_webhook_url", "incoming_webhook_channel", "incoming_webhook_channel_id",
    "incoming_webhook_configuration_url", "is_enterprise_install", "token_type", "installed_at",
    "custom_values",
}


def _scopes_to_str(scopes: Any) -> str:
    if isinstance(scopes, str):
        return scopes
    if scopes is None:
        return ""
    return ",".join(scopes)


def _parse_installed_at(row: dict) -> float:
    updated_at = row.get("updated_at")
    if isinstance(updated_at, str):
        try:
            return datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return datetime.now(timezone.utc).timestamp()
