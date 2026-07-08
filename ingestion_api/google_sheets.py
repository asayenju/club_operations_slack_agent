from typing import Any

import gspread

from common.google_credentials_store import get_google_credentials

GOOGLE_READ_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_sheets_client(workspace_id: str) -> gspread.Client:
    """Authenticates with that workspace's connected Google account and
    returns a gspread client."""
    credentials = get_google_credentials(workspace_id, GOOGLE_READ_SCOPES)
    return gspread.Client(auth=credentials)


def fetch_sheet_rows(sheet_id: str, workspace_id: str) -> tuple[str, list[dict[str, Any]]]:
    """Fetches all rows from all tabs of a Google Sheet, adding a __tab__ key to each row."""
    normalized_id = sheet_id.strip()
    if not normalized_id:
        raise ValueError("sheet_id must not be empty")

    client = get_sheets_client(workspace_id)
    sheet = client.open_by_key(normalized_id)
    title = sheet.title
    rows = []
    for worksheet in sheet.worksheets():
        for row in worksheet.get_all_records():
            rows.append({"__tab_id__": str(worksheet.id), "__tab_name__": worksheet.title, **row})
    return title, rows


def row_to_text(row: dict[str, Any]) -> str:
    """Converts a row dict to a readable string for embedding, skipping empty values."""
    return " | ".join(f"{key}: {value}" for key, value in row.items() if value != "")
