"""Per-workspace admin configuration (issue #67).

Replaces the static DRIVE_SYNC_ADMIN_USER_IDS/RECONCILIATION_APPROVAL_USER_IDS
env vars -- a single deployment-wide list that made no sense once more than
one workspace could install this app. A newly installed workspace gets the
installer seeded as its default admin for both lists (see
ensure_default_admin, called from the Slack OAuth success callback), not a
redeploy or env var edit.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

DEFAULT_APPROVAL_REACTION = "white_check_mark"


@dataclass(frozen=True)
class WorkspaceAdminSettings:
    """Shaped to match what ReconciliationApprovalPolicy.from_settings(...)
    and the /connect-folder admin check already expect: comma-joined strings,
    not lists, plus app_env (a deployment-wide concept, not per-workspace)."""

    workspace_id: str
    drive_sync_admin_user_ids: Optional[str]
    reconciliation_approval_user_ids: Optional[str]
    reconciliation_approval_reaction: str
    app_env: str = "development"


class WorkspaceAdminSettingsStore:
    def __init__(self, supabase_client: Any):
        self._supabase = supabase_client

    def get(self, workspace_id: str, *, app_env: str = "development") -> WorkspaceAdminSettings:
        rows = (
            self._supabase.table("workspace_admin_settings")
            .select("*")
            .eq("workspace_id", workspace_id)
            .execute()
            .data
        )
        if not rows:
            return WorkspaceAdminSettings(
                workspace_id=workspace_id,
                drive_sync_admin_user_ids=None,
                reconciliation_approval_user_ids=None,
                reconciliation_approval_reaction=DEFAULT_APPROVAL_REACTION,
                app_env=app_env,
            )
        row = rows[0]
        return WorkspaceAdminSettings(
            workspace_id=workspace_id,
            drive_sync_admin_user_ids=_join(row.get("drive_sync_admin_user_ids")),
            reconciliation_approval_user_ids=_join(row.get("reconciliation_approval_user_ids")),
            reconciliation_approval_reaction=row.get("reconciliation_approval_reaction") or DEFAULT_APPROVAL_REACTION,
            app_env=app_env,
        )

    def ensure_default_admin(self, workspace_id: str, user_id: Optional[str]) -> None:
        """Seed a newly installed workspace's admin lists with its
        installer. A no-op if that workspace already has settings -- never
        clobbers an admin list someone already customized."""
        if not user_id:
            return
        existing = (
            self._supabase.table("workspace_admin_settings")
            .select("workspace_id")
            .eq("workspace_id", workspace_id)
            .execute()
            .data
        )
        if existing:
            return
        (
            self._supabase.table("workspace_admin_settings")
            .insert({
                "workspace_id": workspace_id,
                "drive_sync_admin_user_ids": [user_id],
                "reconciliation_approval_user_ids": [user_id],
                "reconciliation_approval_reaction": DEFAULT_APPROVAL_REACTION,
            })
            .execute()
        )

    def set_drive_sync_admins(self, workspace_id: str, user_ids: Iterable[str]) -> None:
        self._upsert(workspace_id, drive_sync_admin_user_ids=list(user_ids))

    def set_reconciliation_admins(self, workspace_id: str, user_ids: Iterable[str]) -> None:
        self._upsert(workspace_id, reconciliation_approval_user_ids=list(user_ids))

    def set_reconciliation_reaction(self, workspace_id: str, reaction: str) -> None:
        self._upsert(workspace_id, reconciliation_approval_reaction=reaction)

    def _upsert(self, workspace_id: str, **fields: Any) -> None:
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        row = {"workspace_id": workspace_id, **fields}
        (
            self._supabase.table("workspace_admin_settings")
            .upsert(row, on_conflict="workspace_id")
            .execute()
        )


def _join(values: Any) -> Optional[str]:
    if not values:
        return None
    return ",".join(values)
