from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from downloader_app.runtime import app_path


CLIENT_FILE = Path(os.environ.get("GOOGLE_OAUTH_CLIENT_FILE", app_path("google_oauth_client.json")))
TOKEN_FILE = Path(os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", app_path(".google_token.json")))
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


class GoogleAuthError(RuntimeError):
    pass


class GoogleOAuthManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: str | None = None

    def status(self) -> dict:
        status = {
            "dependencies_ready": False,
            "client_configured": CLIENT_FILE.exists(),
            "authenticated": False,
            "email": None,
            "message": "",
        }

        try:
            self._load_google_modules()
        except GoogleAuthError as exc:
            status["message"] = str(exc)
            return status

        status["dependencies_ready"] = True

        if not status["client_configured"]:
            status["message"] = (
                "Chua co file google_oauth_client.json. "
                "Hay tao OAuth client tren Google Cloud va dat file JSON vao thu muc project."
            )
            return status

        try:
            credentials = self._load_credentials()
        except GoogleAuthError as exc:
            status["message"] = str(exc)
            return status

        if credentials is None:
            status["message"] = "Chua dang nhap Google. Sheet private se can bam Sign in with Google."
            return status

        status["authenticated"] = True
        try:
            status["email"] = self._fetch_user_email(credentials.token)
        except GoogleAuthError:
            status["email"] = None

        status["message"] = (
            f"Da ket noi voi {status['email']}."
            if status["email"]
            else "Da ket noi Google va san sang doc sheet private."
        )
        return status

    def is_authenticated(self) -> bool:
        try:
            credentials = self._load_credentials()
        except GoogleAuthError:
            return False
        return credentials is not None

    def start_auth(self, base_url: str) -> str:
        _, flow_cls, _ = self._load_google_modules()
        self._require_client_file()

        flow = flow_cls.from_client_secrets_file(str(CLIENT_FILE), scopes=SCOPES)
        flow.redirect_uri = f"{base_url}/oauth2/callback"
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        with self._lock:
            self._state = state

        return authorization_url

    def handle_callback(self, current_url: str, base_url: str) -> dict:
        _, flow_cls, _ = self._load_google_modules()
        self._require_client_file()

        with self._lock:
            state = self._state

        if not state:
            raise GoogleAuthError("Trang thai dang nhap da het han. Hay bam Sign in with Google lai.")

        flow = flow_cls.from_client_secrets_file(
            str(CLIENT_FILE),
            scopes=SCOPES,
            state=state,
        )
        flow.redirect_uri = f"{base_url}/oauth2/callback"
        flow.fetch_token(authorization_response=current_url)

        credentials = flow.credentials
        TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")

        with self._lock:
            self._state = None

        email = None
        try:
            email = self._fetch_user_email(credentials.token)
        except GoogleAuthError:
            email = None

        return {"authenticated": True, "email": email}

    def logout(self) -> None:
        with self._lock:
            self._state = None

        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()

    def authorized_json(self, url: str) -> dict:
        credentials = self._load_credentials()
        if credentials is None:
            raise GoogleAuthError("Ban chua dang nhap Google.")

        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GoogleAuthError(self._format_http_error(exc)) from exc

    def _require_client_file(self) -> None:
        if CLIENT_FILE.exists():
            return
        raise GoogleAuthError(
            "Khong tim thay google_oauth_client.json. "
            "Can tao OAuth client tren Google Cloud truoc khi dang nhap."
        )

    def _load_google_modules(self):
        try:
            from google.auth.transport.requests import Request as GoogleRequest
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import Flow
        except ImportError as exc:
            raise GoogleAuthError(
                "Thieu thu vien Google OAuth. Hay chay pip3 install -r requirements.txt."
            ) from exc

        return Credentials, Flow, GoogleRequest

    def _load_credentials(self):
        credentials_cls, _, request_cls = self._load_google_modules()

        if not TOKEN_FILE.exists():
            return None

        try:
            credentials = credentials_cls.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as exc:
            raise GoogleAuthError(
                "Khong doc duoc file token Google. Hay logout roi dang nhap lai."
            ) from exc

        if credentials.valid:
            return credentials

        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(request_cls())
                TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
                return credentials
            except Exception as exc:
                raise GoogleAuthError(
                    "Token Google da het han va khong refresh duoc. Hay dang nhap lai."
                ) from exc

        raise GoogleAuthError("Token Google khong hop le. Hay dang nhap lai.")

    def _fetch_user_email(self, access_token: str) -> str | None:
        request = Request(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GoogleAuthError(self._format_http_error(exc)) from exc
        return payload.get("email")

    def _format_http_error(self, error: HTTPError) -> str:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except Exception:
            return f"Google request failed: {error.reason}"

        error_data = payload.get("error")
        if isinstance(error_data, dict):
            message = error_data.get("message")
            if message:
                return str(message)
        return f"Google request failed: {error.reason}"


google_oauth = GoogleOAuthManager()
