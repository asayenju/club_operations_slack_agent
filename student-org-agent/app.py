import logging
import os
import re

from pydantic import ValidationError
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from common.config import get_ingestion_settings, get_slack_settings
from decisions.embedding import EmbeddingError, VoyageEmbeddingClient
from decisions.repository import SupabaseDocumentsRepository
from decisions.service import DecisionAlreadyStored, DecisionService
from ingestion_api.drive_sync import DriveSyncService
from registrations.repository import SupabaseRegistrationRepository
from registrations.service import EmailAlreadyRegistered, RegistrationService


logger = logging.getLogger(__name__)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    token_verification_enabled=os.environ.get(
        "SLACK_TOKEN_VERIFICATION_ENABLED", "false"
    ).lower()
    == "true",
)


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
    if not ensure_configured_workspace(command, respond):
        return
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
    if command.get("team_id") != configured_workspace_id():
        respond(
            response_type="ephemeral",
            text="This command is not available in this workspace.",
        )
        return
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


@app.command("/unregister")
def handle_unregister_command(ack, command, respond):
    ack()
    if command.get("team_id") != configured_workspace_id():
        respond(
            response_type="ephemeral",
            text="This command is not available in this workspace.",
        )
        return

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


def configured_workspace_id() -> str:
    return get_ingestion_settings().required_workspace_id


def ensure_configured_workspace(command, respond) -> bool:
    if command.get("team_id") == configured_workspace_id():
        return True
    respond(
        response_type="ephemeral",
        text="This command is not available in this workspace.",
    )
    return False


def ensure_drive_sync_admin(command, respond) -> bool:
    settings = get_ingestion_settings()
    configured = settings.drive_sync_admin_user_ids
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


@app.command("/connect-folder")
def handle_connect_folder_command(ack, command, respond):
    ack()
    if not ensure_configured_workspace(command, respond):
        return
    if not ensure_drive_sync_admin(command, respond):
        return
    folder_reference = str(command.get("text", "")).strip()
    if not folder_reference:
        respond(
            response_type="ephemeral",
            text="Usage: `/connect-folder <google-drive-folder-url>`",
        )
        return

    try:
        result = DriveSyncService.from_settings().connect_folder(
            folder_reference,
            connected_by=command.get("user_id"),
        )
    except Exception as exc:
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
            f"Found {result.discovered} supported items and ingested "
            f"{result.ingested} changed files."
        ),
    )


@app.command("/disconnect-folder")
def handle_disconnect_folder_command(ack, command, respond):
    ack()
    if not ensure_configured_workspace(command, respond):
        return
    if not ensure_drive_sync_admin(command, respond):
        return
    folder_reference = str(command.get("text", "")).strip()
    if not folder_reference:
        respond(
            response_type="ephemeral",
            text="Usage: `/disconnect-folder <google-drive-folder-url>`",
        )
        return

    try:
        purged = DriveSyncService.from_settings().disconnect_folder(
            folder_reference
        )
    except Exception as exc:
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


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
