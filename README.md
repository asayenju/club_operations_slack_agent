# Club Operations Ingestion API

A FastAPI service for future student organization document and spreadsheet
ingestion webhooks.

## Requirements

- Docker and Docker Compose

## Local setup

Create a local environment file:

```bash
cp .env.example .env
```

Fill in the required values in `.env`, then run:

```bash
docker compose up --build
```

The ingestion API will be available at `http://localhost:8000`.
The Slack bot serves events, slash commands, interactivity, and OAuth
install/redirect over HTTP (not Socket Mode, and not a single static bot
token) — see [Multi-workspace install (OAuth)](#multi-workspace-install-oauth)
below.

The Slack bot responds to messages containing `hello` and supports `/decide`
for recording club decisions into the existing Supabase `documents` table.
Decisions are stored as sentence-aware chunks and embedded with Voyage before
insertion. Slack Real-time Search is implemented separately under `tools/` as
a function/tool for a future LLM integration. The bot also backfills and
ingests messages from explicitly monitored channels in the background — see
[Slack message ingestion](#slack-message-ingestion) below.

Required `.env` values for `/decide`:

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
VOYAGE_API_KEY=...
VOYAGE_EMBED_MODEL=...
VOYAGE_EMBED_DIMENSION=...
```

`SUPABASE_SERVICE_KEY` is also accepted as an alias for
`SUPABASE_SERVICE_ROLE_KEY`. If `VOYAGE_EMBED_MODEL` is not set, the bot uses
`voyage-3.5-lite`. If `VOYAGE_EMBED_DIMENSION` is not set, the bot requests
1024-dimensional embeddings.

Do not expose the Supabase service key or `VOYAGE_API_KEY` to clients. They are
server-side values used by the Slack bot container.

Check the ingestion API:

```bash
curl http://localhost:8000/health
```

Run only the Slack bot:

```bash
docker compose up --build slack-bot
```

Test the bot by inviting it to a public channel and sending:

```text
hello
```

You can also test it in Slack by sending `hello` in a channel or DM where the
bot is present.

Test `/decide` in Slack:

```text
/decide We approved $300 for tabling supplies.
```

On success, the bot posts a public confirmation that echoes the decision. Empty
input, duplicate content, embedding failures, and database failures are shown
only to the user who ran the command.

Internally, `/decide` chunks each decision before embedding. Each chunk is stored
as its own `documents` row with metadata that links it back to the full decision.
The current implementation uses local deterministic sentence packing rather
than LangChain, while keeping the chunking boundary isolated for a future
semantic chunker.

The Slack app manifest includes `/decide`, but the Slack app must be updated or
reinstalled for the slash command to appear in the workspace.

## Multi-workspace install (OAuth)

The app is installable by more than one Slack workspace at once (issue #61).
Each installing workspace gets its own bot token via Slack's OAuth flow
rather than sharing one static `SLACK_BOT_TOKEN` — that env var no longer
exists. Tokens are stored encrypted in the `slack_installations` table
instead of an env var.

Run this migration before installing into any workspace:

```text
supabase/migrations/20260708_slack_installations.sql
```

**Upgrading a workspace that's already running on the old static
`SLACK_BOT_TOKEN`?** The moment this ships, that env var stops being read at
all — the bot and ingestion API lose their token entirely, and the only
normal recovery is completing `/slack/install` again, which isn't reachable
from outside the host until real public hosting exists (see [HTTP mode +
hosting](#http-mode--hosting-issue-62)). Avoid that gap by seeding the
existing token into `slack_installations` directly, before or during that
deploy:

```bash
SLACK_BOT_TOKEN=xoxb-your-existing-token python -m tools.seed_slack_installation
```

This calls `auth.test` with that token to find the workspace's `team_id` and
writes one encrypted row — no OAuth flow or public endpoint required.

Required `.env` values:

```text
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_SIGNING_SECRET=...
SLACK_PORT=3000
APP_ENCRYPTION_KEY=...
```

`SLACK_CLIENT_ID`/`SLACK_CLIENT_SECRET`/`SLACK_SIGNING_SECRET` come from the
Slack app's **Basic Information** page — Distribution must be turned on for
`client_id`/`client_secret` to be visible. `APP_ENCRYPTION_KEY` encrypts
tokens at rest; generate one with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

To install into a workspace, visit `http://<host>:<SLACK_PORT>/slack/install`
(default port `3000`) and complete Slack's OAuth consent screen.

Commands are not yet workspace-aware beyond this install flow — every
command still checks against a single `WORKSPACE_ID` (issue #63 replaces
that with a lookup against `slack_installations`), and `app_uninstalled`/
`tokens_revoked` cleanup isn't wired up yet (issue #64).

## HTTP mode + hosting (issue #62)

Socket Mode apps can't be listed in the Slack Marketplace, so all Slack
traffic — events, slash commands, interactivity, and the OAuth routes above
— is served over plain HTTP instead, with Bolt verifying every request's
`X-Slack-Signature`/`X-Slack-Request-Timestamp` against
`SLACK_SIGNING_SECRET` before any handler runs. There is no
`SLACK_APP_TOKEN`/Socket Mode connection anymore.

Locally, `docker compose up` binds this to `127.0.0.1:${SLACK_PORT:-3000}`,
same pattern as `ingestion-api`. For a real public HTTPS endpoint (needed
for Slack's OAuth redirect, the Events API, and Marketplace submission),
deploy with [Fly.io](https://fly.io):

```bash
fly auth login          # interactive browser login, one-time
fly launch              # scaffolds/merges fly.toml, pick a public app name
fly secrets set SLACK_CLIENT_ID=... SLACK_CLIENT_SECRET=... \
  SLACK_SIGNING_SECRET=... APP_ENCRYPTION_KEY=... \
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... VOYAGE_API_KEY=... \
  WORKSPACE_ID=... ANTHROPIC_API_KEY=...
fly deploy
```

`fly.toml` runs only the Slack-facing process (`student-org-agent/app.py`)
publicly — `ingestion-api` and `drive-sync-worker` stay local/private via
`docker-compose.yml`, matching how `ingestion-api` was already
`127.0.0.1`-only. Once deployed, update `student-org-agent/manifest.json`'s
`YOUR_PUBLIC_DOMAIN` placeholders (`oauth_config.redirect_urls`,
`settings.event_subscriptions.request_url`,
`settings.interactivity.request_url`) with the real `*.fly.dev` hostname (or
your own domain), then update/reinstall the Slack app manifest.

## Slack-to-Google account registration

Run this migration before enabling account registration:

```text
supabase/migrations/20260623_user_google_accounts.sql
```

Members can privately link any valid Google-account email to their own Slack
identity:

```text
/register member@example.com
```

Emails are trimmed and lowercased. Re-running `/register` updates that Slack
user's mapping. A Google email can belong to only one Slack user within a
workspace. Responses are always ephemeral.

Members can remove their mapping:

```text
/unregister
```

Unregistering is idempotent. Calendar and commitment features should resolve an
account through:

```python
from registrations import resolve_google_email

email = resolve_google_email(workspace_id, slack_user_id)
```

The stable identity is `(workspace_id, slack_user_id)`. Display names are stored
only as optional metadata. Explicit `/register` records use `source=register`
and should not be overwritten by future roster imports.

## Connected Drive folders

Docs and Sheets are discovered from explicitly connected Drive folders instead
of scanning every file visible to the club Google account.

Before using folder sync, run this migration in the Supabase SQL editor:

```text
supabase/migrations/20260623_drive_folder_sync.sql
```

Set these environment values for the Slack bot, ingestion API, and Drive sync
worker:

```text
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
VOYAGE_API_KEY=...
WORKSPACE_ID=...
GOOGLE_TOKEN_PATH=secrets/club_token.json
DRIVE_POLL_INTERVAL_SECONDS=300
```

`SUPABASE_SERVICE_KEY` is also accepted as an alias for
`SUPABASE_SERVICE_ROLE_KEY`; when both are set, `SUPABASE_SERVICE_ROLE_KEY`
is used.

Then update or reinstall the Slack app manifest so `/connect-folder` and
`/disconnect-folder` are available, and connect a folder:

```text
/connect-folder https://drive.google.com/drive/folders/<folder_id>
```

In non-development environments, set the Slack users allowed to manage connected
folders:

```text
DRIVE_SYNC_ADMIN_USER_IDS=U123456789,U987654321
```

The initial scan recursively walks subfolders and records subfolder membership
plus supported Google Docs and Sheets. Supported files are dispatched to the
existing heading-based Docs ingestor or the full-rewrite Sheets ingestor.
Folder and file membership is stored in:

- `connected_folders`
- `connected_files`
- `drive_sync_state`

Disconnect a folder and remove source documents no longer referenced by another
connected root:

```text
/disconnect-folder https://drive.google.com/drive/folders/<folder_id>
```

The `drive-sync-worker` Docker Compose service polls the Drive Changes API. A
change identifies affected connected roots; those roots are rescanned, but only
files with a changed Drive `modifiedTime` are re-ingested.

Configure the interval in seconds:

```text
DRIVE_POLL_INTERVAL_SECONDS=300
```

Internal API equivalents are also available:

```bash
curl -X POST http://localhost:8000/drive/connect \
  -H "Content-Type: application/json" \
  -H "X-Ingestion-Api-Key: $INGESTION_API_KEY" \
  -d '{"folder":"https://drive.google.com/drive/folders/<folder_id>","user_id":"U123"}'

curl -X POST http://localhost:8000/drive/sync \
  -H "X-Ingestion-Api-Key: $INGESTION_API_KEY"

curl -X POST http://localhost:8000/drive/disconnect \
  -H "Content-Type: application/json" \
  -H "X-Ingestion-Api-Key: $INGESTION_API_KEY" \
  -d '{"folder":"<folder_id>"}'
```

In Docker Compose, the ingestion API is bound to `127.0.0.1` by default. If
exposed outside localhost, configure `INGESTION_API_KEY`; production-like
environments reject protected routes without it.

## Slack RTS tool

Slack Real-time Search lives in `tools/slack_search.py`. It exposes a
Claude-compatible tool metadata object and a Python function that a future LLM
router can call:

```python
from tools.slack_search import SLACK_RTS_SEARCH_TOOL, search_slack_public_context
```

The tool searches public Slack messages only. It requires a short-lived
`action_token` from a Slack interaction and must not log or expose that token.
See `tools/README.md` for the tool contract and edge cases.

## Google Docs ingestion

The ingestion service uses the backend-only Supabase secret key. Configure:

```text
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
VOYAGE_API_KEY=...
WORKSPACE_ID=...
GOOGLE_TOKEN_PATH=secrets/club_token.json
```

Never expose `SUPABASE_SERVICE_KEY`, `VOYAGE_API_KEY`, `client_secret.json`, or
the generated Google token to a browser or commit them to Git.

Create a Google OAuth Desktop client with the Docs, Drive, and Sheets APIs
enabled. Download it as `client_secret.json`, sign into the dedicated club
Google account, and run:

```bash
python -m tools.google_auth_bootstrap
```

This writes the reusable OAuth token to `secrets/club_token.json`.

The `documents` table must include `workspace_id`, `source`, `source_id`,
`chunk_key`, `content`, `content_hash`, `metadata`, `embedding`, `created_at`,
and `updated_at`, with a unique constraint on:

```text
(workspace_id, source, source_id, chunk_key)
```

Ingest one shared Google Doc using its ID:

```bash
python -m ingestion_api.ingest_docs <google_doc_id>
```

Or call the API:

```bash
curl -X POST http://localhost:8000/ingest/doc \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"google-doc-id"}'
```

Sections are split by Google Docs heading hierarchy. Oversized sections are
split rather than truncated, and unchanged chunks are not re-embedded.

## Google Sheets ingestion

Reads all tabs from Sheets found below connected Drive folders. When Drive marks
a Sheet as changed, the file is fully rewritten: all row embeddings are
prepared first, then the prior rows for that Sheet are replaced.

Ingest a single sheet by its ID (found in the sheet URL):

```bash
python -m ingestion_api.ingest_sheets <google_sheet_id>
```

Or call the API:

```bash
# Ingest one sheet
curl -X POST http://localhost:8000/ingest/sheet \
  -H "Content-Type: application/json" \
  -d '{"sheet_id":"google-sheet-id"}'

```

Each row becomes a chunk keyed by `{tab_id}:{content_hash}`. Duplicate rows
within the same tab are de-duplicated automatically. Multi-tab sheets are fully
supported; tabs are identified by their stable numeric ID so renaming a tab
does not trigger re-embedding.

To enable automatic background polling, set `DRIVE_POLL_INTERVAL_SECONDS` to
the desired interval in seconds (e.g. `300` for every 5 minutes).

The existing webhook can still trigger a direct rewrite:

```bash
curl -X POST http://localhost:8000/webhooks/spreadsheets \
  -H "Content-Type: application/json" \
  -d '{"sheet_id":"google-sheet-id"}'
```

## Slack message ingestion

Run this migration before starting the bot, or `ingestion-api`/`slack-bot`
will crash-loop on startup with
`Could not find the table 'public.monitored_channels' in the schema cache`:

```text
supabase/migrations/20260703_monitored_channels.sql
```

The bot does **not** scan or ingest the workspace's full Slack history. Only
channels explicitly listed in the `monitored_channels` Supabase table are ever
backfilled or watched in real time — see
[`docs/slack_ingestion_setup.md`](docs/slack_ingestion_setup.md) for how to add
a channel via the Supabase SQL editor (there is no admin UI yet).

Backfill is bounded, not a one-time full scan:

```text
SLACK_BACKFILL_LIMIT=200
```

This is the default per-run message budget for a channel's initial backfill,
overridable per channel via the `monitored_channels.backfill_limit` column.
Progress is resumable — each channel tracks `oldest_ts_backfilled` and
`initial_backfill_complete`, so a restart continues where it left off instead
of re-walking history already covered.

Once a channel's initial backfill completes, it's kept in sync by:

- **Real-time events** — new, edited, and deleted messages are ingested as
  they happen.
- **A daily scheduled reconciliation** — a full walk that catches edits and
  deletions missed in real time, controlled by:

  ```text
  SLACK_RECONCILE_CRON_HOUR=6
  ```

- **An on-demand endpoint** for manual/triggered runs:

  ```bash
  curl -X POST http://localhost:8000/ingest/slack/backfill \
    -H "X-Ingestion-Api-Key: $INGESTION_API_KEY"
  ```

Scopes/events required for Slack ingestion specifically (a subset of the full
bot manifest at `student-org-agent/manifest.json`, which also grants scopes
for other features like `/decide` and `/ask`): `channels:history` and
`im:history`, with event subscriptions `message.channels` and `message.im`.
**Private channels are not supported today** — that would require adding
`groups:history` and the `message.groups` event, then reinstalling the app.

Manual verification against a test workspace:

1. Insert a test channel row via the Supabase SQL editor:

   ```sql
   insert into public.monitored_channels (channel_id, channel_name, backfill_limit)
   values ('C0123456789', 'general', 200);
   ```

2. Restart the bot (or hit the endpoint above). Confirm rows appear in
   `documents` for that channel, with `channel_name` correctly populated as
   `general` — not the raw channel ID.
3. Post a message in that channel, then edit it, then delete it. Confirm each
   change is reflected in `documents` shortly after (ingested, re-embedded,
   and removed, respectively).

## Reconciliation proposals

Human-in-the-loop reconciliation findings are stored as durable proposals before
any write-back behavior runs. Run this migration before enabling proposal
workflows:

```text
supabase/migrations/20260701_reconciliation_proposals.sql
```

The proposal model tracks:

- workspace and proposal ID
- status: `pending`, `confirmed`, `expired`, `rejected`, or `superseded`
- source evidence and proposed action payloads
- Slack channel/message references for posted proposals
- created and expiry timestamps
- confirmation metadata: approving Slack user and confirmation timestamp
- audit events for creation, confirmation, expiry, rejection, and superseding

Use `ReconciliationProposalService` for state changes so invalid transitions,
such as confirming an expired proposal, are rejected consistently.
Pending proposals default to expiring 72 hours after creation when callers do
not provide an explicit expiry timestamp. Run `expire_due(workspace_id)`
regularly from the reconciliation scheduler or maintenance job to mark overdue
pending proposals expired before processing late approvals.

Proposal confirmation is controlled by Slack user and reaction configuration:

```text
RECONCILIATION_APPROVAL_USER_IDS=U123456789,U987654321
RECONCILIATION_APPROVAL_REACTION=white_check_mark
```

Only configured committee lead Slack user IDs can confirm pending proposals.
The approval reaction defaults to Slack's `white_check_mark` name for the
checkmark emoji. Wrong reactions, unconfigured users, missing approval user
configuration, and proposals that are expired, rejected, superseded, or already
confirmed are ignored. The Slack app manifest subscribes to `reaction_added` and
requires `reactions:read`; reinstall or update the app after changing the
manifest.

## Ingestion setup

The ingestion API currently provides a placeholder endpoint for later document
sync logic:

```bash
curl -X POST http://localhost:8000/webhooks/documents \
  -H "Content-Type: application/json" \
  -d '{"document_id":"example"}'
```

This endpoint acknowledges the payload but does not write to Supabase yet.

## Development

Run tests locally after installing dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Or, using the existing virtualenv:

```bash
.venv/bin/python -m pytest -q
```

Validate Docker Compose:

```bash
docker compose config --quiet
```

Build the Slack bot image:

```bash
docker compose build slack-bot
```

Ingestion routes live in `ingestion_api/main.py`; shared settings live in
`common/config.py`.

## Reference documentation

- [Slack Bolt for Python](docs/slack-bolt-python-reference.md)
