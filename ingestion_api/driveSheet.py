from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from common.config import get_ingestion_settings

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


def _build_drive_service():
    """Authenticates with Google using the stored OAuth token and returns a Drive API client."""
    token_path = get_ingestion_settings().google_token_path
    if not token_path.exists():
        raise FileNotFoundError(
            f"Google OAuth token not found at {token_path}. "
            "Run: python -m tools.google_auth_bootstrap"
        )
    credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    return build("drive", "v3", credentials=credentials)


def list_all_sheets() -> list[dict]:
    """Returns all Google Sheets accessible to the account as a list of {sheet_id, name, folder_id}."""
    service = _build_drive_service()
    results = (
        service.files()
        .list(
            q=f"mimeType='{SHEETS_MIME_TYPE}'",
            fields="files(id, name, parents)",
        )
        .execute()
    )
    files = results.get("files", [])
    return [
        {
            "sheet_id": f["id"],
            "name": f["name"],
            "folder_id": f.get("parents", [None])[0],
        }
        for f in files
    ]
