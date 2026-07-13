"""Drive polling iterates every workspace that has connected a folder. Google
auth is a single shared account (secrets/club_token.json), so the list of
workspaces to poll comes from the connected-folder registry, not a per-workspace
credential store. A deployment with zero connected folders must no-op with an
explicit log line rather than iterating nothing silently."""

from types import SimpleNamespace

from tools import drive_poll_worker


def test_poll_all_workspaces_logs_when_none_connected(monkeypatch, caplog):
    monkeypatch.setattr(drive_poll_worker, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        drive_poll_worker, "SupabaseDriveRegistry",
        lambda supabase: SimpleNamespace(list_workspace_ids=lambda: []),
    )

    with caplog.at_level("INFO"):
        drive_poll_worker._poll_all_workspaces()

    assert any("connect-folder" in record.message for record in caplog.records)


def test_poll_all_workspaces_polls_each_connected_workspace(monkeypatch):
    monkeypatch.setattr(drive_poll_worker, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        drive_poll_worker, "SupabaseDriveRegistry",
        lambda supabase: SimpleNamespace(list_workspace_ids=lambda: ["T_A", "T_B"]),
    )
    polled = []
    monkeypatch.setattr(
        drive_poll_worker.DriveSyncService, "from_settings",
        lambda workspace_id: SimpleNamespace(
            poll_changes=lambda: polled.append(workspace_id) or SimpleNamespace(changed_items=0, synced_folders=0)
        ),
    )

    drive_poll_worker._poll_all_workspaces()

    assert polled == ["T_A", "T_B"]
