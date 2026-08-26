from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from .async_runtime import AsyncRuntime
from .auth import AdminAuth
from .config import ConfigStore, normalize_proxy_url
from .database import Database, _file_url
from .member_auth import MemberAuth
from .notifications import BarkNotifier
from .scraper import (
    CredentialValidationUnavailableError,
    FreeXScraper,
    inspect_cookie_input,
)
from .sync_service import Scheduler, SyncBusyError, SyncService


class Application:
    def __init__(
        self,
        *,
        data_dir: Path,
        public_dir: Path,
        database: Database,
        config: ConfigStore,
        admin_auth: AdminAuth,
        member_auth: MemberAuth,
        notifier: BarkNotifier,
        scraper: FreeXScraper,
        sync_service: SyncService,
        scheduler: Scheduler,
        scraper_runtime: AsyncRuntime,
    ):
        self.data_dir = data_dir.resolve()
        self.public_dir = public_dir.resolve()
        self.database = database
        self.config = config
        self.admin_auth = admin_auth
        self.member_auth = member_auth
        self.notifier = notifier
        self.scraper = scraper
        self.sync_service = sync_service
        self.scheduler = scheduler
        self.scraper_runtime = scraper_runtime

    def account_public(
        self, account: dict[str, Any], *, include_admin: bool = False
    ) -> dict[str, Any]:
        try:
            metrics = json.loads(account.get("public_metrics_json") or "{}")
        except json.JSONDecodeError:
            metrics = {}
        result = {
            "id": account["id"],
            "username": account["username"],
            "displayName": account.get("display_name") or account["username"],
            "bio": account.get("bio") or "",
            "avatarUrl": _file_url(account.get("avatar_path")),
            "bannerUrl": _file_url(account.get("banner_path")),
            "protected": bool(account.get("is_protected")),
            "verified": bool(account.get("is_verified")),
            "isPublic": bool(account.get("is_public", 1)),
            "metrics": metrics,
            "lastSyncedAt": account.get("last_synced_at"),
            "tweetCount": account.get("tweet_count", 0),
            "mediaCount": account.get("media_count", 0),
            "newestTweetAt": account.get("newest_tweet_at"),
        }
        if include_admin:
            result.update(
                {
                    "includeReplies": bool(account.get("include_replies")),
                    "includeReposts": bool(account.get("include_reposts")),
                    "lastTweetId": account.get("last_tweet_id"),
                    "lastError": account.get("last_error"),
                    "syncing": bool(account.get("syncing")),
                    "pendingMediaCount": account.get("pending_media_count", 0),
                }
            )
        return result

    def remove_account_files(self, username: str) -> None:
        for category in ("media", "profiles"):
            parent = (self.data_dir / category).resolve()
            target = (parent / username).resolve()
            try:
                target.relative_to(parent)
            except ValueError as error:
                raise RuntimeError("拒绝删除非法账号路径") from error
            if target != parent and target.is_dir():
                shutil.rmtree(target)


def create_server(address: tuple[str, int], application: Application) -> ThreadingHTTPServer:
    class Handler(RequestHandler):
        app = application

    return ThreadingHTTPServer(address, Handler)


class RequestHandler(BaseHTTPRequestHandler):
    app: Application
    server_version = "IncandescenceLocal/3"

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlsplit(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/api/member/status":
                member = self._member()
                self._json({"authenticated": member is not None, "member": member})
                return
            if path == "/api/public/accounts":
                is_admin = self._admin_authenticated()
                member = None if is_admin else self._member()
                self._json(
                    {
                        "items": [
                            self.app.account_public(a, include_admin=is_admin)
                            for a in self.app.database.list_accounts(
                                public_only=not is_admin and member is None,
                                member_id=int(member["id"]) if member else None,
                            )
                        ]
                    }
                )
                return
            match = re.fullmatch(r"/api/public/accounts/(\d+)/tweets", path)
            if match:
                account_id = int(match.group(1))
                self._require_visible_account(account_id)
                result = self.app.database.list_tweets(
                    account_id,
                    limit=_first(query, "limit", "30"),
                    cursor=_first(query, "cursor"),
                    query=_first(query, "q", ""),
                    kind=_first(query, "kind", "all"),
                    year=_first(query, "year"),
                    month=_first(query, "month"),
                )
                self._json(result)
                return
            match = re.fullmatch(r"/api/public/accounts/(\d+)/months", path)
            if match:
                account_id = int(match.group(1))
                self._require_visible_account(account_id)
                self._json({"items": self.app.database.list_tweet_months(account_id)})
                return
            if path == "/api/admin/status":
                self._json(
                    {
                        "setupRequired": not self.app.admin_auth.is_configured(),
                        "authenticated": self._admin_authenticated(),
                    }
                )
                return
            if path.startswith("/api/admin/"):
                self._require_admin()
            if path == "/api/admin/health":
                scraper_health = self.app.scraper_runtime.run(self.app.scraper.health(), timeout=30)
                self._json(
                    {
                        "version": __version__,
                        "scraper": scraper_health,
                        "sync": self.app.sync_service.status(),
                        "scheduler": self.app.scheduler.status(),
                    }
                )
                return
            if path == "/api/admin/settings":
                self._json(self._admin_settings())
                return
            if path == "/api/admin/scraper-sessions":
                self._json({"items": self.app.scraper_runtime.run(self.app.scraper.list_sessions(), timeout=30)})
                return
            if path == "/api/admin/accounts":
                self._json(
                    {
                        "items": [
                            self.app.account_public(a, include_admin=True)
                            for a in self.app.database.list_accounts()
                        ]
                    }
                )
                return
            if path == "/api/admin/members":
                self._json({"items": self.app.member_auth.list_members()})
                return
            if path.startswith("/files/"):
                self._serve_data_file(path.removeprefix("/files/"))
                return
            self._serve_static(path)
        except Exception as error:
            self._handle_error(error)

    def do_POST(self) -> None:  # noqa: N802
        try:
            path = urlsplit(self.path).path
            body = self._read_json()
            if path == "/api/member/login":
                token, member = self.app.member_auth.login(
                    str(body.get("username") or ""), str(body.get("password") or "")
                )
                self._json(
                    {"authenticated": True, "member": member},
                    headers={"Set-Cookie": self.app.member_auth.session_cookie(token)},
                )
                return
            if path == "/api/member/logout":
                self.app.member_auth.logout(self.headers.get("Cookie"))
                self._json(
                    {"authenticated": False, "member": None},
                    headers={"Set-Cookie": self.app.member_auth.clear_cookie()},
                )
                return
            if path == "/api/admin/setup":
                token = self.app.admin_auth.setup(str(body.get("password") or ""))
                self._json(
                    {"authenticated": True, "setupRequired": False},
                    HTTPStatus.CREATED,
                    headers={"Set-Cookie": self.app.admin_auth.session_cookie(token)},
                )
                return
            if path == "/api/admin/login":
                token = self.app.admin_auth.login(str(body.get("password") or ""))
                self._json(
                    {"authenticated": True, "setupRequired": False},
                    headers={"Set-Cookie": self.app.admin_auth.session_cookie(token)},
                )
                return
            if path == "/api/admin/logout":
                self.app.admin_auth.logout(self.headers.get("Cookie"))
                self._json(
                    {"authenticated": False},
                    headers={"Set-Cookie": self.app.admin_auth.clear_cookie()},
                )
                return
            if path.startswith("/api/admin/"):
                self._require_admin()
            if path == "/api/admin/accounts":
                account = self.app.database.create_account(str(body.get("username") or ""))
                self._json(
                    self.app.account_public(account, include_admin=True), HTTPStatus.CREATED
                )
                return
            if path == "/api/admin/members":
                item = self.app.member_auth.create_member(
                    str(body.get("username") or ""),
                    str(body.get("password") or ""),
                    body.get("accountIds") or [],
                )
                self._json(item, HTTPStatus.CREATED)
                return
            if path == "/api/admin/cookies/inspect":
                self._json(inspect_cookie_input(str(body.get("cookies") or "")))
                return
            if path == "/api/admin/proxy/test":
                proxy_url = normalize_proxy_url(body.get("proxyUrl"))
                if not proxy_url:
                    raise ValueError("请填写代理地址")
                result = self.app.scraper_runtime.run(
                    self.app.scraper.test_proxy(proxy_url), timeout=30
                )
                self._json(result)
                return
            if path == "/api/admin/bark/test":
                accounts = self.app.database.list_accounts()
                icon_url = str(accounts[0].get("profile_image_url") or "") if accounts else ""
                result = asyncio.run(self.app.notifier.test(icon_url=icon_url or None))
                self._json(result)
                return
            if path == "/api/admin/scraper-sessions":
                item = self.app.scraper_runtime.run(
                    self.app.scraper.add_session(
                        str(body.get("label") or ""), str(body.get("cookies") or "")
                    ),
                    timeout=45,
                )
                self._json(item, HTTPStatus.CREATED)
                return
            match = re.fullmatch(r"/api/admin/scraper-sessions/(.+)/validate", path)
            if match:
                result = self.app.scraper_runtime.run(
                    self.app.scraper.validate_saved_session(unquote(match.group(1))),
                    timeout=45,
                )
                self._json(result)
                return
            if path == "/api/admin/sync-all":
                self._json(asyncio.run(self.app.sync_service.sync_all(reason="manual-all")))
                return
            match = re.fullmatch(r"/api/admin/accounts/(\d+)/sync", path)
            if match:
                result = asyncio.run(
                    self.app.sync_service.sync_account(int(match.group(1)), reason="manual")
                )
                self._json(result)
                return
            self._error(HTTPStatus.NOT_FOUND, "接口不存在")
        except Exception as error:
            self._handle_error(error)

    def do_PUT(self) -> None:  # noqa: N802
        try:
            path = urlsplit(self.path).path
            body = self._read_json()
            if path.startswith("/api/admin/"):
                self._require_admin()
            if path == "/api/admin/settings":
                if body.pop("barkClearDeviceKey", False):
                    body["barkDeviceKey"] = ""
                settings = self.app.config.update(body)
                self.app.scheduler.reload()
                self._json(self._admin_settings(settings))
                return
            self._error(HTTPStatus.NOT_FOUND, "接口不存在")
        except Exception as error:
            self._handle_error(error)

    def do_PATCH(self) -> None:  # noqa: N802
        try:
            path = urlsplit(self.path).path
            body = self._read_json()
            if path.startswith("/api/admin/"):
                self._require_admin()
            match = re.fullmatch(r"/api/admin/accounts/(\d+)", path)
            if match:
                account = self.app.database.update_account_options(
                    int(match.group(1)),
                    include_replies=bool(body.get("includeReplies", True)),
                    include_reposts=bool(body.get("includeReposts", False)),
                    is_public=bool(body["isPublic"]) if "isPublic" in body else None,
                )
                self._json(self.app.account_public(account, include_admin=True))
                return
            match = re.fullmatch(r"/api/admin/members/(\d+)", path)
            if match:
                item = self.app.member_auth.update_member(
                    int(match.group(1)),
                    active=bool(body.get("active", True)),
                    account_ids=body.get("accountIds") or [],
                    password=str(body.get("password") or ""),
                )
                self._json(item)
                return
            self._error(HTTPStatus.NOT_FOUND, "接口不存在")
        except Exception as error:
            self._handle_error(error)

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            path = urlsplit(self.path).path
            if path.startswith("/api/admin/"):
                self._require_admin()
            match = re.fullmatch(r"/api/admin/accounts/(\d+)", path)
            if match:
                account = self.app.database.delete_account(int(match.group(1)))
                self.app.remove_account_files(account["username"])
                self._json({"deleted": True})
                return
            match = re.fullmatch(r"/api/admin/scraper-sessions/(.+)", path)
            if match:
                self.app.scraper_runtime.run(
                    self.app.scraper.delete_session(unquote(match.group(1))), timeout=30
                )
                self._json({"deleted": True})
                return
            match = re.fullmatch(r"/api/admin/members/(\d+)", path)
            if match:
                member_id = int(match.group(1))
                self.app.database.delete_member(member_id)
                self.app.member_auth.invalidate_member(member_id)
                self._json({"deleted": True})
                return
            self._error(HTTPStatus.NOT_FOUND, "接口不存在")
        except Exception as error:
            self._handle_error(error)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or 0)
        if length <= 0:
            return {}
        if length > 256 * 1024:
            raise ValueError("请求内容过大")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("JSON 格式无效") from error
        if not isinstance(value, dict):
            raise ValueError("请求内容必须是对象")
        return value

    def _admin_authenticated(self) -> bool:
        return self.app.admin_auth.authenticated(self.headers.get("Cookie"))

    def _require_admin(self) -> None:
        if not self._admin_authenticated():
            raise AdminAuthenticationRequired("需要管理员登录")

    def _member(self) -> dict[str, Any] | None:
        return self.app.member_auth.current(self.headers.get("Cookie"))

    def _admin_settings(
        self, settings: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        result = dict(settings or self.app.config.get())
        result["barkDeviceKeyConfigured"] = bool(result.get("barkDeviceKey"))
        result["barkDeviceKey"] = ""
        return result

    def _require_visible_account(self, account_id: int) -> None:
        account = self.app.database.get_account(account_id)
        if bool(account.get("is_public", 1)) or self._admin_authenticated():
            return
        member = self._member()
        if member and self.app.database.member_can_access(int(member["id"]), account_id):
            return
        raise KeyError("账号不存在")

    def _serve_static(self, request_path: str) -> None:
        if request_path in ("", "/"):
            relative = "home.html"
        elif request_path in ("/reader", "/reader/"):
            relative = "index.html"
        elif request_path in ("/admin", "/admin/"):
            relative = "admin.html"
        elif request_path in ("/login", "/login/"):
            relative = "member.html"
        else:
            relative = unquote(request_path.lstrip("/"))
        target = (self.app.public_dir / relative).resolve()
        try:
            target.relative_to(self.app.public_dir)
        except ValueError:
            self._error(HTTPStatus.FORBIDDEN, "拒绝访问")
            return
        if not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "页面不存在")
            return
        self._send_file(
            target,
            cache="no-cache" if target.suffix.lower() == ".html" else "public, max-age=3600",
        )

    def _serve_data_file(self, relative: str) -> None:
        clean_relative = unquote(relative).replace("\\", "/").lstrip("/")
        category = clean_relative.split("/", 1)[0]
        if category not in ("media", "profiles"):
            self._error(HTTPStatus.FORBIDDEN, "仅允许访问公开媒体文件")
            return
        owners = self.app.database.file_owner_accounts(clean_relative)
        if not self._admin_authenticated():
            if not owners:
                self._error(HTTPStatus.NOT_FOUND, "文件不存在")
                return
            member = self._member()
            allowed = any(bool(owner["is_public"]) for owner in owners)
            if member and not allowed:
                allowed = any(
                    self.app.database.member_can_access(int(member["id"]), int(owner["id"]))
                    for owner in owners
                )
            if not allowed:
                self._error(HTTPStatus.NOT_FOUND, "文件不存在")
                return
        target = (self.app.data_dir / clean_relative).resolve()
        try:
            target.relative_to(self.app.data_dir)
        except ValueError:
            self._error(HTTPStatus.FORBIDDEN, "拒绝访问")
            return
        if not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "文件不存在")
            return
        self._send_file(target, cache="public, max-age=31536000, immutable", ranges=True)

    def _send_file(self, path: Path, *, cache: str, ranges: bool = False) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("range") if ranges else None
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            left, right = match.groups()
            if not left and right:
                count = min(size, int(right))
                start = size - count
            else:
                start = int(left or 0)
                end = min(size - 1, int(right or size - 1))
            if start > end or start >= size:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        if ranges:
            self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self._security_headers()
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _json(
        self,
        value: Any,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def _handle_error(self, error: Exception) -> None:
        if isinstance(error, KeyError):
            self._error(HTTPStatus.NOT_FOUND, str(error).strip("'"))
        elif isinstance(error, AdminAuthenticationRequired):
            self._error(HTTPStatus.UNAUTHORIZED, str(error))
        elif isinstance(error, (ValueError, FileNotFoundError)):
            self._error(HTTPStatus.BAD_REQUEST, str(error))
        elif isinstance(error, CredentialValidationUnavailableError):
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
        elif isinstance(error, SyncBusyError):
            self._error(HTTPStatus.CONFLICT, str(error))
        else:
            self.log_error("%s", error)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error) or "服务器内部错误")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[web] {self.address_string()} - {format % args}")


def _first(query: dict[str, list[str]], key: str, default: Any = None) -> Any:
    values = query.get(key)
    return values[0] if values else default


class AdminAuthenticationRequired(RuntimeError):
    pass
