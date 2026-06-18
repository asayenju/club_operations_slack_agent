# Slack Real-Time Search Retrieval

This package contains the first retrieval tool for the club operations Slack
agent. It calls Slack's Real-time Search API and normalizes public Slack message
results into chunks that a future LLM prompt layer can use.

## What We Built

- `retrieval.models` defines the source-agnostic retrieval contract:
  - `SearchRequest`
  - `RetrievedChunk`
- `retrieval.slack_search` implements `search_slack_public_context(...)`.
- The Slack bot calls this function from the `app_mention` handler in
  `student-org-agent/app.py`.
- Results are returned as text snippets with Slack citations, channel metadata,
  author metadata, timestamps, and raw context metadata.

The current implementation is intentionally public-channel only. Private
channel retrieval is deferred until a user OAuth flow is added, because private
Slack search must run with user-granted permissions.

## How It Works

1. A user mentions the bot in a public Slack channel.
2. Slack sends an `app_mention` event to the Bolt app over Socket Mode.
3. The bot extracts the query text from the mention.
4. The bot calls `search_slack_public_context(...)` with:
   - Slack `WebClient`
   - the user query
   - the event `action_token`
   - a default limit of 10 results
5. The search function calls:

```python
client.api_call("assistant.search.context", json=payload)
```

6. Slack returns matching public message context.
7. The function maps Slack results into `RetrievedChunk` objects.
8. The bot posts the top chunks and permalinks back in the Slack thread.

The Slack SDK version in this repo does not expose a typed
`assistant_search_context` helper, so the implementation uses the lower-level
`api_call(...)` method.

## Required Slack App Configuration

The Slack app must have these bot scopes:

```text
app_mentions:read
channels:history
chat:write
search:read.public
```

The app must subscribe to this bot event:

```text
app_mention
```

Socket Mode must also be enabled, and `.env` must contain:

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

## Run Tests

Run the full local test suite:

```bash
.venv/bin/python -m pytest -q
```

The Slack search tests mock Slack API responses. They do not call live Slack.

## Run With Docker

Build and run only the Slack bot:

```bash
docker compose up --build slack-bot
```

Run it in the background:

```bash
docker compose up -d --build slack-bot
```

Check the container status:

```bash
docker compose ps slack-bot
```

Check logs:

```bash
docker compose logs --no-color --tail=80 slack-bot
```

Expected startup log:

```text
Bolt app is running!
```

## Test In Slack

Invite the bot to a public channel, then mention it with a question:

```text
@student-org-agent what did we decide about tabling?
```

The bot should reply in the thread with up to 10 public Slack results and links.

Plain messages and DMs do not trigger the real-time search flow in this version.
The current handler is only for `app_mention`.
