import importlib.util
from pathlib import Path
from types import SimpleNamespace

from memoryAnswer.service import MemoryAnswer


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
