from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import re
import secrets
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .database import Database


MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


class MediaStore:
    def __init__(
        self,
        data_dir: Path,
        database: Database,
        proxy_url_getter: Callable[[], str | None] | None = None,
    ):
        self.data_dir = data_dir.resolve()
        self.database = database
        self._proxy_url_getter = proxy_url_getter or (lambda: None)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    async def download_profile_assets(
        self,
        account: dict[str, Any],
        profile: dict[str, Any],
        *,
        max_media_mb: int,
    ) -> tuple[str | None, str | None]:
        try:
            import httpx
        except ImportError as error:
            raise RuntimeError("抓取组件未安装，请先运行 setup-windows.ps1") from error
        timeout = httpx.Timeout(60, connect=20)
        async with httpx.AsyncClient(
            proxy=self._proxy_url_getter(),
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://x.com/"},
        ) as client:
            avatar = await self._profile_asset(
                client,
                account,
                profile.get("avatar_url"),
                account.get("profile_image_url"),
                account.get("avatar_path"),
                "avatar",
                max_media_mb,
            )
            banner = await self._profile_asset(
                client,
                account,
                profile.get("banner_url"),
                account.get("profile_banner_url"),
                account.get("banner_path"),
                "banner",
                max_media_mb,
            )
        return avatar, banner

    async def _profile_asset(
        self,
        client: Any,
        account: dict[str, Any],
        source_url: str | None,
        old_source_url: str | None,
        old_local_path: str | None,
        name: str,
        max_media_mb: int,
    ) -> str | None:
        if not source_url:
            return old_local_path
        if source_url == old_source_url and old_local_path:
            old_file = self._safe_local(old_local_path)
            if old_file.is_file():
                return old_local_path
        try:
            target_dir = self.data_dir / "profiles" / _safe_name(account["username"])
            path, _ = await self._download(
                client, source_url, target_dir, name, max_media_mb=max_media_mb
            )
            return self._relative(path)
        except Exception:
            return old_local_path

    async def download_pending(
        self,
        account_id: int,
        *,
        concurrency: int,
        max_media_mb: int,
    ) -> dict[str, int]:
        records = self.database.pending_media(account_id)
        if not records:
            return {"downloaded": 0, "failed": 0, "pending": 0}
        try:
            import httpx
        except ImportError as error:
            raise RuntimeError("抓取组件未安装，请先运行 setup-windows.ps1") from error
        semaphore = asyncio.Semaphore(max(1, concurrency))
        result = {"downloaded": 0, "failed": 0, "pending": len(records)}
        result_lock = asyncio.Lock()
        timeout = httpx.Timeout(120, connect=20)
        async with httpx.AsyncClient(
            proxy=self._proxy_url_getter(),
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://x.com/"},
        ) as client:

            async def run(record: dict[str, Any]) -> None:
                async with semaphore:
                    try:
                        local, preview, mime_type = await self._download_media_record(
                            client, record, max_media_mb=max_media_mb
                        )
                        self.database.media_downloaded(record["id"], local, preview, mime_type)
                        async with result_lock:
                            result["downloaded"] += 1
                    except Exception as error:
                        self.database.media_failed(record["id"], str(error))
                        async with result_lock:
                            result["failed"] += 1

            await asyncio.gather(*(run(record) for record in records))
        return result

    async def download_author_avatars(
        self,
        account: dict[str, Any],
        tweets: list[dict[str, Any]],
        *,
        max_media_mb: int,
    ) -> dict[str, str]:
        sources: dict[str, tuple[str, str]] = {}
        for tweet in tweets:
            username = str(tweet.get("author_username") or "").strip()
            url = str(tweet.get("author_avatar_url") or "").strip()
            if username and url:
                sources[username.lower()] = (username, url)
        if not sources:
            return {}
        try:
            import httpx
        except ImportError as error:
            raise RuntimeError("抓取组件未安装，请先运行 setup-windows.ps1") from error
        results: dict[str, str] = {}
        semaphore = asyncio.Semaphore(4)
        timeout = httpx.Timeout(60, connect=20)
        async with httpx.AsyncClient(
            proxy=self._proxy_url_getter(),
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://x.com/"},
        ) as client:

            async def run(key: str, username: str, url: str) -> None:
                digest = hashlib.sha1(
                    url.encode("utf-8"), usedforsecurity=False
                ).hexdigest()[:12]
                target_dir = (
                    self.data_dir
                    / "profiles"
                    / _safe_name(account["username"])
                    / "authors"
                    / _safe_name(username)
                )
                try:
                    async with semaphore:
                        path, _ = await self._download(
                            client,
                            url,
                            target_dir,
                            f"avatar-{digest}",
                            max_media_mb=max_media_mb,
                        )
                    results[key] = self._relative(path)
                except Exception:
                    return

            await asyncio.gather(
                *(run(key, username, url) for key, (username, url) in sources.items())
            )
        return results

    async def _download_media_record(
        self, client: Any, record: dict[str, Any], *, max_media_mb: int
    ) -> tuple[str, str | None, str | None]:
        target_dir = (
            self.data_dir
            / "media"
            / _safe_name(record["username"])
            / _safe_name(record["tweet_id"])
        )
        stem = _safe_name(record["media_key"])
        path, mime_type = await self._download(
            client,
            record["source_url"],
            target_dir,
            stem,
            max_media_mb=max_media_mb,
        )
        preview_local = None
        if record.get("preview_source_url"):
            try:
                preview, _ = await self._download(
                    client,
                    record["preview_source_url"],
                    target_dir,
                    stem + "-preview",
                    max_media_mb=max_media_mb,
                )
                preview_local = self._relative(preview)
            except Exception:
                preview_local = None
        return self._relative(path), preview_local, mime_type

    async def _download(
        self,
        client: Any,
        url: str,
        target_dir: Path,
        stem: str,
        *,
        max_media_mb: int,
    ) -> tuple[Path, str | None]:
        self._validate_remote(url)
        target_dir = target_dir.resolve()
        self._ensure_inside_data(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        guessed_ext = _extension_from_url(url)
        existing = next(target_dir.glob(stem + ".*"), None)
        if existing and existing.is_file() and ".part-" not in existing.name:
            return existing, mimetypes.guess_type(existing.name)[0]

        async with client.stream("GET", url) as response:
            response.raise_for_status()
            mime_type = (response.headers.get("content-type") or "").split(";", 1)[0].lower()
            extension = MIME_EXTENSIONS.get(mime_type) or guessed_ext or ".bin"
            final_path = (target_dir / f"{stem}{extension}").resolve()
            self._ensure_inside_data(final_path)
            if final_path.is_file():
                return final_path, mime_type or None
            max_bytes = max_media_mb * 1024 * 1024
            declared = int(response.headers.get("content-length") or 0)
            if declared > max_bytes:
                raise RuntimeError(f"媒体超过 {max_media_mb} MB 限制")
            temporary = final_path.with_name(final_path.name + f".part-{secrets.token_hex(4)}")
            written = 0
            try:
                with temporary.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        written += len(chunk)
                        if written > max_bytes:
                            raise RuntimeError(f"媒体超过 {max_media_mb} MB 限制")
                        output.write(chunk)
                os.replace(temporary, final_path)
            finally:
                temporary.unlink(missing_ok=True)
        return final_path, mime_type or None

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.data_dir).as_posix()

    def _safe_local(self, relative_path: str) -> Path:
        path = (self.data_dir / relative_path).resolve()
        self._ensure_inside_data(path)
        return path

    def _ensure_inside_data(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.data_dir)
        except ValueError as error:
            raise RuntimeError("非法的本地媒体路径") from error

    @staticmethod
    def _validate_remote(url: str) -> None:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not (host == "twimg.com" or host.endswith(".twimg.com")):
            raise RuntimeError("拒绝下载非 X 媒体域名")


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value))
    return safe[:120] or "file"


def _extension_from_url(url: str) -> str | None:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    format_value = (query.get("format") or [None])[0]
    if format_value and re.fullmatch(r"[A-Za-z0-9]{2,5}", format_value):
        return "." + format_value.lower().replace("jpeg", "jpg")
    suffix = Path(parts.path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{2,5}", suffix):
        return suffix
    return None
