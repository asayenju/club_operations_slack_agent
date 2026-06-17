from typing import Any

from fastapi import Body, FastAPI, status

from common.config import get_ingestion_settings

settings = get_ingestion_settings()

app = FastAPI(
    title="Club Operations Ingestion API",
    description="Webhook API for future club document and spreadsheet ingestion.",
    version="0.1.0",
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
