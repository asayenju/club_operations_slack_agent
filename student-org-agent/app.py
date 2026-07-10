import logging
import os
import re
import threading

from fastapi import FastAPI, Request
from pydantic import ValidationError
from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler
from slack_bolt.oauth.callback_options import CallbackOptions, FailureArgs, SuccessArgs
from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk import WebClient

from common.config import get_ingestion_settings, get_slack_settings
from common.google_credentials_store import WorkspaceGoogleCredentialsStore
from common.google_oauth_state_store import GoogleOAuthStateStore
from common.google_oauth_flow import (
    GOOGLE_DRIVE_SCOPES,
    build_authorization_url,
    exchange_code_for_refresh_token,
)
from common.slack_ingestion import (
    delete_monitored_channels_for_workspace,
    delete_slack_message,
    ingest_slack_message,
    list_monitored_channels,
    normalize_message,
    run_channel_backfill,
)
from common.slack_installation_store import SupabaseInstallationStore
from common.workspace_admin_settings import WorkspaceAdminSettingsStore
from decisions.embedding import EmbeddingError, VoyageEmbeddingClient
from decisions.repository import SupabaseDocumentsRepository
from decisions.service import DecisionAlreadyStored, DecisionService
from ingestion_api.drive_sync import DriveSyncService
from registrations.repository import SupabaseRegistrationRepository
from registrations.service import EmailAlreadyRegistered, RegistrationService

from memoryAnswer.service import MemoryAnswerService
from reconciliation.approval import (
    ReconciliationApprovalPolicy,
    ReconciliationApprovalRejected,
    validate_reconciliation_approval,
)
from reconciliation.repository import SupabaseReconciliationProposalRepository
from reconciliation.service import (
    InvalidProposalTransition,
    ProposalNotFound,
    ReconciliationProposalService,
)

logger = logging.getLogger(__name__)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Must match student-org-agent/manifest.json's oauth_config.scopes.bot exactly
# -- this is what Slack's OAuth consent screen actually grants per install.
BOT_SCOPES = [
    "app_mentions:read",
    "channels:history",
    "chat:write",
    "commands",
    "groups:history",
    "im:history",
    "reactions:read",
    "search:read.public",
]


def _get_supabase():
    from supabase import create_client
    settings = get_slack_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


_slack_settings = get_slack_settings()


def _on_install_success(args: SuccessArgs):
    """Issue #67: seed a newly installed workspace's admin lists with its
    installer, so /connect-folder and reconciliation approval work without
    a redeploy or env var edit. A no-op if that workspace already has admin
    settings (e.g. a reinstall)."""
    try:
        WorkspaceAdminSettingsStore(_get_supabase()).ensure_default_admin(
            args.installation.team_id, args.installation.user_id
        )
    except Exception:
        logger.exception(
            f"Failed to seed default admin settings for {args.installation.team_id}"
        )
    return args.default.success(args)


def _on_install_failure(args: FailureArgs):
    return args.default.failure(args)


app = App(
    signing_secret=_slack_settings.slack_signing_secret,
    installation_store=SupabaseInstallationStore(_get_supabase()),
    installation_store_bot_only=True,
    oauth_settings=OAuthSettings(
        client_id=_slack_settings.slack_client_id,
        client_secret=_slack_settings.slack_client_secret,
        scopes=BOT_SCOPES,
        installation_store_bot_only=True,
        callback_options=CallbackOptions(success=_on_install_success, failure=_on_install_failure),
    ),
    token_verification_enabled=os.environ.get(
        "SLACK_TOKEN_VERIFICATION_ENABLED", "false"
    ).lower()
    == "true",
)


# ---------------------------------------------------------------------------
# Slice 3 — Startup backfill
# ---------------------------------------------------------------------------

def _run_backfill() -> None:
    """Backfill every currently-installed workspace, not just one -- each
    install has its own bot token (issue #61) and its own monitored channels
    (issue #65), so this can no longer assume a single configured workspace."""
    supabase = _get_supabase()
    store = SupabaseInstallationStore(supabase)
    try:
        team_ids = store.list_team_ids()
    except Exception as exc:
        print(f"[backfill] failed to list installed workspaces: {exc}")
        return

    for team_id in team_ids:
        try:
            bot = store.find_bot(enterprise_id=None, team_id=team_id)
            if bot is None or not bot.bot_token:
                print(f"[backfill] no bot token for workspace {team_id}, skipping")
                continue
            client = WebClient(token=bot.bot_token)
            run_channel_backfill(client, supabase, team_id, log_prefix="backfill")
        except Exception as exc:
            print(f"[backfill] failed for workspace {team_id}: {exc}")


@app.message("hello")
def message_hello(message, say):
    say(build_hello_response(message["user"]))


def build_hello_response(user_id: str) -> dict:
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Hey there <@{user_id}>!"},
            }
        ],
        "text": f"Hey there <@{user_id}>!",
    }


@app.command("/decide")
def handle_decide_command(ack, command, respond):
    ack()
    decision_text = str(command.get("text", "")).strip()
    if not decision_text:
        respond(
            response_type="ephemeral",
            text="Usage: `/decide We approved the spring budget.`",
        )
        return

    try:
        service = build_decision_service()
        service.store_decision(command)
    except ValidationError:
        respond(
            response_type="ephemeral",
            text="I couldn't store that decision: `/decide` is missing required server configuration.",
        )
        return
    except DecisionAlreadyStored:
        respond(
            response_type="ephemeral",
            text="That decision is already stored.",
        )
        return
    except (EmbeddingError, RuntimeError, ValueError):
        logger.exception("Failed to store decision")
        respond(
            response_type="ephemeral",
            text="I couldn't store that decision right now.",
        )
        return

    user_id = command.get("user_id")
    author = f" by <@{user_id}>" if user_id else ""
    respond(
        response_type="in_channel",
        text=f"Decision recorded{author}: {decision_text}",
    )


def build_decision_service() -> DecisionService:
    settings = get_slack_settings()
    repository = SupabaseDocumentsRepository.from_settings(
        supabase_url=settings.supabase_url,
        supabase_service_role_key=settings.supabase_service_role_key,
    )
    embedding_client = VoyageEmbeddingClient(
        api_key=settings.voyage_api_key,
        model=settings.voyage_embed_model,
        output_dimension=settings.voyage_embed_dimension,
    )
    return DecisionService(
        documents_repository=repository,
        embedding_client=embedding_client,
    )


@app.command("/register")
def handle_register_command(ack, command, respond):
    ack()
    email = str(command.get("text", "")).strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        respond(
            response_type="ephemeral",
            text="Usage: `/register you@example.com`",
        )
        return
    service = build_registration_service()
    try:
        registered_email = service.register(
            workspace_id=command["team_id"],
            slack_user_id=command["user_id"],
            email=email,
            display_name=command.get("user_name"),
        )
    except EmailAlreadyRegistered as exc:
        respond(response_type="ephemeral", text=str(exc))
        return
    except Exception:
        logger.exception("Failed to register Google account")
        respond(
            response_type="ephemeral",
            text="I couldn't link that Google account right now.",
        )
        return
    respond(
        response_type="ephemeral",
        text=f"Google account linked: {registered_email}",
    )


def build_registration_service() -> RegistrationService:
    settings = get_slack_settings()
    repository = SupabaseRegistrationRepository.from_settings(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
    return RegistrationService(repository)


def build_reconciliation_proposal_service() -> ReconciliationProposalService:
    settings = get_ingestion_settings()
    repository = SupabaseReconciliationProposalRepository.from_settings(
        supabase_url=settings.required_supabase_url,
        supabase_service_key=settings.required_supabase_service_key,
    )
    return ReconciliationProposalService(repository)


def build_reconciliation_approval_policy(workspace_id: str) -> ReconciliationApprovalPolicy:
    ingestion_settings = get_ingestion_settings()
    workspace_settings = WorkspaceAdminSettingsStore(_get_supabase()).get(
        workspace_id, app_env=ingestion_settings.app_env
    )
    return ReconciliationApprovalPolicy.from_settings(workspace_settings)


@app.event("reaction_added")
def handle_reconciliation_reaction_event(event, body, ack):
    ack()
    handle_reconciliation_reaction_added(event, body=body)


def handle_reconciliation_reaction_added(event, body=None) -> bool:
    workspace_id = reaction_workspace_id(event, body)
    item = event.get("item") or {}
    if not workspace_id:
        logger.info("Ignored reconciliation reaction without workspace context")
        return False
    if item.get("type") != "message":
        return False

    slack_channel_id = item.get("channel")
    slack_message_ts = item.get("ts")
    approving_user_id = event.get("user")
    reaction = event.get("reaction")
    if not all([slack_channel_id, slack_message_ts, approving_user_id, reaction]):
        return False

    try:
        validate_reconciliation_approval(
            policy=build_reconciliation_approval_policy(workspace_id),
            approving_user_id=approving_user_id,
            reaction=reaction,
        )
        service = build_reconciliation_proposal_service()
        proposal = service.find_by_slack_message(
            workspace_id,
            slack_channel_id,
            slack_message_ts,
        )
        if proposal is None:
            return False

        service.confirm(
            workspace_id=workspace_id,
            proposal_id=proposal.id,
            approving_user_id=approving_user_id,
        )
        return True
    except (
        ReconciliationApprovalRejected,
        InvalidProposalTransition,
        ProposalNotFound,
        ValueError,
    ):
        logger.info(
            "Ignored reconciliation proposal reaction",
            extra={
                "workspace_id": workspace_id,
                "slack_channel_id": slack_channel_id,
                "slack_message_ts": slack_message_ts,
            },
        )
        return False
    except Exception:
        logger.exception("Failed to handle reconciliation proposal reaction")
        return False


def reaction_workspace_id(event, body=None) -> str | None:
    body = body or {}
    return (
        body.get("team_id")
        or body.get("team")
        or event.get("team")
        or event.get("team_id")
    )


@app.command("/unregister")
def handle_unregister_command(ack, command, respond):
    ack()

    try:
        removed = build_registration_service().unregister(
            command["team_id"],
            command["user_id"],
        )
    except Exception:
        logger.exception("Failed to unregister Google account")
        respond(
            response_type="ephemeral",
            text="I couldn't unlink that Google account right now.",
        )
        return
    respond(
        response_type="ephemeral",
        text=(
            "Google account unlinked."
            if removed
            else "No Google account was registered."
        ),
    )


def ensure_drive_sync_admin(command, respond) -> bool:
    settings = get_ingestion_settings()
    workspace_settings = WorkspaceAdminSettingsStore(_get_supabase()).get(
        command["team_id"], app_env=settings.app_env
    )
    configured = workspace_settings.drive_sync_admin_user_ids
    if configured:
        allowed_user_ids = {
            user_id.strip()
            for user_id in configured.split(",")
            if user_id.strip()
        }
        if command.get("user_id") in allowed_user_ids:
            return True
        respond(
            response_type="ephemeral",
            text="You are not allowed to manage connected Drive folders.",
        )
        return False

    if settings.app_env == "development":
        return True

    respond(
        response_type="ephemeral",
        text="Drive folder administrators are not configured.",
    )
    return False


def ensure_drive_connected(command, respond) -> bool:
    """Each workspace connects its own Google account (issue #66) -- no more
    single shared Drive credential. If this workspace hasn't completed that
    OAuth flow yet, send its admin a connection link instead of failing
    deeper inside DriveSyncService."""
    workspace_id = command["team_id"]
    supabase = _get_supabase()
    store = WorkspaceGoogleCredentialsStore(supabase)
    if store.is_connected(workspace_id):
        return True
    try:
        state = GoogleOAuthStateStore(supabase).create(workspace_id, command.get("user_id"))
        url = build_authorization_url(state)
    except Exception:
        logger.exception("Failed to build Google authorization URL")
        respond(
            response_type="ephemeral",
            text="I couldn't start the Google Drive connection right now.",
        )
        return False
    respond(
        response_type="ephemeral",
        text=f"Connect Google Drive for this workspace first: {url}",
    )
    return False


@app.command("/connect-folder")
def handle_connect_folder_command(ack, command, respond):
    ack()
    if not ensure_drive_sync_admin(command, respond):
        return
    if not ensure_drive_connected(command, respond):
        return
    folder_reference = str(command.get("text", "")).strip()
    if not folder_reference:
        respond(
            response_type="ephemeral",
            text="Usage: `/connect-folder <google-drive-folder-url>`",
        )
        return

    try:
        result = DriveSyncService.from_settings(command["team_id"]).connect_folder(
            folder_reference,
            connected_by=command.get("user_id"),
        )
    except Exception:
        logger.exception("Failed to connect Drive folder")
        respond(
            response_type="ephemeral",
            text="I couldn't connect that folder right now.",
        )
        return

    respond(
        response_type="ephemeral",
        text=(
            f"Connected *{result.folder_name}*. "
            f"Discovered {result.discovered} items and ingested "
            f"{result.ingested} changed files."
        ),
    )


@app.command("/disconnect-folder")
def handle_disconnect_folder_command(ack, command, respond):
    ack()
    if not ensure_drive_sync_admin(command, respond):
        return
    if not ensure_drive_connected(command, respond):
        return
    folder_reference = str(command.get("text", "")).strip()
    if not folder_reference:
        respond(
            response_type="ephemeral",
            text="Usage: `/disconnect-folder <google-drive-folder-url>`",
        )
        return

    try:
        purged = DriveSyncService.from_settings(command["team_id"]).disconnect_folder(
            folder_reference
        )
    except Exception:
        logger.exception("Failed to disconnect Drive folder")
        respond(
            response_type="ephemeral",
            text="I couldn't disconnect that folder right now.",
        )
        return

    respond(
        response_type="ephemeral",
        text=f"Folder disconnected. Removed {purged} unreferenced sources.",
    )


@app.command("/ask")
def handle_ask_command(ack, command, respond):
    ack()
    question = str(command.get("text", "")).strip()

    if not question:
        respond(
            response_type="ephemeral",
            text="Usage: `/ask <your question>`",
        )
        return

    try:
        service = MemoryAnswerService()
        answer = service.answer(question, command["team_id"])
        respond(
            response_type="ephemeral",
            text=(
                f"{answer.answer}\n"
                f"_Confidence: {answer.confidence.level} — {answer.confidence.reason}_"
            ),
        )
    except Exception:
        logger.exception("Failed to answer question")
        respond(
            response_type="ephemeral",
            text="I couldn't answer that question right now.",
        )


# ---------------------------------------------------------------------------
# Slice 4 — Real-time message ingestion
# ---------------------------------------------------------------------------

_monitored_channels_by_workspace: dict[str, dict[str, str]] = {}
_monitored_lock = threading.Lock()


def _get_monitored_channels(workspace_id: str) -> dict[str, str]:
    """Return {channel_id: channel_name} from the monitored_channels config,
    for one workspace.

    Slack's message events never include a channel_name field (on either
    message_changed or a plain new message), so this config cache — not the
    event payload — is the source of truth for the human-readable name.
    Cached per workspace_id since #65 scoped monitored_channels per install.
    """
    with _monitored_lock:
        if workspace_id not in _monitored_channels_by_workspace:
            try:
                supabase = _get_supabase()
                rows = list_monitored_channels(supabase, workspace_id)
                _monitored_channels_by_workspace[workspace_id] = {
                    r["channel_id"]: r["channel_name"] for r in rows
                }
            except Exception as exc:
                print(f"[monitored_channels] failed to load for {workspace_id}: {exc}")
                return {}
    return _monitored_channels_by_workspace[workspace_id]


@app.event("message")
def handle_message(event, context, logger):
    workspace_id = context["team_id"]
    channel_id = event.get("channel", "")
    monitored = _get_monitored_channels(workspace_id)
    if channel_id not in monitored:
        return

    channel_name = monitored[channel_id]
    subtype = event.get("subtype")

    try:
        if subtype == "message_deleted":
            ts = event.get("deleted_ts", "")
            if ts:
                delete_slack_message(workspace_id, channel_id, ts)

        elif subtype == "message_changed":
            raw = event.get("message", {})
            msg = normalize_message(raw, channel_id, channel_name)
            if msg:
                ingest_slack_message(workspace_id, msg)

        elif subtype is None:
            msg = normalize_message(event, channel_id, channel_name)
            if msg:
                ingest_slack_message(workspace_id, msg)

    except Exception as exc:
        logger.error(f"[handle_message] ingestion failed for {channel_id}: {exc}")


# ---------------------------------------------------------------------------
# Install lifecycle -- app_uninstalled / tokens_revoked (issue #64)
#
# Slack does not guarantee ordering or exactly-once delivery between these
# two events, so both handlers are written to be safe to run more than once
# (deleting an already-gone row is a no-op, not an error) and independent of
# each other.
# ---------------------------------------------------------------------------

def _forget_workspace(team_id: str | None, *, reason: str) -> None:
    if not team_id:
        return
    supabase = _get_supabase()
    store = SupabaseInstallationStore(supabase)
    try:
        store.delete_all(enterprise_id=None, team_id=team_id)
    except Exception:
        logger.exception(f"[{reason}] failed to remove installation for {team_id}")
    try:
        removed = delete_monitored_channels_for_workspace(supabase, team_id)
        logger.info(f"[{reason}] removed {removed} monitored channel(s) for {team_id}")
    except Exception:
        logger.exception(f"[{reason}] failed to remove monitored channels for {team_id}")
    try:
        WorkspaceGoogleCredentialsStore(supabase).delete(team_id)
    except Exception:
        logger.exception(f"[{reason}] failed to remove Google Drive credentials for {team_id}")
    try:
        WorkspaceAdminSettingsStore(supabase).delete(team_id)
    except Exception:
        logger.exception(f"[{reason}] failed to remove admin settings for {team_id}")
    with _monitored_lock:
        _monitored_channels_by_workspace.pop(team_id, None)


@app.event("app_uninstalled")
def handle_app_uninstalled(context, logger):
    _forget_workspace(context.get("team_id"), reason="app_uninstalled")


@app.event("tokens_revoked")
def handle_tokens_revoked(event, context, logger):
    """Only bot-scope installs matter here (installation_store_bot_only=True
    everywhere else in this app) -- a non-empty `tokens.bot` list means our
    one bot token for this team is no longer valid, so drop the whole
    installation rather than trying to track individual token IDs we never
    stored."""
    revoked_bot_users = (event.get("tokens") or {}).get("bot") or []
    if not revoked_bot_users:
        return
    _forget_workspace(context.get("team_id"), reason="tokens_revoked")


# ---------------------------------------------------------------------------
# HTTP mode (issue #62)
#
# Socket Mode apps can't be listed in the Slack Marketplace, and a single
# Socket Mode connection isn't built around per-installation routing anyway.
# All Slack traffic -- events, slash commands, interactivity, and the OAuth
# install/redirect routes from #61 -- is served over HTTP instead, with
# Bolt verifying each request's X-Slack-Signature/X-Slack-Request-Timestamp
# against SLACK_SIGNING_SECRET before any handler logic runs (built into
# SlackRequestHandler; not hand-rolled here).
# ---------------------------------------------------------------------------

_slack_request_handler = SlackRequestHandler(app)
http_app = FastAPI()


@http_app.post("/slack/events")
async def slack_events(request: Request):
    return await _slack_request_handler.handle(request)


@http_app.get("/slack/install")
async def slack_install(request: Request):
    return await _slack_request_handler.handle(request)


@http_app.get("/slack/oauth_redirect")
async def slack_oauth_redirect(request: Request):
    return await _slack_request_handler.handle(request)


@http_app.get("/health")
async def health():
    return {"status": "ok", "service": "slack-bot"}


# ---------------------------------------------------------------------------
# Google Drive OAuth (issue #66)
#
# Mirrors the Slack OAuth install flow above: one registered Google OAuth
# client shared by the whole app, each workspace's admin completes their own
# consent. `state` is an unguessable, single-use token issued by
# GoogleOAuthStateStore.create() and redeemed via .consume() below -- the
# callback never trusts client-supplied team_id/user_id directly (issue #74
# review, Aman: a plain "{team_id}|{user_id}" state was forgeable).
# ---------------------------------------------------------------------------

@http_app.get("/google/oauth_redirect")
async def google_oauth_redirect(request: Request):
    from fastapi.responses import PlainTextResponse

    params = request.query_params
    error = params.get("error")
    if error:
        return PlainTextResponse(f"Google authorization failed: {error}", status_code=400)

    code = params.get("code")
    state = params.get("state") or ""
    if not code or not state:
        return PlainTextResponse("Missing code or state in callback.", status_code=400)

    supabase = _get_supabase()
    consumed = GoogleOAuthStateStore(supabase).consume(state)
    if consumed is None:
        # Covers unknown, forged, expired, and already-used state tokens
        # alike -- the caller doesn't get to distinguish which, since that
        # itself would leak information to whoever is probing this endpoint.
        return PlainTextResponse(
            "This connection link is invalid, expired, or already used. Run /connect-folder again.",
            status_code=400,
        )
    workspace_id, user_id = consumed

    try:
        refresh_token = exchange_code_for_refresh_token(code)
    except Exception:
        logger.exception(f"[google_oauth] token exchange failed for workspace {workspace_id}")
        return PlainTextResponse(
            "Couldn't complete the Google connection. Try /connect-folder again.",
            status_code=502,
        )

    store = WorkspaceGoogleCredentialsStore(supabase)
    store.save(
        workspace_id,
        refresh_token,
        GOOGLE_DRIVE_SCOPES,
        connected_by_user_id=user_id or None,
    )
    return PlainTextResponse("Google Drive connected. You can close this tab and run /connect-folder again in Slack.")


if __name__ == "__main__":
    import uvicorn

    threading.Thread(target=_run_backfill, daemon=True).start()
    uvicorn.run(http_app, host="0.0.0.0", port=_slack_settings.slack_port)
