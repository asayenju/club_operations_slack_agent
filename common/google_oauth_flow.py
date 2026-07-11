"""Per-workspace Google OAuth web flow (issue #66) -- the "Connect Google
Drive" equivalent of #61's Slack OAuth install flow. One registered Google
OAuth client (GOOGLE_OAUTH_CLIENT_ID/SECRET) shared by the whole app; each
workspace's admin completes their own consent, producing a refresh token
scoped to whichever Google account they authorized.
"""

from google_auth_oauthlib.flow import Flow

from common.config import get_ingestion_settings

GOOGLE_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


class MissingRefreshToken(RuntimeError):
    def __init__(self):
        super().__init__(
            "Google did not return a refresh token. This usually means the "
            "workspace's Google account already granted access previously "
            "without being re-prompted for consent -- disconnect access at "
            "https://myaccount.google.com/permissions and try again."
        )


def redirect_uri() -> str:
    settings = get_ingestion_settings()
    base = (settings.public_base_url or "").rstrip("/")
    return f"{base}/google/oauth_redirect"


def _build_flow() -> Flow:
    settings = get_ingestion_settings()
    client_config = {
        "web": {
            "client_id": settings.required_google_oauth_client_id,
            "client_secret": settings.required_google_oauth_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri()],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=GOOGLE_DRIVE_SCOPES)
    flow.redirect_uri = redirect_uri()
    return flow


def build_authorization_url(state: str) -> str:
    """`state` should encode enough to finish the callback -- this app uses
    "{team_id}|{user_id}"."""
    flow = _build_flow()
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        state=state,
    )
    return url


def exchange_code_for_refresh_token(code: str) -> str:
    flow = _build_flow()
    flow.fetch_token(code=code)
    refresh_token = flow.credentials.refresh_token
    if not refresh_token:
        raise MissingRefreshToken()
    return refresh_token
