from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, Body, FastAPI, status
from slack_sdk import WebClient

from common.config import get_ingestion_settings
from common.slack_ingestion import backfill_channel, list_monitored_channels

settings = get_ingestion_settings()
scheduler = BackgroundScheduler()


def _get_supabase():
    from supabase import create_client
    return create_client(settings.required_supabase_url, settings.required_supabase_service_key)


def _get_slack_client() -> WebClient:
    import os
    return WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))


def _run_slack_backfill() -> None:
    """On-demand trigger: bounded initial backfill for channels still catching up,
    full reconciliation for channels that have already completed it."""
    supabase = _get_supabase()
    slack = _get_slack_client()
    workspace_id = settings.required_workspace_id
    channels = list_monitored_channels(supabase)
    for ch in channels:
        full_walk = bool(ch.get("initial_backfill_complete"))
        result = backfill_channel(slack, supabase, workspace_id, ch, full_walk=full_walk)
        print(
            f"[backfill] #{ch['channel_name']}: {result['ingested']} ingested, "
            f"{result['failed']} failed, {result['deleted']} deleted"
        )


def _run_slack_reconcile() -> None:
    """Scheduled daily reconciliation: always a full walk (edits + deletions)."""
    supabase = _get_supabase()
    slack = _get_slack_client()
    workspace_id = settings.required_workspace_id
    channels = list_monitored_channels(supabase)
    for ch in channels:
        result = backfill_channel(slack, supabase, workspace_id, ch, full_walk=True)
        print(
            f"[reconcile] #{ch['channel_name']}: {result['ingested']} ingested, "
            f"{result['failed']} failed, {result['deleted']} deleted"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        _run_slack_reconcile,
        CronTrigger(hour=settings.slack_reconcile_cron_hour, minute=0),
        id="slack_reconcile",
        replace_existing=True,
    )
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Club Operations Ingestion API",
    description="Webhook API for club document and spreadsheet ingestion.",
    version="0.2.0",
    lifespan=lifespan,
)


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


@app.post("/ingest/slack/backfill", status_code=status.HTTP_202_ACCEPTED)
async def slack_backfill_endpoint(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Manually trigger backfill/reconciliation of all monitored Slack channels."""
    background_tasks.add_task(_run_slack_backfill)
    return {"status": "accepted", "source": "slack_backfill"}
