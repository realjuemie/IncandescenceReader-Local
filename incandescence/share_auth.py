from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from typing import Any

from .database import Database


class ShareAuth:
    """Issue restart-safe, account-scoped temporary reader links."""

    COOKIE_NAME = "xglow_share"
    MIN_MINUTES = 5
    MAX_MINUTES = 90 * 24 * 60

    def __init__(self, database: Database):
        self.database = database

    def create(self, account_id: int, expires_in_minutes: Any) -> dict[str, Any]:
        self.database.get_account(account_id)
        try:
            minutes = int(expires_in_minutes)
        except (TypeError, ValueError) as error:
            raise ValueError("临时链接有效期无效") from error
        if not self.MIN_MINUTES <= minutes <= self.MAX_MINUTES:
            raise ValueError("临时链接有效期需要在 5 分钟到 90 天之间")
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        record = self.database.create_temporary_share(
            account_id,
            self._token_hash(token),
            expires_at.isoformat().replace("+00:00", "Z"),
        )
        return {
            "accountId": int(record["account_id"]),
            "token": token,
            "expiresAt": record["expires_at"],
        }

    def resolve_token(self, token: str | None) -> dict[str, Any] | None:
        value = str(token or "").strip()
        if not value or len(value) > 256:
            return None
        return self.database.get_temporary_share(self._token_hash(value))

    def current(self, cookie_header: str | None) -> dict[str, Any] | None:
        return self.resolve_token(self._cookie_token(cookie_header))

    def session_cookie(self, token: str, expires_at: str) -> str:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        seconds = max(0, int((expiry - datetime.now(timezone.utc)).total_seconds()))
        secure = "; Secure" if os.environ.get("COOKIE_SECURE") == "1" else ""
        return (
            f"{self.COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={seconds}{secure}"
        )

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def _cookie_token(cls, header: str | None) -> str | None:
        if not header:
            return None
        cookies = SimpleCookie()
        try:
            cookies.load(header)
        except Exception:
            return None
        morsel = cookies.get(cls.COOKIE_NAME)
        return morsel.value if morsel else None
