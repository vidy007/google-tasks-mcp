"""OAuth 2.0 for Google Tasks.

The password never reaches this code: the user signs in to Google in their own
browser, and Google hands back a refresh token scoped to Tasks only. That token
is stored locally with 0600 permissions and can be revoked at any time at
https://myaccount.google.com/permissions.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/tasks"]


def config_dir() -> Path:
    override = os.environ.get("GOOGLE_TASKS_MCP_HOME")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or (
        os.environ.get("APPDATA") if os.name == "nt" else None
    )
    return Path(base or Path.home() / ".config") / "google-tasks-mcp"


def token_path() -> Path:
    return config_dir() / "token.json"


def _write_private(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def run_oauth_flow(client_secret_file: str, delete_client_secret: bool = False) -> Path:
    """Open the browser for Google sign-in and store the resulting refresh token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not creds.refresh_token:
        raise RuntimeError("Google did not return a refresh token; run auth again.")
    path = token_path()
    _write_private(path, creds.to_json())
    if delete_client_secret:
        # The token file already carries client_id/secret, so the download is no
        # longer needed; remove it so the secret exists in exactly one place.
        Path(client_secret_file).unlink(missing_ok=True)
    return path


def load_credentials() -> Credentials:
    path = token_path()
    if not path.exists():
        raise RuntimeError(
            f"Not authorized: {path} is missing. Run `google-tasks-mcp auth "
            "--client-secret <client_secret.json>` once on this computer."
        )
    creds = Credentials.from_authorized_user_info(json.loads(path.read_text("utf-8")), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _write_private(path, creds.to_json())
        else:
            raise RuntimeError("Stored token is invalid; run `google-tasks-mcp auth` again.")
    return creds


def logout() -> bool:
    """Revoke the token at Google and delete it locally."""
    path = token_path()
    if not path.exists():
        return False
    try:
        import requests

        token = json.loads(path.read_text("utf-8")).get("refresh_token")
        if token:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
    finally:
        path.unlink(missing_ok=True)
    return True
