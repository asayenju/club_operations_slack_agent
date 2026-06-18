import importlib.util
from pathlib import Path

from retrieval.models import RetrievedChunk


def load_bot_module(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    module_path = Path(__file__).resolve().parents[1] / "student-org-agent" / "app.py"
    spec = importlib.util.spec_from_file_location("student_org_agent_app", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_query_removes_mentions(monkeypatch):
    bot = load_bot_module(monkeypatch)

    assert (
        bot.extract_query("<@U123ABC> what did we decide about budget?", "B123")
        == "what did we decide about budget?"
    )


def test_format_chunks_response_includes_citations(monkeypatch):
    bot = load_bot_module(monkeypatch)
    chunks = [
        RetrievedChunk(
            source="slack",
            text="We approved the spring tabling budget.",
            permalink="https://example.slack.com/archives/C123/p1710000000000100",
            channel_name="announcements",
            author_name="Priya",
        )
    ]

    response = bot.format_chunks_response("budget", chunks)

    assert "Top public Slack results for: `budget`" in response
    assert "*#announcements* - Priya" in response
    assert "We approved the spring tabling budget." in response
    assert "<https://example.slack.com/archives/C123/p1710000000000100|Open>" in response


def test_format_chunks_response_handles_no_results(monkeypatch):
    bot = load_bot_module(monkeypatch)

    assert bot.format_chunks_response("budget", []) == "No public Slack results found for: `budget`"
