import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from memoryAnswer.service import MemoryAnswer
from reconciliation.approval import ReconciliationApprovalPolicy
from reconciliation.models import ProposalStatus, ReconciliationProposal


def load_bot_module(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("WORKSPACE_ID", "T123")
    module_path = Path(__file__).resolve().parents[1] / "student-org-agent" / "app.py"
    spec = importlib.util.spec_from_file_location("student_org_agent_app", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "configured_workspace_id", lambda: "T123")
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
        lambda: ReconciliationApprovalPolicy(
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


def test_handle_decide_command_rejects_wrong_workspace(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeDecisionService()
    responses = []

    monkeypatch.setattr(bot, "build_decision_service", lambda: service)
    bot.handle_decide_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_OTHER", "text": "We approved snacks."},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "This command is not available in this workspace.",
        },
    ]
    assert service.commands == []


def test_handle_connect_folder_command_reports_summary(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
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
        lambda: service,
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
    assert responses[1]["response_type"] == "ephemeral"
    assert "Club Files" in responses[1]["text"]


def test_handle_disconnect_folder_command_purges_sources(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    service = SimpleNamespace(disconnect_folder=lambda folder: 2)
    monkeypatch.setattr(
        bot.DriveSyncService,
        "from_settings",
        lambda: service,
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


def test_handle_connect_folder_command_rejects_wrong_workspace(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []

    bot.handle_connect_folder_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_OTHER", "text": "root"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "This command is not available in this workspace.",
        },
    ]


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


def test_handle_ask_command_rejects_wrong_workspace(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []

    bot.handle_ask_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T_OTHER", "text": "What is our budget?"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "This command is not available in this workspace.",
        },
    ]


def test_handle_ask_command_returns_mocked_answer(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []
    service = FakeMemoryAnswerService(
        result=MemoryAnswer(
            answer="We have $500 left in the budget.",
            sources=["Budget Sheet"],
            confidence="high",
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
            "text": "We have $500 left in the budget.\n_Confidence: high_",
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
        lambda: SimpleNamespace(
            app_env="production",
            drive_sync_admin_user_ids="U_ALLOWED",
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


def test_reconciliation_reaction_rejects_wrong_workspace_before_lookup(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeReconciliationService(
        proposal=build_reconciliation_proposal(),
    )
    allow_reconciliation_approval(bot, monkeypatch, service)

    handled = bot.handle_reconciliation_reaction_added(
        reaction_event(team="T999"),
    )

    assert handled is False
    assert service.lookups == []
    assert service.confirmations == []


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
        lambda: ReconciliationApprovalPolicy(
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
        lambda: ReconciliationApprovalPolicy(
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
