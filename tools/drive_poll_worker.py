import logging
import time

from common.config import get_ingestion_settings
from common.google_credentials_store import WorkspaceGoogleCredentialsStore
from ingestion_api.drive_sync import DriveSyncService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _get_supabase():
    from supabase import create_client
    settings = get_ingestion_settings()
    return create_client(settings.required_supabase_url, settings.required_supabase_service_key)


def _poll_all_workspaces() -> None:
    """Poll Drive changes for every workspace that has connected a Google
    account (issue #66) -- not just one, since Drive is no longer a single
    shared account."""
    supabase = _get_supabase()
    workspace_ids = WorkspaceGoogleCredentialsStore(supabase).list_workspace_ids()
    if not workspace_ids:
        logger.warning(
            "No workspaces have connected Google Drive yet -- this poll is a "
            "no-op. If a workspace previously relied on the old shared "
            "secrets/club_token.json, that stopped being read entirely as of "
            "issue #66; an admin must run /connect-folder in Slack to "
            "reconnect it under the new per-workspace OAuth flow."
        )
        return
    for workspace_id in workspace_ids:
        try:
            result = DriveSyncService.from_settings(workspace_id).poll_changes()
            logger.info(
                "Drive poll complete for %s: changed=%s synced_folders=%s",
                workspace_id,
                result.changed_items,
                result.synced_folders,
            )
        except Exception:
            logger.exception("Drive poll failed for workspace %s", workspace_id)


def main() -> None:
    settings = get_ingestion_settings()
    interval = max(settings.drive_poll_interval_seconds, 30)
    logger.info("Drive polling worker started with interval=%s seconds", interval)

    while True:
        _poll_all_workspaces()
        time.sleep(interval)


if __name__ == "__main__":
    main()
