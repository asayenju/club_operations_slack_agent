"""Materializes secrets that must exist as files on disk before credential
loading, from env-var-based secrets (Fly.io has no first-class "secret file"
primitive -- Machines get a fresh filesystem from the image on every
deploy/secret update, so anything not baked into the image must be
reconstructed at process startup).

Call materialize_google_token() once, early, in every entrypoint that will
touch Google credentials (student-org-agent/app.py, ingestion_api/main.py,
tools/drive_poll_worker.py) -- before common.config.get_ingestion_settings()
or any Drive/Docs/Sheets call. A no-op locally, where the token file already
exists on disk and GOOGLE_TOKEN_JSON_B64 isn't set.
"""

import base64
import logging
import os

logger = logging.getLogger(__name__)


def materialize_google_token() -> None:
    from common.config import get_ingestion_settings

    token_path = get_ingestion_settings().google_token_path
    if token_path.exists():
        logger.info("materialize_google_token: %s already exists, skipping", token_path)
        return

    encoded = os.environ.get("GOOGLE_TOKEN_JSON_B64")
    if not encoded:
        logger.warning(
            "materialize_google_token: GOOGLE_TOKEN_JSON_B64 not set, %s will not be created",
            token_path,
        )
        return

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_bytes(base64.b64decode(encoded))
    try:
        token_path.chmod(0o600)
    except OSError:
        pass
    logger.info(
        "materialize_google_token: wrote %s (%d bytes) from GOOGLE_TOKEN_JSON_B64",
        token_path,
        token_path.stat().st_size,
    )
