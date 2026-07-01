import re
from dataclasses import dataclass
from typing import Any, Protocol

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from common.config import get_ingestion_settings


DRIVE_READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DOC_MIME_TYPE = "application/vnd.google-apps.document"
SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
SUPPORTED_FILE_MIME_TYPES = {DOC_MIME_TYPE, SHEET_MIME_TYPE}
FOLDER_URL_PATTERN = re.compile(r"(?:/folders/|[?&]id=)([-\w]+)")
RAW_ID_PATTERN = re.compile(r"^[-\w]+$")


@dataclass(frozen=True)
class DriveItem:
    file_id: str
    name: str
    mime_type: str
    parents: tuple[str, ...] = ()
    modified_time: str | None = None
    trashed: bool = False

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME_TYPE

    @property
    def is_supported_file(self) -> bool:
        return self.mime_type in SUPPORTED_FILE_MIME_TYPES


@dataclass(frozen=True)
class DriveChangesPage:
    items: tuple[DriveItem, ...]
    removed_file_ids: tuple[str, ...]
    next_page_token: str | None
    new_start_page_token: str | None


class DriveGateway(Protocol):
    def get_item(self, file_id: str) -> DriveItem:
        ...

    def scan_folder(self, folder_id: str) -> list[DriveItem]:
        ...

    def get_start_page_token(self) -> str:
        ...

    def list_changes(self, page_token: str) -> DriveChangesPage:
        ...


class DriveCursorExpired(RuntimeError):
    pass


def parse_folder_id(folder_reference: str) -> str:
    normalized = folder_reference.strip()
    if RAW_ID_PATTERN.fullmatch(normalized):
        return normalized

    match = FOLDER_URL_PATTERN.search(normalized)
    if not match:
        raise ValueError(
            "Use a Google Drive folder URL or folder ID, for example "
            "`https://drive.google.com/drive/folders/<folder_id>`."
        )
    return match.group(1)


def get_drive_service() -> Any:
    token_path = get_ingestion_settings().google_token_path
    if not token_path.exists():
        raise FileNotFoundError(
            f"Google OAuth token not found at {token_path}. "
            "Run: python -m tools.google_auth_bootstrap"
        )

    credentials = Credentials.from_authorized_user_file(
        str(token_path),
        [DRIVE_READ_SCOPE],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


class GoogleDriveGateway:
    def __init__(self, service: Any | None = None):
        self.service = service or get_drive_service()

    def get_item(self, file_id: str) -> DriveItem:
        payload = (
            self.service.files()
            .get(
                fileId=file_id,
                fields="id,name,mimeType,parents,modifiedTime,trashed",
                supportsAllDrives=True,
            )
            .execute()
        )
        return _to_drive_item(payload)

    def scan_folder(self, folder_id: str) -> list[DriveItem]:
        root = self.get_item(folder_id)
        if not root.is_folder:
            raise ValueError("The supplied Google Drive item is not a folder.")
        if root.trashed:
            raise ValueError("The supplied Google Drive folder is in the trash.")

        discovered: list[DriveItem] = []
        pending = [folder_id]
        while pending:
            parent_id = pending.pop()
            page_token: str | None = None
            while True:
                response = (
                    self.service.files()
                    .list(
                        q=f"'{parent_id}' in parents and trashed = false",
                        fields=(
                            "nextPageToken,"
                            "files(id,name,mimeType,parents,modifiedTime,trashed)"
                        ),
                        pageToken=page_token,
                        pageSize=1000,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    )
                    .execute()
                )
                for payload in response.get("files", []):
                    item = _to_drive_item(payload)
                    if item.is_folder:
                        pending.append(item.file_id)
                        discovered.append(item)
                    elif item.is_supported_file:
                        discovered.append(item)

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

        return discovered

    def get_start_page_token(self) -> str:
        response = (
            self.service.changes()
            .getStartPageToken(supportsAllDrives=True)
            .execute()
        )
        return str(response["startPageToken"])

    def list_changes(self, page_token: str) -> DriveChangesPage:
        try:
            response = (
                self.service.changes()
                .list(
                    pageToken=page_token,
                    spaces="drive",
                    fields=(
                        "nextPageToken,newStartPageToken,"
                        "changes(removed,fileId,"
                        "file(id,name,mimeType,parents,modifiedTime,trashed))"
                    ),
                    pageSize=1000,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            if exc.resp.status == 410:
                raise DriveCursorExpired(
                    "Google Drive change cursor expired"
                ) from exc
            raise
        items: list[DriveItem] = []
        removed_ids: list[str] = []
        for change in response.get("changes", []):
            if change.get("removed") or not change.get("file"):
                removed_ids.append(str(change["fileId"]))
                continue
            items.append(_to_drive_item(change["file"]))

        return DriveChangesPage(
            items=tuple(items),
            removed_file_ids=tuple(removed_ids),
            next_page_token=response.get("nextPageToken"),
            new_start_page_token=response.get("newStartPageToken"),
        )


def _to_drive_item(payload: dict[str, Any]) -> DriveItem:
    return DriveItem(
        file_id=str(payload["id"]),
        name=str(payload.get("name") or "untitled"),
        mime_type=str(payload.get("mimeType") or ""),
        parents=tuple(str(parent) for parent in payload.get("parents", [])),
        modified_time=payload.get("modifiedTime"),
        trashed=bool(payload.get("trashed", False)),
    )
