import logging
import time

from common.config import get_ingestion_settings
from common.secrets_bootstrap import materialize_google_token
from ingestion_api.drive_repository import SupabaseDriveRegistry
from ingestion_api.drive_sync import DriveSyncService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

materialize_google_token()


def _get_supabase():
    from supabase import create_client
    settings = get_ingestion_settings()
    return create_client(settings.required_supabase_url, settings.required_supabase_service_key)


def _poll_all_workspaces() -> None:
    """Poll Drive changes for every workspace that has connected a folder.
    Google auth is a single shared account (secrets/club_token.json via
    `python -m tools.google_auth_bootstrap`); workspace_id scopes the folder
    registry, not the credential."""
    workspace_ids = SupabaseDriveRegistry(_get_supabase()).list_workspace_ids()
    if not workspace_ids:
        logger.info(
            "No workspaces have connected a Drive folder yet -- this poll is a "
            "no-op. Run /connect-folder in Slack to connect one."
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
