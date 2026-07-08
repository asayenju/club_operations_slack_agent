from dataclasses import replace

from ingestion_api.drive_gateway import (
    DOC_MIME_TYPE,
    FOLDER_MIME_TYPE,
    SHEET_MIME_TYPE,
    DriveCursorExpired,
    DriveChangesPage,
    DriveItem,
)
from ingestion_api.drive_repository import ConnectedFile, ConnectedFolder
from ingestion_api.drive_sync import DriveSyncService


class InMemoryRegistry:
    def __init__(self):
        self.folders = {}
        self.files = {}
        self.page_token = None

    def upsert_folder(self, folder):
        self.folders[folder.folder_id] = folder

    def list_folders(self, workspace_id):
        return list(self.folders.values())

    def get_folder(self, workspace_id, folder_id):
        return self.folders.get(folder_id)

    def mark_folder_scanned(self, workspace_id, folder_id):
        folder = self.folders[folder_id]
        self.folders[folder_id] = replace(
            folder,
            last_scanned_at="2026-06-23T00:00:00Z",
        )

    def delete_folder(self, workspace_id, folder_id):
        self.folders.pop(folder_id)
        for key in list(self.files):
            if key[0] == folder_id:
                del self.files[key]

    def list_folder_files(self, workspace_id, folder_id):
        return [
            file
            for (root_id, _), file in self.files.items()
            if root_id == folder_id
        ]

    def upsert_file(self, file):
        self.files[(file.folder_id, file.file_id)] = file

    def delete_file_mapping(self, workspace_id, folder_id, file_id):
        self.files.pop((folder_id, file_id), None)

    def roots_for_item(self, workspace_id, file_id):
        return {
            root_id
            for (root_id, item_id) in self.files
            if item_id == file_id
        }

    def roots_for_parents(self, workspace_id, parent_ids):
        roots = {folder_id for folder_id in self.folders if folder_id in parent_ids}
        roots.update(
            root_id
            for (root_id, item_id) in self.files
            if item_id in parent_ids
        )
        return roots

    def file_reference_count(self, workspace_id, file_id):
        return sum(item_id == file_id for _, item_id in self.files)

    def get_page_token(self, workspace_id):
        return self.page_token

    def set_page_token(self, workspace_id, page_token):
        self.page_token = page_token


class FakeDrive:
    def __init__(self):
        self.root = DriveItem("root", "Club Folder", FOLDER_MIME_TYPE)
        self.scan_calls = []
        self.items = [
            DriveItem(
                "doc-1",
                "Minutes",
                DOC_MIME_TYPE,
                ("root",),
                "2026-06-23T00:00:00Z",
            ),
            DriveItem(
                "sheet-1",
                "Budget",
                SHEET_MIME_TYPE,
                ("root",),
                "2026-06-23T00:00:00Z",
            ),
        ]
        self.change_pages = []

    def get_item(self, file_id):
        return self.root

    def scan_folder(self, folder_id):
        self.scan_calls.append(folder_id)
        return list(self.items)

    def get_start_page_token(self):
        return "token-1"

    def list_changes(self, page_token):
        return self.change_pages.pop(0)


def build_service():
    registry = InMemoryRegistry()
    drive = FakeDrive()
    ingested = []
    deleted = []
    service = DriveSyncService(
        workspace_id="T123",
        registry=registry,
        drive=drive,
        doc_ingestor=lambda file_id, workspace_id, modified_time=None: ingested.append(("doc", file_id)),
        sheet_ingestor=lambda file_id, workspace_id, modified_time=None: ingested.append(("sheet", file_id)),
        document_deleter=lambda workspace, source, file_id: deleted.append(
            (source, file_id)
        )
        or 1,
    )
    return service, registry, drive, ingested, deleted


def test_connect_folder_ingests_supported_files_and_initializes_cursor():
    service, registry, _, ingested, _ = build_service()

    result = service.connect_folder(
        "https://drive.google.com/drive/folders/root",
        connected_by="U123",
    )

    assert result.ingested == 2
    assert ingested == [("doc", "doc-1"), ("sheet", "sheet-1")]
    assert registry.page_token == "token-1"
    assert registry.folders["root"].connected_by == "U123"


def test_connect_folder_records_discovered_supported_files():
    service, registry, _, ingested, _ = build_service()

    result = service.connect_folder("root")

    assert result.discovered == 2
    assert set(registry.files) == {("root", "doc-1"), ("root", "sheet-1")}
    assert registry.files[("root", "doc-1")].mime_type == DOC_MIME_TYPE
    assert registry.files[("root", "sheet-1")].mime_type == SHEET_MIME_TYPE
    assert ingested == [("doc", "doc-1"), ("sheet", "sheet-1")]


def test_connect_folder_rolls_back_new_registration_when_ingestion_fails():
    registry = InMemoryRegistry()
    drive = FakeDrive()
    service = DriveSyncService(
        workspace_id="T123",
        registry=registry,
        drive=drive,
        doc_ingestor=lambda file_id, workspace_id, modified_time=None: (_ for _ in ()).throw(
            RuntimeError("embedding unavailable")
        ),
        sheet_ingestor=lambda file_id, workspace_id, modified_time=None: None,
        document_deleter=lambda workspace, source, file_id: 0,
    )

    try:
        service.connect_folder("root")
    except RuntimeError as exc:
        assert "embedding unavailable" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")

    assert registry.folders == {}
    assert registry.files == {}


def test_sync_folder_only_reingests_modified_files():
    service, _, drive, ingested, _ = build_service()
    service.connect_folder("root")
    ingested.clear()

    first, second = drive.items
    drive.items = [
        replace(first, modified_time="2026-06-24T00:00:00Z"),
        second,
    ]
    result = service.sync_folder("root")

    assert result.ingested == 1
    assert result.unchanged == 1
    assert ingested == [("doc", "doc-1")]


def test_sync_folder_treats_equivalent_timestamp_formats_as_unchanged():
    service, registry, _, ingested, _ = build_service()
    service.connect_folder("root")
    ingested.clear()
    stored = registry.files[("root", "doc-1")]
    registry.files[("root", "doc-1")] = replace(
        stored,
        modified_time="2026-06-23T00:00:00+00:00",
    )

    result = service.sync_folder("root")

    assert result.ingested == 0
    assert result.unchanged == 2
    assert ingested == []


def test_disconnect_purges_unreferenced_sources():
    service, registry, _, _, deleted = build_service()
    service.connect_folder("root")

    purged = service.disconnect_folder("root")

    assert purged == 2
    assert registry.folders == {}
    assert deleted == [("gdoc", "doc-1"), ("gsheet", "sheet-1")]


def test_poll_changes_rescans_only_affected_roots_and_advances_token():
    service, registry, drive, ingested, _ = build_service()
    service.connect_folder("root")
    ingested.clear()
    drive.items[0] = replace(
        drive.items[0],
        modified_time="2026-06-24T00:00:00Z",
    )
    drive.change_pages = [
        DriveChangesPage(
            items=(drive.items[0],),
            removed_file_ids=(),
            next_page_token=None,
            new_start_page_token="token-2",
        )
    ]

    result = service.poll_changes()

    assert result.changed_items == 1
    assert result.synced_folders == 1
    assert registry.page_token == "token-2"
    assert ingested == [("doc", "doc-1")]


def test_poll_changes_does_not_scan_changes_outside_connected_roots():
    service, registry, drive, ingested, _ = build_service()
    service.connect_folder("root")
    ingested.clear()
    drive.scan_calls.clear()
    drive.change_pages = [
        DriveChangesPage(
            items=(
                DriveItem(
                    "outside-doc",
                    "Outside Notes",
                    DOC_MIME_TYPE,
                    ("outside-folder",),
                    "2026-06-24T00:00:00Z",
                ),
            ),
            removed_file_ids=(),
            next_page_token=None,
            new_start_page_token="token-2",
        )
    ]

    result = service.poll_changes()

    assert result.changed_items == 1
    assert result.synced_folders == 0
    assert registry.page_token == "token-2"
    assert drive.scan_calls == []
    assert ingested == []


def test_poll_changes_recovers_from_expired_cursor():
    service, registry, drive, ingested, _ = build_service()
    service.connect_folder("root")
    ingested.clear()

    def expired(_page_token):
        raise DriveCursorExpired("expired")

    drive.list_changes = expired
    drive.get_start_page_token = lambda: "replacement-token"

    result = service.poll_changes()

    assert result.synced_folders == 1
    assert registry.page_token == "replacement-token"
    assert ingested == []
