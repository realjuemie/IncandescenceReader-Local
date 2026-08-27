from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from http.cookies import SimpleCookie
from threading import RLock
from typing import Any

from .config import normalize_bark_device_key, normalize_http_base_url
from .database import Database


class MemberAuth:
    COOKIE_NAME = "incandescence_member"
    SESSION_SECONDS = 30 * 24 * 60 * 60
    PBKDF2_ROUNDS = 450_000

    def __init__(self, database: Database):
        self.database = database
        self._lock = RLock()
        self._sessions: dict[str, tuple[int, float]] = {}

    @staticmethod
    def normalize_username(value: str) -> str:
        username = str(value or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,32}", username):
            raise ValueError("会员名只能使用 3–32 位字母、数字、点、下划线或短横线")
        return username

    @staticmethod
    def validate_password(value: str) -> str:
        password = str(value or "")
        if len(password) < 8:
            raise ValueError("会员密码至少需要 8 个字符")
        if len(password) > 256:
            raise ValueError("会员密码过长")
        return password

    def create_member(
        self, username: str, password: str, account_ids: list[Any]
    ) -> dict[str, Any]:
        username = self.normalize_username(username)
        password = self.validate_password(password)
        normalized_ids = self._validate_account_ids(account_ids)
        salt, digest = self._hash_password(password)
        member = self.database.create_member(
            username, salt, digest, self.PBKDF2_ROUNDS
        )
        self.database.update_member(
            member["id"], active=True, account_ids=normalized_ids
        )
        return self._public_member_by_id(int(member["id"]))

    def update_member(
        self,
        member_id: int,
        *,
        active: bool,
        account_ids: list[Any],
        password: str = "",
    ) -> dict[str, Any]:
        normalized_ids = self._validate_account_ids(account_ids)
        salt = digest = None
        rounds = None
        if password:
            password = self.validate_password(password)
            salt, digest = self._hash_password(password)
            rounds = self.PBKDF2_ROUNDS
        member = self.database.update_member(
            member_id,
            active=active,
            account_ids=normalized_ids,
            password_salt=salt,
            password_digest=digest,
            password_rounds=rounds,
        )
        if not active or password:
            self.invalidate_member(member_id)
        return self._public_member_by_id(int(member["id"]))

    def login(self, username: str, password: str) -> tuple[str, dict[str, Any]]:
        normalized = self.normalize_username(username)
        member = self.database.get_member_by_username(normalized)
        if not member or not bool(member.get("active")):
            raise ValueError("会员名或密码不正确")
        if not self._password_matches(member, password):
            raise ValueError("会员名或密码不正确")
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._remove_expired_unlocked(now)
            self._sessions[token] = (int(member["id"]), now + self.SESSION_SECONDS)
        self.database.mark_member_login(int(member["id"]))
        return token, self.public_member(self.database.get_member(int(member["id"])))

    def change_password(
        self,
        member_id: int,
        *,
        current_password: str,
        new_password: str,
        cookie_header: str | None,
    ) -> None:
        member = self.database.get_member(member_id)
        if not bool(member.get("active")) or not self._password_matches(
            member, current_password
        ):
            raise ValueError("当前密码不正确")
        validated = self.validate_password(new_password)
        salt, digest = self._hash_password(validated)
        self.database.update_member_password(
            member_id,
            password_salt=salt,
            password_digest=digest,
            password_rounds=self.PBKDF2_ROUNDS,
        )
        self.invalidate_member(
            member_id,
            except_token=self._cookie_token(cookie_header),
        )

    @staticmethod
    def _password_matches(member: dict[str, Any], password: str) -> bool:
        try:
            salt = base64.b64decode(member["password_salt"], validate=True)
            expected = base64.b64decode(member["password_digest"], validate=True)
            rounds = int(member["password_rounds"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("会员凭证数据损坏") from error
        actual = hashlib.pbkdf2_hmac(
            "sha256", str(password or "").encode("utf-8"), salt, rounds
        )
        return hmac.compare_digest(actual, expected)

    def current(self, cookie_header: str | None) -> dict[str, Any] | None:
        token = self._cookie_token(cookie_header)
        if not token:
            return None
        now = time.time()
        with self._lock:
            self._remove_expired_unlocked(now)
            session = self._sessions.get(token)
            if not session or session[1] <= now:
                return None
            member_id = session[0]
            self._sessions[token] = (member_id, now + self.SESSION_SECONDS)
        try:
            member = self.database.get_member(member_id)
        except KeyError:
            self.invalidate_member(member_id)
            return None
        if not bool(member.get("active")):
            self.invalidate_member(member_id)
            return None
        return self.public_member(member)

    def logout(self, cookie_header: str | None) -> None:
        token = self._cookie_token(cookie_header)
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    def invalidate_member(self, member_id: int, *, except_token: str | None = None) -> None:
        with self._lock:
            for token, session in list(self._sessions.items()):
                if session[0] == member_id and token != except_token:
                    self._sessions.pop(token, None)

    def list_members(self) -> list[dict[str, Any]]:
        return [self.public_member(item) for item in self.database.list_members()]

    def notification_settings(self, member_id: int) -> dict[str, Any]:
        settings = self.database.get_member_notification_settings(member_id)
        accounts = self.database.list_accounts(member_id=member_id)
        return {
            "enabled": bool(settings["enabled"]),
            "serverUrl": settings["server_url"],
            "deviceKeyConfigured": bool(settings["device_key"]),
            "group": settings["group"],
            "accountIds": settings["account_ids"],
            "availableAccounts": [
                {
                    "id": int(account["id"]),
                    "username": account["username"],
                    "displayName": account.get("display_name") or account["username"],
                    "isPublic": bool(account.get("is_public", 1)),
                }
                for account in accounts
            ],
        }

    def update_notification_settings(
        self,
        member_id: int,
        *,
        enabled: bool,
        server_url: Any,
        device_key: Any | None,
        clear_device_key: bool,
        group: Any,
        account_ids: Any,
    ) -> dict[str, Any]:
        current = self.database.get_member_notification_settings(member_id)
        normalized_server = normalize_http_base_url(
            server_url or "https://api.day.app",
            field_name="Bark 服务器地址",
            allow_path=True,
        )
        if clear_device_key:
            normalized_key: str | None = ""
        elif device_key is not None and str(device_key).strip():
            normalized_key = normalize_bark_device_key(device_key)
        else:
            normalized_key = None
        effective_key = current["device_key"] if normalized_key is None else normalized_key
        normalized_group = str(group or "Incandescence").strip()[:64] or "Incandescence"
        if not isinstance(account_ids, list):
            raise ValueError("通知账号列表格式无效")
        normalized_ids = sorted({int(value) for value in account_ids})
        if enabled and not effective_key:
            raise ValueError("开启 Bark 推送前请填写 Device Key")
        if enabled and not normalized_ids:
            raise ValueError("开启 Bark 推送前请至少选择一个通知账号")
        self.database.update_member_notification_settings(
            member_id,
            enabled=enabled,
            server_url=normalized_server,
            device_key=normalized_key,
            group=normalized_group,
            account_ids=normalized_ids,
        )
        return self.notification_settings(member_id)

    def _public_member_by_id(self, member_id: int) -> dict[str, Any]:
        for item in self.database.list_members():
            if int(item["id"]) == member_id:
                return self.public_member(item)
        raise KeyError("会员不存在")

    @staticmethod
    def public_member(member: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(member["id"]),
            "username": member["username"],
            "active": bool(member.get("active")),
            "accountIds": [int(value) for value in member.get("account_ids", [])],
            "lastLoginAt": member.get("last_login_at"),
            "createdAt": member.get("created_at"),
        }

    def session_cookie(self, token: str) -> str:
        secure = "; Secure" if os.environ.get("COOKIE_SECURE") == "1" else ""
        return (
            f"{self.COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; "
            f"Max-Age={self.SESSION_SECONDS}{secure}"
        )

    def clear_cookie(self) -> str:
        secure = "; Secure" if os.environ.get("COOKIE_SECURE") == "1" else ""
        return (
            f"{self.COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0{secure}"
        )

    def _validate_account_ids(self, values: list[Any]) -> list[int]:
        if not isinstance(values, list):
            raise ValueError("可查看用户列表格式无效")
        normalized = sorted({int(value) for value in values})
        for account_id in normalized:
            self.database.get_account(account_id)
        return normalized

    @classmethod
    def _hash_password(cls, password: str) -> tuple[str, str]:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, cls.PBKDF2_ROUNDS
        )
        return base64.b64encode(salt).decode("ascii"), base64.b64encode(digest).decode("ascii")

    def _remove_expired_unlocked(self, now: float) -> None:
        for token, session in list(self._sessions.items()):
            if session[1] <= now:
                self._sessions.pop(token, None)

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
