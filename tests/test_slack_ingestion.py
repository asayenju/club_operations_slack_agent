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
    assert row["author_id"] == "U01"
    assert row["channel_id"] == "C01"
    assert row["metadata"]["channel_name"] == "general"
    assert "user_id" not in row["metadata"]
    assert "channel_id" not in row["metadata"]


def test_ingest_stores_thread_ts_in_metadata(monkeypatch):
    upserted = []
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)

    slack_ingestion.ingest_slack_message("T123", _msg(thread_ts="1234567890.000001"))

    assert upserted[0]["metadata"]["thread_ts"] == "1234567890.000001"


# ---------------------------------------------------------------------------
# Slice 2 — delete_slack_message
# ---------------------------------------------------------------------------

def test_delete_targets_exact_chunk_key(monkeypatch):
    deleted_calls = []
    monkeypatch.setattr(
        slack_ingestion,
        "delete_chunk_key",
        lambda workspace_id, source, source_id, chunk_key: deleted_calls.append(
            (workspace_id, source, source_id, chunk_key)
        )
        or 1,
    )

    slack_ingestion.delete_slack_message("T123", "C01", "1234567890.000100")

    assert deleted_calls == [("T123", "slack", "C01", "C01:1234567890.000100")]


# ---------------------------------------------------------------------------
# Slice 3 — backfill_channel
# ---------------------------------------------------------------------------

def _channel(channel_id="C01", channel_name="general", **kwargs):
    defaults = {"channel_id": channel_id, "channel_name": channel_name, "backfill_limit": 200}
    defaults.update(kwargs)
    return defaults


def _key_state(hashes=None, meta=None):
    """Build the combined {chunk_key: {content_hash, metadata}} shape existing_key_state returns."""
    hashes = hashes or {}
    meta = meta or {}
    return {
        key: {"content_hash": content_hash, "metadata": meta.get(key, {})}
        for key, content_hash in hashes.items()
    }


class _FakeMonitoredTable:
    def __init__(self, recorder):
        self._recorder = recorder
        self._pending: dict = {}

    def update(self, fields):
        self._pending = fields
        return self

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        self._recorder.append(self._pending)
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self):
        self.updates: list[dict] = []

    def table(self, name):
        assert name == "monitored_channels"
        return _FakeMonitoredTable(self.updates)


def _fake_slack(messages):
    """Single-page fake: returns all given messages in one page (no next_cursor)."""
    class FakeClient:
        def conversations_history(self, **kwargs):
            limit = kwargs.get("limit", 200)
            return {"messages": messages[:limit], "response_metadata": {}}
    return FakeClient()


def _fake_slack_paginated(pages):
    """pages: list of (messages, next_cursor) tuples, one per expected call."""
    calls = []

    class FakeClient:
        def conversations_history(self, **kwargs):
            calls.append(kwargs)
            messages, next_cursor = pages[len(calls) - 1]
            meta = {"next_cursor": next_cursor} if next_cursor else {}
            return {"messages": messages, "response_metadata": meta}

    client = FakeClient()
    client.calls = calls
    return client


def test_backfill_ingests_new_messages(monkeypatch):
    upserted = []
    messages = [_raw(text=f"Message {i}", ts=f"100000000{i}.000000") for i in range(3)]
    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(_fake_slack(messages), _FakeSupabase(), "T123", _channel())

    assert result["ingested"] == 3
    assert len(upserted) == 3


def test_backfill_skips_existing_messages(monkeypatch):
    upserted = []
    messages = [_raw(text="Old message", ts="1000000000.000000")]
    monkeypatch.setattr(
        slack_ingestion, "existing_key_state",
        lambda *a: _key_state({"C01:1000000000.000000": "hash"}),
    )
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(_fake_slack(messages), _FakeSupabase(), "T123", _channel())

    assert result["ingested"] == 0
    assert upserted == []


def test_backfill_respects_limit(monkeypatch):
    fetched_kwargs = []

    class FakeClient:
        def conversations_history(self, **kwargs):
            fetched_kwargs.append(kwargs)
            return {"messages": [], "response_metadata": {}}

    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    slack_ingestion.backfill_channel(FakeClient(), _FakeSupabase(), "T123", _channel(backfill_limit=50))

    assert fetched_kwargs[0]["limit"] == 50


def test_backfill_filters_bot_messages(monkeypatch):
    upserted = []
    messages = [
        _raw(text="Real message", ts="1000000001.000000"),
        _raw(text="Bot noise", ts="1000000002.000000", bot_id="B01"),
    ]
    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(_fake_slack(messages), _FakeSupabase(), "T123", _channel())

    assert result["ingested"] == 1
    assert upserted[0]["content"] == "Real message"


def test_backfill_returns_zero_for_empty_channel(monkeypatch):
    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(_fake_slack([]), _FakeSupabase(), "T123", _channel())

    assert result["ingested"] == 0


def test_backfill_paginates_across_multiple_pages(monkeypatch):
    upserted = []
    page1 = ([_raw(text="A", ts="1000000001.000000")], "cursor-1")
    page2 = ([_raw(text="B", ts="1000000002.000000")], None)
    client = _fake_slack_paginated([page1, page2])
    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(client, _FakeSupabase(), "T123", _channel(backfill_limit=200))

    assert result["ingested"] == 2
    assert len(client.calls) == 2
    assert client.calls[1]["cursor"] == "cursor-1"


def test_backfill_resumes_from_oldest_ts_backfilled(monkeypatch):
    captured_kwargs = []

    class FakeClient:
        def conversations_history(self, **kwargs):
            captured_kwargs.append(kwargs)
            return {"messages": [], "response_metadata": {}}

    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    slack_ingestion.backfill_channel(
        FakeClient(), _FakeSupabase(), "T123",
        _channel(oldest_ts_backfilled="1000000000.000000"),
    )

    assert captured_kwargs[0]["oldest"] == "1000000000.000000"


def test_backfill_marks_initial_complete_when_cursor_exhausted(monkeypatch):
    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)
    supabase = _FakeSupabase()

    slack_ingestion.backfill_channel(_fake_slack([]), supabase, "T123", _channel())

    assert supabase.updates[-1]["initial_backfill_complete"] is True


class _FakeSlackResponse:
    def __init__(self, error: str, retry_after: str = "0"):
        self._error = error
        self.headers = {"Retry-After": retry_after}

    def get(self, key, default=None):
        return {"error": self._error}.get(key, default)


def test_backfill_retries_on_ratelimited_error(monkeypatch):
    from slack_sdk.errors import SlackApiError

    attempts = []

    class FakeClient:
        def conversations_history(self, **kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise SlackApiError("rate limited", _FakeSlackResponse("ratelimited"))
            return {"messages": [], "response_metadata": {}}

    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(FakeClient(), _FakeSupabase(), "T123", _channel())

    assert result["ingested"] == 0
    assert len(attempts) == 2


def test_backfill_gives_up_after_max_retries_and_records_error(monkeypatch):
    from slack_sdk.errors import SlackApiError

    class FakeClient:
        def conversations_history(self, **kwargs):
            raise SlackApiError("rate limited", _FakeSlackResponse("ratelimited"))

    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)
    supabase = _FakeSupabase()

    result = slack_ingestion.backfill_channel(FakeClient(), supabase, "T123", _channel())

    assert result["ingested"] == 0
    assert supabase.updates, "expected an error to be recorded"
    assert "last_backfill_error" in supabase.updates[-1]


# ---------------------------------------------------------------------------
# Slice 3 continued — thread reply fetching
# ---------------------------------------------------------------------------

def _fake_slack_with_replies(top_level_messages, replies_by_thread_ts):
    class FakeClient:
        def __init__(self):
            self.reply_calls: list[str] = []

        def conversations_history(self, **kwargs):
            return {"messages": top_level_messages, "response_metadata": {}}

        def conversations_replies(self, channel, ts, **kwargs):
            self.reply_calls.append(ts)
            replies = replies_by_thread_ts.get(ts, [])
            return {"messages": [{"ts": ts}] + replies, "response_metadata": {}}

    return FakeClient()


def test_backfill_fetches_thread_replies_for_new_threads(monkeypatch):
    upserted = []
    parent = _raw(text="Parent", ts="1000000001.000000", reply_count=1, latest_reply="1000000002.000000")
    reply = _raw(text="Reply", ts="1000000002.000000", thread_ts="1000000001.000000")
    client = _fake_slack_with_replies([parent], {"1000000001.000000": [reply]})

    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(client, _FakeSupabase(), "T123", _channel())

    assert result["ingested"] == 2
    assert client.reply_calls == ["1000000001.000000"]
    contents = {row["content"] for row in upserted}
    assert contents == {"Parent", "Reply"}


def test_backfill_skips_reply_fetch_when_latest_reply_unchanged(monkeypatch):
    upserted = []
    parent = _raw(text="Parent", ts="1000000001.000000", reply_count=1, latest_reply="1000000002.000000")
    client = _fake_slack_with_replies([parent], {"1000000001.000000": []})

    monkeypatch.setattr(
        slack_ingestion, "existing_key_state",
        lambda *a: _key_state(
            {"C01:1000000001.000000": "hash"},
            {"C01:1000000001.000000": {"latest_reply_ts": "1000000002.000000"}},
        ),
    )
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(client, _FakeSupabase(), "T123", _channel())

    assert result["ingested"] == 0
    assert client.reply_calls == []


def test_backfill_refetches_replies_when_latest_reply_advanced(monkeypatch):
    upserted = []
    parent = _raw(text="Parent", ts="1000000001.000000", reply_count=2, latest_reply="1000000003.000000")
    new_reply = _raw(text="New reply", ts="1000000003.000000", thread_ts="1000000001.000000")
    client = _fake_slack_with_replies([parent], {"1000000001.000000": [new_reply]})

    monkeypatch.setattr(
        slack_ingestion, "existing_key_state",
        lambda *a: _key_state(
            {"C01:1000000001.000000": "hash"},
            {"C01:1000000001.000000": {"latest_reply_ts": "1000000002.000000"}},
        ),
    )
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(client, _FakeSupabase(), "T123", _channel())

    assert client.reply_calls == ["1000000001.000000"]
    assert result["ingested"] == 1
    assert upserted[0]["content"] == "New reply"


# ---------------------------------------------------------------------------
# Slice 4 — per-message fault isolation
# ---------------------------------------------------------------------------

def test_backfill_continues_after_embedding_failure_for_one_message(monkeypatch):
    upserted = []
    messages = [_raw(text=f"Message {i}", ts=f"100000000{i}.000000") for i in range(3)]

    def flaky_embed(texts):
        if len(texts) > 1:
            raise RuntimeError("batch embed failed")
        if texts[0] == "Message 1":
            raise RuntimeError("this message is bad")
        return [[0.1] * 1024]

    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion, "embed_documents", flaky_embed)
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(_fake_slack(messages), _FakeSupabase(), "T123", _channel())

    assert result["ingested"] == 2
    assert result["failed"] == 1
    assert len(result["errors"]) == 1
    assert len(upserted) == 2
    assert {row["content"] for row in upserted} == {"Message 0", "Message 2"}


def test_backfill_reports_failed_count(monkeypatch):
    messages = [_raw(text="Bad message", ts="1000000005.000000")]

    def always_fails(texts):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion, "embed_documents", always_fails)
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", lambda rows: None)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(_fake_slack(messages), _FakeSupabase(), "T123", _channel())

    assert result["ingested"] == 0
    assert result["failed"] == 1
    assert "embedding service down" in result["errors"][0]


# ---------------------------------------------------------------------------
# Slice 5 — edit detection + deletion reconciliation (full_walk=True)
# ---------------------------------------------------------------------------

def test_reconcile_detects_edited_message_and_reembeds(monkeypatch):
    upserted = []
    messages = [_raw(text="Edited content", ts="1000000001.000000")]
    monkeypatch.setattr(
        slack_ingestion, "existing_key_state",
        lambda *a: _key_state({"C01:1000000001.000000": "stale-hash-that-does-not-match"}),
    )
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion, "delete_missing", lambda *a, **k: 0)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(
        _fake_slack(messages), _FakeSupabase(), "T123", _channel(), full_walk=True
    )

    assert result["ingested"] == 1
    assert upserted[0]["content"] == "Edited content"


def test_reconcile_leaves_unchanged_messages_alone(monkeypatch):
    upserted = []
    messages = [_raw(text="Same as before", ts="1000000001.000000")]
    unchanged_hash = slack_ingestion._content_hash("Same as before")
    monkeypatch.setattr(
        slack_ingestion, "existing_key_state",
        lambda *a: _key_state({"C01:1000000001.000000": unchanged_hash}),
    )
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(slack_ingestion, "delete_missing", lambda *a, **k: 0)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(
        _fake_slack(messages), _FakeSupabase(), "T123", _channel(), full_walk=True
    )

    assert result["ingested"] == 0
    assert upserted == []


def test_reconcile_deletes_messages_removed_from_slack(monkeypatch):
    delete_calls = []
    # Only one of the two previously-stored messages still exists in Slack.
    messages = [_raw(text="Still here", ts="1000000001.000000")]
    monkeypatch.setattr(
        slack_ingestion, "existing_key_state",
        lambda *a: _key_state({
            "C01:1000000001.000000": slack_ingestion._content_hash("Still here"),
            "C01:1000000002.000000": "some-hash",
        }),
    )
    monkeypatch.setattr(slack_ingestion, "embed_documents", lambda texts: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(slack_ingestion, "upsert_chunks", lambda rows: None)
    monkeypatch.setattr(
        slack_ingestion, "delete_missing",
        lambda workspace_id, source, source_id, current_keys: delete_calls.append(current_keys) or 1,
    )
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    result = slack_ingestion.backfill_channel(
        _fake_slack(messages), _FakeSupabase(), "T123", _channel(), full_walk=True
    )

    assert result["deleted"] == 1
    assert len(delete_calls) == 1
    kept_keys = delete_calls[0]
    assert "C01:1000000001.000000" in kept_keys
    assert "C01:1000000002.000000" not in kept_keys


def test_reconcile_full_walk_ignores_resume_bound(monkeypatch):
    captured_kwargs = []

    class FakeClient:
        def conversations_history(self, **kwargs):
            captured_kwargs.append(kwargs)
            return {"messages": [], "response_metadata": {}}

    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a: {})
    monkeypatch.setattr(slack_ingestion, "delete_missing", lambda *a, **k: 0)
    monkeypatch.setattr(slack_ingestion.time, "sleep", lambda s: None)

    slack_ingestion.backfill_channel(
        FakeClient(), _FakeSupabase(), "T123",
        _channel(oldest_ts_backfilled="1000000000.000000", backfill_limit=50),
        full_walk=True,
    )

    # full_walk must walk the whole channel — no `oldest` bound, no page-size
    # truncation from `backfill_limit` — otherwise the deletion diff below
    # would be computed against a partial view and wrongly delete rows.
    assert "oldest" not in captured_kwargs[0]
    assert captured_kwargs[0]["limit"] == slack_ingestion._HISTORY_PAGE_SIZE


# ---------------------------------------------------------------------------
# Slice 6 — run_channel_backfill (shared orchestration)
# ---------------------------------------------------------------------------

def test_run_channel_backfill_isolates_one_channel_failure(monkeypatch, capsys):
    """Regression test: PR #48 review found one channel's exception aborted
    every channel after it in the same run."""
    calls = []

    def fake_backfill_channel(slack_client, supabase_client, workspace_id, channel, full_walk=False):
        calls.append(channel["channel_id"])
        if channel["channel_id"] == "C_BAD":
            raise RuntimeError("boom")
        return slack_ingestion.BackfillResult(ingested=1, failed=0, errors=[], deleted=0)

    monkeypatch.setattr(slack_ingestion, "backfill_channel", fake_backfill_channel)
    monkeypatch.setattr(
        slack_ingestion, "list_monitored_channels",
        lambda sb: [_channel("C_BAD", "bad-channel"), _channel("C_GOOD", "good-channel")],
    )

    slack_ingestion.run_channel_backfill(object(), object(), "T123")

    # Both channels were attempted despite the first one raising.
    assert calls == ["C_BAD", "C_GOOD"]
    assert "unexpected error" in capsys.readouterr().out


def test_run_channel_backfill_decides_full_walk_per_channel(monkeypatch):
    seen_full_walk = {}

    def fake_backfill_channel(slack_client, supabase_client, workspace_id, channel, full_walk=False):
        seen_full_walk[channel["channel_id"]] = full_walk
        return slack_ingestion.BackfillResult(ingested=0, failed=0, errors=[], deleted=0)

    monkeypatch.setattr(slack_ingestion, "backfill_channel", fake_backfill_channel)
    monkeypatch.setattr(
        slack_ingestion, "list_monitored_channels",
        lambda sb: [
            _channel("C_DONE", "done", initial_backfill_complete=True),
            _channel("C_NOT_DONE", "not-done", initial_backfill_complete=False),
        ],
    )

    slack_ingestion.run_channel_backfill(object(), object(), "T123")

    assert seen_full_walk == {"C_DONE": True, "C_NOT_DONE": False}


def test_run_channel_backfill_force_full_walk_overrides_per_channel_state(monkeypatch):
    seen_full_walk = {}

    def fake_backfill_channel(slack_client, supabase_client, workspace_id, channel, full_walk=False):
        seen_full_walk[channel["channel_id"]] = full_walk
        return slack_ingestion.BackfillResult(ingested=0, failed=0, errors=[], deleted=0)

    monkeypatch.setattr(slack_ingestion, "backfill_channel", fake_backfill_channel)
    monkeypatch.setattr(
        slack_ingestion, "list_monitored_channels",
        lambda sb: [_channel("C_NOT_DONE", "not-done", initial_backfill_complete=False)],
    )

    slack_ingestion.run_channel_backfill(object(), object(), "T123", force_full_walk=True)

    assert seen_full_walk == {"C_NOT_DONE": True}


# ---------------------------------------------------------------------------
# Slice 4 — real-time handler (app.py)
# ---------------------------------------------------------------------------

def _load_app(monkeypatch, monitored_ids=("C01",)):
    import importlib.util
    from pathlib import Path

    monkeypatch.setenv("SLACK_CLIENT_ID", "client-id-test")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "client-secret-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "signing-secret-test")

    # Stub out Supabase + settings so the module loads without credentials
    monkeypatch.setattr("common.config.get_slack_settings", lambda: SimpleNamespace(
        supabase_url="http://fake",
        supabase_service_role_key="fake.fake.fake",
        slack_signing_secret="signing-secret-test",
        slack_client_id="client-id-test",
        slack_client_secret="client-secret-test",
        slack_port=3000,
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
    # Reset cached monitored channels so the stub takes effect
    bot._monitored_channels = {"C01": "general"}

    # Real Slack message events never include channel_name — only the ID.
    event = {"channel": "C01", "user": "U01", "text": "Hello", "ts": "1234567890.000100"}
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert len(ingested) == 1
    assert ingested[0]["text"] == "Hello"
    # channel_name must come from the monitored_channels cache, not the event
    assert ingested[0]["channel_name"] == "general"


def test_real_time_unmonitored_channel_skipped(monkeypatch):
    ingested = []
    monkeypatch.setattr(slack_ingestion, "ingest_slack_message", lambda ws, msg: ingested.append(msg))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    bot._monitored_channels = {"C01": "general"}

    event = {"channel": "C99", "user": "U01", "text": "Should not ingest",
              "ts": "1234567890.000100"}
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert ingested == []


def test_real_time_message_changed_reupserts(monkeypatch):
    ingested = []
    monkeypatch.setattr(slack_ingestion, "ingest_slack_message", lambda ws, msg: ingested.append(msg))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    bot._monitored_channels = {"C01": "general"}

    # Real message_changed events never include channel_name either.
    event = {
        "channel": "C01",
        "subtype": "message_changed",
        "message": {"user": "U01", "text": "Edited text", "ts": "1234567890.000100"},
    }
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert len(ingested) == 1
    assert ingested[0]["text"] == "Edited text"
    assert ingested[0]["channel_name"] == "general"


def test_real_time_message_deleted_removes(monkeypatch):
    deleted = []
    monkeypatch.setattr(slack_ingestion, "delete_slack_message",
                        lambda ws, ch, ts: deleted.append((ch, ts)))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    bot._monitored_channels = {"C01": "general"}

    event = {"channel": "C01", "subtype": "message_deleted", "deleted_ts": "1234567890.000100"}
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert deleted == [("C01", "1234567890.000100")]


def test_real_time_bot_message_not_ingested(monkeypatch):
    ingested = []
    monkeypatch.setattr(slack_ingestion, "ingest_slack_message", lambda ws, msg: ingested.append(msg))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    bot._monitored_channels = {"C01": "general"}

    event = {"channel": "C01", "bot_id": "B01", "text": "I am a bot",
              "ts": "1234567890.000100"}
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert ingested == []


def test_real_time_channel_name_never_falls_back_to_channel_id(monkeypatch):
    """Regression test: PR #48 review found channel_name silently became the
    raw channel ID because Slack message events never include channel_name.
    The config cache's name must be used even when it differs from the ID."""
    ingested = []
    monkeypatch.setattr(slack_ingestion, "ingest_slack_message", lambda ws, msg: ingested.append(msg))
    bot = _load_app(monkeypatch, monitored_ids=["C01"])
    bot._monitored_channels = {"C01": "club-announcements"}

    event = {"channel": "C01", "user": "U01", "text": "Hello", "ts": "1234567890.000100"}
    bot.handle_message(event, logger=SimpleNamespace(error=print))

    assert ingested[0]["channel_name"] == "club-announcements"
    assert ingested[0]["channel_name"] != "C01"
