"""Per-workspace Google OAuth credentials (issue #66).

Replaces the single shared secrets/club_token.json file: each installing
Slack workspace connects its own Google account via its own OAuth consent,
so Drive/Docs/Sheets access is isolated per workspace, not shared. Refresh
tokens are encrypted at rest via common/crypto.py -- the same mechanism
already used for Slack bot tokens (#61).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from google.oauth2.credentials import Credentials

from common.config import get_ingestion_settings
from common.crypto import decrypt, encrypt

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleDriveNotConnected(RuntimeError):
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        super().__init__(
            f"Google Drive is not connected for workspace {workspace_id!r}. "
            "Run /connect-folder to get a connection link."
        )


@dataclass(frozen=True)
class WorkspaceGoogleCredentials:
    workspace_id: str
    refresh_token: str
    scopes: list[str]
    google_account_email: Optional[str]
    connected_by_user_id: Optional[str]


class WorkspaceGoogleCredentialsStore:
    def __init__(self, supabase_client: Any):
        self._supabase = supabase_client

    def save(
        self,
        workspace_id: str,
        refresh_token: str,
        scopes: list[str],
        *,
        connected_by_user_id: Optional[str] = None,
        google_account_email: Optional[str] = None,
    ) -> None:
        row = {
            "workspace_id": workspace_id,
            "refresh_token_encrypted": encrypt(refresh_token),
            "scopes": " ".join(scopes),
            "connected_by_user_id": connected_by_user_id,
            "google_account_email": google_account_email,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        (
            self._supabase.table("workspace_google_credentials")
            .upsert(row, on_conflict="workspace_id")
            .execute()
        )

    def get(self, workspace_id: str) -> Optional[WorkspaceGoogleCredentials]:
        rows = (
            self._supabase.table("workspace_google_credentials")
            .select("*")
            .eq("workspace_id", workspace_id)
            .execute()
            .data
        )
        if not rows:
            return None
        row = rows[0]
        return WorkspaceGoogleCredentials(
            workspace_id=row["workspace_id"],
            refresh_token=decrypt(row["refresh_token_encrypted"]),
            scopes=(row.get("scopes") or "").split(),
            google_account_email=row.get("google_account_email"),
            connected_by_user_id=row.get("connected_by_user_id"),
        )

    def is_connected(self, workspace_id: str) -> bool:
        return self.get(workspace_id) is not None

    def list_workspace_ids(self) -> list[str]:
        """Every workspace with a connected Google account -- used to iterate
        all installs for background Drive polling (tools/drive_poll_worker.py)."""
        rows = (
            self._supabase.table("workspace_google_credentials")
            .select("workspace_id")
            .execute()
            .data
        )
        return [row["workspace_id"] for row in rows]

    def delete(self, workspace_id: str) -> None:
        (
            self._supabase.table("workspace_google_credentials")
            .delete()
            .eq("workspace_id", workspace_id)
            .execute()
        )


def get_google_credentials(
    workspace_id: str,
    scopes: list[str],
    supabase_client: Any | None = None,
) -> Credentials:
    """Build refreshable google-auth Credentials for one workspace's
    connected Google account. Raises GoogleDriveNotConnected if that
    workspace hasn't completed the /connect-folder OAuth flow yet."""
    if supabase_client is None:
        from supabase import create_client
        settings = get_ingestion_settings()
        supabase_client = create_client(
            settings.required_supabase_url,
            settings.required_supabase_service_key,
        )

    store = WorkspaceGoogleCredentialsStore(supabase_client)
    stored = store.get(workspace_id)
    if stored is None:
        raise GoogleDriveNotConnected(workspace_id)

    settings = get_ingestion_settings()
    return Credentials(
        token=None,
        refresh_token=stored.refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=settings.required_google_oauth_client_id,
        client_secret=settings.required_google_oauth_client_secret,
        scopes=scopes,
    )
