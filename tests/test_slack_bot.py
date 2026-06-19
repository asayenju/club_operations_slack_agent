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
