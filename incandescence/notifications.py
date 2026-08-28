from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from .config import ConfigStore


class BarkDeliveryError(RuntimeError):
    pass


class BarkNotifier:
    def __init__(
        self,
        config: ConfigStore,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.config = config
        self.transport = transport

    async def test(self, *, icon_url: str | None = None) -> dict[str, Any]:
        settings = self.config.get()
        return await self.test_settings(settings, icon_url=icon_url)

    async def test_settings(
        self, settings: dict[str, Any], *, icon_url: str | None = None
    ) -> dict[str, Any]:
        return await self._send(
            settings,
            title="XGlow · Bark 测试成功",
            body="通知渠道已连接。后续选中的账号出现新内容时会在这里提醒。",
            icon_url=icon_url,
            target_url=settings.get("siteBaseUrl") or None,
        )

    async def notify_account_update(
        self,
        *,
        account_id: int,
        profile: dict[str, Any],
        tweets: list[dict[str, Any]],
        inserted: int,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        settings = settings or self.config.get()
        if not settings["barkEnabled"] or inserted <= 0:
            return None
        username = str(profile.get("username") or "unknown").lstrip("@")
        display_name = str(profile.get("display_name") or username)
        newest = tweets[0] if tweets else {}
        new_items = tweets[:inserted]
        kinds: list[str] = []
        originals = sum(
            1 for item in new_items if not item.get("is_reply") and not item.get("is_repost")
        )
        replies = sum(1 for item in new_items if item.get("is_reply"))
        reposts = sum(1 for item in new_items if item.get("is_repost"))
        media = sum(len(item.get("media") or []) for item in new_items)
        if originals:
            kinds.append(f"原创 {originals}")
        if replies:
            kinds.append(f"回复 {replies}")
        if reposts:
            kinds.append(f"转发 {reposts}")
        if media:
            kinds.append(f"媒体 {media}")
        summary = _summary_text(newest.get("text"))
        lines = [f"{display_name}（@{username}）", "新增：" + " · ".join(kinds or [f"内容 {inserted}"])]
        if summary:
            lines.append("最新：" + summary)
        base_url = str(settings.get("siteBaseUrl") or "").rstrip("/")
        target_url = (
            f"{base_url}/reader?account={account_id}"
            if base_url
            else str(newest.get("source_url") or f"https://x.com/{quote(username)}")
        )
        return await self._send(
            settings,
            title=f"@{username} 有 {inserted} 条新内容",
            body="\n".join(lines),
            icon_url=_profile_icon_url(profile),
            target_url=target_url,
        )

    async def notify_invalid_credentials(
        self,
        *,
        sessions: list[dict[str, Any]],
        cause: str | None = None,
    ) -> dict[str, Any] | None:
        settings = self.config.get()
        if not settings["barkEnabled"] or not sessions:
            return None
        lines = ["以下 X 登录凭证已不可用，请在管理后台重新导入 Cookie："]
        for item in sessions[:12]:
            label = str(item.get("label") or "未命名凭证")
            username = str(item.get("verifiedUsername") or "").lstrip("@")
            identity = f"{label}（@{username}）" if username else label
            reason = str(item.get("error") or "验证失败或登录状态已失效").strip()
            lines.append(f"• {identity}：{_summary_text(reason)}")
        if len(sessions) > 12:
            lines.append(f"另有 {len(sessions) - 12} 个凭证失效")
        if cause:
            lines.append("触发原因：" + _summary_text(cause))
        base_url = str(settings.get("siteBaseUrl") or "").rstrip("/")
        target_url = f"{base_url}/admin#credential-panel" if base_url else None
        return await self._send(
            settings,
            title=f"X 登录凭证失效（{len(sessions)}）",
            body="\n".join(lines),
            icon_url=None,
            target_url=target_url,
        )

    async def _send(
        self,
        settings: dict[str, Any],
        *,
        title: str,
        body: str,
        icon_url: str | None,
        target_url: str | None,
    ) -> dict[str, Any]:
        server_url = str(settings.get("barkServerUrl") or "").rstrip("/")
        device_key = str(settings.get("barkDeviceKey") or "")
        if not server_url or not device_key:
            raise ValueError("请先填写 Bark 服务器地址和 Device Key")
        payload: dict[str, Any] = {
            "device_key": device_key,
            "title": title[:120],
            "body": body[:1500],
            "group": str(settings.get("barkGroup") or "XGlow")[:64],
            "level": "active",
        }
        if icon_url:
            payload["icon"] = icon_url
        if target_url:
            payload["url"] = target_url
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                follow_redirects=True,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.post(f"{server_url}/push", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise BarkDeliveryError(f"Bark 推送连接失败：{error}") from error
        try:
            result = response.json()
        except ValueError as error:
            raise BarkDeliveryError("Bark 服务器返回了无法识别的响应") from error
        code = result.get("code") if isinstance(result, dict) else None
        if str(code) != "200":
            message = str(result.get("message") or "推送被服务器拒绝") if isinstance(result, dict) else "推送被服务器拒绝"
            raise BarkDeliveryError(f"Bark 推送失败：{message[:160]}")
        return {
            "sent": True,
            "status": int(response.status_code),
            "elapsedMs": round((time.perf_counter() - started) * 1000),
        }


def _summary_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:137] + "…" if len(text) > 140 else text


def _profile_icon_url(profile: dict[str, Any]) -> str | None:
    """Choose the most reliable remote profile image for Bark's icon fetcher."""
    for key in ("avatar_icon_url", "avatar_url"):
        value = str(profile.get(key) or "").strip()
        if value.startswith(("https://", "http://")):
            return value
    return None
