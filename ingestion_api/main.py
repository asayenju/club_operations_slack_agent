from typing import Any

from fastapi import BackgroundTasks, Body, FastAPI, status
from slack_sdk import WebClient

from common.config import get_ingestion_settings
from common.slack_ingestion import backfill_channel, list_monitored_channels

settings = get_ingestion_settings()

app = FastAPI(
    title="Club Operations Ingestion API",
    description="Webhook API for club document and spreadsheet ingestion.",
    version="0.2.0",
)


def _get_supabase():
    from supabase import create_client
    return create_client(settings.required_supabase_url, settings.required_supabase_service_key)


def _get_slack_client() -> WebClient:
    import os
    return WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env, "service": "ingestion-api"}


@app.post("/webhooks/documents", status_code=status.HTTP_202_ACCEPTED)
async def ingest_document_webhook(
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, str]:
    return {"status": "accepted", "source": "documents"}


@app.post("/webhooks/spreadsheets", status_code=status.HTTP_202_ACCEPTED)
async def ingest_spreadsheet_webhook(
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, str]:
    return {"status": "accepted", "source": "spreadsheets"}


def _run_slack_backfill() -> None:
    supabase = _get_supabase()
    slack = _get_slack_client()
    workspace_id = settings.required_workspace_id
    channels = list_monitored_channels(supabase)
    for ch in channels:
        count = backfill_channel(
            slack,
            workspace_id,
            ch["channel_id"],
            ch["channel_name"],
            ch.get("backfill_limit", 200),
        )
        print(f"[backfill] #{ch['channel_name']}: {count} messages ingested")


@app.post("/ingest/slack/backfill", status_code=status.HTTP_202_ACCEPTED)
async def slack_backfill_endpoint(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Manually trigger a bounded backfill of all monitored Slack channels."""
    background_tasks.add_task(_run_slack_backfill)
    return {"status": "accepted", "source": "slack_backfill"}
