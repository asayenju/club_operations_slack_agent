from ingestion_api.drive_gateway import (
    DOC_MIME_TYPE,
    FOLDER_MIME_TYPE,
    SHEET_MIME_TYPE,
    GoogleDriveGateway,
    parse_folder_id,
)


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeFiles:
    def __init__(self):
        self.list_calls = []

    def get(self, **kwargs):
        return FakeRequest(
            {
                "id": kwargs["fileId"],
                "name": "Club Operations",
                "mimeType": FOLDER_MIME_TYPE,
                "parents": [],
                "trashed": False,
            }
        )

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        parent = kwargs["q"].split("'")[1]
        page_token = kwargs.get("pageToken")
        responses = {
            ("root", None): {
                "nextPageToken": "page-2",
                "files": [
                    {
                        "id": "subfolder",
                        "name": "Notes",
                        "mimeType": FOLDER_MIME_TYPE,
                        "parents": ["root"],
                    },
                    {
                        "id": "doc-1",
                        "name": "Minutes",
                        "mimeType": DOC_MIME_TYPE,
                        "parents": ["root"],
                        "modifiedTime": "2026-06-23T00:00:00Z",
                    },
                    {
                        "id": "image-1",
                        "name": "Poster",
                        "mimeType": "image/png",
                        "parents": ["root"],
                        "modifiedTime": "2026-06-23T00:00:00Z",
                    },
                ],
            },
            ("root", "page-2"): {
                "files": [
                    {
                        "id": "sheet-1",
                        "name": "Budget",
                        "mimeType": SHEET_MIME_TYPE,
                        "parents": ["root"],
                        "modifiedTime": "2026-06-23T00:00:00Z",
                    }
                ]
            },
            ("subfolder", None): {
                "files": [
                    {
                        "id": "doc-2",
                        "name": "Proposal",
                        "mimeType": DOC_MIME_TYPE,
                        "parents": ["subfolder"],
                    }
                ]
            },
        }
        return FakeRequest(responses[(parent, page_token)])


class FakeService:
    def __init__(self):
        self.files_api = FakeFiles()

    def files(self):
        return self.files_api


def test_parse_folder_id_accepts_url_and_raw_id():
    assert (
        parse_folder_id("https://drive.google.com/drive/folders/folder_123?usp=sharing")
        == "folder_123"
    )
    assert parse_folder_id("folder_123") == "folder_123"


def test_parse_folder_id_rejects_non_folder_url():
    try:
        parse_folder_id("https://docs.google.com/document/d/doc-id/edit")
    except ValueError as exc:
        assert "folder URL" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_scan_folder_is_recursive_and_paginated():
    gateway = GoogleDriveGateway(service=FakeService())

    items = gateway.scan_folder("root")

    assert {item.file_id for item in items} == {
        "subfolder",
        "doc-1",
        "sheet-1",
        "doc-2",
    }
    assert len(gateway.service.files_api.list_calls) == 3


def test_scan_folder_excludes_unsupported_files():
    gateway = GoogleDriveGateway(service=FakeService())

    items = gateway.scan_folder("root")

    assert "image-1" not in {item.file_id for item in items}
