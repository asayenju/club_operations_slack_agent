# Memora — Club Operations Assistant

**Memora is a Slack-native operational memory for student organizations.** It
turns the scattered knowledge of a club — decisions made in channels, budgets in
spreadsheets, meeting minutes in Google Docs — into a single, searchable memory
your members can query in plain language, right where they already work.

Ask *"what did we decide about the spring formal budget?"* in Slack and get an
answer grounded in your club's actual records, with a citation and a confidence
level — not a guess.

> Built by **Ashwin Sayenju**, **Hailee Zhang**, and **Aman Singh**.

---

## Table of contents

- [What it does](#what-it-does)
- [Slash commands](#slash-commands)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Local development](#local-development)
- [Deployment (Railway)](#deployment-railway)
- [Configuration](#configuration)
- [Feature reference](#feature-reference)
  - [Recording decisions (`/decide`)](#recording-decisions-decide)
  - [Asking questions (`/ask`)](#asking-questions-ask)
  - [Connected Google Drive folders](#connected-google-drive-folders)
  - [Slack message ingestion](#slack-message-ingestion)
  - [Reconciliation proposals](#reconciliation-proposals)
  - [Slack ⇄ Google account registration](#slack--google-account-registration)
- [Data model](#data-model)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Contributors](#contributors)
- [Reference documentation](#reference-documentation)

---

## What it does

Memora watches the places a club's knowledge already lives and makes it
retrievable:

- **Captures decisions** — `/decide We approved $300 for tabling supplies.`
  records a durable, timestamped decision.
- **Ingests documents** — connect a Google Drive folder and Memora pulls in the
  Google **Docs** and **Sheets** inside it (budgets, rosters, meeting minutes)
  and keeps them in sync as they change.
- **Ingests Slack history** — explicitly monitored channels are backfilled and
  then kept current in real time (new, edited, and deleted messages).
- **Answers questions** — `/ask` runs semantic search across everything above
  and has Claude compose a cited answer, tagged **High / Medium / Low**
  confidence based on the strength of the retrieved evidence.
- **Reconciles the record** — a human-in-the-loop workflow proposes updates and
  posts them to a review channel, where a designated approver confirms with an
  emoji reaction.

Everything is **workspace-scoped** and stored in your own Supabase project;
secrets are encrypted at rest.

## Slash commands

| Command | What it does |
| --- | --- |
| `/decide <text>` | Record a club decision. Chunked, embedded, and stored for later retrieval. |
| `/ask <question>` | Answer a question from the club's memory (decisions + Docs + Sheets), with a citation and confidence level. |
| `/connect-folder <drive-url>` | Connect a Google Drive folder; its Docs and Sheets are ingested and kept in sync. |
| `/disconnect-folder <drive-url>` | Disconnect a folder and purge documents no longer referenced by another connected folder. |
| `/reconcile-run <topic>` | Kick off a reconciliation run; a proposal is posted to the workspace's review channel for approval. |
| `/register <email>` | Link your Slack identity to a Google account email. |
| `/unregister` | Remove your Slack ⇄ Google account link. |

## How it works

```
                       ┌──────────────────────────────────────────┐
   Slack workspace     │                 Memora                    │
   ┌───────────┐       │  ┌────────────┐   embed    ┌───────────┐  │
   │  /decide  │──────▶│  │  slack-bot │──────────▶ │  Voyage   │  │
   │  /ask     │◀──────│  │ (Socket    │            │ embeddings│  │
   │  /connect │       │  │  Mode)     │            └───────────┘  │
   └───────────┘       │  └─────┬──────┘                  │        │
                       │        │ retrieve + compose      ▼        │
   Google Drive        │        │              ┌─────────────────┐ │
   ┌───────────┐       │  ┌─────▼──────┐        │    Supabase     │ │
   │ Docs      │──────▶│  │ ingestion  │───────▶│  Postgres +     │ │
   │ Sheets    │       │  │ (FastAPI + │        │  pgvector       │ │
   └───────────┘       │  │  cron)     │        └─────────────────┘ │
                       │  └────────────┘                 ▲          │
                       │  ┌────────────┐  poll changes   │          │
                       │  │  worker    │─────────────────┘          │
                       │  │ (Drive)    │        ┌───────────┐       │
                       │  └────────────┘        │  Claude   │◀──────┤ compose /ask
                       │                        │ (Anthropic)│       │ answers
                       └────────────────────────└───────────┘───────┘
```

1. **Capture.** `/decide`, connected Drive folders, and monitored Slack channels
   feed content into the system. Text is split into sentence-aware chunks.
2. **Embed & store.** Each chunk is embedded with **Voyage** and written to the
   `documents` table in **Supabase**, which uses **pgvector** for similarity
   search. Every row is tagged with its `source` (`slack_decide`, `gdoc`,
   `gsheet`, or a monitored channel) and `workspace_id`.
3. **Retrieve.** `/ask` embeds the question, runs a vector search over decisions
   and knowledge (Docs/Sheets) via the `match_documents` Postgres function, and
   filters by a similarity threshold.
4. **Compose.** The retrieved evidence is handed to **Claude**, which writes a
   grounded answer. A separate confidence scorer rates the result **High /
   Medium / Low** from the evidence quality — so an answer with no real support
   says so instead of hallucinating.
5. **Keep in sync.** A background worker polls the Google Drive Changes API, and
   a daily scheduled job reconciles Slack channels to catch edits/deletions
   missed in real time.

## Architecture

Memora runs as **three cooperating processes** that share one Supabase database
and one Google account, but have distinct jobs:

| Process | Command | Responsibility |
| --- | --- | --- |
| **`app`** (`slack-bot`) | `python student-org-agent/app.py` | Handles all Slack traffic — slash commands, events, and reactions. Connects to Slack over **Socket Mode** (an outbound WebSocket), so it needs no public URL. Runs `/decide`, `/ask`, `/connect-folder`, `/reconcile-run`, etc. in-process. |
| **`ingestion`** | `uvicorn ingestion_api.main:app` | FastAPI service exposing internal ingestion endpoints (Docs, Sheets, Drive connect/sync) and running the **daily Slack reconciliation cron**. Not publicly exposed. |
| **`worker`** | `python -m tools.drive_poll_worker` | Polls the Google Drive Changes API on an interval and re-ingests only changed files. The sole Drive poller. |

**Slack connectivity — Socket Mode.** The bot dials out to Slack rather than
receiving inbound webhooks, so there is no public endpoint to host, no OAuth
redirect to register, and nothing for a restrictive network to block. This suits
a single-club, single-workspace deployment. The codebase also retains an
**HTTP/OAuth multi-workspace mode** (Bolt over FastAPI with a Supabase-backed
installation store) for a future marketplace-style distribution — it activates
automatically when `SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN` are absent and OAuth
credentials are present. See [Slack connectivity modes](#slack-connectivity-modes).

**Google authentication — one shared account.** All Drive/Docs/Sheets access
goes through a single Google account, authorized once via a local browser
consent bootstrap that produces a refresh token. `workspace_id` scopes the
connected-folder *registry*, not the credential.

## Tech stack

- **Python 3.12+**, **Slack Bolt** (Socket Mode + HTTP adapters)
- **FastAPI** + **Uvicorn** (ingestion service)
- **Supabase** (Postgres + **pgvector**) for storage and vector search
- **Voyage AI** for embeddings (`voyage-3.5-lite`, 1024-dim by default)
- **Anthropic Claude** for answer composition (`/ask`)
- **Google Drive / Docs / Sheets APIs** for document ingestion
- **APScheduler** for the daily reconciliation cron
- **Fernet** (`cryptography`) for encrypting stored tokens at rest
- **Railway** (Railpack builder) for deployment
- **pytest** for the test suite

## Local development

Local development runs the three processes directly against the source — no
container build required.

**1. Install dependencies**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Configure** — copy the example env file and fill it in (see
[Configuration](#configuration)):

```bash
cp .env.example .env
```

**3. Authorize Google once** — put an OAuth 2.0 **Desktop app**
`client_secret.json` in the repo root, then run the bootstrap. It opens a
browser for consent and writes a refresh token to `secrets/club_token.json`:

```bash
python -m tools.google_auth_bootstrap
```

**4. Run the processes** — each in its own terminal, with the repo root on
`PYTHONPATH` (so `from common.config import …` resolves):

```bash
# Terminal 1 — Slack bot (Socket Mode)
set -a; . ./.env; set +a
PYTHONPATH=$PWD python student-org-agent/app.py

# Terminal 2 — ingestion API + reconciliation cron
set -a; . ./.env; set +a
PYTHONPATH=$PWD uvicorn ingestion_api.main:app --host 0.0.0.0 --port 8000

# Terminal 3 — Drive poll worker
set -a; . ./.env; set +a
PYTHONPATH=$PWD python -m tools.drive_poll_worker
```

The Slack bot logs `⚡️ Bolt app is running!` once its Socket Mode connection is
established. Check the ingestion API with `curl http://localhost:8000/health`.

> **Socket Mode setup.** In your Slack app config: enable **Socket Mode**,
> generate an **app-level token** (`xapp-…`, scope `connections:write`), and copy
> the **bot token** (`xoxb-…`) from *OAuth & Permissions*. Put both in `.env` as
> `SLACK_APP_TOKEN` and `SLACK_BOT_TOKEN`.

> **Note on Docker Compose.** A `docker-compose.yml` remains in the repo but is
> unmaintained — the supported local workflow is the direct commands above, and
> deployment uses Railway's native builder (there is no Dockerfile).

## Deployment (Railway)

Memora deploys to **Railway** as one project with three services (`app`,
`ingestion`, `worker`), all built from this repo with Railway's native
**Railpack** builder (no Dockerfile). Infrastructure is declared as code in
[`.railway/railway.ts`](.railway/railway.ts).

Key points:

- Each service runs the same repo with a different **start command** and
  `PYTHONPATH=.`.
- Secrets are set per service via `railway variable set` (never committed to
  `.railway/railway.ts`, which is version-controlled).
- The **shared Google credential** can't be a file on Railway's ephemeral disk,
  so `secrets/club_token.json` is base64-encoded into the `GOOGLE_TOKEN_JSON_B64`
  variable and reconstructed at process startup by
  `common/secrets_bootstrap.py`.
- No service is given a public domain — Socket Mode needs no inbound listener.

Preview and apply infrastructure changes:

```bash
railway config plan     # preview
railway config apply    # apply (asks before destructive changes)
```

## Configuration

Environment variables (see [`.env.example`](.env.example)):

| Variable | Required | Purpose |
| --- | --- | --- |
| `SUPABASE_URL` | ✅ | Supabase project URL. |
| `SUPABASE_SERVICE_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Backend-only Supabase key (aliases; role key wins if both set). |
| `VOYAGE_API_KEY` | ✅ | Voyage AI key for embeddings. |
| `ANTHROPIC_API_KEY` | ✅ | Anthropic key for `/ask` answer composition. |
| `WORKSPACE_ID` | ✅ | The Slack team ID this deployment serves. |
| `APP_ENCRYPTION_KEY` | ✅ | Fernet key encrypting stored tokens. **Must stay constant** — changing it makes existing encrypted rows undecryptable. |
| `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | Socket Mode | `xoxb-…` bot token and `xapp-…` app-level token. Set both to run in Socket Mode. |
| `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` / `SLACK_SIGNING_SECRET` | ✅ | Slack app credentials (still required by config even in Socket Mode). |
| `GOOGLE_TOKEN_PATH` | | Path to the Google refresh-token file (default `secrets/club_token.json`). |
| `GOOGLE_TOKEN_JSON_B64` | Deploy | Base64 of the token file, materialized to disk at startup (used on Railway). |
| `VOYAGE_EMBED_MODEL` | | Embedding model (default `voyage-3.5-lite`). |
| `VOYAGE_EMBED_DIMENSION` | | Embedding dimension (default `1024`). |
| `DRIVE_POLL_INTERVAL_SECONDS` | | Drive change-poll interval (default `300`). |
| `SLACK_BACKFILL_LIMIT` | | Default per-run message budget for a channel's initial backfill (default `200`). |
| `SLACK_RECONCILE_CRON_HOUR` | | Hour (0–23) for the daily Slack reconciliation walk (default `6`). |
| `INGESTION_API_KEY` | | Protects the ingestion API's internal routes when exposed beyond localhost. |

Generate an encryption key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Database migrations

Apply the SQL in `supabase/migrations/` (Supabase → SQL Editor) before first
run. Notable tables: `documents` (chunks + embeddings), `monitored_channels`,
`connected_folders` / `connected_files` / `drive_sync_state`,
`workspace_admin_settings`, `reconciliation_proposals`, `slack_installations`,
and `user_google_accounts`. The bot crash-loops on startup if
`monitored_channels` is missing.

## Feature reference

### Recording decisions (`/decide`)

```text
/decide We approved $300 for tabling supplies.
```

On success the bot posts a public confirmation echoing the decision. Empty
input, duplicate content, embedding failures, and database failures are shown
only to the user who ran the command. Internally each decision is split into
sentence-aware chunks; every chunk becomes a `documents` row (`source =
slack_decide`) with metadata linking it back to the full decision. Chunking uses
local deterministic sentence packing, with the boundary isolated for a future
semantic chunker.

### Asking questions (`/ask`)

```text
/ask what is the budget for the tennis event?
```

`/ask` embeds the question, runs vector search over both decisions
(`slack_decide`) and knowledge (`gdoc`, `gsheet`) via the `match_documents`
Postgres function, filters by a similarity threshold, and has Claude compose an
answer from the surviving evidence. The reply includes a **confidence level**
(High / Medium / Low) and reasoning — a query with no supporting evidence
returns *Low — no relevant evidence found* rather than a fabricated answer.

### Connected Google Drive folders

Docs and Sheets are discovered from **explicitly connected** Drive folders, not
by scanning everything a Google account can see.

```text
/connect-folder https://drive.google.com/drive/folders/<folder_id>
```

The initial scan recursively walks subfolders and records subfolder membership
plus supported Google Docs and Sheets, dispatching each to the heading-aware
Docs ingestor or the Sheets ingestor. Membership lives in `connected_folders`,
`connected_files`, and `drive_sync_state`. The `worker` process polls the Drive
Changes API; a change identifies affected connected roots, which are rescanned —
but only files with a changed `modifiedTime` are re-ingested.

Disconnect and purge documents no longer referenced by another connected root:

```text
/disconnect-folder https://drive.google.com/drive/folders/<folder_id>
```

Who may manage folders is per-workspace (`workspace_admin_settings.drive_sync_admin_user_ids`).
Equivalent internal REST endpoints (`/drive/connect`, `/drive/sync`,
`/drive/disconnect`) exist on the ingestion API, protected by `INGESTION_API_KEY`
when exposed beyond localhost.

### Slack message ingestion

The bot does **not** scan full Slack history. Only channels listed in the
`monitored_channels` table are backfilled and watched — see
[`docs/slack_ingestion_setup.md`](docs/slack_ingestion_setup.md) for adding one
via the Supabase SQL editor.

Backfill is **bounded and resumable**: each channel has a per-run message budget
(`SLACK_BACKFILL_LIMIT`, or `monitored_channels.backfill_limit`) and tracks
`oldest_ts_backfilled` / `initial_backfill_complete`, so a restart continues
where it left off. Once initial backfill completes, a channel stays in sync via:

- **Real-time events** — new, edited, and deleted messages are ingested live.
- **A daily reconciliation walk** — catches edits/deletions missed in real time
  (`SLACK_RECONCILE_CRON_HOUR`).
- **An on-demand endpoint** — `POST /ingest/slack/backfill`.

Required scopes/events: `channels:history`, `im:history` (+ `groups:history` for
private channels), with the corresponding `message.*` event subscriptions.

### Reconciliation proposals

A human-in-the-loop workflow stores findings as durable **proposals** before any
write-back. Proposals track status (`pending`, `confirmed`, `expired`,
`rejected`, `superseded`), source evidence, proposed actions, Slack
channel/message references, expiry (default 72h), and an audit trail. Use
`ReconciliationProposalService` for state changes so invalid transitions (e.g.
confirming an expired proposal) are rejected consistently.

```text
/reconcile-run spring formal budget
```

The command posts a proposal to the workspace's configured **review channel**
(`workspace_admin_settings.reconciliation_channel_id`); if none is configured it
returns an ephemeral error rather than posting to the command's channel.
Approval is by emoji **reaction** (`white_check_mark` by default) from a
configured approver (`reconciliation_approval_user_ids`). Wrong reactions,
unconfigured users, and already-resolved proposals are ignored. Requires the
`reaction_added` event subscription and `reactions:read` scope.

### Slack ⇄ Google account registration

`/register <email>` links a member's Slack identity to a Google account email
(stored in `user_google_accounts`); `/unregister` removes it. This underpins
per-user attribution for Google-sourced content.

## Data model

Everything retrievable lives in the Supabase **`documents`** table — one row per
chunk, each with its embedding, `content_hash`, `chunk_key`, `workspace_id`,
`source`, and `metadata`. Sources:

| `source` | Origin |
| --- | --- |
| `slack_decide` | `/decide` statements |
| `gdoc` | Google Docs from connected folders |
| `gsheet` | Google Sheets from connected folders |
| *(channel-tagged)* | Ingested Slack messages |

Vector search is performed by the `match_documents` Postgres function
(pgvector), filtered by source and a similarity threshold. There is **no**
separate `decisions` table — decisions are `documents` rows with `source =
slack_decide`.

## Project structure

```
student-org-agent/   Slack bot entrypoint (Bolt: Socket Mode + HTTP adapters), slash-command handlers
ingestion_api/       FastAPI ingestion service, Drive sync, Docs/Sheets ingestors
tools/               Drive poll worker, vector search, Google auth bootstrap, admin scripts
common/              Config, crypto, Slack installation store, secrets bootstrap, shared ingestion
memoryAnswer/        /ask service — retrieval → Claude answer composition
reconciliation/      Reconciliation proposal model, service, and approval policy
decisions/           /decide service (chunking, embedding, storage)
registrations/       Slack ⇄ Google account registration
supabase/migrations/ Database schema
.railway/            Infrastructure-as-code for the Railway deployment
tests/               pytest suite
```

## Testing

```bash
.venv/bin/python -m pytest -q
```

Ingestion routes live in `ingestion_api/main.py`; shared settings live in
`common/config.py`.

## Slack connectivity modes

Memora supports two ways of talking to Slack, selected automatically at startup:

- **Socket Mode** (current deployment) — active when `SLACK_BOT_TOKEN` and
  `SLACK_APP_TOKEN` are set. The bot opens an outbound WebSocket to Slack; no
  public URL, no OAuth install flow, single workspace. Ideal for a single club.
- **HTTP / OAuth multi-workspace mode** — active when those tokens are absent
  and `SLACK_CLIENT_ID`/`SLACK_CLIENT_SECRET` are present. Bolt is served over
  FastAPI with real request-signature verification, and each installing
  workspace gets its own bot token stored (encrypted) in the
  `slack_installations` table via Slack's OAuth flow. Intended for a future
  marketplace-style distribution.

Both modes share the same command handlers, so features behave identically.

## Contributors

Memora is built and maintained by:

- **Ashwin Sayenju**
- **Hailee Zhang**
- **Aman Singh**

## Reference documentation

- [Slack Bolt for Python](docs/slack-bolt-python-reference.md)
- [Slack ingestion setup](docs/slack_ingestion_setup.md)
- [`tools/` tool contracts](tools/README.md)
