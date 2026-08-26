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
    "incrementalScanLimit": 500,
    "mediaConcurrency": 3,
    "maxMediaMb": 250,
    "proxyEnabled": False,
    "proxyUrl": "",
    "barkEnabled": False,
    "barkServerUrl": "https://api.day.app",
    "barkDeviceKey": "",
    "barkGroup": "Incandescence",
    "siteBaseUrl": "",
}


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
                data.get("incrementalScanLimit"), 500, 40, 3200
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
            "barkGroup": str(data.get("barkGroup") or "Incandescence").strip()[:64]
            or "Incandescence",
            "siteBaseUrl": normalize_http_base_url(
                data.get("siteBaseUrl"), field_name="站点访问地址", allow_path=False
            ),
        }
        if normalized["barkEnabled"] and not normalized["barkDeviceKey"]:
            raise ValueError("开启 Bark 推送前请填写 Device Key")
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
