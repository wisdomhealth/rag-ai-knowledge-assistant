from __future__ import annotations

from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.utils.logger import get_logger


logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def get_drive_service(credentials_path: str | Path = "credentials.json", token_path: str | Path = "token.json") -> Any:
    """Authenticate with OAuth InstalledAppFlow and return a Google Drive service."""
    credentials_file = Path(credentials_path)
    token_file = Path(token_path)
    credentials: Credentials | None = _load_cached_credentials(token_file)

    if credentials and credentials.expired and credentials.refresh_token:
        logger.info("Refreshing cached Google OAuth token from %s", token_file)
        try:
            credentials.refresh(Request())
            _save_credentials(credentials, token_file)
        except RefreshError as exc:
            logger.warning("Cached Google OAuth token could not be refreshed: %s", exc)
            credentials = None

    if not credentials or not credentials.valid:
        credentials = _run_installed_app_flow(credentials_file)
        _save_credentials(credentials, token_file)

    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _load_cached_credentials(token_file: Path) -> Credentials | None:
    """Load token.json when it exists, ignoring invalid cache files."""
    if not token_file.exists():
        return None
    try:
        return Credentials.from_authorized_user_file(str(token_file), SCOPES)
    except ValueError as exc:
        logger.warning("Ignoring invalid Google OAuth token cache %s: %s", token_file, exc)
        return None


def _run_installed_app_flow(credentials_file: Path) -> Credentials:
    """Open a local browser OAuth login using a desktop OAuth client file."""
    if not credentials_file.exists():
        raise FileNotFoundError(
            "Google OAuth client file not found: "
            f"{credentials_file}. Download an OAuth desktop client JSON from Google Cloud, "
            "save it as credentials.json, then rerun python scripts/ingest_drive.py."
        )

    logger.info("Starting Google OAuth browser login with %s", credentials_file)
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    return flow.run_local_server(port=0)


def _save_credentials(credentials: Credentials, token_file: Path) -> None:
    """Persist OAuth credentials so future ingestion runs skip browser login."""
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    logger.info("Saved Google OAuth token cache to %s", token_file)
