from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from http.cookies import SimpleCookie
from pathlib import Path
from threading import RLock
from typing import Any


class AdminAuth:
    """Small local-admin authentication store with restart-safe password hashes."""

    COOKIE_NAME = "incandescence_admin"
    SESSION_SECONDS = 12 * 60 * 60
    PBKDF2_ROUNDS = 600_000

    def __init__(self, data_dir: Path):
        self.path = data_dir.resolve() / "admin-auth.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._sessions: dict[str, float] = {}
        initial_password = os.environ.get("ADMIN_PASSWORD")
        if initial_password and not self.is_configured():
            self.setup(initial_password)

    def is_configured(self) -> bool:
        return self._read_record() is not None

    def setup(self, password: str) -> str:
        password = self._validate_password(password)
        with self._lock:
            if self.is_configured():
                raise ValueError("管理员密码已经设置")
            salt = secrets.token_bytes(16)
            digest = self._derive(password, salt)
            self._write_record(
                {
                    "version": 1,
                    "algorithm": "pbkdf2-sha256",
                    "rounds": self.PBKDF2_ROUNDS,
                    "salt": base64.b64encode(salt).decode("ascii"),
                    "digest": base64.b64encode(digest).decode("ascii"),
                }
            )
            return self._issue_session_unlocked()

    def login(self, password: str) -> str:
        record = self._read_record()
        if record is None:
            raise ValueError("请先设置管理员密码")
        try:
            salt = base64.b64decode(record["salt"], validate=True)
            expected = base64.b64decode(record["digest"], validate=True)
            rounds = int(record["rounds"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("管理员凭证文件损坏") from error
        actual = hashlib.pbkdf2_hmac(
            "sha256", str(password).encode("utf-8"), salt, rounds
        )
        if not hmac.compare_digest(actual, expected):
            raise ValueError("管理员密码不正确")
        with self._lock:
            return self._issue_session_unlocked()

    def authenticated(self, cookie_header: str | None) -> bool:
        token = self._cookie_token(cookie_header)
        if not token:
            return False
        now = time.time()
        with self._lock:
            self._remove_expired_unlocked(now)
            expires = self._sessions.get(token)
            if not expires or expires <= now:
                return False
            self._sessions[token] = now + self.SESSION_SECONDS
            return True

    def logout(self, cookie_header: str | None) -> None:
        token = self._cookie_token(cookie_header)
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    def session_cookie(self, token: str) -> str:
        secure = "; Secure" if os.environ.get("COOKIE_SECURE") == "1" else ""
        return (
            f"{self.COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; "
            f"Max-Age={self.SESSION_SECONDS}{secure}"
        )

    def clear_cookie(self) -> str:
        secure = "; Secure" if os.environ.get("COOKIE_SECURE") == "1" else ""
        return (
            f"{self.COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; "
            f"Max-Age=0{secure}"
        )

    @staticmethod
    def _validate_password(password: str) -> str:
        password = str(password or "")
        if len(password) < 10:
            raise ValueError("管理员密码至少需要 10 个字符")
        if len(password) > 256:
            raise ValueError("管理员密码过长")
        return password

    @classmethod
    def _derive(cls, password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, cls.PBKDF2_ROUNDS
        )

    def _issue_session_unlocked(self) -> str:
        now = time.time()
        self._remove_expired_unlocked(now)
        token = secrets.token_urlsafe(32)
        self._sessions[token] = now + self.SESSION_SECONDS
        return token

    def _remove_expired_unlocked(self, now: float) -> None:
        for token, expires in list(self._sessions.items()):
            if expires <= now:
                self._sessions.pop(token, None)

    def _read_record(self) -> dict[str, Any] | None:
        with self._lock:
            if not self.path.is_file():
                return None
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError("管理员凭证文件损坏") from error
            if not isinstance(value, dict):
                raise RuntimeError("管理员凭证文件损坏")
            return value

    def _write_record(self, record: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)

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
