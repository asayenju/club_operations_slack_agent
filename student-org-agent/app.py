import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler


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


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
