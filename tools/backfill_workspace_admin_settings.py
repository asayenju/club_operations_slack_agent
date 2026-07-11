"""One-off admin tool: seed workspace_admin_settings for workspaces that
installed the app before issue #67 shipped.

The OAuth success callback (student-org-agent/app.py's _on_install_success)
only seeds a default admin for *new* installs going forward. A workspace
that was already in slack_installations before this feature landed gets no
row -- and there's no fallback to the old DRIVE_SYNC_ADMIN_USER_IDS/
RECONCILIATION_APPROVAL_USER_IDS env vars, since those were deleted from
config entirely. Without a row: /connect-folder breaks with a visible
"Drive folder administrators are not configured" error, and reconciliation
reaction approval breaks silently (no error surfaced anywhere, since Slack
reaction events have no response channel).

For every already-installed workspace, seed the installer (slack_installations.
installed_by_user_id) into whichever of drive_sync_admin_user_ids /
reconciliation_approval_user_ids is still unset -- not just workspaces with
no settings row at all. A workspace that already has both fields configured
is left untouched; a workspace with only one of the two set (e.g. an admin
ran set_drive_sync_admins() by hand) gets just the missing field backfilled,
instead of being skipped entirely.

Usage:
    python -m tools.backfill_workspace_admin_settings
"""

from common.config import get_ingestion_settings
from common.workspace_admin_settings import WorkspaceAdminSettingsStore


def main() -> None:
    settings = get_ingestion_settings()
    from supabase import create_client
    supabase = create_client(settings.required_supabase_url, settings.required_supabase_service_key)

    rows = (
        supabase.table("slack_installations")
        .select("team_id,installed_by_user_id")
        .execute()
        .data
    )

    store = WorkspaceAdminSettingsStore(supabase)
    seeded = 0
    skipped = 0
    for row in rows:
        team_id = row["team_id"]
        installer = row.get("installed_by_user_id")
        if not installer:
            print(f"workspace {team_id!r} has no installed_by_user_id on record -- skipping, seed it manually")
            skipped += 1
            continue
        if store.backfill_missing_defaults(team_id, installer):
            seeded += 1
            print(f"seeded missing admin settings for workspace {team_id!r} (installer {installer!r})")
        else:
            skipped += 1

    print(f"done: {seeded} seeded, {skipped} skipped (already fully configured or no installer on record)")


if __name__ == "__main__":
    main()
