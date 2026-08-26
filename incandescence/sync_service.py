from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from .async_runtime import AsyncRuntime
from .config import ConfigStore
from .database import Database
from .media import MediaStore
from .notifications import BarkNotifier
from .scraper import FreeXScraper


class SyncBusyError(RuntimeError):
    pass


class SyncService:
    def __init__(
        self,
        database: Database,
        config: ConfigStore,
        scraper: FreeXScraper,
        media: MediaStore,
        scraper_runtime: AsyncRuntime | None = None,
        notifier: BarkNotifier | None = None,
    ):
        self.database = database
        self.config = config
        self.scraper = scraper
        self.media = media
        self.scraper_runtime = scraper_runtime
        self.notifier = notifier
        self._lock = threading.Lock()
        self._current_account_id: int | None = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._lock.locked(),
            "accountId": self._current_account_id,
        }

    async def sync_account(self, account_id: int, reason: str = "manual") -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise SyncBusyError("已有同步任务正在运行，请稍后再试")
        self._current_account_id = account_id
        try:
            account = self.database.get_account(account_id)
            self.database.mark_sync_started(account_id)
            settings = self.config.get()
            fetch = self.scraper.fetch_latest(
                username=account["username"],
                last_tweet_id=account.get("last_tweet_id"),
                include_replies=bool(account["include_replies"]),
                include_reposts=bool(account["include_reposts"]),
                initial_limit=settings["initialFetchLimit"],
                incremental_limit=settings["incrementalScanLimit"],
            )
            result = (
                await self.scraper_runtime.await_result(fetch)
                if self.scraper_runtime
                else await fetch
            )
            avatar_path, banner_path = await self.media.download_profile_assets(
                account,
                result["profile"],
                max_media_mb=settings["maxMediaMb"],
            )
            self.database.update_profile(
                account_id, result["profile"], avatar_path, banner_path
            )
            author_avatar_paths = await self.media.download_author_avatars(
                account,
                result["tweets"],
                max_media_mb=settings["maxMediaMb"],
            )
            profile_username = str(result["profile"].get("username") or "").lower()
            for tweet in result["tweets"]:
                key = str(tweet.get("author_username") or "").lower()
                if key == profile_username and avatar_path:
                    tweet["author_avatar_path"] = avatar_path
                elif key in author_avatar_paths:
                    tweet["author_avatar_path"] = author_avatar_paths[key]
            inserted = self.database.insert_tweets(account_id, result["tweets"])
            media_result = await self.media.download_pending(
                account_id,
                concurrency=settings["mediaConcurrency"],
                max_media_mb=settings["maxMediaMb"],
            )
            self.database.mark_sync_succeeded(account_id, result.get("newestSeenId"))
            response = {
                "accountId": account_id,
                "reason": reason,
                "fetched": len(result["tweets"]),
                "inserted": inserted,
                "mediaDownloaded": media_result["downloaded"],
                "mediaFailed": media_result["failed"],
            }
            if self.notifier and inserted > 0 and account.get("last_tweet_id"):
                try:
                    notification = await self.notifier.notify_account_update(
                        account_id=account_id,
                        profile=result["profile"],
                        tweets=result["tweets"],
                        inserted=inserted,
                    )
                    if notification:
                        response["notification"] = notification
                except Exception as notification_error:
                    response["notification"] = {
                        "sent": False,
                        "error": str(notification_error),
                    }
            return response
        except Exception as error:
            try:
                self.database.mark_sync_failed(account_id, str(error))
            except Exception:
                pass
            raise
        finally:
            self._current_account_id = None
            self._lock.release()

    async def backfill_author_avatars(self, account_id: int) -> dict[str, int]:
        account = self.database.get_account(account_id)
        usernames = self.database.missing_author_usernames(account_id)
        if not usernames:
            return {"requested": 0, "resolved": 0, "downloaded": 0}
        profiles = (
            await self.scraper_runtime.await_result(self.scraper.lookup_users(usernames))
            if self.scraper_runtime
            else await self.scraper.lookup_users(usernames)
        )
        pseudo_tweets = [
            {
                "author_username": profile["username"],
                "author_avatar_url": profile.get("avatar_url"),
            }
            for profile in profiles
        ]
        paths = await self.media.download_author_avatars(
            account,
            pseudo_tweets,
            max_media_mb=self.config.get()["maxMediaMb"],
        )
        for profile in profiles:
            key = str(profile["username"]).lower()
            if key in paths:
                self.database.update_author_avatar(
                    account_id, profile["username"], profile.get("avatar_url") or "", paths[key]
                )
        return {
            "requested": len(usernames),
            "resolved": len(profiles),
            "downloaded": len(paths),
        }

    async def sync_all(self, reason: str = "manual-all") -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for account in self.database.list_accounts():
            try:
                results.append(await self.sync_account(account["id"], reason=reason))
            except SyncBusyError:
                results.append(
                    {"accountId": account["id"], "error": "已有同步任务正在运行"}
                )
                break
            except Exception as error:
                results.append({"accountId": account["id"], "error": str(error)})
        return {
            "results": results,
            "succeeded": sum(1 for item in results if "error" not in item),
            "failed": sum(1 for item in results if "error" in item),
        }


class Scheduler:
    def __init__(self, config: ConfigStore, sync_service: SyncService):
        self.config = config
        self.sync_service = sync_service
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._next_run_at: datetime | None = None
        self._last_result: dict[str, Any] | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="auto-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def reload(self) -> None:
        self._wake.set()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "nextRunAt": self._next_run_at.isoformat().replace("+00:00", "Z")
                if self._next_run_at
                else None,
                "lastResult": self._last_result,
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            settings = self.config.get()
            if not settings["scheduleEnabled"]:
                self._set_next(None)
                self._wake.wait()
                self._wake.clear()
                continue
            target = datetime.now(timezone.utc) + timedelta(
                minutes=settings["scheduleMinutes"]
            )
            self._set_next(target)
            wait_seconds = max(1, (target - datetime.now(timezone.utc)).total_seconds())
            changed = self._wake.wait(wait_seconds)
            self._wake.clear()
            if changed or self._stop.is_set():
                continue
            try:
                result = asyncio.run(self.sync_service.sync_all(reason="schedule"))
            except Exception as error:
                result = {"error": str(error)}
            with self._state_lock:
                self._last_result = result

    def _set_next(self, value: datetime | None) -> None:
        with self._state_lock:
            self._next_run_at = value
