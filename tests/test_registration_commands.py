import importlib.util
from pathlib import Path


class FakeRegistrationService:
    def __init__(self):
        self.registrations = []
        self.unregister_results = []

    def register(
        self,
        workspace_id,
        slack_user_id,
        email,
        display_name=None,
    ):
        self.registrations.append(
            {
                "workspace_id": workspace_id,
                "slack_user_id": slack_user_id,
                "email": email,
                "display_name": display_name,
            }
        )
        return "member@club.org"

    def unregister(self, workspace_id, slack_user_id):
        self.unregister_results.append((workspace_id, slack_user_id))
        return True


def load_bot_module(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "client-id-test")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "client-secret-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "signing-secret-test")
    monkeypatch.setenv("WORKSPACE_ID", "T123")
    module_path = Path(__file__).resolve().parents[1] / "student-org-agent" / "app.py"
    spec = importlib.util.spec_from_file_location("student_org_agent_register", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "configured_workspace_id", lambda: "T123")
    return module


def test_register_stores_normalized_self_mapping_and_confirms_ephemerally(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeRegistrationService()
    responses = []
    monkeypatch.setattr(bot, "build_registration_service", lambda: service)

    bot.handle_register_command(
        ack=lambda: responses.append({"acked": True}),
        command={
            "team_id": "T123",
            "user_id": "U123",
            "user_name": "aman",
            "text": "  Member@Club.ORG  ",
        },
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "Google account linked: member@club.org",
        },
    ]
    assert service.registrations == [
        {
            "workspace_id": "T123",
            "slack_user_id": "U123",
            "email": "member@club.org",
            "display_name": "aman",
        }
    ]


def test_register_rejects_invalid_email_without_persisting(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeRegistrationService()
    responses = []
    monkeypatch.setattr(bot, "build_registration_service", lambda: service)

    bot.handle_register_command(
        ack=lambda: responses.append({"acked": True}),
        command={
            "team_id": "T123",
            "user_id": "U123",
            "user_name": "aman",
            "text": "not-an-email",
        },
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "Usage: `/register you@example.com`",
        },
    ]
    assert service.registrations == []


def test_register_rejects_command_from_wrong_workspace(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeRegistrationService()
    responses = []
    monkeypatch.setattr(bot, "build_registration_service", lambda: service)
    monkeypatch.setattr(bot, "configured_workspace_id", lambda: "T_EXPECTED")

    bot.handle_register_command(
        ack=lambda: responses.append({"acked": True}),
        command={
            "team_id": "T_OTHER",
            "user_id": "U123",
            "text": "member@club.org",
        },
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "This command is not available in this workspace.",
        },
    ]
    assert service.registrations == []


def test_unregister_removes_self_mapping_and_confirms_ephemerally(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeRegistrationService()
    responses = []
    monkeypatch.setattr(bot, "build_registration_service", lambda: service)

    bot.handle_unregister_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "user_id": "U123"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "Google account unlinked.",
        },
    ]
    assert service.unregister_results == [("T123", "U123")]


def test_unregister_is_safe_when_no_mapping_exists(monkeypatch):
    bot = load_bot_module(monkeypatch)
    service = FakeRegistrationService()
    service.unregister = lambda workspace_id, slack_user_id: False
    responses = []
    monkeypatch.setattr(bot, "build_registration_service", lambda: service)

    bot.handle_unregister_command(
        ack=lambda: responses.append({"acked": True}),
        command={"team_id": "T123", "user_id": "U123"},
        respond=lambda **kwargs: responses.append(kwargs),
    )

    assert responses == [
        {"acked": True},
        {
            "response_type": "ephemeral",
            "text": "No Google account was registered.",
        },
    ]
