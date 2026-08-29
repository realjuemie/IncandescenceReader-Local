from __future__ import annotations

import hashlib
import hmac
import html
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl
from urllib.parse import quote

import httpx

from .auth import AdminAuth
from .config import ConfigStore, normalize_telegram_user_id
from .database import Database
from .member_auth import MemberAuth


class TelegramAuthError(ValueError):
    pass


class TelegramDeliveryError(RuntimeError):
    pass


def x_profile_html(username: Any) -> str:
    """Return an HTML link that Telegram cannot mistake for a TG mention."""

    normalized = str(username or "unknown").strip().lstrip("@") or "unknown"
    label = html.escape(f"@{normalized}")
    url = f"https://x.com/{quote(normalized, safe='')}"
    return f'<a href="{url}">{label}</a>'


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 10 * 60,
    now: float | None = None,
) -> dict[str, Any]:
    """Validate Telegram Mini App initData and return its trusted user object."""

    if not init_data or len(init_data) > 16_384:
        raise TelegramAuthError("Telegram 登录数据缺失或过长")
    if not bot_token:
        raise TelegramAuthError("Telegram Bot 尚未配置")
    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as error:
        raise TelegramAuthError("Telegram 登录数据格式无效") from error
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise TelegramAuthError("Telegram 登录签名缺失")
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(received_hash.lower(), expected_hash):
        raise TelegramAuthError("Telegram 登录签名无效")
    try:
        auth_date = int(values["auth_date"])
    except (KeyError, TypeError, ValueError) as error:
        raise TelegramAuthError("Telegram 登录时间无效") from error
    current = time.time() if now is None else float(now)
    if auth_date > current + 30 or current - auth_date > max_age_seconds:
        raise TelegramAuthError("Telegram 登录信息已过期，请重新打开 Mini App")
    try:
        user = json.loads(values["user"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise TelegramAuthError("Telegram 用户信息无效") from error
    if not isinstance(user, dict):
        raise TelegramAuthError("Telegram 用户信息无效")
    user["id"] = normalize_telegram_user_id(user.get("id"))
    if not user["id"]:
        raise TelegramAuthError("Telegram 用户 ID 缺失")
    return user


class TelegramBotClient:
    def __init__(
        self,
        config: ConfigStore,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.config = config
        self.transport = transport

    async def call(
        self, method: str, payload: dict[str, Any] | None = None,
        *, token: str | None = None
    ) -> Any:
        bot_token = token or str(self.config.get().get("telegramBotToken") or "")
        if not bot_token:
            raise TelegramDeliveryError("请先填写 Telegram Bot Token")
        try:
            settings = self.config.get()
            proxy_url = None
            if not self.transport:
                proxy_url = (
                    settings.get("telegramProxyUrl")
                    if settings.get("telegramProxyEnabled")
                    else self.config.proxy_url()
                )
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
                proxy=proxy_url,
            ) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/{method}",
                    json=payload or {},
                )
        except httpx.HTTPError as error:
            raise TelegramDeliveryError("Telegram Bot API 连接失败") from error
        try:
            result = response.json()
        except ValueError as error:
            raise TelegramDeliveryError("Telegram 返回了无法识别的响应") from error
        if response.status_code >= 400 or not isinstance(result, dict) or not result.get("ok"):
            description = (
                str(result.get("description") or "请求被 Telegram 拒绝")
                if isinstance(result, dict)
                else "请求被 Telegram 拒绝"
            )
            raise TelegramDeliveryError(f"Telegram 操作失败：{description[:180]}")
        return result.get("result")

    async def test(self, *, token: str | None = None) -> dict[str, Any]:
        bot = await self.call("getMe", token=token)
        return {
            "ok": True,
            "id": str(bot.get("id") or ""),
            "username": str(bot.get("username") or ""),
            "name": str(bot.get("first_name") or ""),
        }

    async def deploy(self) -> dict[str, Any]:
        settings = self.config.get()
        base_url = str(settings.get("siteBaseUrl") or "").rstrip("/")
        if not base_url.lower().startswith("https://"):
            raise ValueError("Telegram Mini App 必须使用公开可访问的 HTTPS 站点地址")
        bot = await self.test()
        secret = str(settings.get("telegramWebhookSecret") or "")
        if not secret:
            secret = secrets.token_urlsafe(32)
        webhook_url = f"{base_url}/api/telegram/webhook/{secret}"
        await self.call(
            "setWebhook",
            {
                "url": webhook_url,
                "secret_token": secret,
                "allowed_updates": ["message"],
                "drop_pending_updates": False,
            },
        )
        await self.call(
            "setChatMenuButton",
            {"menu_button": {"type": "commands"}},
        )
        await self.call(
            "setMyCommands",
            {
                "scope": {"type": "all_private_chats"},
                "commands": [
                    {"command": "start", "description": "打开 X拾光 Mini App"},
                    {"command": "whoami", "description": "查看 Telegram ID 和会员状态"},
                    {"command": "app", "description": "打开阅读页面"},
                    {"command": "admin", "description": "管理员入口"},
                    {"command": "grant", "description": "管理员：授权 TG_ID 为会员"},
                    {"command": "revoke", "description": "管理员：停用 TG_ID 会员"},
                ]
            },
        )
        deployed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.config.update(
            {
                "telegramWebhookSecret": secret,
                "telegramBotUsername": bot["username"],
                "telegramDeployedAt": deployed_at,
                "telegramEnabled": True,
            }
        )
        return {
            **bot,
            "webhookConfigured": True,
            "deployedAt": deployed_at,
        }

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "text": str(text)[:4096],
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return await self.call("sendMessage", payload)


class TelegramService:
    def __init__(
        self,
        config: ConfigStore,
        database: Database,
        admin_auth: AdminAuth,
        member_auth: MemberAuth,
        client: TelegramBotClient,
    ):
        self.config = config
        self.database = database
        self.admin_auth = admin_auth
        self.member_auth = member_auth
        self.client = client

    def authenticate(
        self, init_data: str, *, current_member_id: int | None = None
    ) -> dict[str, Any]:
        settings = self.config.get()
        if not settings.get("telegramEnabled"):
            raise TelegramAuthError("Telegram Mini App 尚未启用")
        user = validate_init_data(init_data, settings.get("telegramBotToken") or "")
        self.database.upsert_telegram_user(user)
        user_id = str(user["id"])
        if user_id == str(settings.get("telegramAdminUserId") or ""):
            return {
                "role": "admin",
                "token": self.admin_auth.issue_session(),
                "user": user,
            }
        if current_member_id is not None:
            member = self.member_auth.bind_telegram(current_member_id, user)
            token, member = self.member_auth.issue_session(current_member_id)
            return {"role": "member", "token": token, "member": member, "user": user}
        login = self.member_auth.login_telegram(user)
        if login:
            token, member = login
            return {"role": "member", "token": token, "member": member, "user": user}
        return {"role": "pending", "user": user}

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict):
            return
        sender = message.get("from")
        chat = message.get("chat")
        if not isinstance(sender, dict) or not isinstance(chat, dict):
            return
        try:
            user = self.database.upsert_telegram_user(sender, chat_id=chat.get("id"))
        except ValueError:
            return
        text = str(message.get("text") or "").strip()
        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        chat_id = str(chat.get("id") or "")
        if not chat_id:
            return
        settings = self.config.get()
        base_url = str(settings.get("siteBaseUrl") or "").rstrip("/")
        is_admin = str(sender.get("id")) == str(settings.get("telegramAdminUserId") or "")
        member = self.database.get_member_by_telegram_user_id(sender.get("id"))
        if command in ("/start", "/app"):
            await self.client.send_message(
                chat_id,
                "欢迎来到 X拾光。点击下方按钮，在 Telegram 内直接阅读你的时间线。",
                reply_markup=self._web_app_button(base_url, "打开 X拾光"),
            )
        elif command == "/whoami":
            status = "管理员" if is_admin else ("有效会员" if member and member.get("active") else "待授权")
            await self.client.send_message(
                chat_id, f"你的 Telegram ID：{sender.get('id')}\n当前身份：{status}"
            )
        elif command == "/admin":
            if not is_admin:
                await self.client.send_message(chat_id, "此入口仅管理员可用。")
                return
            await self.client.send_message(
                chat_id,
                "打开 X拾光管理面板：",
                reply_markup=self._web_app_button(f"{base_url}/admin", "打开管理面板"),
            )
        elif command in ("/grant", "/revoke"):
            await self._handle_membership_command(
                command, argument.strip(), sender, chat_id, is_admin
            )

    async def _handle_membership_command(
        self,
        command: str,
        argument: str,
        sender: dict[str, Any],
        chat_id: str,
        is_admin: bool,
    ) -> None:
        if not is_admin:
            await self.client.send_message(chat_id, "此命令仅管理员可用。")
            return
        try:
            target_id = normalize_telegram_user_id(argument)
        except ValueError:
            await self.client.send_message(chat_id, f"用法：{command} <Telegram ID>")
            return
        if command == "/grant":
            result = await self.grant_member(target_id)
            member = result["member"]
            notification = result["notification"]
            suffix = ""
            if not notification.get("sent"):
                suffix = f"\n授权成功，但会员通知未送达：{notification.get('error') or '用户尚未启动机器人'}"
            await self.client.send_message(
                chat_id,
                f"已授权 TG {target_id}，会员账号：{member['username']}。{suffix}",
            )
            return
        member = self.database.get_member_by_telegram_user_id(target_id)
        if not member:
            await self.client.send_message(chat_id, f"TG {target_id} 尚未绑定会员。")
            return
        member_ids = self.database.list_members()
        full = next(item for item in member_ids if int(item["id"]) == int(member["id"]))
        self.member_auth.update_member(
            int(member["id"]), active=False, account_ids=full.get("account_ids", [])
        )
        await self.client.send_message(chat_id, f"已停用 TG {target_id} 对应的会员。")

    async def grant_member(self, target_id: str | int) -> dict[str, Any]:
        """Create or reactivate a Telegram member and notify that Telegram user."""

        normalized = normalize_telegram_user_id(target_id)
        try:
            target = self.database.get_telegram_user(normalized)
        except KeyError:
            target = {"user_id": normalized, "id": normalized}
        target_user = {
            "id": normalized,
            "username": target.get("username") or "",
            "first_name": target.get("first_name") or "",
            "last_name": target.get("last_name") or "",
            "photo_url": target.get("photo_url") or "",
        }
        member = self.member_auth.create_telegram_member(target_user)
        chat_id = str(target.get("chat_id") or normalized).strip()
        notification = await self._deliver_member_notice(
            chat_id,
            "你已升级为 X拾光会员。\n现在可以重新打开 Mini App，查看管理员为你开放的内容。",
        )
        return {"member": member, "notification": notification}

    async def notify_account_access_granted(
        self, member_id: int, account_ids: list[int]
    ) -> dict[str, Any]:
        """Notify a Telegram-bound member about newly assigned private accounts."""

        if not account_ids:
            return {"sent": False, "skipped": True, "reason": "no-new-accounts"}
        member = self.database.get_member(member_id)
        telegram_user_id = str(member.get("telegram_user_id") or "").strip()
        if not bool(member.get("active")) or not telegram_user_id:
            return {"sent": False, "skipped": True, "reason": "member-not-bound"}
        accounts = []
        for account_id in sorted({int(value) for value in account_ids}):
            account = self.database.get_account(account_id)
            if not bool(account.get("is_public", 1)):
                accounts.append(account)
        if not accounts:
            return {"sent": False, "skipped": True, "reason": "no-private-accounts"}
        try:
            telegram_user = self.database.get_telegram_user(telegram_user_id)
            chat_id = str(telegram_user.get("chat_id") or telegram_user_id)
        except KeyError:
            chat_id = telegram_user_id
        account_lines = "\n".join(
            f"• {html.escape(str(item.get('display_name') or item['username']))} "
            f"({x_profile_html(item['username'])})"
            for item in accounts
        )
        return await self._deliver_member_notice(
            chat_id,
            f"你获得了新的 X拾光会员专属账号权限：\n{account_lines}\n\n重新打开或刷新 Mini App 即可查看。",
            parse_mode="HTML",
        )

    async def _deliver_member_notice(
        self, chat_id: str, message: str, *, parse_mode: str | None = None
    ) -> dict[str, Any]:
        if not chat_id:
            return {"sent": False, "skipped": True, "reason": "chat-unavailable"}
        try:
            await self.client.send_message(
                chat_id,
                message,
                reply_markup=self._web_app_button(
                    str(self.config.get().get("siteBaseUrl") or ""), "打开 X拾光"
                ),
                parse_mode=parse_mode,
            )
        except Exception as error:
            return {"sent": False, "error": str(error)}
        return {"sent": True}

    @staticmethod
    def _web_app_button(url: str, text: str) -> dict[str, Any] | None:
        if not str(url).lower().startswith("https://"):
            return None
        return {
            "inline_keyboard": [[{"text": text, "web_app": {"url": url}}]]
        }
