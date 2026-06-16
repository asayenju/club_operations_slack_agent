from fastapi import FastAPI, Request
from slack_bolt.adapter.fastapi import SlackRequestHandler

from app.config import get_settings
from app.slack_app import slack_app

settings = get_settings()
handler = SlackRequestHandler(slack_app)

app = FastAPI(
    title="Club Operations Slack Agent",
    description="Slack assistant for club handover and operations workflows.",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@app.post("/slack/events")
async def slack_events(request: Request):
    return await handler.handle(request)
