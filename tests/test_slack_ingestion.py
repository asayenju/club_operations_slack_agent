from types import SimpleNamespace

from common import slack_ingestion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw(text="Hello world", ts="1234567890.000100", user="U01", **kwargs):
    return {"text": text, "ts": ts, "user": user, **kwargs}


def _msg(channel_id="C01", channel_name="general", **kwargs):
    defaults = {"ts": "1234567890.000100", "user_id": "U01", "text": "Hello world",
                "permalink": "", "thread_ts": None}
    defaults.update(kwargs)
    return slack_ingestion.SlackMessage(channel_id=channel_id, channel_name=channel_name, **defaults)


# ---------------------------------------------------------------------------
# Slice 1 — normalize_message
# ---------------------------------------------------------------------------

def test_normalize_valid_message():
    msg = slack_ingestion.normalize_message(_raw(), channel_id="C01", channel_name="general")

    assert msg is not None
    assert msg["channel_id"] == "C01"
    assert msg["channel_name"] == "general"
    assert msg["text"] == "Hello world"
    assert msg["user_id"] == "U01"


def test_normalize_filters_bot_messages():
    raw = _raw(bot_id="B01234")

    assert slack_ingestion.normalize_message(raw, "C01", "general") is None


def test_normalize_filters_bot_message_subtype():
    raw = _raw(subtype="bot_message")

    assert slack_ingestion.normalize_message(raw, "C01", "general") is None


def test_normalize_filters_system_events():
    for subtype in ("channel_join", "channel_leave", "channel_archive", "channel_name"):
        raw = _raw(subtype=subtype)
        assert slack_ingestion.normalize_message(raw, "C01", "general") is None, subtype


def test_normalize_returns_none_for_empty_text():
    assert slack_ingestion.normalize_message(_raw(text="   "), "C01", "general") is None


def test_normalize_preserves_thread_ts():
    raw = _raw(thread_ts="1234567890.000001")

    msg = slack_ingestion.normalize_message(raw, "C01", "general")

    assert msg is not None
    assert msg["thread_ts"] == "1234567890.000001"


def test_normalize_sets_thread_ts_none_for_top_level():
    msg = slack_ingestion.normalize_message(_raw(), "C01", "general")

    assert msg is not None
    assert msg["thread_ts"] is None


# ---------------------------------------------------------------------------
# Slice 2 — ingest_slack_message
# ---------------------------------------------------------------------------

def test_ingest_new_message_embeds_and_upserts(monkeypatch):
    upserted = []
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)

    slack_ingestion.ingest_slack_message("T123", _msg())

    assert len(upserted) == 1
    row = upserted[0]
    assert row["source"] == "slack"
    assert row["source_id"] == "C01"
    assert row["chunk_key"] == "C01:1234567890.000100"
    assert row["content"] == "Hello world"
    assert "content_hash" in row
    assert row["metadata"]["channel_name"] == "general"
    assert row["metadata"]["user_id"] == "U01"


def test_ingest_stores_thread_ts_in_metadata(monkeypatch):
    upserted = []
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)

    slack_ingestion.ingest_slack_message("T123", _msg(thread_ts="1234567890.000001"))

    assert upserted[0]["metadata"]["thread_ts"] == "1234567890.000001"


# ---------------------------------------------------------------------------
# Slice 2 — delete_slack_message
# ---------------------------------------------------------------------------

def test_delete_removes_chunk(monkeypatch):
    deleted_calls = []
    monkeypatch.setattr(
        slack_ingestion,
        "existing_keys",
        lambda workspace_id, source, source_id: {"C01:1234567890.000100", "C01:9999999999.000001"},
    )
    monkeypatch.setattr(
        slack_ingestion,
        "delete_missing",
        lambda workspace_id, source, source_id, current_keys: deleted_calls.append(current_keys) or 1,
    )

    slack_ingestion.delete_slack_message("T123", "C01", "1234567890.000100")

    assert len(deleted_calls) == 1
    # The deleted ts should NOT be in current_keys passed to delete_missing
    assert "C01:1234567890.000100" not in deleted_calls[0]
    assert "C01:9999999999.000001" in deleted_calls[0]


def test_delete_no_op_when_key_not_in_store(monkeypatch):
    deleted_calls = []
    monkeypatch.setattr(
        slack_ingestion,
        "existing_keys",
        lambda workspace_id, source, source_id: set(),
    )
    monkeypatch.setattr(
        slack_ingestion,
        "delete_missing",
        lambda workspace_id, source, source_id, current_keys: deleted_calls.append(current_keys) or 0,
    )

    slack_ingestion.delete_slack_message("T123", "C01", "9999999999.000001")

    # delete_missing still called but with empty set — no actual deletion
    assert deleted_calls[0] == set()


# ---------------------------------------------------------------------------
# Slice 3 — backfill_channel
# ---------------------------------------------------------------------------

def _fake_slack(messages):
    class FakeClient:
        def conversations_history(self, channel, limit):
            return {"messages": messages[:limit]}
    return FakeClient()


def test_backfill_ingests_new_messages(monkeypatch):
    upserted = []
    messages = [_raw(text=f"Message {i}", ts=f"100000000{i}.000000") for i in range(3)]
    monkeypatch.setattr(slack_ingestion, "existing_keys", lambda *a: set())
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)

    count = slack_ingestion.backfill_channel(_fake_slack(messages), "T123", "C01", "general")

    assert count == 3
    assert len(upserted) == 3


def test_backfill_skips_existing_messages(monkeypatch):
    upserted = []
    messages = [_raw(text="Old message", ts="1000000000.000000")]
    monkeypatch.setattr(
        slack_ingestion, "existing_keys", lambda *a: {"C01:1000000000.000000"}
    )
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)

    count = slack_ingestion.backfill_channel(_fake_slack(messages), "T123", "C01", "general")

    assert count == 0
    assert upserted == []


def test_backfill_respects_limit(monkeypatch):
    fetched_limit = []

    class FakeClient:
        def conversations_history(self, channel, limit):
            fetched_limit.append(limit)
            return {"messages": []}

    monkeypatch.setattr(slack_ingestion, "existing_keys", lambda *a: set())

    slack_ingestion.backfill_channel(FakeClient(), "T123", "C01", "general", limit=50)

    assert fetched_limit == [50]


def test_backfill_filters_bot_messages(monkeypatch):
    upserted = []
    messages = [
        _raw(text="Real message", ts="1000000001.000000"),
        _raw(text="Bot noise", ts="1000000002.000000", bot_id="B01"),
    ]
    monkeypatch.setattr(slack_ingestion, "existing_keys", lambda *a: set())
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)

    count = slack_ingestion.backfill_channel(_fake_slack(messages), "T123", "C01", "general")

    assert count == 1
    assert upserted[0]["content"] == "Real message"


def test_backfill_returns_zero_for_empty_channel(monkeypatch):
    monkeypatch.setattr(slack_ingestion, "existing_keys", lambda *a: set())

    count = slack_ingestion.backfill_channel(_fake_slack([]), "T123", "C01", "general")

    assert count == 0


# ---------------------------------------------------------------------------
# Slice 4 — real-time handler (app.py)
# ---------------------------------------------------------------------------

def _load_app(monkeypatch, monitored_ids=("C01",)):
    import importlib.util
    from pathlib import Path

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")

    # Stub out Supabase + settings so the module loads without credentials
    monkeypatch.setattr("common.config.get_slack_settings", lambda: SimpleNamespace(
        required_supabase_url="http://fake",
        required_supabase_service_key="fake",
        required_workspace_id="T123",
        slack_backfill_limit=200,
    ))

    module_path = Path(__file__).resolve().parents[1] / "student-org-agent" / "app.py"
    spec = importlib.util.spec_from_file_location("student_org_agent_app", module_path)
    module = importlib.util.module_from_spec(spec)

    # Patch slack_ingestion functions before exec so the module picks them up
    monkeypatch.setattr(slack_ingestion, "list_monitored_channels",
                        lambda sb: [{"channel_id": cid, "channel_name": cid} for cid in monitored_ids])

    spec.loader.exec_module(module)
    return module


def test_build_hello_response_mentions_user(monkeypatch):
    bot = _load_app(monkeypatch)

    response = bot.build_hello_response("U123")

    assert response["text"] == "Hey there <@U123>!"


def test_real_time_new_message_ingested(monkeypatch):
    ingested = []
    monkeypatch.setattr(slack_ingestion, "ingest_slack_message", lambda ws, msg: ingested.append(msg))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    # Reset cached monitored ids so the stub takes effect
    bot._monitored_channel_ids = {"C01"}

    event = {"channel": "C01", "channel_name": "general", "user": "U01",
              "text": "Hello", "ts": "1234567890.000100"}
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert len(ingested) == 1
    assert ingested[0]["text"] == "Hello"


def test_real_time_unmonitored_channel_skipped(monkeypatch):
    ingested = []
    monkeypatch.setattr(slack_ingestion, "ingest_slack_message", lambda ws, msg: ingested.append(msg))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    bot._monitored_channel_ids = {"C01"}

    event = {"channel": "C99", "user": "U01", "text": "Should not ingest",
              "ts": "1234567890.000100"}
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert ingested == []


def test_real_time_message_changed_reupserts(monkeypatch):
    ingested = []
    monkeypatch.setattr(slack_ingestion, "ingest_slack_message", lambda ws, msg: ingested.append(msg))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    bot._monitored_channel_ids = {"C01"}

    event = {
        "channel": "C01",
        "channel_name": "general",
        "subtype": "message_changed",
        "message": {"user": "U01", "text": "Edited text", "ts": "1234567890.000100"},
    }
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert len(ingested) == 1
    assert ingested[0]["text"] == "Edited text"


def test_real_time_message_deleted_removes(monkeypatch):
    deleted = []
    monkeypatch.setattr(slack_ingestion, "delete_slack_message",
                        lambda ws, ch, ts: deleted.append((ch, ts)))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    bot._monitored_channel_ids = {"C01"}

    event = {"channel": "C01", "subtype": "message_deleted", "deleted_ts": "1234567890.000100"}
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert deleted == [("C01", "1234567890.000100")]


def test_real_time_bot_message_not_ingested(monkeypatch):
    ingested = []
    monkeypatch.setattr(slack_ingestion, "ingest_slack_message", lambda ws, msg: ingested.append(msg))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    bot._monitored_channel_ids = {"C01"}

    event = {"channel": "C01", "bot_id": "B01", "text": "I am a bot",
              "ts": "1234567890.000100"}
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert ingested == []
