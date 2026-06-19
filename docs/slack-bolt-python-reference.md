# Slack Bolt for Python: Consolidated Reference

A single-file reference for building Slack apps and agents with Bolt for Python. Pulls together app setup, listeners, interactivity, the Web API, streaming, MCP, and the Assistant class. Code blocks are reformatted for readability.

---

## Table of Contents

1. [What Bolt Is](#1-what-bolt-is)
2. [Creating an App](#2-creating-an-app)
3. [Tokens and Scopes](#3-tokens-and-scopes)
4. [Project Setup](#4-project-setup)
5. [Socket Mode vs HTTP](#5-socket-mode-vs-http)
6. [Setting Up Events](#6-setting-up-events)
7. [Listening to Messages](#7-listening-to-messages)
8. [Listening to Events](#8-listening-to-events)
9. [Slash Commands](#9-slash-commands)
10. [Actions](#10-actions)
11. [Shortcuts](#11-shortcuts)
12. [Opening Modals](#12-opening-modals)
13. [Select Menu Options](#13-select-menu-options)
14. [Sending Messages](#14-sending-messages)
15. [Streaming Messages](#15-streaming-messages)
16. [Feedback Buttons](#16-feedback-buttons)
17. [Using the Web API](#17-using-the-web-api)
18. [Listener Middleware](#18-listener-middleware)
19. [Agent Features](#19-agent-features)
20. [The Slack MCP Server](#20-the-slack-mcp-server)
21. [The Assistant Class](#21-the-assistant-class)

---

## 1. What Bolt Is

Bolt for Python is a framework for building Slack apps against the latest platform features. It wraps the Events API, interactivity, and the Web API behind a small set of decorators (`message`, `event`, `command`, `action`, `shortcut`, `options`, `view`). Available in JavaScript, Python, and Java; this doc covers Python.

Useful links: the [Issue Tracker](http://github.com/slackapi/bolt-python/issues) for bugs and questions, `support@slack.com` for developer support, and the [release notes](https://github.com/slackapi/bolt-python/releases).

---

## 2. Creating an App

Before writing any code, [create a Slack app](https://api.slack.com/apps/new). For development, use a throwaway workspace so you do not disrupt real work; you can [create one for free](https://slack.com/get-started#create).

After naming the app (changeable later) and picking a workspace, hit **Create App**. You land on the **Basic Information** page, which holds an overview plus the credentials you need later. Add an icon and description, then start configuring.

If you do not have a paid workspace, join the [Developer Program](https://api.slack.com/developer-program) to provision a free sandbox with access to all Slack features. This is the path that unlocks paid-tier features like the Assistant side panel and AI search.

---

## 3. Tokens and Scopes

Slack apps use OAuth to manage access. Installing an app yields a token used to call API methods. Three token types exist:

- **User tokens (`xoxp`)**: act on behalf of a user after they authenticate. Multiple per workspace possible.
- **Bot tokens (`xoxb`)**: tied to the app's bot user, granted once per workspace, identical regardless of who installed. Most apps use these.
- **App-level tokens (`xapp`)**: represent the app across a whole org, commonly used to open WebSocket (Socket Mode) connections.

### Getting your tokens

1. Go to **OAuth & Permissions**, scroll to **Bot Token Scopes**, click **Add an OAuth Scope**. Start with [`chat:write`](https://docs.slack.dev/reference/scopes/chat.write) so the app can post in channels it belongs to.
2. Scroll up and click **Install App to Workspace**, then approve the OAuth prompt.
3. Back on **OAuth & Permissions**, copy the **Bot User OAuth Access Token** (`xoxb-...`).
4. On **Basic Information**, under App-Level Tokens, click **Generate Token and Scopes**, add the `connections:write` scope, and save the `xapp-...` token.
5. Enable **Socket Mode** from the left nav.

Treat tokens like passwords. Never commit them to version control; load them from environment variables.

---

## 4. Project Setup

Create a directory and a virtual environment (Python 3.7 or later):

```bash
mkdir first-bolt-app
cd first-bolt-app

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Confirm the venv is active:

```bash
which python3
# /path/to/first-bolt-app/.venv/bin/python3
```

Export your tokens:

```bash
export SLACK_BOT_TOKEN=xoxb-<your-bot-token>
export SLACK_APP_TOKEN=<your-app-level-token>
```

Install Bolt:

```bash
pip install slack_bolt
```

Minimal `app.py` (Socket Mode):

```python
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Initialize with the bot token
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

# Start the app
if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
```

Run it:

```bash
python3 app.py
```

---

## 5. Socket Mode vs HTTP

**Socket Mode** opens a WebSocket from your app to Slack, so no public HTTP endpoint is required. Best for local development or behind-a-firewall setups. Requires the `xapp` app-level token and `connections:write`.

```python
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

app = App(token=os.environ["SLACK_BOT_TOKEN"])

# Add middleware / listeners here

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
```

**HTTP** mode runs a server with endpoints Slack posts to. Better for hosted deployments, large org workspaces, or Marketplace distribution. Requires a signing secret and a public Request URL ending in `/slack/events`.

```python
import os
from slack_bolt import App

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)

if __name__ == "__main__":
    app.start(port=int(os.environ.get("PORT", 3000)))
```

For local HTTP development, tunnel with a proxy like ngrok and point the Request URL at `https://<your-domain>/slack/events`.

### Async variant

For asyncio-based adapters (aiohttp, websockets), use `AsyncApp` and `AsyncSocketModeHandler`. The whole app must follow the async/await model.

```python
import os
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])

# Add middleware / listeners here

async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## 6. Setting Up Events

To react to things happening in a workspace (messages, reactions, joins), subscribe to [Events API](https://docs.slack.dev/apis/events-api/) event types.

**Socket Mode path:** enable Socket Mode, generate the app-level token with `connections:write`, then under **Event Subscriptions** toggle **Enable Events**.

**HTTP path:** under **Event Subscriptions**, enable events and set the Request URL to `https://<your-domain>/slack/events`. The URL verifies automatically while your app is running.

Under **Subscribe to Bot Events**, the four message-related events are:

- `message.channels`: messages in public channels the app is in
- `message.groups`: messages in private channels the app is in
- `message.im`: messages in the app's DMs
- `message.mpim`: messages in multi-person DMs the app is in

Pick the ones you need and save.

---

## 7. Listening to Messages

`message()` filters for `message` events and matches a `str` or compiled `re.Pattern`.

```python
@app.message("hello")
def message_hello(message, say):
    # say() posts back to the channel the event came from
    say(f"Hey there <@{message['user']}>!")
```

Emoji and regex both work:

```python
import re

@app.message(":wave:")
def say_hello(message, say):
    user = message["user"]
    say(f"Hi there, <@{user}>!")

@app.message(re.compile("(hi|hello|hey)"))
def say_hello_regex(say, context):
    # regex matches live in context["matches"]
    greeting = context["matches"][0]
    say(f"{greeting}, how are you?")
```

`message()` is equivalent to `event("message")`.

---

## 8. Listening to Events

`event()` takes an event type string and fires after you subscribe to it in app config.

```python
@app.event("team_join")
def ask_for_introduction(event, say):
    welcome_channel_id = "C12345"
    user_id = event["user"]
    text = f"Welcome to the team, <@{user_id}>! You can introduce yourself in this channel."
    say(text=text, channel=welcome_channel_id)
```

### Filtering on subtypes

Pass a dict with `subtype`. Use `None` to match events that have no subtype.

```python
@app.event({"type": "message", "subtype": "message_changed"})
def log_message_change(logger, event):
    user, text = event["user"], event["text"]
    logger.info(f"The user {user} changed the message to {text}")
```

---

## 9. Slash Commands

`command()` listens for a slash command by name. Always `ack()` to confirm receipt. Respond with `say()` (posts a message) or `respond()` (uses the `response_url`). Append `/slack/events` to the Request URL in config.

```python
@app.command("/echo")
def repeat_text(ack, respond, command):
    ack()
    respond(f"{command['text']}")
```

---

## 10. Actions

`action()` listens for interactive component events (button clicks, menu selects), keyed on `action_id` (`str` or `re.Pattern`). Always `ack()`.

```python
@app.action("approve_button")
def update_message(ack):
    ack()
    # Update the message to reflect the action
```

### Constraint objects

Match on combinations of `block_id` and `action_id`:

```python
@app.action({"block_id": "assign_ticket", "action_id": "select_user"})
def update_message(ack, body, client):
    ack()
    if "container" in body and "message_ts" in body["container"]:
        client.reactions_add(
            name="white_check_mark",
            channel=body["channel"]["id"],
            timestamp=body["container"]["message_ts"],
        )
```

### Responding

`say()` posts back to the conversation; `respond()` is a utility over the `response_url` and accepts message payload props plus `response_type` (`"in_channel"` or `"ephemeral"`), `replace_original`, `delete_original`, and the unfurl flags.

```python
@app.action("approve_button")
def approve_request(ack, say):
    ack()
    say("Request approved 👍")

@app.action("user_select")
def select_user(ack, action, respond):
    ack()
    respond(f"You selected <@{action['selected_user']}>")
```

---

## 11. Shortcuts

`shortcut()` handles both global and message shortcuts, keyed on a `callback_id`. Acknowledge with `ack()`. Shortcuts carry a `trigger_id` you can use to open a modal.

Note: global shortcuts do not include a channel ID (use a `conversations_select` element in a modal if you need one). Message shortcuts do include a channel ID.

```python
@app.shortcut("open_modal")
def open_modal(ack, shortcut, client):
    ack()
    client.views_open(
        trigger_id=shortcut["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "My App"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "About the simplest modal you could conceive of :smile:",
                    },
                }
            ],
        },
    )
```

Constraint-object form (match `callback_id` AND `type`):

```python
@app.shortcut({"callback_id": "open_modal", "type": "message_action"})
def open_modal(ack, shortcut, client):
    ack()
    # ... open a view
```

---

## 12. Opening Modals

Open a modal with `views.open`, passing a valid `trigger_id` (from a slash command, button, or menu interaction) and a view payload. The `trigger_id` must be used within 3 seconds.

```python
@app.shortcut("open_modal")
def open_modal(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "view_1",
            "title": {"type": "plain_text", "text": "My App"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Welcome to a modal with _blocks_"},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Click me!"},
                        "action_id": "button_abc",
                    },
                },
                {
                    "type": "input",
                    "block_id": "input_c",
                    "label": {"type": "plain_text", "text": "What are your hopes and dreams?"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "dreamy_input",
                        "multiline": True,
                    },
                },
            ],
        },
    )
```

---

## 13. Select Menu Options

`options()` responds to external-data select menus. Like `action()`, it needs an `action_id` or constraints object. Provide an options load URL (ending `/slack/events`) in config. Respond by calling `ack()` with an `options` or `option_groups` list. You can filter on the typed `value` from the `payload`.

```python
@app.options("external_action")
def show_options(ack, payload):
    options = [
        {"text": {"type": "plain_text", "text": "Option 1"}, "value": "1-1"},
        {"text": {"type": "plain_text", "text": "Option 2"}, "value": "1-2"},
    ]
    keyword = payload.get("value")
    if keyword:
        options = [o for o in options if keyword in o["text"]["text"]]
    ack(options=options)
```

---

## 14. Sending Messages

`say()` is available in any listener tied to a conversation. It accepts a string or a JSON payload. For sends outside a listener or finer control, call `client.chat_postMessage`.

```python
@app.message("knock knock")
def ask_who(message, say):
    say("_Who's there?_")
```

### With blocks

Blocks are the building units of a message (text, images, datepickers, buttons). When using `blocks`, include `text` as a notification/accessibility fallback.

```python
@app.event("reaction_added")
def show_datepicker(event, say):
    if event["reaction"] == "calendar":
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Pick a date for me to remind you"},
                "accessory": {
                    "type": "datepicker",
                    "action_id": "datepicker_remind",
                    "initial_date": "2020-05-04",
                    "placeholder": {"type": "plain_text", "text": "Select a date"},
                },
            }
        ]
        say(blocks=blocks, text="Pick a date for me to remind you")
```

### Message + button + handler

A common interactive pattern: post a button, then handle the click.

```python
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

@app.message("hello")
def message_hello(message, say):
    say(
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Hey there <@{message['user']}>!"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Click Me"},
                    "action_id": "button_click",
                },
            }
        ],
        text=f"Hey there <@{message['user']}>!",
    )

@app.action("button_click")
def action_button_click(body, ack, say):
    ack()
    say(f"<@{body['user']['id']}> clicked the button")

if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
```

Prototype block layouts in the [Block Kit Builder](https://app.slack.com/block-kit-builder), which generates pasteable JSON.

---

## 15. Streaming Messages

`say_stream` streams a response in to mimic agent behavior. It is a listener argument for `app.event` and `app.message`, and wraps the SDK's `chat_stream`, sourcing `channel_id`, `thread_ts`, `recipient_team_id`, and `recipient_user_id` from the event payload. If `channel_id` or `thread_ts` cannot be sourced, the utility is `None`.

```python
streamer = say_stream()
streamer.append(markdown_text="Here's my response...")
streamer.append(markdown_text="And here's more...")
streamer.stop()
```

Full listener example:

```python
import os
from slack_bolt import App, SayStream
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

@app.event("app_mention")
def handle_app_mention(client: WebClient, say_stream: SayStream):
    stream = say_stream()
    stream.append(markdown_text="Someone rang the bat signal!")
    stream.stop()

@app.message("")
def handle_message(client: WebClient, say_stream: SayStream):
    stream = say_stream()
    stream.append(markdown_text="Let me consult my *vast knowledge database*...")
    stream.stop()

if __name__ == "__main__":
    SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN")).start()
```

---

## 16. Feedback Buttons

Pass a feedback-buttons block element to `stream.stop` to render thumbs up/down at the bottom of a message. Clicks fire a block action event.

```python
from slack_sdk.models.blocks import (
    Block,
    ContextActionsBlock,
    FeedbackButtonObject,
    FeedbackButtonsElement,
)

def build_feedback_blocks() -> list[Block]:
    return [
        ContextActionsBlock(
            elements=[
                FeedbackButtonsElement(
                    action_id="feedback",
                    positive_button=FeedbackButtonObject(
                        text="Good Response",
                        accessibility_label="Submit positive feedback on this response",
                        value="good-feedback",
                    ),
                    negative_button=FeedbackButtonObject(
                        text="Bad Response",
                        accessibility_label="Submit negative feedback on this response",
                        value="bad-feedback",
                    ),
                )
            ]
        )
    ]
```

Render them when stopping the stream:

```python
streamer = say_stream()
streamer.append(markdown_text=result.output)
feedback_blocks = build_feedback_blocks()
streamer.stop(blocks=feedback_blocks)
```

Handle the click:

```python
from logging import Logger
from slack_bolt import Ack, BoltContext
from slack_sdk import WebClient

def handle_feedback_button(
    ack: Ack, body: dict, client: WebClient, context: BoltContext, logger: Logger
):
    ack()
    try:
        channel_id = context.channel_id
        user_id = context.user_id
        message_ts = body["message"]["ts"]
        feedback_value = body["actions"][0]["value"]

        if feedback_value == "good-feedback":
            client.chat_postEphemeral(
                channel=channel_id, user=user_id, thread_ts=message_ts,
                text="Glad that was helpful! :tada:",
            )
        else:
            client.chat_postEphemeral(
                channel=channel_id, user=user_id, thread_ts=message_ts,
                text="Sorry that wasn't helpful. Try rephrasing, or I can open a ticket.",
            )
    except Exception as e:
        logger.exception(f"Failed to handle feedback: {e}")
```

---

## 17. Using the Web API

Call [any Web API method](https://docs.slack.dev/reference/methods) (200+) via the `WebClient` exposed as `app.client` or as `client` in listeners, provided the app has the right scopes. Each call returns a `SlackResponse`. The init token lives on the `context` object.

```python
@app.message("wake me up")
def say_hello(client, message):
    # Unix epoch for September 30, 2020 11:59:59 PM
    when_september_ends = 1601510399
    channel_id = message["channel"]
    client.chat_scheduleMessage(
        channel=channel_id,
        post_at=when_september_ends,
        text="Summer has come and passed",
    )
```

---

## 18. Listener Middleware

Listener middleware runs only for the listener it is attached to, passed via the `middleware` list. Each middleware calls `next()` to proceed. A simpler form, a listener matcher, returns a `bool` instead.

```python
# Middleware: drop bot messages
def no_bot_messages(message, next):
    if "bot_id" not in message:
        next()

@app.event(event="message", middleware=[no_bot_messages])
def log_message(logger, event):
    logger.info(f"(MSG) User: {event['user']} Message: {event['text']}")

# Matcher form
def no_bot_messages_matcher(message) -> bool:
    return "bot_id" not in message

@app.event(event="message", matchers=[no_bot_messages_matcher])
def log_message_2(logger, event):
    logger.info(f"(MSG) User: {event['user']} Message: {event['text']}")
```

---

## 19. Agent Features

Agents can be invoked by `@mention` in channels, by DM, and through the Assistant side panel. They can stream text, attach feedback buttons, set a working status, and use the `Assistant` class for an AI-focused side panel. The reference implementation is the [Casey support agent](https://github.com/slack-samples/bolt-python-support-agent), which integrates with Pydantic, Anthropic, and OpenAI.

### Set status

Show background activity while the agent works:

```python
def handle_app_mentioned(set_status, ...):
    set_status(
        status="Thinking...",
        loading_messages=[
            "Teaching the hamsters to type faster…",
            "Untangling the internet cables…",
            "Consulting the office goldfish…",
            "Polishing up the response just for you…",
            "Convincing the AI to stop overthinking…",
        ],
    )
```

### Suggested prompts on thread start

```python
from logging import Logger
from slack_bolt.context.set_suggested_prompts import SetSuggestedPrompts

SUGGESTED_PROMPTS = [
    {"title": "Reset Password", "message": "I need to reset my password"},
    {"title": "Request Access", "message": "I need access to a system or tool"},
    {"title": "Network Issues", "message": "I'm having network connectivity issues"},
]

def handle_assistant_thread_started(set_suggested_prompts: SetSuggestedPrompts, logger: Logger):
    try:
        set_suggested_prompts(prompts=SUGGESTED_PROMPTS, title="How can I help you today?")
    except Exception as e:
        logger.exception(f"Failed to handle assistant thread started: {e}")
```

### Full app-mention handler (Anthropic flavor)

This ties together status, history, agent run, streaming, and feedback.

```python
import re
from logging import Logger
from slack_bolt import BoltContext, Say, SayStream, SetStatus
from slack_sdk import WebClient

from agent import CaseyDeps, casey_agent, get_model
from thread_context import conversation_store
from listeners.views.feedback_builder import build_feedback_blocks

def handle_app_mentioned(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
    say: Say,
    say_stream: SayStream,
    set_status: SetStatus,
):
    """Handle @Casey mentions in channels."""
    try:
        channel_id = context.channel_id
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event["ts"]
        user_id = context.user_id

        # Strip the bot mention from the text
        cleaned_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
        if not cleaned_text:
            say(
                text="Hey there! Describe your issue and I'll do my best to assist.",
                thread_ts=thread_ts,
            )
            return

        # Eyes reaction only on the first (non-threaded) message
        if not event.get("thread_ts"):
            client.reactions_add(channel=channel_id, timestamp=event["ts"], name="eyes")

        set_status(
            status="Thinking...",
            loading_messages=[
                "Teaching the hamsters to type faster…",
                "Untangling the internet cables…",
                "Consulting the office goldfish…",
            ],
        )

        history = conversation_store.get_history(channel_id, thread_ts)

        deps = CaseyDeps(
            client=client,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            message_ts=event["ts"],
        )
        result = casey_agent.run_sync(
            cleaned_text, model=get_model(), deps=deps, message_history=history
        )

        # Stream the response and attach feedback buttons
        streamer = say_stream()
        streamer.append(markdown_text=result.output)
        streamer.stop(blocks=build_feedback_blocks())

        conversation_store.set_history(channel_id, thread_ts, result.all_messages())
    except Exception as e:
        logger.exception(f"Failed to handle app mention: {e}")
        say(text=f":warning: Something went wrong! ({e})", thread_ts=event.get("thread_ts") or event["ts"])
```

### Handling DMs and thread replies

The message handler must skip subtypes and unrelated bot messages, and only engage in channel threads where the bot is already active.

```python
def handle_message(client, context, event, logger, say, say_stream, set_status):
    is_issue_submission = event.get("metadata", {}).get("event_type") == "issue_submission"

    if event.get("subtype"):
        return
    if event.get("bot_id") and not is_issue_submission:
        return

    is_dm = event.get("channel_type") == "im"
    is_thread_reply = event.get("thread_ts") is not None

    if is_dm:
        pass
    elif is_thread_reply:
        session = session_store.get_session(context.channel_id, event["thread_ts"])
        if session is None:
            return  # bot not engaged in this thread
    else:
        return  # top-level channel messages handled by app_mention
    # ... run the agent
```

### Adding a custom tool

Define a tool with the `@tool` decorator, then register it.

```python
from claude_agent_sdk import tool
import httpx

@tool(
    name="check_github_status",
    description="Check GitHub's current operational status",
    input_schema={},
)
async def check_github_status_tool(args):
    async with httpx.AsyncClient() as client:
        response = await client.get("https://www.githubstatus.com/api/v2/status.json")
        data = response.json()
        status = data["status"]["indicator"]
        description = data["status"]["description"]
        return {
            "content": [
                {"type": "text", "text": f"**GitHub Status** — {status}\n{description}"}
            ]
        }
```

Register it in the tools server and the tool list:

```python
from agent.tools import check_github_status_tool

casey_tools_server = create_sdk_mcp_server(
    name="casey-tools",
    version="1.0.0",
    tools=[check_github_status_tool],
)

CASEY_TOOLS = ["check_github_status"]
```

---

## 20. The Slack MCP Server

An agent can use the [Slack MCP Server](https://docs.slack.dev/ai/slack-mcp-server/developing) when deployed over HTTP with OAuth. Setup outline:

1. Start an ngrok tunnel: `ngrok http 3000`, copy the `https://*.ngrok-free.app` URL.
2. In `manifest.json`, set `socket_mode_enabled` to `false` and use your ngrok domain.
3. Create a local dev app: `slack install -E local`.
4. Enable MCP: run `slack app settings`, go to **Agents & AI Apps**, toggle **Model Context Protocol** on.
5. Set OAuth env vars (Client ID, Client Secret, Signing Secret, redirect URI):

```bash
SLACK_CLIENT_ID=YOUR_CLIENT_ID
SLACK_CLIENT_SECRET=YOUR_CLIENT_SECRET
SLACK_REDIRECT_URI=https://YOUR_NGROK_SUBDOMAIN.ngrok-free.app/slack/oauth_redirect
SLACK_SIGNING_SECRET=YOUR_SIGNING_SECRET
```

6. Start: `slack run app_oauth.py`, then open the printed install URL to install via OAuth.

---

## 21. The Assistant Class

The `Assistant` class handles events from a user interacting with an app that has **Agents & AI Apps** enabled. Typical flow: the user starts a thread (`assistant_thread_started`), the thread context may change (`assistant_thread_context_changed`), and the user replies (`message.im`). Some features here require a paid plan or a Developer Program sandbox.

### Config

In App Settings: enable **Agents & AI Apps**. Add scopes `assistant:write`, `chat:write`, `im:history`. Subscribe to events `assistant_thread_started`, `assistant_thread_context_changed`, `message.im`.

### Skeleton

```python
assistant = Assistant()

@assistant.thread_started
def start_assistant_thread(say, get_thread_context, set_suggested_prompts, logger):
    ...

@assistant.user_message
def respond_in_assistant_thread(client, context, get_thread_context, logger, payload, say, set_status):
    ...

# Enable the middleware
app.use(assistant)
```

### Handling a new thread

When a user opens a thread from inside a channel, the channel info is stored as `AssistantThreadContext`. Grab it with `get_thread_context`, since later message payloads will not include it.

```python
assistant = Assistant()

@assistant.thread_started
def start_assistant_thread(say, get_thread_context, set_suggested_prompts, logger):
    try:
        say("How can I help you?")
        prompts = [
            {
                "title": "Suggest names for my Slack app",
                "message": "Can you suggest a few names for my Slack app? It helps teammates organize info and plan priorities.",
            },
        ]
        thread_context = get_thread_context()
        if thread_context is not None and thread_context.channel_id is not None:
            prompts.append({
                "title": "Summarize the referred channel",
                "message": "Can you generate a brief summary of the referred channel?",
            })
        set_suggested_prompts(prompts=prompts)
    except Exception as e:
        logger.exception(f"Failed to handle assistant_thread_started: {e}")
        say(f":warning: Something went wrong! ({e})")
```

### Thread context storage

By default the middleware saves updated context as message metadata on the app's first reply, which adds calls to `conversations.history`. To store context elsewhere, pass a custom `AssistantThreadContextStore` to the constructor (the bundled `FileAssistantThreadContextStore` is a local-file reference implementation, not for production).

```python
from slack_bolt import FileAssistantThreadContextStore

assistant = Assistant(thread_context_store=FileAssistantThreadContextStore())
```

A custom store must implement `find` and `save`.

### Handling the user response

`message.im` events carry no subtype, so deduce intent from shape and metadata. Useful utilities: `say`, `set_title`, `set_status` (which can cycle through `loading_messages`).

```python
@assistant.user_message
def respond_in_assistant_thread(client, context, get_thread_context, logger, payload, say, set_status):
    try:
        set_status(
            status="thinking...",
            loading_messages=[
                "Untangling the internet cables…",
                "Consulting the office goldfish…",
                "Convincing the AI to stop overthinking…",
            ],
        )

        replies = client.conversations_replies(
            channel=context.channel_id,
            ts=context.thread_ts,
            oldest=context.thread_ts,
            limit=10,
        )
        messages_in_thread = []
        for message in replies["messages"]:
            role = "user" if message.get("bot_id") is None else "assistant"
            messages_in_thread.append({"role": role, "content": message["text"]})

        returned_message = call_llm(messages_in_thread)
        say(text=returned_message)
    except Exception as e:
        logger.exception(f"Failed to respond to an inquiry: {e}")
        # Always send something on error, or the "is typing..." status never clears
        say(f":warning: Sorry, something went wrong (error: {e})")

app.use(assistant)
```

### Block Kit alongside messages

For advanced flows you can use buttons instead of suggested prompts and pass structured metadata to drive follow-up interactions. By default an app cannot respond to its own bot messages (Bolt prevents loops). To opt in, pass `ignoring_self_assistant_message_events_enabled=False` and add a `bot_message` listener.

```python
app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    ignoring_self_assistant_message_events_enabled=False,  # needed for bot_message
)
assistant = Assistant()

@assistant.thread_started
def start_assistant_thread(say):
    say(
        text=":wave: Hi, how can I help you today?",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": ":wave: Hi, how can I help you today?"}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "assistant-generate-random-numbers",
                        "text": {"type": "plain_text", "text": "Generate random numbers"},
                        "value": "clicked",
                    }
                ],
            },
        ],
    )

@app.action("assistant-generate-random-numbers")
def configure_random_number_generation(ack, client, body):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "configure_assistant_summarize_channel",
            "title": {"type": "plain_text", "text": "My Assistant"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "private_metadata": json.dumps({
                "channel_id": body["channel"]["id"],
                "thread_ts": body["message"]["thread_ts"],
            }),
            "blocks": [
                {
                    "type": "input",
                    "block_id": "num",
                    "label": {"type": "plain_text", "text": "# of outputs"},
                    "element": {
                        "type": "static_select",
                        "action_id": "input",
                        "placeholder": {"type": "plain_text", "text": "How many numbers?"},
                        "options": [
                            {"text": {"type": "plain_text", "text": "5"}, "value": "5"},
                            {"text": {"type": "plain_text", "text": "10"}, "value": "10"},
                            {"text": {"type": "plain_text", "text": "20"}, "value": "20"},
                        ],
                        "initial_option": {"text": {"type": "plain_text", "text": "5"}, "value": "5"},
                    },
                }
            ],
        },
    )

@app.view("configure_assistant_summarize_channel")
def receive_random_number_generation_details(ack, client, payload):
    ack()
    num = payload["state"]["values"]["num"]["input"]["selected_option"]["value"]
    thread = json.loads(payload["private_metadata"])
    client.chat_postMessage(
        channel=thread["channel_id"],
        thread_ts=thread["thread_ts"],
        text=f"OK, you need {num} numbers. I will generate it shortly!",
        metadata={
            "event_type": "assistant-generate-random-numbers",
            "event_payload": {"num": int(num)},
        },
    )

@assistant.bot_message
def respond_to_bot_messages(logger, set_status, say, payload):
    try:
        if payload.get("metadata", {}).get("event_type") == "assistant-generate-random-numbers":
            set_status("is generating an array of random numbers...")
            time.sleep(1)
            nums = set()
            num = payload["metadata"]["event_payload"]["num"]
            while len(nums) < num:
                nums.add(str(random.randint(1, 100)))
            say(f"Here you are: {', '.join(nums)}")
        else:
            pass  # be careful not to create an infinite messaging loop
    except Exception as e:
        logger.exception(f"Failed to respond to an inquiry: {e}")
```

---

## Quick Reference: Decorators

| Decorator | Fires on | Must `ack()`? |
|---|---|---|
| `@app.message(pattern)` | message events matching a string/regex | No |
| `@app.event(type)` | any subscribed Events API event | No |
| `@app.command("/name")` | slash command | Yes |
| `@app.action(action_id)` | button/menu interaction | Yes |
| `@app.shortcut(callback_id)` | global or message shortcut | Yes |
| `@app.view(callback_id)` | modal submission | Yes |
| `@app.options(action_id)` | external select menu load | `ack(options=...)` |
| `@assistant.thread_started` | `assistant_thread_started` | No |
| `@assistant.user_message` | `message.im` in an assistant thread | No |
| `@assistant.bot_message` | the app's own bot messages (opt-in) | No |

---

*Compiled from the official Slack Bolt for Python documentation at docs.slack.dev. Prose summarized; code reformatted for readability.*
