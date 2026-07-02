import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from common.config import get_ingestion_settings
from ingestion_api.drive_sync import DriveSyncService
from ingestion_api.ingest_docs import IngestionResult, ingest_doc
from ingestion_api.ingest_sheets import ingest_sheet

settings = get_ingestion_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    poll_interval = settings.drive_poll_interval_seconds
    task = None
    if poll_interval > 0:
        async def _poll_loop():
            while True:
                await asyncio.sleep(poll_interval)
                try:
                    await asyncio.to_thread(DriveSyncService.from_settings().poll_changes)
                except Exception as exc:
                    print(f"[poll] drive sync failed: {exc}")
        task = asyncio.create_task(_poll_loop())
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Club Operations Ingestion API",
    description="API for club document and spreadsheet ingestion.",
    version="0.2.0",
    lifespan=lifespan,
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


def require_api_key(x_ingestion_api_key: str | None = Header(default=None)) -> None:
    configured_key = settings.ingestion_api_key
    if configured_key:
        if x_ingestion_api_key != configured_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid ingestion API key",
            )
        return
    if settings.app_env != "development":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INGESTION_API_KEY must be configured",
        )


@app.post(
    "/ingest/doc",
    response_model=DocIngestResponse,
    dependencies=[Depends(require_api_key)],
)
def ingest_doc_endpoint(request: DocIngestRequest) -> IngestionResult:
    return ingest_doc(request.doc_id)


@app.post(
    "/webhooks/documents",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
async def ingest_document_webhook(
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, str]:
    return {"status": "accepted", "source": "documents"}


class SheetIngestRequest(BaseModel):
    sheet_id: str = Field(min_length=1)


@app.post(
    "/ingest/sheet",
    response_model=None,
    dependencies=[Depends(require_api_key)],
)
def ingest_sheet_endpoint(request: SheetIngestRequest) -> Any:
    return ingest_sheet(request.sheet_id)


class FolderRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    folder: str = Field(min_length=1)
    user_id: str | None = None


@app.post("/drive/connect", dependencies=[Depends(require_api_key)])
def connect_drive_folder(request: FolderRequest) -> dict[str, Any]:
    result = DriveSyncService.from_settings().connect_folder(
        request.folder,
        connected_by=request.user_id,
    )
    return asdict(result)


@app.post("/drive/disconnect", dependencies=[Depends(require_api_key)])
def disconnect_drive_folder(request: FolderRequest) -> dict[str, Any]:
    purged = DriveSyncService.from_settings().disconnect_folder(request.folder)
    return {"status": "disconnected", "purged_sources": purged}


@app.post(
    "/drive/sync",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
def sync_drive_folders(background_tasks: BackgroundTasks) -> dict[str, str]:
    background_tasks.add_task(DriveSyncService.from_settings().poll_changes)
    return {"status": "accepted", "source": "drive"}


@app.get("/drive/folders", dependencies=[Depends(require_api_key)])
def list_drive_folders() -> list[dict[str, Any]]:
    return [
        asdict(folder)
        for folder in DriveSyncService.from_settings().list_connected_folders()
    ]


@app.post(
    "/webhooks/spreadsheets",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
async def ingest_spreadsheet_webhook(
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, str]:
    if payload and payload.get("sheet_id"):
        background_tasks.add_task(ingest_sheet, payload["sheet_id"])
    return {"status": "accepted", "source": "spreadsheets"}
