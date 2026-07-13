from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


def main() -> None:
    from common.config import get_ingestion_settings

    credentials_path = Path("client_secret.json")
    token_path = get_ingestion_settings().google_token_path

    if not credentials_path.exists():
        raise FileNotFoundError(
            "client_secret.json was not found in the repository root"
        )

    credentials = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path),
        SCOPES,
    ).run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    try:
        token_path.chmod(0o600)
    except OSError:
        pass
    print(f"wrote {token_path}")


if __name__ == "__main__":
    main()
