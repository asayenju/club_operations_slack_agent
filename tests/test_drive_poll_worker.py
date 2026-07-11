"""Issue #74 review (Hailee): after moving to per-workspace Google Drive
credentials, a deployment with zero connected workspaces (e.g. the existing
workspace that hasn't re-run /connect-folder under the new OAuth client yet)
polled silently -- the loop just iterated nothing, no error, no log line.
These pin the fix: it must say so explicitly."""

from types import SimpleNamespace

from tools import drive_poll_worker


def test_poll_all_workspaces_warns_when_none_connected(monkeypatch, caplog):
    monkeypatch.setattr(drive_poll_worker, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        drive_poll_worker, "WorkspaceGoogleCredentialsStore",
        lambda supabase: SimpleNamespace(list_workspace_ids=lambda: []),
    )

    with caplog.at_level("WARNING"):
        drive_poll_worker._poll_all_workspaces()

    assert any("connect-folder" in record.message for record in caplog.records)


def test_poll_all_workspaces_polls_each_connected_workspace(monkeypatch):
    monkeypatch.setattr(drive_poll_worker, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        drive_poll_worker, "WorkspaceGoogleCredentialsStore",
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
