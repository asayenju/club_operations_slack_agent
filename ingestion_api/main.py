from typing import Any

from fastapi import Body, FastAPI, status
from pydantic import BaseModel, Field

from common.config import get_ingestion_settings
from ingestion_api.ingest_docs import IngestionResult, ingest_doc

settings = get_ingestion_settings()

app = FastAPI(
    title="Club Operations Ingestion API",
    description="API for club document and spreadsheet ingestion.",
    version="0.2.0",
)


class DocIngestRequest(BaseModel):
    doc_id: str = Field(min_length=1)


class DocIngestResponse(BaseModel):
    doc_id: str
    title: str
    inserted_or_changed: int
    unchanged: int
    deleted: int
    total: int


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env, "service": "ingestion-api"}


@app.post("/ingest/doc", response_model=DocIngestResponse)
def ingest_doc_endpoint(request: DocIngestRequest) -> IngestionResult:
    return ingest_doc(request.doc_id)


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
