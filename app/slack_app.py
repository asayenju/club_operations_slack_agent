from slack_bolt import App

from app.config import get_settings

settings = get_settings()

slack_app = App(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
    token_verification_enabled=settings.slack_token_verification_enabled,
)


@slack_app.event("app_mention")
def handle_app_mention(event, say):
    say(
        text=(
            "Handover assistant is connected. Ask me a club operations "
            "question and I will help route it soon."
        ),
        thread_ts=event.get("thread_ts") or event.get("ts"),
    )


@slack_app.event("message")
def handle_direct_message(event, say):
    if event.get("channel_type") != "im" or event.get("subtype"):
        return

    say(
        text=(
            "Handover assistant is connected. I am ready for direct "
            "handover questions once the knowledge layer is added."
        )
    )
