import os

from pydantic import ValidationError
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from common.config import get_slack_settings
from decisions.embedding import EmbeddingError, VoyageEmbeddingClient
from decisions.repository import SupabaseDocumentsRepository
from decisions.service import DecisionAlreadyStored, DecisionService


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
    except (EmbeddingError, RuntimeError, ValueError) as exc:
        respond(
            response_type="ephemeral",
            text=f"I couldn't store that decision: {exc}",
        )
        return

    respond(
        response_type="in_channel",
        text=f"Decision recorded: {decision_text}",
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


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
