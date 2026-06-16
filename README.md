# Club Operations Slack Agent

A FastAPI service with Slack Bolt wired in for a future club handover assistant.
The first version confirms the Slack app can receive mentions and direct
messages, then responds with a placeholder while the knowledge layer is built.

## Requirements

- Docker and Docker Compose
- Slack app credentials:
  - Bot token (`xoxb-...`)
  - Signing secret

## Local setup

Create a local environment file:

```bash
cp .env.example .env
```

Fill in `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET`, then run:

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`.

`SLACK_TOKEN_VERIFICATION_ENABLED` defaults to `false` so the app can start
locally without calling Slack during boot. Set it to `true` later if you want
startup to fail fast when the bot token is invalid.

Check the service:

```bash
curl http://localhost:8000/health
```

## Slack setup

In the Slack app configuration:

1. Add bot scopes:
   - `app_mentions:read`
   - `chat:write`
   - `im:history`
   - `im:read`
2. Enable Event Subscriptions.
3. Set the request URL to your public tunnel URL plus `/slack/events`.
   For local development, expose the Docker service with a tunnel such as
   ngrok or Cloudflare Tunnel.
4. Subscribe to bot events:
   - `app_mention`
   - `message.im`
5. Install or reinstall the app to the workspace after changing scopes.

## Development

Run tests locally after installing dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

The main app lives in `app/main.py`; Slack handlers live in `app/slack_app.py`.
