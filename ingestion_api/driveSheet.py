import json
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


def _build_drive_service(service_account_json: str):
    """
    Authenticates with Google using a service account and returns a Drive API client.
    """
    creds_dict = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def list_all_sheets(service_account_json: str) -> list[dict]:
    """
    Returns all Google Sheets accessible to the service account as a list of {sheet_id, name, folder_id}.
    """
    service = _build_drive_service(service_account_json)
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


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent.parent / ".env")

    sheets = list_all_sheets(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    print(sheets)