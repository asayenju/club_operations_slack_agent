import importlib.util
from pathlib import Path


def load_bot_module(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    module_path = Path(__file__).resolve().parents[1] / "student-org-agent" / "app.py"
    spec = importlib.util.spec_from_file_location("student_org_agent_app", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
        command={"text": "  We approved snacks.  "},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {"response_type": "in_channel", "text": "Decision recorded: We approved snacks."},
    ]
    assert service.commands == [{"text": "  We approved snacks.  "}]


def test_handle_decide_command_rejects_empty_text(monkeypatch):
    bot = load_bot_module(monkeypatch)
    responses = []

    bot.handle_decide_command(
        ack=lambda: responses.append({"acked": True}),
        command={"text": "   "},
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
        command={"text": "We approved snacks."},
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
        command={"text": "We approved snacks."},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "I couldn't store that decision: database down",
        },
    ]
