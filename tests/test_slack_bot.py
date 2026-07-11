import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from memoryAnswer.service import MemoryAnswer
from reconciliation.approval import ReconciliationApprovalPolicy
from reconciliation.models import ProposalStatus, ReconciliationProposal
from tools.confidence import ConfidenceResult


def load_bot_module(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "client-id-test")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "client-secret-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "signing-secret-test")
    monkeypatch.setenv("WORKSPACE_ID", "T123")
    module_path = Path(__file__).resolve().parents[1] / "student-org-agent" / "app.py"
    spec = importlib.util.spec_from_file_location("student_org_agent_app", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "get_ingestion_settings",
        lambda: SimpleNamespace(
            app_env="development",
            drive_sync_admin_user_ids=None,
        ),
    )
    return module


PROPOSAL_ID = "00000000-0000-0000-0000-000000000001"


def build_reconciliation_proposal(*, status=ProposalStatus.PENDING, expired=False):
    now = datetime.now(UTC)
    confirmed_at = now if status == ProposalStatus.CONFIRMED else None
    return ReconciliationProposal(
        id=PROPOSAL_ID,
        workspace_id="T123",
        status=status,
        source_evidence=[],
        proposed_action={"kind": "notify"},
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
        created_at=now - timedelta(hours=1),
        expires_at=now - timedelta(minutes=1) if expired else now + timedelta(hours=1),
        confirmed_by_user_id="UAPPROVER" if confirmed_at else None,
        confirmed_at=confirmed_at,
    )


class FakeReconciliationService:
    def __init__(self, proposal=None, error=None, confirm_error=None):
        self.proposal = proposal
        self.error = error
        self.confirm_error = confirm_error
        self.lookups = []
        self.confirmations = []

    def find_by_slack_message(self, workspace_id, slack_channel_id, slack_message_ts):
        self.lookups.append((workspace_id, slack_channel_id, slack_message_ts))
        if self.error:
            raise self.error
        return self.proposal

    def confirm(self, **kwargs):
        self.confirmations.append(kwargs)
        if self.confirm_error:
            raise self.confirm_error
        return self.proposal


def allow_reconciliation_approval(bot, monkeypatch, service):
    monkeypatch.setattr(bot, "build_reconciliation_proposal_service", lambda: service)
    monkeypatch.setattr(
        bot,
        "build_reconciliation_approval_policy",
        lambda workspace_id: ReconciliationApprovalPolicy(
            lead_user_ids=frozenset({"UAPPROVER"}),
            approval_reaction="white_check_mark",
        ),
    )


def reaction_event(**overrides):
    event = {
        "team": "T123",
        "user": "UAPPROVER",
        "reaction": "white_check_mark",
        "item": {
            "type": "message",
            "channel": "C123",
            "ts": "1710000000.000100",
        },
    }
    event.update(overrides)
    return event


def test_on_install_success_seeds_default_admin_then_calls_default_success(monkeypatch):
    """Issue #67: a newly installed workspace gets its installer seeded as
    admin automatically -- no redeploy or env var edit needed."""
    bot = load_bot_module(monkeypatch)
    seeded = []
    monkeypatch.setattr(
        bot,
        "WorkspaceAdminSettingsStore",
        lambda supabase: SimpleNamespace(
            ensure_default_admin=lambda workspace_id, user_id: seeded.append((workspace_id, user_id))
        ),
    )
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())

    default_calls = []
    args = SimpleNamespace(
        installation=SimpleNamespace(team_id="T_NEW", user_id="U_INSTALLER"),
        default=SimpleNamespace(success=lambda a: default_calls.append(a) or "default-success-response"),
    )

    result = bot._on_install_success(args)

    assert seeded == [("T_NEW", "U_INSTALLER")]
    assert result == "default-success-response"
    assert default_calls == [args]


def test_on_install_success_still_calls_default_success_if_seeding_fails(monkeypatch):
    """A DB hiccup while seeding admin defaults shouldn't break the actual
    Slack install -- the user should still see Slack's success page."""
    bot = load_bot_module(monkeypatch)

    def _raise(supabase):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(bot, "WorkspaceAdminSettingsStore", _raise)
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())

    default_calls = []
    args = SimpleNamespace(
        installation=SimpleNamespace(team_id="T_NEW", user_id="U_INSTALLER"),
        default=SimpleNamespace(success=lambda a: default_calls.append(a) or "default-success-response"),
    )

    result = bot._on_install_success(args)

    assert result == "default-success-response"
    assert default_calls == [args]


def test_run_backfill_iterates_every_installed_workspace(monkeypatch):
    """Issue #63: startup backfill can no longer assume a single configured
    workspace -- it must backfill every currently-installed workspace, each
    with its own resolved bot token."""
    bot = load_bot_module(monkeypatch)
    backfill_calls = []

    class FakeInstallationStore:
        def __init__(self, supabase):
            pass

        def list_team_ids(self):
            return ["T_A", "T_B"]

        def find_bot(self, *, enterprise_id, team_id):
            return SimpleNamespace(bot_token=f"xoxb-{team_id}")

    monkeypatch.setattr(bot, "SupabaseInstallationStore", FakeInstallationStore)
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bot,
        "run_channel_backfill",
        lambda client, supabase, workspace_id, log_prefix=None: backfill_calls.append(
            (workspace_id, client.token)
        ),
    )

    bot._run_backfill()

    assert sorted(backfill_calls) == [("T_A", "xoxb-T_A"), ("T_B", "xoxb-T_B")]


def test_run_backfill_skips_workspace_with_no_bot_token(monkeypatch):
    bot = load_bot_module(monkeypatch)
    backfill_calls = []

    class FakeInstallationStore:
        def __init__(self, supabase):
            pass

        def list_team_ids(self):
            return ["T_NO_BOT"]

        def find_bot(self, *, enterprise_id, team_id):
            return None

    monkeypatch.setattr(bot, "SupabaseInstallationStore", FakeInstallationStore)
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bot,
        "run_channel_backfill",
        lambda client, supabase, workspace_id, log_prefix=None: backfill_calls.append(workspace_id),
    )

    bot._run_backfill()

    assert backfill_calls == []


class _FakeInstallationStoreForUninstall:
    def __init__(self, supabase):
        self.deleted_team_ids = []

    def delete_all(self, *, enterprise_id, team_id):
        self.deleted_team_ids.append(team_id)


def _stub_uninstall_dependencies(bot, monkeypatch, *, deleted_channel_counts=None):
    store = _FakeInstallationStoreForUninstall(None)
    monkeypatch.setattr(bot, "SupabaseInstallationStore", lambda supabase: store)
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    deleted_channels = []
    monkeypatch.setattr(
        bot,
        "delete_monitored_channels_for_workspace",
        lambda supabase, workspace_id: deleted_channels.append(workspace_id) or (deleted_channel_counts or 0),
    )
    deleted_google_creds = []
    monkeypatch.setattr(
        bot,
        "WorkspaceGoogleCredentialsStore",
        lambda supabase: SimpleNamespace(delete=lambda workspace_id: deleted_google_creds.append(workspace_id)),
    )
    deleted_admin_settings = []
    monkeypatch.setattr(
        bot,
        "WorkspaceAdminSettingsStore",
        lambda supabase: SimpleNamespace(delete=lambda workspace_id: deleted_admin_settings.append(workspace_id)),
    )
    return store, deleted_channels, deleted_google_creds, deleted_admin_settings


def test_app_uninstalled_removes_installation_and_monitored_channels(monkeypatch):
    bot = load_bot_module(monkeypatch)
    store, deleted_channels, deleted_google_creds, deleted_admin_settings = _stub_uninstall_dependencies(
        bot, monkeypatch
    )
    bot._monitored_channels_by_workspace["T_UNINSTALLED"] = {"C01": "general"}

    bot.handle_app_uninstalled(context={"team_id": "T_UNINSTALLED"}, logger=SimpleNamespace(
        info=lambda *a, **k: None, exception=lambda *a, **k: None,
    ))

    assert store.deleted_team_ids == ["T_UNINSTALLED"]
    assert deleted_channels == ["T_UNINSTALLED"]
    assert "T_UNINSTALLED" not in bot._monitored_channels_by_workspace


def test_app_uninstalled_removes_google_credentials_and_admin_settings(monkeypatch):
    """Issue #64 acceptance criteria (Aman review, #73): uninstall cleanup
    must also drop workspace-scoped Google Drive credentials (#66) and admin
    settings (#67), not just the Slack installation and monitored channels."""
    bot = load_bot_module(monkeypatch)
    _, _, deleted_google_creds, deleted_admin_settings = _stub_uninstall_dependencies(bot, monkeypatch)
    noop_logger = SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None)

    bot.handle_app_uninstalled(context={"team_id": "T_UNINSTALLED"}, logger=noop_logger)

    assert deleted_google_creds == ["T_UNINSTALLED"]
    assert deleted_admin_settings == ["T_UNINSTALLED"]


def test_app_uninstalled_is_idempotent(monkeypatch):
    """Slack does not guarantee exactly-once delivery -- receiving this
    event twice for the same team must not raise."""
    bot = load_bot_module(monkeypatch)
    store, _, deleted_google_creds, deleted_admin_settings = _stub_uninstall_dependencies(bot, monkeypatch)
    noop_logger = SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None)

    bot.handle_app_uninstalled(context={"team_id": "T_UNINSTALLED"}, logger=noop_logger)
    bot.handle_app_uninstalled(context={"team_id": "T_UNINSTALLED"}, logger=noop_logger)

    assert store.deleted_team_ids == ["T_UNINSTALLED", "T_UNINSTALLED"]
    assert deleted_google_creds == ["T_UNINSTALLED", "T_UNINSTALLED"]
    assert deleted_admin_settings == ["T_UNINSTALLED", "T_UNINSTALLED"]


def test_tokens_revoked_removes_installation_when_bot_token_revoked(monkeypatch):
    bot = load_bot_module(monkeypatch)
    store, deleted_channels, deleted_google_creds, deleted_admin_settings = _stub_uninstall_dependencies(
        bot, monkeypatch
    )
    noop_logger = SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None)

    bot.handle_tokens_revoked(
        event={"tokens": {"bot": ["U_BOT_1"], "oauth": []}},
        context={"team_id": "T_REVOKED"},
        logger=noop_logger,
    )

    assert store.deleted_team_ids == ["T_REVOKED"]
    assert deleted_channels == ["T_REVOKED"]
    assert deleted_google_creds == ["T_REVOKED"]
    assert deleted_admin_settings == ["T_REVOKED"]


def test_tokens_revoked_ignores_user_only_token_revocation(monkeypatch):
    """This app is bot-scope-only (installation_store_bot_only=True) -- a
    revoked user token with no bot token revoked isn't ours to react to."""
    bot = load_bot_module(monkeypatch)
    store, deleted_channels, deleted_google_creds, deleted_admin_settings = _stub_uninstall_dependencies(
        bot, monkeypatch
    )
    noop_logger = SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None)

    bot.handle_tokens_revoked(
        event={"tokens": {"bot": [], "oauth": ["U123"]}},
        context={"team_id": "T_REVOKED"},
        logger=noop_logger,
    )

    assert store.deleted_team_ids == []
    assert deleted_channels == []
    assert deleted_google_creds == []
    assert deleted_admin_settings == []


def test_app_uninstalled_continues_cleanup_when_google_credentials_deletion_fails(monkeypatch):
    """A DB hiccup deleting one workspace-scoped table must not stop the
    rest of the cleanup (installation, monitored channels, admin settings)
    from running."""
    bot = load_bot_module(monkeypatch)
    store, deleted_channels, _, deleted_admin_settings = _stub_uninstall_dependencies(bot, monkeypatch)

    def _raise(supabase):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(bot, "WorkspaceGoogleCredentialsStore", _raise)
    noop_logger = SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None)

    bot.handle_app_uninstalled(context={"team_id": "T_UNINSTALLED"}, logger=noop_logger)

    assert store.deleted_team_ids == ["T_UNINSTALLED"]
    assert deleted_channels == ["T_UNINSTALLED"]
    assert deleted_admin_settings == ["T_UNINSTALLED"]


def test_build_hello_response_mentions_user(monkeypatch):
    bot = load_bot_module(monkeypatch)

    response = bot.build_hello_response("U123")

    assert response["text"] == "Hey there <@U123>!"
    assert response["blocks"][0]["text"]["text"] == "Hey there <@U123>!"


class FakeDecisionService:
    def __init__(self, error=None):
        self.error = error
        self.commands = []

    def store_decision(self, command):
        self.commands.append(command)
        if self.error:
            raise self.error
        return object()


def test_handle_decide_command_stores_decision_and_confirms_publicly(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeDecisionService()
    responses = []

    monkeypatch.setattr(bot, "build_decision_service", lambda: service)
    bot.handle_decide_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "text": "  We approved snacks.  ", "user_id": "U123"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "in_channel",
            "text": "Decision recorded by <@U123>: We approved snacks.",
        },
    ]
    assert service.commands == [
        {"team_id": "T123", "text": "  We approved snacks.  ", "user_id": "U123"}
    ]


def test_handle_decide_command_works_for_any_installed_workspace(monkeypatch):
    """Issue #63: no static WORKSPACE_ID allowlist anymore -- any team_id
    Bolt's own OAuth authorization let through gets served, not just the one
    workspace previously hardcoded via configured_workspace_id()."""
    bot = load_bot_module(monkeypatch)
    service = FakeDecisionService()
    responses = []

    monkeypatch.setattr(bot, "build_decision_service", lambda: service)
    bot.handle_decide_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_SOME_OTHER_WORKSPACE", "text": "We approved snacks.", "user_id": "U123"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "in_channel",
            "text": "Decision recorded by <@U123>: We approved snacks.",
        },
    ]
    assert service.commands == [
        {"team_id": "T_SOME_OTHER_WORKSPACE", "text": "We approved snacks.", "user_id": "U123"}
    ]


def test_handle_decide_command_confirms_without_author_when_missing(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeDecisionService()
    responses = []

    monkeypatch.setattr(bot, "build_decision_service", lambda: service)
    bot.handle_decide_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "text": "We approved snacks."},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {"response_type": "in_channel", "text": "Decision recorded: We approved snacks."},
    ]


def test_handle_decide_command_rejects_empty_text(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []

    bot.handle_decide_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "text": "   "},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "Usage: `/decide We approved the spring budget.`",
        },
    ]


def test_handle_decide_command_reports_duplicate_ephemerally(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    service = FakeDecisionService(error=bot.DecisionAlreadyStored({"id": "doc-123"}))

    monkeypatch.setattr(bot, "build_decision_service", lambda: service)
    bot.handle_decide_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "text": "We approved snacks."},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {"response_type": "ephemeral", "text": "That decision is already stored."},
    ]


def test_handle_decide_command_reports_failures_ephemerally(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    service = FakeDecisionService(error=RuntimeError("database down"))

    monkeypatch.setattr(bot, "build_decision_service", lambda: service)
    bot.handle_decide_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "text": "We approved snacks."},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "I couldn't store that decision right now.",
        },
    ]




def _stub_drive_connected(bot, monkeypatch):
    monkeypatch.setattr(
        bot,
        "WorkspaceGoogleCredentialsStore",
        lambda supabase: SimpleNamespace(is_connected=lambda workspace_id: True),
    )
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bot,
        "WorkspaceAdminSettingsStore",
        lambda supabase: SimpleNamespace(
            get=lambda workspace_id, app_env="development": SimpleNamespace(
                drive_sync_admin_user_ids=None,
            )
        ),
    )


def test_handle_connect_folder_command_reports_summary(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    _stub_drive_connected(bot, monkeypatch)
    service = SimpleNamespace(
        connect_folder=lambda folder, connected_by: SimpleNamespace(
            folder_name="Club Files",
            discovered=5,
            ingested=2,
        )
    )
    monkeypatch.setattr(
        bot.DriveSyncService,
        "from_settings",
        lambda workspace_id: service,
    )

    bot.handle_connect_folder_command(
        ack=lambda: responses.append({"acked": True}),
        command={
            "team_id": "T123",
            "text": "https://drive.google.com/drive/folders/root",
            "user_id": "U1",
        },
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses[0] == {"acked": True}
    assert responses[1] == {
        "response_type": "ephemeral",
        "text": (
            "Connected *Club Files*. "
            "Discovered 5 items and ingested 2 changed files."
        ),
    }


def test_handle_disconnect_folder_command_purges_sources(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    _stub_drive_connected(bot, monkeypatch)
    service = SimpleNamespace(disconnect_folder=lambda folder: 2)
    monkeypatch.setattr(
        bot.DriveSyncService,
        "from_settings",
        lambda workspace_id: service,
    )

    bot.handle_disconnect_folder_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "text": "root"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "Folder disconnected. Removed 2 unreferenced sources.",
        },
    ]


def test_handle_connect_folder_command_prompts_connection_when_drive_not_connected(monkeypatch):
    """Issue #66: no more single-workspace restriction -- any workspace can
    use /connect-folder once IT has connected its own Google Drive. If it
    hasn't yet, show a connection link instead of a rejection."""
    bot = load_bot_module(monkeypatch)
    responses = []
    monkeypatch.setattr(
        bot,
        "WorkspaceGoogleCredentialsStore",
        lambda supabase: SimpleNamespace(is_connected=lambda workspace_id: False),
    )
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bot,
        "WorkspaceAdminSettingsStore",
        lambda supabase: SimpleNamespace(
            get=lambda workspace_id, app_env="development": SimpleNamespace(
                drive_sync_admin_user_ids=None,
            )
        ),
    )
    monkeypatch.setattr(
        bot,
        "GoogleOAuthStateStore",
        lambda supabase: SimpleNamespace(create=lambda workspace_id, user_id, **kwargs: "opaque-test-token"),
    )
    monkeypatch.setattr(bot, "build_authorization_url", lambda state: f"https://accounts.google.com/auth?state={state}")

    bot.handle_connect_folder_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_ANY_WORKSPACE", "text": "root", "user_id": "U1"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "Connect Google Drive for this workspace first: "
                    "https://accounts.google.com/auth?state=opaque-test-token",
        },
    ]


def test_handle_connect_folder_command_reports_failure_when_google_oauth_misconfigured(monkeypatch):
    """GOOGLE_OAUTH_CLIENT_ID/SECRET missing (or any other failure building
    the authorization URL) must give an ephemeral error, not crash the
    whole command handler uncaught."""
    bot = load_bot_module(monkeypatch)
    responses = []
    monkeypatch.setattr(
        bot,
        "WorkspaceGoogleCredentialsStore",
        lambda supabase: SimpleNamespace(is_connected=lambda workspace_id: False),
    )
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bot,
        "WorkspaceAdminSettingsStore",
        lambda supabase: SimpleNamespace(
            get=lambda workspace_id, app_env="development": SimpleNamespace(
                drive_sync_admin_user_ids=None,
            )
        ),
    )

    def _raise(state):
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID must be configured")

    monkeypatch.setattr(bot, "build_authorization_url", _raise)

    bot.handle_connect_folder_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_ANY_WORKSPACE", "text": "root", "user_id": "U1"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "I couldn't start the Google Drive connection right now.",
        },
    ]


def test_handle_connect_folder_command_works_for_any_workspace_once_connected(monkeypatch):
    """A workspace other than whatever used to be the single configured one
    now works fine, as long as its own Drive is connected."""
    bot = load_bot_module(monkeypatch)
    responses = []
    _stub_drive_connected(bot, monkeypatch)
    calls = []
    service = SimpleNamespace(
        connect_folder=lambda folder, connected_by: calls.append(folder) or SimpleNamespace(
            folder_name="Some Folder", discovered=1, ingested=1,
        )
    )
    monkeypatch.setattr(bot.DriveSyncService, "from_settings", lambda workspace_id: service)

    bot.handle_connect_folder_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_ANY_WORKSPACE", "text": "root", "user_id": "U1"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert calls == ["root"]
    assert responses[1]["response_type"] == "ephemeral"
    assert "Connected" in responses[1]["text"]


def test_admin_check_is_independent_per_workspace(monkeypatch):
    """Issue #67: one workspace's admin list must not affect another's --
    replacing the old single deployment-wide DRIVE_SYNC_ADMIN_USER_IDS list."""
    bot = load_bot_module(monkeypatch)
    responses = []
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    admin_lists = {"T_A": "U_A_ADMIN", "T_B": "U_B_ADMIN"}
    monkeypatch.setattr(
        bot,
        "WorkspaceAdminSettingsStore",
        lambda supabase: SimpleNamespace(
            get=lambda workspace_id, app_env="development": SimpleNamespace(
                drive_sync_admin_user_ids=admin_lists[workspace_id],
            )
        ),
    )

    # U_A_ADMIN is T_A's admin but not T_B's -- must be rejected in T_B.
    bot.handle_connect_folder_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_B", "user_id": "U_A_ADMIN", "text": "root"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses[-1] == {
        "response_type": "ephemeral",
        "text": "You are not allowed to manage connected Drive folders.",
    }


class FakeMemoryAnswerService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def answer(self, question, workspace_id):
        self.calls.append((question, workspace_id))
        if self.error:
            raise self.error
        return self.result


def test_handle_ask_command_rejects_empty_text(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []

    bot.handle_ask_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "text": "   "},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "Usage: `/ask <your question>`",
        },
    ]


def test_handle_ask_command_returns_mocked_answer(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    service = FakeMemoryAnswerService(
        result=MemoryAnswer(
            answer="We have $500 left in the budget.",
            confidence=ConfidenceResult(level="High", reason="Found in a single Google Sheet."),
        )
    )
    monkeypatch.setattr(bot, "MemoryAnswerService", lambda: service)

    bot.handle_ask_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "text": "What is our budget?"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": (
                "We have $500 left in the budget.\n"
                "_Confidence: High — Found in a single Google Sheet._"
            ),
        },
    ]
    assert service.calls == [("What is our budget?", "T123")]


def test_handle_ask_command_reports_failures_ephemerally(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    service = FakeMemoryAnswerService(error=RuntimeError("search backend down"))
    monkeypatch.setattr(bot, "MemoryAnswerService", lambda: service)

    bot.handle_ask_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "text": "What is our budget?"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "I couldn't answer that question right now.",
        },
    ]


def test_handle_connect_folder_command_rejects_non_admin(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    monkeypatch.setattr(
        bot,
        "get_ingestion_settings",
        lambda: SimpleNamespace(app_env="production"),
    )
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bot,
        "WorkspaceAdminSettingsStore",
        lambda supabase: SimpleNamespace(
            get=lambda workspace_id, app_env="development": SimpleNamespace(
                drive_sync_admin_user_ids="U_ALLOWED",
            )
        ),
    )

    bot.handle_connect_folder_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "user_id": "U_OTHER", "text": "root"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "You are not allowed to manage connected Drive folders.",
        },
    ]


def test_reconciliation_reaction_event_acks_before_handling(monkeypatch):
    bot = load_bot_module(monkeypatch)
    calls = []
    monkeypatch.setattr(
        bot,
        "handle_reconciliation_reaction_added",
        lambda event, body=None: calls.append(("handled", event, body)),
    )

    bot.handle_reconciliation_reaction_event(
        event={"team": "T123"},
        body={"team_id": "T123"},
        ack=lambda: calls.append(("acked",)),
    )

    assert calls == [
        ("acked",),
        ("handled", {"team": "T123"}, {"team_id": "T123"}),
    ]


def test_reconcile_run_uses_request_workspace_client_and_configured_channel(monkeypatch):
    bot = load_bot_module(monkeypatch)
    calls = []
    responses = []
    request_client = object()
    proposal = object()
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bot,
        "WorkspaceAdminSettingsStore",
        lambda supabase: SimpleNamespace(
            get=lambda workspace_id, app_env="development": SimpleNamespace(
                reconciliation_channel_id="C_RECON"
            )
        ),
    )
    monkeypatch.setattr(
        bot,
        "run_reconciliation",
        lambda **kwargs: calls.append(kwargs) or proposal,
    )
    service = object()
    monkeypatch.setattr(bot, "build_reconciliation_proposal_service", lambda: service)

    bot.handle_reconcile_run_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_OTHER", "channel_id": "C_COMMAND", "text": "finance"},
        client=request_client,
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert calls == [
        {
            "workspace_id": "T_OTHER",
            "topic": "finance",
            "slack_client": request_client,
            "slack_channel_id": "C_RECON",
            "proposal_service": service,
        }
    ]
    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "Reconciliation run posted — awaiting confirmation.",
        },
    ]


def test_reconcile_run_requires_a_workspace_reconciliation_channel(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    monkeypatch.setattr(bot, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bot,
        "WorkspaceAdminSettingsStore",
        lambda supabase: SimpleNamespace(
            get=lambda workspace_id, app_env="development": SimpleNamespace(
                reconciliation_channel_id=None
            )
        ),
    )
    monkeypatch.setattr(
        bot,
        "run_reconciliation",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    bot.handle_reconcile_run_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_OTHER", "channel_id": "C_COMMAND", "text": "finance"},
        client=object(),
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "A reconciliation review channel is not configured for this workspace.",
        },
    ]


def test_reconciliation_reaction_confirms_matching_proposal(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(reaction_event())

    assert handled is True
    assert service.lookups == [("T123", "C123", "1710000000.000100")]
    assert service.confirmations == [
        {
            "workspace_id": "T123",
            "proposal_id": PROPOSAL_ID,
            "approving_user_id": "UAPPROVER",
        }
    ]


def test_reconciliation_reaction_uses_body_team_id_when_event_omits_team(
    monkeypatch,
):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)
    event = reaction_event()
    event.pop("team")

    handled = bot.handle_reconciliation_reaction_added(
        event,
        body={"team_id": "T123"},
    )

    assert handled is True
    assert service.lookups == [("T123", "C123", "1710000000.000100")]


def test_reconciliation_reaction_uses_body_team_id_before_event_fallback(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(
        reaction_event(team="T999"),
        body={"team_id": "T123"},
    )

    assert handled is True
    assert service.lookups == [("T123", "C123", "1710000000.000100")]


def test_reconciliation_reaction_ignores_unknown_message(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(proposal=None)
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(reaction_event())

    assert handled is False
    assert service.lookups == [("T123", "C123", "1710000000.000100")]
    assert service.confirmations == []


def test_reconciliation_reaction_ignores_non_message_item(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(
        reaction_event(item={"type": "file", "file": "F123"}),
    )

    assert handled is False
    assert service.lookups == []
    assert service.confirmations == []


def test_reconciliation_reaction_ignores_unauthorized_user(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(
        reaction_event(user="UOTHER"),
    )

    assert handled is False
    assert service.lookups == []
    assert service.confirmations == []


def test_reconciliation_reaction_ignores_wrong_reaction(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(reaction_event(reaction="eyes"))

    assert handled is False
    assert service.lookups == []
    assert service.confirmations == []


def test_reconciliation_reaction_accepts_skin_tone_reaction_variant(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
    )
    monkeypatch.setattr(bot, "build_reconciliation_proposal_service", lambda: service)
    monkeypatch.setattr(
        bot,
        "build_reconciliation_approval_policy",
        lambda workspace_id: ReconciliationApprovalPolicy(
            lead_user_ids=frozenset({"UAPPROVER"}),
            approval_reaction="+1",
        ),
    )

    handled = bot.handle_reconciliation_reaction_added(
        reaction_event(reaction="+1::skin-tone-3"),
    )

    assert handled is True
    assert service.confirmations


def test_reconciliation_reaction_skips_lookup_when_approval_unconfigured(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
    )
    monkeypatch.setattr(bot, "build_reconciliation_proposal_service", lambda: service)
    monkeypatch.setattr(
        bot,
        "build_reconciliation_approval_policy",
        lambda workspace_id: ReconciliationApprovalPolicy(
            lead_user_ids=frozenset(),
            approval_reaction="white_check_mark",
        ),
    )

    handled = bot.handle_reconciliation_reaction_added(reaction_event())

    assert handled is False
    assert service.lookups == []
    assert service.confirmations == []


def test_reconciliation_reaction_ignores_expired_proposal(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(expired=True),
        confirm_error=bot.InvalidProposalTransition("expired"),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(reaction_event())

    assert handled is False
    assert service.confirmations


def test_reconciliation_reaction_ignores_already_confirmed_proposal(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(status=ProposalStatus.CONFIRMED),
        confirm_error=bot.InvalidProposalTransition("already confirmed"),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(reaction_event())

    assert handled is False
    assert service.confirmations


def test_reconciliation_reaction_ignores_missing_proposal_during_confirm(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
        confirm_error=bot.ProposalNotFound("missing"),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(reaction_event())

    assert handled is False
    assert service.confirmations


def test_reconciliation_reaction_logs_failures_safely(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(error=RuntimeError("database down"))
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(reaction_event())

    assert handled is False
    assert service.confirmations == []
