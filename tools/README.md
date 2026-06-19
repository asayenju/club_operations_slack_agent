# Slack RTS Tool

This package contains LLM-callable tools for the club operations Slack agent.
The first tool wraps Slack's Real-time Search API so a future Claude integration
can retrieve public Slack message chunks for a prompt.

The active Bolt bot does not call this tool directly right now. The bot is back
to the simple `hello` test behavior, and this tool is ready for the future LLM
router.

## Tool Contract

`tools.slack_search` exports:

- `SLACK_RTS_SEARCH_TOOL`: Claude-compatible tool metadata
- `search_slack_public_context(...)`: Python function that calls Slack RTS
- `SlackSearchError`: wrapper error for Slack API failures

The metadata shape is:

```python
{
    "name": "search_slack_public_context",
    "description": "...",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "action_token": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query", "action_token"],
        "additionalProperties": False,
    },
}
```

## Function Arguments

```python
search_slack_public_context(
    client,
    query,
    action_token,
    limit=10,
)
```

- `client`: Slack `WebClient`
- `query`: natural-language search query
- `action_token`: sensitive short-lived Slack token from the current Slack interaction
- `limit`: result count, default 10, clamped between 1 and 20

Do not log, display, persist, or send `action_token` back to users. It should be
passed in memory from the Slack interaction/tool caller to Slack's API call.

## How It Works

1. A future LLM router receives a user question.
2. The router decides to call `search_slack_public_context`.
3. The router passes `query`, `action_token`, and optional `limit`.
4. The function calls Slack with:

```python
client.api_call("assistant.search.context", json=payload)
```

5. Slack returns public message context.
6. The function normalizes valid Slack messages into `RetrievedChunk` objects.

The installed Slack SDK does not expose a typed helper for
`assistant.search.context`, so the implementation uses the lower-level
`api_call(...)` method.

## Edge Cases

- Blank `query`: raises `ValueError`
- Missing `action_token`: raises `ValueError`
- Slack API error: raises `SlackSearchError`
- Empty results: returns an empty list
- Malformed message entries: ignored during normalization
- `limit` below 1 or above 20: clamped to Slack-compatible bounds
- Private-channel search: not supported in this tool version

## Required Slack App Configuration

The Slack app needs these bot scopes for public RTS search:

```text
chat:write
search:read.public
```

If a future Slack event flow provides `action_token`, that flow may need
additional event scopes such as `app_mentions:read`.

## Run Tests

Run all tests:

```bash
.venv/bin/python -m pytest -q
```

Run only Slack RTS tool tests:

```bash
.venv/bin/python -m pytest tests/test_slack_search.py -q
```

The tests mock Slack responses and do not call live Slack.

## Run With Docker

Build the Slack bot image:

```bash
docker compose build slack-bot
```

Run the Slack bot:

```bash
docker compose up --build slack-bot
```

Run it in the background:

```bash
docker compose up -d --build slack-bot
```

Check logs:

```bash
docker compose logs --no-color --tail=80 slack-bot
```

## Test In Slack

The current live bot behavior is the default Bolt `hello` test. You can test it
in Slack by sending:

```text
hello
```

The bot should reply with:

```text
Hey there <you>!
```

The RTS tool itself is tested through unit tests for now. It is ready to be
called by a future LLM/tool router that can provide a valid Slack `action_token`.
