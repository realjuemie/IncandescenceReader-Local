from __future__ import annotations

import json
import os
import re
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlsplit


DEFAULT_SETTINGS: dict[str, Any] = {
    "scheduleEnabled": False,
    "scheduleMinutes": 30,
    "initialFetchLimit": 100,
    "incrementalScanLimit": 80,
    "mediaConcurrency": 3,
    "maxMediaMb": 250,
    "proxyEnabled": False,
    "proxyUrl": "",
    "barkEnabled": False,
    "barkServerUrl": "https://api.day.app",
    "barkDeviceKey": "",
    "barkGroup": "XGlow",
    "siteBaseUrl": "",
    "telegramEnabled": False,
    "telegramNotificationsEnabled": False,
    "telegramBotToken": "",
    "telegramApiId": "",
    "telegramApiHash": "",
    "telegramAdminUserId": "",
    "telegramWebhookSecret": "",
    "telegramBotUsername": "",
    "telegramDeployedAt": "",
    "telegramProxyEnabled": False,
    "telegramProxyUrl": "",
    "assistantEnabled": True,
    "assistantContactName": "作者",
    "assistantContactTagline": "",
    "assistantContactTelegram": "",
    "assistantContactEmail": "",
    "assistantContactHome": "",
    "assistantContactX": "",
    "assistantContactWechat": "",
    "assistantCustom1Label": "",
    "assistantCustom1Value": "",
    "assistantCustom1Href": "",
    "assistantCustom2Label": "",
    "assistantCustom2Value": "",
    "assistantCustom2Href": "",
    "assistantCustom3Label": "",
    "assistantCustom3Value": "",
    "assistantCustom3Href": "",
}


def _bounded_text(value: Any, default: str = "", maximum: int = 80) -> str:
    text = str(value if value is not None else default).strip()
    return text[:maximum]


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


class ConfigStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.path = self.data_dir / "settings.json"
        self._lock = RLock()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def get(self) -> dict[str, Any]:
        with self._lock:
            data = dict(DEFAULT_SETTINGS)
            if self.path.exists():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data.update(loaded)
                except (OSError, json.JSONDecodeError):
                    pass
            return self._normalize(data)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_SETTINGS)
        with self._lock:
            data = self.get()
            for key, value in patch.items():
                if key in allowed:
                    data[key] = value
            data = self._normalize(data)
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
            return data

    def proxy_url(self) -> str | None:
        settings = self.get()
        if settings["proxyEnabled"]:
            return settings["proxyUrl"] or None
        environment_proxy = os.environ.get("TWS_PROXY")
        return normalize_proxy_url(environment_proxy) or None

    @staticmethod
    def _normalize(data: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "scheduleEnabled": bool(data.get("scheduleEnabled", False)),
            "scheduleMinutes": _bounded_int(data.get("scheduleMinutes"), 30, 5, 10080),
            "initialFetchLimit": _bounded_int(data.get("initialFetchLimit"), 100, 20, 500),
            "incrementalScanLimit": _bounded_int(
                data.get("incrementalScanLimit"), 80, 40, 3200
            ),
            "mediaConcurrency": _bounded_int(data.get("mediaConcurrency"), 3, 1, 6),
            "maxMediaMb": _bounded_int(data.get("maxMediaMb"), 250, 10, 2000),
            "proxyEnabled": bool(data.get("proxyEnabled", False)),
            "proxyUrl": normalize_proxy_url(data.get("proxyUrl")),
            "barkEnabled": bool(data.get("barkEnabled", False)),
            "barkServerUrl": normalize_http_base_url(
                data.get("barkServerUrl") or "https://api.day.app",
                field_name="Bark 服务器地址",
                allow_path=True,
            ),
            "barkDeviceKey": normalize_bark_device_key(data.get("barkDeviceKey")),
            "barkGroup": str(data.get("barkGroup") or "XGlow").strip()[:64]
            or "XGlow",
            "siteBaseUrl": normalize_http_base_url(
                data.get("siteBaseUrl"), field_name="站点访问地址", allow_path=False
            ),
            "telegramEnabled": bool(data.get("telegramEnabled", False)),
            "telegramNotificationsEnabled": bool(
                data.get("telegramNotificationsEnabled", False)
            ),
            "telegramBotToken": normalize_telegram_bot_token(
                data.get("telegramBotToken")
            ),
            "telegramApiId": normalize_telegram_api_id(data.get("telegramApiId")),
            "telegramApiHash": normalize_telegram_api_hash(
                data.get("telegramApiHash")
            ),
            "telegramAdminUserId": normalize_telegram_user_id(
                data.get("telegramAdminUserId"), field_name="管理员 Telegram ID"
            ),
            "telegramWebhookSecret": normalize_telegram_webhook_secret(
                data.get("telegramWebhookSecret")
            ),
            "telegramBotUsername": str(data.get("telegramBotUsername") or "")
            .strip()
            .lstrip("@")[:64],
            "telegramDeployedAt": str(data.get("telegramDeployedAt") or "").strip()[:64],
            "telegramProxyEnabled": bool(data.get("telegramProxyEnabled", False)),
            "telegramProxyUrl": normalize_proxy_url(data.get("telegramProxyUrl")),
            "assistantEnabled": bool(data.get("assistantEnabled", True)),
            "assistantContactName": _bounded_text(
                data.get("assistantContactName"), "作者", 32
            )
            or "作者",
            "assistantContactTagline": _bounded_text(
                data.get("assistantContactTagline"), "", 80
            ),
            "assistantContactTelegram": _bounded_text(
                data.get("assistantContactTelegram"), "", 64
            ),
            "assistantContactEmail": _bounded_text(
                data.get("assistantContactEmail"), "", 80
            ),
            "assistantContactHome": _bounded_text(
                data.get("assistantContactHome"), "", 120
            ),
            "assistantContactX": _bounded_text(data.get("assistantContactX"), "", 64),
            "assistantContactWechat": _bounded_text(
                data.get("assistantContactWechat"), "", 64
            ),
            "assistantCustom1Label": _bounded_text(
                data.get("assistantCustom1Label"), "", 24
            ),
            "assistantCustom1Value": _bounded_text(
                data.get("assistantCustom1Value"), "", 80
            ),
            "assistantCustom1Href": _bounded_text(
                data.get("assistantCustom1Href"), "", 160
            ),
            "assistantCustom2Label": _bounded_text(
                data.get("assistantCustom2Label"), "", 24
            ),
            "assistantCustom2Value": _bounded_text(
                data.get("assistantCustom2Value"), "", 80
            ),
            "assistantCustom2Href": _bounded_text(
                data.get("assistantCustom2Href"), "", 160
            ),
            "assistantCustom3Label": _bounded_text(
                data.get("assistantCustom3Label"), "", 24
            ),
            "assistantCustom3Value": _bounded_text(
                data.get("assistantCustom3Value"), "", 80
            ),
            "assistantCustom3Href": _bounded_text(
                data.get("assistantCustom3Href"), "", 160
            ),
        }
        if normalized["barkEnabled"] and not normalized["barkDeviceKey"]:
            raise ValueError("开启 Bark 推送前请填写 Device Key")
        if normalized["telegramEnabled"] and not normalized["telegramBotToken"]:
            raise ValueError("开启 Telegram 前请填写 Bot Token")
        if normalized["telegramProxyEnabled"] and not normalized["telegramProxyUrl"]:
            raise ValueError("开启 Telegram 独立代理前请填写代理地址")
        return normalized


def normalize_proxy_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as error:
        raise ValueError("代理地址格式无效") from error
    if parsed.scheme.lower() not in ("http", "https", "socks5"):
        raise ValueError("代理仅支持 http://、https:// 或 socks5://")
    if not parsed.hostname:
        raise ValueError("代理地址缺少主机名")
    if port is None:
        raise ValueError("代理地址必须包含端口，例如 http://127.0.0.1:7890")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("代理地址不能包含路径、查询参数或片段")
    return text


def normalize_http_base_url(
    value: Any, *, field_name: str, allow_path: bool
) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
        _ = parsed.port
    except ValueError as error:
        raise ValueError(f"{field_name}格式无效") from error
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{field_name}必须是完整的 http:// 或 https:// 地址")
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name}不能包含账号密码")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field_name}不能包含查询参数或片段")
    if not allow_path and parsed.path not in ("", "/"):
        raise ValueError(f"{field_name}不能包含路径")
    return text


def normalize_bark_device_key(value: Any) -> str:
    key = str(value or "").strip()
    if not key:
        return ""
    if not re.fullmatch(r"[^\s/]{4,512}", key):
        raise ValueError("Bark Device Key 格式无效")
    return key


def normalize_telegram_bot_token(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if not re.fullmatch(r"\d{6,16}:[A-Za-z0-9_-]{20,160}", token):
        raise ValueError("Telegram Bot Token 格式无效")
    return token


def normalize_telegram_api_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.fullmatch(r"\d{4,15}", text):
        raise ValueError("Telegram api_id 格式无效")
    return text


def normalize_telegram_api_hash(value: Any) -> str:
    value = str(value or "").strip().lower()
    if not value:
        return ""
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Telegram api_hash 格式无效")
    return value


def normalize_telegram_user_id(value: Any, *, field_name: str = "Telegram ID") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.fullmatch(r"[1-9]\d{4,19}", text):
        raise ValueError(f"{field_name}必须是 5–20 位数字")
    return text


def normalize_telegram_webhook_secret(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,128}", text):
        raise ValueError("Telegram Webhook 密钥格式无效")
    return text


def runtime_paths(project_root: Path) -> tuple[Path, Path]:
    data_dir = Path(os.environ.get("DATA_DIR", project_root / "data")).expanduser().resolve()
    public_dir = (project_root / "public").resolve()
    return data_dir, public_dir


def server_address() -> tuple[str, int]:
    host = os.environ.get("HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("PORT", "8787"))
    except ValueError:
        port = 8787
    return host, min(65535, max(1, port))
