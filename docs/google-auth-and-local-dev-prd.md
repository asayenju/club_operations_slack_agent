# PRD — Google auth revert (single shared account) + Socket Mode local dev

**Branch:** `fix/google-auth-single-account-and-socket-mode`
**Author:** Ashwin · **Status:** code done, needs manual Slack/Google setup to run live
**Audience:** teammate picking this up

---

## 1. Why this change exists

Two problems on `feature/per-workspace-admin-config`:

1. **Google Drive OAuth was broken.** The branch (issue #66) replaced the
   original single shared Google account with a **per-workspace web OAuth flow**
   (`/connect-folder` → Google consent link → `/google/oauth_redirect` callback →
   per-workspace refresh token in Supabase). It never worked in practice: the
   callback needs a correctly-typed **Web** OAuth client, a registered redirect
   URI, and a public `PUBLIC_BASE_URL` — none of which were set up, so after
   consent the browser hit a dead page and no credential was stored.

2. **Can't test Slack locally.** The bot runs in **HTTP mode** (FastAPI), so
   Slack must reach a public URL. The dev's ISP (**Spectrum**) blocks tunneling
   services (ngrok is DNS-hijacked to a "Security Shield" block page **and**
   SNI-filtered at the TLS layer), so no tunnel-based local testing works.

**Decision (agreed):** revert Google auth to the **single shared account** that
worked on `main` (Aman's original `InstalledAppFlow` bootstrap), and add a
**Socket Mode** entrypoint so the bot can run on localhost with no public URL.

---

## 2. What was done (this branch)

### A. Google auth reverted to one shared account ✅
All workspaces read Drive/Docs/Sheets through a single Google account authorized
once via a local bootstrap. `workspace_id` still scopes the *connected-folder
registry* — only the credential source changed.

- `common/config.py` — re-added `google_token_path` (default
  `secrets/club_token.json`); removed the web-flow settings
  (`google_oauth_client_id/secret`, `public_base_url`).
- `tools/google_auth_bootstrap.py` — restored (Desktop `InstalledAppFlow` →
  writes `secrets/club_token.json`). Run once: `python -m tools.google_auth_bootstrap`.
- `ingestion_api/{drive_gateway,google_docs,google_sheets}.py` — load
  `Credentials.from_authorized_user_file(google_token_path, SCOPES)`; raise a
  clear "run the bootstrap" error if the token file is missing.
- `student-org-agent/app.py` — deleted the `ensure_drive_connected` OAuth-link
  gate, the `/google/oauth_redirect` route, and the per-workspace credential
  cleanup in `_forget_workspace`.
- Deleted modules: `common/google_oauth_flow.py`, `google_oauth_state_store.py`,
  `google_credentials_store.py` (+ their tests).
- `ingestion_api/drive_repository.py` — added `SupabaseDriveRegistry.list_workspace_ids()`
  (distinct workspaces with a connected folder); `ingestion_api/main.py` +
  `tools/drive_poll_worker.py` now poll via that instead of the deleted store.
- Docs: `.env.example`, `README.md` updated.

**Verified live:** ran the bootstrap → authorized `slackhack.agent@gmail.com` →
exercised Drive/Docs/Sheets against the real API successfully (Drive `about.get`
+ `files.list` returned real files). Google auth is confirmed working.

### B. Socket Mode entrypoint for local dev ✅ (code) / ⏳ (needs setup to run)
Lets the bot run on localhost with no tunnel — it dials **out** to Slack over a
WebSocket, which Spectrum doesn't block.

- `common/config.py` — added optional `slack_bot_token` (xoxb-) and
  `slack_app_token` (xapp-) to `SlackSettings`.
- `student-org-agent/app.py`:
  - App is built with a **static bot token** when `slack_bot_token` is set
    (single-workspace, skips OAuth install); otherwise the existing
    multi-workspace OAuth `App` is used unchanged.
  - `__main__`: if `slack_app_token` is set, runs
    `SocketModeHandler(app, app_token).start()`; else `uvicorn` (HTTP mode).
    **HTTP mode is fully preserved when the two tokens are absent.**
- `requirements.txt` — added `websocket-client` (Socket Mode transport).

### C. docker-compose ngrok service (⚠️ blocked by ISP — see below)
- `docker-compose.yml` — added an `ngrok` service tunneling to `slack-bot:3000`
  (reads `NGROK_AUTHTOKEN` from `.env`). Works in principle but **unusable on
  Spectrum**; kept for teammates on other networks. Socket Mode is the primary
  local-dev path now.

### Test status
`pytest` — **all green** (441 passing before Socket Mode; `test_slack_bot.py`
39 passing after). Obsolete OAuth-flow tests were removed; poll-worker and
uninstall tests updated to the new registry/no-credential-store world.

---

## 3. What still needs to happen (hand-off checklist)

### To run the bot locally via Socket Mode (recommended)
Manual Slack + Google steps (only an admin can do these; nothing in code blocks them):

- [ ] **Google:** put a Desktop-app `client_secret.json` in the repo root and run
      `python -m tools.google_auth_bootstrap` on the machine that will run the
      services (writes `secrets/club_token.json`). Already done on Ashwin's
      machine; each new host needs its own token file (gitignored).
- [ ] **Slack app config** (api.slack.com/apps → the app):
  - Enable **Socket Mode**.
  - Create an **App-Level Token** (`xapp-…`) with scope `connections:write`.
  - Get the **Bot User OAuth Token** (`xoxb-…`) from OAuth & Permissions
    (Install to Workspace if not yet installed).
  - Ensure the slash commands exist (`/connect-folder`, `/disconnect-folder`,
    `/ask`, `/register`, `/unregister`, `/decide`). Request URLs can be blank in
    Socket Mode.
- [ ] Add to `.env`: `SLACK_BOT_TOKEN=xoxb-…` and `SLACK_APP_TOKEN=xapp-…`.
- [ ] Run: `python student-org-agent/app.py` → expect
      `Starting Slack bot in Socket Mode (no public URL needed)` → test
      `/connect-folder <drive-folder-url>` (folder must be shared with the
      authorized Google account).

### Known gaps / follow-ups
- [ ] **Socket Mode not yet exercised end-to-end** — code is in and unit-tested,
      but a real `/connect-folder` round-trip over the socket hasn't been run
      (was blocked on getting the two Slack tokens). This is the main thing to
      confirm.
- [ ] **`slack_installations` table is empty** — no workspace was ever installed
      via the OAuth flow. Irrelevant for Socket Mode (static token), but note it
      if anyone tries HTTP mode.
- [ ] **Unused migrations left in place** — `workspace_google_credentials` and
      `google_oauth_states` tables are now dead but not dropped (harmless, no
      down-migration). Decide whether to remove.
- [ ] **docker-compose `slack-bot` has no hot-reload** (`python app.py`), so code
      changes need `docker compose restart slack-bot`. Consider a reload wrapper.
- [ ] **Production still uses HTTP mode** (`fly.toml`). This change doesn't touch
      the Fly deploy path; Socket Mode is dev-only. If we want per-workspace
      Google accounts back later, that's a separate re-design (reverts this).

---

## 4. Files changed
See `git diff main...fix/google-auth-single-account-and-socket-mode`. Summary:
~194 insertions / ~1042 deletions across config, ingestion_api, the Slack app,
tools, tests, and docs (most deletions are the removed per-workspace OAuth
modules + their tests).
