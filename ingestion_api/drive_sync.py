from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ingestion_api.documents_repo import delete_source
from ingestion_api.drive_gateway import (
    DOC_MIME_TYPE,
    FOLDER_MIME_TYPE,
    SHEET_MIME_TYPE,
    DriveCursorExpired,
    DriveGateway,
    DriveItem,
    GoogleDriveGateway,
    parse_folder_id,
)
from ingestion_api.drive_repository import (
    ConnectedFile,
    ConnectedFolder,
    DriveRegistry,
    SupabaseDriveRegistry,
)
from ingestion_api.ingest_docs import ingest_doc
from ingestion_api.ingest_sheets import ingest_sheet


Ingestor = Callable[[str, str, str | None], Any]
DocumentDeleter = Callable[[str, str, str], int]


@dataclass(frozen=True)
class FolderSyncResult:
    folder_id: str
    folder_name: str
    discovered: int
    ingested: int
    unchanged: int
    removed: int


@dataclass(frozen=True)
class PollResult:
    changed_items: int
    synced_folders: int
    page_token: str


class DriveSyncService:
    def __init__(
        self,
        workspace_id: str,
        registry: DriveRegistry,
        drive: DriveGateway,
        doc_ingestor: Ingestor = ingest_doc,
        sheet_ingestor: Ingestor = ingest_sheet,
        document_deleter: DocumentDeleter = delete_source,
    ):
        self.workspace_id = workspace_id
        self.registry = registry
        self.drive = drive
        self.doc_ingestor = doc_ingestor
        self.sheet_ingestor = sheet_ingestor
        self.document_deleter = document_deleter

    @classmethod
    def from_settings(cls, workspace_id: str) -> "DriveSyncService":
        return cls(
            workspace_id=workspace_id,
            registry=SupabaseDriveRegistry(),
            drive=GoogleDriveGateway(workspace_id),
        )

    def connect_folder(
        self,
        folder_reference: str,
        connected_by: str | None = None,
    ) -> FolderSyncResult:
        folder_id = parse_folder_id(folder_reference)
        root = self.drive.get_item(folder_id)
        if root.mime_type != FOLDER_MIME_TYPE:
            raise ValueError("The supplied Google Drive item is not a folder.")
        if root.trashed:
            raise ValueError("The supplied Google Drive folder is in the trash.")

        existing_folder = self.registry.get_folder(self.workspace_id, folder_id)
        self.registry.upsert_folder(
            ConnectedFolder(
                workspace_id=self.workspace_id,
                folder_id=folder_id,
                folder_name=root.name,
                connected_by=connected_by,
            )
        )
        if self.registry.get_page_token(self.workspace_id) is None:
            self.registry.set_page_token(
                self.workspace_id,
                self.drive.get_start_page_token(),
            )
        try:
            return self.sync_folder(folder_id)
        except Exception:
            if existing_folder is None:
                self.disconnect_folder(folder_id)
            raise

    def sync_folder(self, folder_id: str) -> FolderSyncResult:
        folder = self.registry.get_folder(self.workspace_id, folder_id)
        if folder is None:
            raise ValueError(f"Drive folder {folder_id} is not connected.")

        discovered = self.drive.scan_folder(folder_id)
        existing = {
            file.file_id: file
            for file in self.registry.list_folder_files(
                self.workspace_id,
                folder_id,
            )
        }
        current_ids = {item.file_id for item in discovered}
        ingested = 0
        unchanged = 0

        for item in discovered:
            previous = existing.get(item.file_id)
            should_ingest = item.is_supported_file and (
                previous is None
                or not _same_timestamp(
                    previous.modified_time,
                    item.modified_time,
                )
            )
            if should_ingest:
                self._ingest(item)
                ingested += 1
            elif item.is_supported_file:
                unchanged += 1

            self.registry.upsert_file(
                ConnectedFile(
                    workspace_id=self.workspace_id,
                    folder_id=folder_id,
                    file_id=item.file_id,
                    file_name=item.name,
                    mime_type=item.mime_type,
                    modified_time=item.modified_time,
                    last_ingested_at=_utc_now() if should_ingest else (
                        previous.last_ingested_at if previous else None
                    ),
                )
            )

        stale_ids = set(existing) - current_ids
        removed = 0
        for file_id in stale_ids:
            stale = existing[file_id]
            self.registry.delete_file_mapping(
                self.workspace_id,
                folder_id,
                file_id,
            )
            if stale.mime_type in {DOC_MIME_TYPE, SHEET_MIME_TYPE}:
                self._purge_if_unreferenced(stale)
                removed += 1

        self.registry.mark_folder_scanned(self.workspace_id, folder_id)
        return FolderSyncResult(
            folder_id=folder_id,
            folder_name=folder.folder_name,
            discovered=len(discovered),
            ingested=ingested,
            unchanged=unchanged,
            removed=removed,
        )

    def sync_all_folders(self) -> list[FolderSyncResult]:
        return [
            self.sync_folder(folder.folder_id)
            for folder in self.registry.list_folders(self.workspace_id)
        ]

    def list_connected_folders(self) -> list[ConnectedFolder]:
        return self.registry.list_folders(self.workspace_id)

    def disconnect_folder(self, folder_reference: str) -> int:
        folder_id = parse_folder_id(folder_reference)
        folder = self.registry.get_folder(self.workspace_id, folder_id)
        if folder is None:
            raise ValueError(f"Drive folder {folder_id} is not connected.")

        files = self.registry.list_folder_files(self.workspace_id, folder_id)
        self.registry.delete_folder(self.workspace_id, folder_id)
        purged = 0
        for file in files:
            if file.mime_type in {DOC_MIME_TYPE, SHEET_MIME_TYPE}:
                purged += int(self._purge_if_unreferenced(file))
        return purged

    def poll_changes(self) -> PollResult:
        page_token = self.registry.get_page_token(self.workspace_id)
        if page_token is None:
            page_token = self.drive.get_start_page_token()
            self.registry.set_page_token(self.workspace_id, page_token)
            results = self.sync_all_folders()
            return PollResult(
                changed_items=0,
                synced_folders=len(results),
                page_token=page_token,
            )

        changed_items = 0
        affected_roots: set[str] = set()
        current_token = page_token
        final_token = page_token
        while True:
            try:
                page = self.drive.list_changes(current_token)
            except DriveCursorExpired:
                replacement_token = self.drive.get_start_page_token()
                results = self.sync_all_folders()
                self.registry.set_page_token(
                    self.workspace_id,
                    replacement_token,
                )
                return PollResult(
                    changed_items=0,
                    synced_folders=len(results),
                    page_token=replacement_token,
                )
            changed_items += len(page.items) + len(page.removed_file_ids)
            for file_id in page.removed_file_ids:
                affected_roots.update(
                    self.registry.roots_for_item(self.workspace_id, file_id)
                )
            for item in page.items:
                affected_roots.update(
                    self.registry.roots_for_item(
                        self.workspace_id,
                        item.file_id,
                    )
                )
                affected_roots.update(
                    self.registry.roots_for_parents(
                        self.workspace_id,
                        item.parents,
                    )
                )

            if page.next_page_token:
                current_token = page.next_page_token
                continue
            final_token = page.new_start_page_token or current_token
            break

        for folder_id in sorted(affected_roots):
            self.sync_folder(folder_id)
        self.registry.set_page_token(self.workspace_id, final_token)
        return PollResult(
            changed_items=changed_items,
            synced_folders=len(affected_roots),
            page_token=final_token,
        )

    def _ingest(self, item: DriveItem) -> None:
        if item.mime_type == DOC_MIME_TYPE:
            self.doc_ingestor(item.file_id, self.workspace_id, item.modified_time)
        elif item.mime_type == SHEET_MIME_TYPE:
            self.sheet_ingestor(item.file_id, self.workspace_id, item.modified_time)

    def _purge_if_unreferenced(self, file: ConnectedFile) -> bool:
        if self.registry.file_reference_count(
            self.workspace_id,
            file.file_id,
        ):
            return False
        source = "gdoc" if file.mime_type == DOC_MIME_TYPE else "gsheet"
        self.document_deleter(self.workspace_id, source, file.file_id)
        return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _same_timestamp(left: str | None, right: str | None) -> bool:
    if left == right:
        return True
    if left is None or right is None:
        return False
    try:
        return _parse_timestamp(left) == _parse_timestamp(right)
    except ValueError:
        return False


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
