from typing import Any

from fastapi import BackgroundTasks, Body, FastAPI, status
from pydantic import BaseModel, ConfigDict, Field

from common.config import get_ingestion_settings
from ingestion_api.ingest_docs import IngestionResult, ingest_doc
from ingestion_api.ingest_sheets import ingest_all_sheets, ingest_sheet

settings = get_ingestion_settings()

app = FastAPI(
    title="Club Operations Ingestion API",
    description="API for club document and spreadsheet ingestion.",
    version="0.2.0",
)


class DocIngestRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

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


class SheetIngestRequest(BaseModel):
    sheet_id: str = Field(min_length=1)


@app.post("/ingest/sheet", response_model=None)
def ingest_sheet_endpoint(request: SheetIngestRequest) -> Any:
    return ingest_sheet(request.sheet_id)


@app.post("/ingest/sheets", status_code=status.HTTP_202_ACCEPTED)
async def ingest_all_sheets_endpoint(background_tasks: BackgroundTasks) -> dict[str, str]:
    background_tasks.add_task(ingest_all_sheets)
    return {"status": "accepted", "source": "all_sheets"}


@app.post("/webhooks/spreadsheets", status_code=status.HTTP_202_ACCEPTED)
async def ingest_spreadsheet_webhook(
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, str]:
    if payload and payload.get("sheet_id"):
        background_tasks.add_task(ingest_sheet, payload["sheet_id"])
    return {"status": "accepted", "source": "spreadsheets"}
