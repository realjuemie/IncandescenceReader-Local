from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import tempfile
from contextlib import aclosing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any, Callable
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

os.environ.setdefault("TWS_HTTP_BACKEND", "curl")
os.environ.setdefault("TWS_RAISE_WHEN_NO_ACCOUNT", "1")
os.environ.setdefault("TWS_TELEMETRY", "0")



NO_SESSION_MESSAGE = "没有可用的 X 登录会话，请在设置中添加 Cookie"
RATE_LIMIT_MESSAGE = "X 请求额度暂时耗尽或会话被短暂锁定，Cookie 仍有效，请稍后再试"
PROTECTED_UNFOLLOWED_MESSAGE = "是私密账号，当前 Cookie 都未关注，无法读取时间线"
# Stop after this many already-archived timeline items in a row. Do NOT stop on
# snowflake id <= last_tweet_id: X can omit one of a burst, and that hole sits
# behind the newest id we already saved.
KNOWN_TWEET_STOP_STREAK = 10


def describe_no_account(sessions: list[dict[str, Any]] | None) -> str:
    """Map twscrape NoAccountError to a user-facing reason.

    An empty pool really has no Cookie. Any saved session — even one X just
    403-locked — still has credentials; the caller should wait, not re-paste.
    """
    if sessions:
        return RATE_LIMIT_MESSAGE
    return NO_SESSION_MESSAGE


def is_rate_limit_message(text: str) -> bool:
    message = str(text or "")
    return "额度暂时耗尽" in message or "会话被短暂锁定" in message

class ScraperUnavailableError(RuntimeError):
    pass


class CredentialValidationUnavailableError(RuntimeError):
    pass


class FreeXScraper:
    """通过已登录网页会话读取 X 的 GraphQL 时间线，不使用付费 API。"""

    def __init__(
        self,
        session_db: Path,
        proxy_url_getter: Callable[[], str | None] | None = None,
    ):
        self.session_db = session_db.resolve()
        self.session_db.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.session_db.with_name("scraper-session-meta.json")
        self._metadata_lock = RLock()
        self._proxy_url_getter = proxy_url_getter or (lambda: None)

    def _proxy(self) -> str | None:
        return self._proxy_url_getter()

    @staticmethod
    def _imports():
        try:
            from twscrape import API
            from twscrape.accounts_pool import NoAccountError
        except ImportError as error:
            raise ScraperUnavailableError(
                "抓取组件未安装，请先运行 setup-windows.ps1"
            ) from error
        FreeXScraper._enable_round_robin(API)
        return API, NoAccountError

    @staticmethod
    def _enable_round_robin(api_cls: Any) -> None:
        """Prefer the least-recently-used Cookie instead of username order.

        twscrape defaults to ORDER BY username, so two sessions pile onto the
        alphabetically first label until it 403-locks.
        """
        if getattr(api_cls, "_incandescence_round_robin", False):
            return
        original_init = api_cls.__init__

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            original_init(self, *args, **kwargs)
            pool = getattr(self, "pool", None)
            if pool is not None:
                pool._order_by = (
                    "CASE WHEN last_used IS NULL THEN 0 ELSE 1 END, "
                    "last_used ASC, username ASC"
                )

        api_cls.__init__ = __init__
        api_cls._incandescence_round_robin = True

    async def health(self) -> dict[str, Any]:
        try:
            version = importlib.metadata.version("twscrape")
            sessions = await self.list_sessions()
            return {
                "installed": True,
                "version": version,
                "activeSessions": sum(1 for item in sessions if item["active"]),
                "sessions": len(sessions),
            }
        except ScraperUnavailableError as error:
            return {"installed": False, "error": str(error), "activeSessions": 0, "sessions": 0}

    async def list_sessions(self) -> list[dict[str, Any]]:
        API, _ = self._imports()
        api = API(
            str(self.session_db),
            proxy=self._proxy(),
            raise_when_no_account=True,
            wait_timeout=10,
        )
        items = await api.pool.accounts_info()
        metadata = self._read_metadata()
        return [
            {
                "label": item["username"],
                "active": bool(item["active"]),
                "loggedIn": bool(item["logged_in"]),
                "lastUsed": item["last_used"].isoformat() if item["last_used"] else None,
                "totalRequests": item["total_req"],
                "error": item["error_msg"] if item["error_msg"] != "None" else None,
                "verifiedUsername": metadata.get(item["username"], {}).get(
                    "verifiedUsername"
                ),
                "verifiedAt": metadata.get(item["username"], {}).get("verifiedAt"),
                "credentialState": metadata.get(item["username"], {}).get(
                    "state", "unverified"
                ),
            }
            for item in items
        ]

    async def pending_invalid_session_alerts(self) -> list[dict[str, Any]]:
        """Return newly invalid sessions and clear dedupe state after recovery."""

        sessions = await self.list_sessions()
        with self._metadata_lock:
            metadata = self._read_metadata()
            changed = False
            pending: list[dict[str, Any]] = []
            for item in sessions:
                label = str(item.get("label") or "")
                state = metadata.setdefault(label, {})
                # Rate-limit 403 makes twscrape flip loggedIn/active; that is
                # not a dead Cookie. Only explicit validation failures alert.
                invalid = item.get("credentialState") == "invalid"
                if not invalid:
                    if state.pop("invalidAlertSent", None) is not None:
                        changed = True
                    continue
                if not state.get("invalidAlertSent"):
                    pending.append(item)
            if changed:
                self._write_metadata(metadata)
        return pending

    def mark_invalid_session_alerted(self, labels: list[str]) -> None:
        if not labels:
            return
        with self._metadata_lock:
            metadata = self._read_metadata()
            changed = False
            for label in labels:
                if label not in metadata:
                    metadata[label] = {}
                if not metadata[label].get("invalidAlertSent"):
                    metadata[label]["invalidAlertSent"] = True
                    changed = True
            if changed:
                self._write_metadata(metadata)

    async def add_session(self, label: str, cookies: str) -> dict[str, Any]:
        parsed = extract_session_cookies(cookies)
        validation = await self.validate_cookies(
            parsed, user_id=extract_cookie_user_id(cookies)
        )
        label = (
            label
            or validation.get("username")
            or datetime.now(timezone.utc).strftime("session-%Y%m%d-%H%M%S")
        ).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", label):
            raise ValueError("请填写会话名称；只能使用字母、数字、点、下划线或短横线")
        API, _ = self._imports()
        api = API(
            str(self.session_db),
            proxy=self._proxy(),
            raise_when_no_account=True,
            wait_timeout=10,
        )
        canonical = canonical_cookie_header(parsed)
        await api.pool.add_account_cookies(label, canonical)
        self._save_validation(label, validation)
        for item in await self.list_sessions():
            if item["label"] == label:
                item["validation"] = validation
                return item
        raise RuntimeError("会话保存失败")

    async def validate_saved_session(self, label: str) -> dict[str, Any]:
        API, _ = self._imports()
        api = API(
            str(self.session_db),
            proxy=self._proxy(),
            raise_when_no_account=True,
            wait_timeout=10,
        )
        account = await api.pool.get_account(label)
        if account is None:
            raise KeyError("抓取会话不存在")
        try:
            validation = await self.validate_cookies(account.cookies)
        except ValueError:
            await api.pool.set_active(label, False)
            self._save_validation(label, {"valid": False, "username": None})
            raise
        if not validation.get("username"):
            previous = self._read_metadata().get(label, {})
            validation["username"] = previous.get("verifiedUsername")
        await api.pool.add_account_cookies(label, canonical_cookie_header(account.cookies))
        self._save_validation(label, validation)
        return validation

    async def validate_cookies(
        self, cookies: dict[str, str], *, user_id: int | None = None
    ) -> dict[str, Any]:
        """Validate cookies through the same GraphQL path used for real scraping."""

        API, NoAccountError = self._imports()
        username: str | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="incandescence-cookie-check-") as directory:
                api = API(
                    str(Path(directory) / "sessions.db"),
                    proxy=self._proxy(),
                    raise_when_no_account=True,
                    wait_timeout=8,
                    wait_interval=1,
                )
                await api.pool.add_account_cookies(
                    "credential-check", canonical_cookie_header(cookies)
                )
                query = (
                    api.user_by_id(user_id)
                    if user_id is not None
                    else api.user_by_login("X")
                )
                user = await asyncio.wait_for(query, timeout=25)
                if user is None:
                    raise CredentialValidationUnavailableError(
                        "X 返回了空的验证结果，请稍后重试"
                    )
                if user_id is not None:
                    username = str(user.username or "").strip() or None
        except NoAccountError as error:
            raise ValueError("Cookie 已失效或不是已登录的 X 会话") from error
        except (TimeoutError, asyncio.TimeoutError) as error:
            raise CredentialValidationUnavailableError(
                "连接 X 验证 Cookie 超时，请检查网络或代理后重试"
            ) from error
        except (ValueError, CredentialValidationUnavailableError):
            raise
        except Exception as error:
            raise CredentialValidationUnavailableError(
                "无法通过 X 时间线接口验证 Cookie，请检查网络、代理或稍后重试"
            ) from error

        return {
            "valid": True,
            "username": username,
            "verifiedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "detectedCookies": sorted(cookies),
        }

    async def test_proxy(self, proxy_url: str) -> dict[str, Any]:
        try:
            from twscrape.http import ConnectError, NetworkError, make_client
        except ImportError as error:
            raise ScraperUnavailableError(
                "抓取组件未安装，请先运行 setup-windows.ps1"
            ) from error
        started = perf_counter()
        try:
            async with make_client(
                proxy=proxy_url,
                headers={"user-agent": "@chrome", "accept": "text/plain,*/*"},
            ) as client:
                response = await asyncio.wait_for(
                    client.get("https://x.com/robots.txt", timeout=12), timeout=16
                )
        except (ConnectError, NetworkError, TimeoutError, asyncio.TimeoutError) as error:
            raise CredentialValidationUnavailableError(
                "代理无法连接 X，请确认代理程序、地址和端口"
            ) from error
        return {
            "reachable": True,
            "status": response.status_code,
            "elapsedMs": max(1, round((perf_counter() - started) * 1000)),
        }

    async def delete_session(self, label: str) -> None:
        API, _ = self._imports()
        api = API(
            str(self.session_db),
            proxy=self._proxy(),
            raise_when_no_account=True,
            wait_timeout=10,
        )
        await api.pool.delete_accounts(label)
        with self._metadata_lock:
            metadata = self._read_metadata()
            if label in metadata:
                metadata.pop(label, None)
                self._write_metadata(metadata)

    def _save_validation(self, label: str, validation: dict[str, Any]) -> None:
        with self._metadata_lock:
            metadata = self._read_metadata()
            metadata[label] = {
                "state": "valid" if validation.get("valid") else "invalid",
                "verifiedUsername": validation.get("username"),
                "verifiedAt": validation.get("verifiedAt")
                or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            self._write_metadata(metadata)

    def _read_metadata(self) -> dict[str, dict[str, Any]]:
        with self._metadata_lock:
            if not self.metadata_path.is_file():
                return {}
            try:
                value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}

    def _write_metadata(self, metadata: dict[str, dict[str, Any]]) -> None:
        temporary = self.metadata_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.metadata_path)


    async def _collect_visible_tweets(
        self,
        api: Any,
        user: Any,
        *,
        limit: int,
        last_tweet_id: str | None,
        include_replies: bool,
        include_reposts: bool,
        known_tweet_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        generator = (
            api.user_tweets_and_replies(user.id, limit=limit)
            if include_replies
            else api.user_tweets(user.id, limit=limit)
        )
        tweets: list[dict[str, Any]] = []
        saw_any = False
        newest_seen: int | None = int(last_tweet_id) if last_tweet_id else None
        known = {int(value) for value in (known_tweet_ids or []) if str(value).strip()}
        old_streak = 0
        async with aclosing(generator) as stream:
            async for tweet in stream:
                saw_any = True
                tweet_id = int(tweet.id)
                if tweet.retweetedTweet is not None and not include_reposts:
                    continue
                if tweet_id in known:
                    newest_seen = max(newest_seen or tweet_id, tweet_id)
                    old_streak += 1
                    if old_streak >= KNOWN_TWEET_STOP_STREAK:
                        break
                    continue
                old_streak = 0
                newest_seen = max(newest_seen or tweet_id, tweet_id)
                tweets.append(self._tweet_to_dict(tweet))
        return {"tweets": tweets, "saw_any": saw_any, "newest_seen": newest_seen}

    def _cookie_header_from_account(self, account: Any) -> str:
        cookies = getattr(account, "cookies", None)
        if isinstance(cookies, dict):
            return canonical_cookie_header(cookies)
        text = str(cookies or "").strip()
        if not text:
            return ""
        try:
            parsed = extract_session_cookies(text)
        except Exception:
            return text
        return canonical_cookie_header(parsed) if parsed else text

    async def _collect_protected_via_other_sessions(
        self,
        pool_api: Any,
        *,
        username: str,
        user: Any,
        limit: int,
        last_tweet_id: str | None,
        include_replies: bool,
        include_reposts: bool,
        NoAccountError: type[BaseException],
        API: Any,
        known_tweet_ids: list[str] | None = None,
    ) -> tuple[Any, dict[str, Any]] | None:
        try:
            accounts = await pool_api.pool.get_all()
        except Exception:
            accounts = []
        for account in accounts:
            header = self._cookie_header_from_account(account)
            if not header:
                continue
            label = str(getattr(account, "username", "") or "viewer")
            try:
                with tempfile.TemporaryDirectory(prefix="incandescence-protected-") as directory:
                    isolated = API(
                        str(Path(directory) / "sessions.db"),
                        proxy=self._proxy(),
                        raise_when_no_account=True,
                        wait_timeout=15,
                        wait_interval=1,
                    )
                    await isolated.pool.add_account_cookies(label, header)
                    isolated_user = await isolated.user_by_login(username)
                    if isolated_user is None:
                        continue
                    collected = await self._collect_visible_tweets(
                        isolated,
                        isolated_user,
                        limit=limit,
                        last_tweet_id=last_tweet_id,
                        include_replies=include_replies,
                        include_reposts=include_reposts,
                        known_tweet_ids=known_tweet_ids,
                    )
                    if collected["saw_any"]:
                        return isolated_user, collected
            except NoAccountError:
                continue
            except Exception:
                continue
        return None

    async def fetch_latest(
        self,
        *,
        username: str,
        last_tweet_id: str | None,
        include_replies: bool,
        include_reposts: bool,
        initial_limit: int,
        incremental_limit: int,
        reply_context_ids: list[str] | None = None,
        known_tweet_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        API, NoAccountError = self._imports()
        api = API(
            str(self.session_db),
            proxy=self._proxy(),
            raise_when_no_account=True,
            # Give the essential profile/timeline queues a little time to recover
            # from a brief in-use lock without waiting indefinitely for a real
            # rate-limit reset.
            wait_timeout=35,
            wait_interval=1,
        )
        detail_api = API(
            str(self.session_db),
            proxy=self._proxy(),
            raise_when_no_account=True,
            # Reply parents are useful context, but must never hold up or fail the
            # monitored account's own timeline when TweetDetail is rate-limited.
            wait_timeout=2,
            wait_interval=0.5,
        )
        try:
            user = await api.user_by_login(username)
            if user is None:
                raise ValueError(f"找不到账号 @{username}")
            limit = initial_limit if not last_tweet_id else incremental_limit
            collected = await self._collect_visible_tweets(
                api,
                user,
                limit=limit,
                last_tweet_id=last_tweet_id,
                include_replies=include_replies,
                include_reposts=include_reposts,
                known_tweet_ids=known_tweet_ids,
            )
            if bool(getattr(user, "protected", False)) and not collected["saw_any"]:
                fallback = await self._collect_protected_via_other_sessions(
                    api,
                    username=username,
                    user=user,
                    limit=limit,
                    last_tweet_id=last_tweet_id,
                    include_replies=include_replies,
                    include_reposts=include_reposts,
                    NoAccountError=NoAccountError,
                    API=API,
                    known_tweet_ids=known_tweet_ids,
                )
                if fallback is not None:
                    user, collected = fallback
                else:
                    raise RuntimeError(f"@{username} {PROTECTED_UNFOLLOWED_MESSAGE}")
            tweets = collected["tweets"]
            newest_seen = collected["newest_seen"]
            primary_ids = {str(item["id"]) for item in tweets}
            reply_contexts: list[dict[str, Any]] = []
            parent_ids = list(
                dict.fromkeys(
                    [
                        str(item.get("reply_to_id") or "")
                        for item in tweets
                        if item.get("reply_to_id")
                    ]
                    + [str(value) for value in (reply_context_ids or []) if str(value)]
                )
            )
            # Resolve new reply parents first and gradually backfill older missing
            # context. A single credential has a much smaller TweetDetail budget
            # than timeline budget, so a large batch starves later accounts.
            parent_ids = parent_ids[:6]
            deferred_reply_contexts = 0
            for index, parent_id in enumerate(parent_ids):
                if parent_id in primary_ids:
                    continue
                try:
                    parent = await detail_api.tweet_details(int(parent_id))
                except NoAccountError:
                    deferred_reply_contexts = len(parent_ids) - index
                    break
                except Exception:
                    # A deleted, private, or temporarily unavailable parent must not
                    # prevent the monitored account's own reply from being archived.
                    continue
                if parent is None:
                    continue
                mapped_parent = self._tweet_to_dict(parent)
                mapped_parent["context_only"] = True
                reply_contexts.append(mapped_parent)
                primary_ids.add(str(mapped_parent["id"]))
            tweets.extend(reply_contexts)
            tweets.sort(key=lambda item: int(item["id"]))
            return {
                "profile": self._user_to_dict(user),
                "tweets": tweets,
                "replyContextCount": len(reply_contexts),
                "replyContextsDeferred": deferred_reply_contexts,
                "newestSeenId": str(newest_seen) if newest_seen is not None else last_tweet_id,
            }
        except NoAccountError as error:
            sessions = await api.pool.accounts_info()
            raise RuntimeError(describe_no_account(sessions)) from error

    async def lookup_users(self, usernames: list[str]) -> list[dict[str, Any]]:
        """Resolve a bounded set of author profiles for local avatar backfilling."""
        API, NoAccountError = self._imports()
        api = API(
            str(self.session_db),
            proxy=self._proxy(),
            raise_when_no_account=True,
            wait_timeout=20,
            wait_interval=1,
        )
        results: list[dict[str, Any]] = []
        try:
            for username in list(dict.fromkeys(usernames))[:50]:
                try:
                    user = await api.user_by_login(username)
                except NoAccountError:
                    raise
                except Exception:
                    continue
                if user is not None:
                    results.append(self._user_to_dict(user))
        except NoAccountError as error:
            sessions = await api.pool.accounts_info()
            raise RuntimeError(describe_no_account(sessions)) from error
        return results

    @staticmethod
    def _user_to_dict(user: Any) -> dict[str, Any]:
        avatar_icon_url = str(user.profileImageUrl or "").strip()
        avatar_url = avatar_icon_url.replace("_normal.", "_400x400.")
        return {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.displayname,
            "bio": user.rawDescription or "",
            "avatar_url": avatar_url or None,
            # Bark only needs a small icon. Prefer the exact URL returned by X
            # instead of assuming every profile has a 400x400 rendition.
            "avatar_icon_url": avatar_icon_url or avatar_url or None,
            "banner_url": user.profileBannerUrl,
            "protected": bool(user.protected),
            "verified": bool(user.verified or user.blue),
            "metrics": {
                "followers": user.followersCount,
                "following": user.friendsCount,
                "tweets": user.statusesCount,
                "media": user.mediaCount,
            },
        }

    @classmethod
    def _tweet_to_dict(cls, tweet: Any) -> dict[str, Any]:
        quoted = tweet.quotedTweet
        reply_to_id = str(tweet.inReplyToTweetId) if tweet.inReplyToTweetId else None
        reply_to_username = (
            tweet.inReplyToUser.username
            if tweet.inReplyToUser is not None
            else tweet.inReplyToScreenName
        )
        is_reply = bool(
            reply_to_id
            or reply_to_username
            or (
                tweet.conversationId
                and str(tweet.conversationId) != str(tweet.id)
            )
        )
        links = []
        for link in tweet.links or []:
            links.append(
                {"url": link.url, "display": link.text or link.url, "shortUrl": link.tcourl}
            )
        created = tweet.date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "id": str(tweet.id),
            "author_id": str(tweet.user.id),
            "author_username": tweet.user.username,
            "author_name": tweet.user.displayname,
            "author_avatar_url": (tweet.user.profileImageUrl or "").replace(
                "_normal.", "_400x400."
            ) or None,
            "text": tweet.rawContent,
            "created_at": created,
            "conversation_id": str(tweet.conversationId),
            "reply_to_id": reply_to_id,
            "reply_to_username": reply_to_username,
            "lang": tweet.lang,
            "is_reply": is_reply,
            "is_repost": tweet.retweetedTweet is not None,
            "is_quote": quoted is not None,
            "possibly_sensitive": bool(tweet.possibly_sensitive),
            "metrics": {
                "replies": tweet.replyCount,
                "reposts": tweet.retweetCount,
                "likes": tweet.likeCount,
                "quotes": tweet.quoteCount,
                "bookmarks": tweet.bookmarkedCount,
                "views": tweet.viewCount,
            },
            "links": links,
            "quoted": cls._quoted_to_dict(quoted) if quoted else None,
            "source_url": tweet.url,
            "media": cls._media_to_dict(tweet),
        }

    @staticmethod
    def _quoted_to_dict(tweet: Any) -> dict[str, Any]:
        return {
            "id": str(tweet.id),
            "authorUsername": tweet.user.username,
            "authorName": tweet.user.displayname,
            "text": tweet.rawContent,
            "sourceUrl": tweet.url,
        }

    @classmethod
    def _media_to_dict(cls, tweet: Any) -> list[dict[str, Any]]:
        media = tweet.media
        if tweet.retweetedTweet is not None:
            nested = tweet.retweetedTweet.media
            if not (media.photos or media.videos or media.animated):
                media = nested
        items: list[dict[str, Any]] = []
        for photo in media.photos:
            url = cls._original_photo_url(photo.url)
            items.append({"key": cls._media_key("photo", url), "type": "photo", "url": url})
        for video in media.videos:
            variants = [item for item in video.variants if item.url]
            if not variants:
                continue
            best = max(variants, key=lambda item: item.bitrate or 0)
            items.append(
                {
                    "key": cls._media_key("video", best.url),
                    "type": "video",
                    "url": best.url,
                    "preview_url": video.thumbnailUrl,
                    "duration_ms": video.duration,
                }
            )
        for animated in media.animated:
            items.append(
                {
                    "key": cls._media_key("animated", animated.videoUrl),
                    "type": "animated_gif",
                    "url": animated.videoUrl,
                    "preview_url": animated.thumbnailUrl,
                }
            )
        return items

    @staticmethod
    def _media_key(kind: str, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        return f"{kind}-{digest}"

    @staticmethod
    def _original_photo_url(url: str) -> str:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["name"] = "orig"
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


_REQUIRED_COOKIES = ("auth_token", "ct0")
_COLLECTED_COOKIES = (*_REQUIRED_COOKIES, "twid")
_COOKIE_PAIR = re.compile(
    r"(?i)(?:^|[;\s,'\"\\])([!#$%&'*+.^_`|~0-9A-Za-z-]+)\s*=\s*([^;\s,'\"\\]+)"
)


def inspect_cookie_input(raw: str) -> dict[str, Any]:
    found = _collect_cookie_values(raw)
    detected = [name for name in _REQUIRED_COOKIES if found.get(name)]
    missing = [name for name in _REQUIRED_COOKIES if not found.get(name)]
    return {
        "detected": detected,
        "missing": missing,
        "ready": not missing,
        "format": _detect_cookie_format(raw),
    }


def extract_session_cookies(raw: str) -> dict[str, str]:
    if not str(raw or "").strip():
        raise ValueError("Cookie 不能为空")
    found = _collect_cookie_values(raw)
    missing = [name for name in _REQUIRED_COOKIES if not found.get(name)]
    if missing:
        raise ValueError(f"没有找到必需 Cookie：{', '.join(missing)}")
    result = {name: found[name] for name in _REQUIRED_COOKIES}
    for name, value in result.items():
        if len(value) > 4096 or any(ord(character) < 32 for character in value):
            raise ValueError(f"Cookie {name} 的值无效")
    return result


def canonical_cookie_header(cookies: dict[str, str]) -> str:
    parsed = {name: str(cookies.get(name) or "").strip() for name in _REQUIRED_COOKIES}
    if any(not value for value in parsed.values()):
        raise ValueError("Cookie 必须同时包含 auth_token 和 ct0")
    return "; ".join(f"{name}={parsed[name]}" for name in _REQUIRED_COOKIES)


def extract_cookie_user_id(raw: str) -> int | None:
    """Read the optional twid identity for validation without persisting it."""

    value = unquote(_collect_cookie_values(raw).get("twid", "")).strip("'\"")
    match = re.fullmatch(r"u=(\d{1,25})", value)
    return int(match.group(1)) if match else None


def _collect_cookie_values(raw: str) -> dict[str, str]:
    text = str(raw or "").strip()
    found: dict[str, str] = {}

    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        value = None
    if value is not None:
        _cookies_from_json(value, found)

    for match in _COOKIE_PAIR.finditer(text):
        _remember_cookie(found, match.group(1), match.group(2))

    for line in text.splitlines():
        columns = [part.strip() for part in line.split("\t")]
        if len(columns) >= 2:
            if columns[0].lower() in _COLLECTED_COOKIES:
                _remember_cookie(found, columns[0], columns[1])
            elif len(columns) >= 7 and columns[-2].lower() in _COLLECTED_COOKIES:
                _remember_cookie(found, columns[-2], columns[-1])
        whitespace = line.strip().split()
        if len(whitespace) >= 2 and whitespace[0].lower() in _COLLECTED_COOKIES:
            _remember_cookie(found, whitespace[0], whitespace[1])
    return found


def _cookies_from_json(value: Any, found: dict[str, str]) -> None:
    if isinstance(value, list):
        for item in value:
            _cookies_from_json(item, found)
        return
    if not isinstance(value, dict):
        return
    name = value.get("name")
    cookie_value = value.get("value")
    if isinstance(name, str) and isinstance(cookie_value, (str, int)):
        _remember_cookie(found, name, str(cookie_value))
    for key, item in value.items():
        if key.lower() in _COLLECTED_COOKIES and isinstance(item, (str, int)):
            _remember_cookie(found, key, str(item))
        elif key in ("cookies", "items", "data"):
            _cookies_from_json(item, found)


def _remember_cookie(found: dict[str, str], name: str, value: str) -> None:
    normalized = str(name or "").strip().lower()
    if normalized not in _COLLECTED_COOKIES:
        return
    cleaned = str(value or "").strip().strip("'\"")
    if cleaned:
        found[normalized] = cleaned


def _detect_cookie_format(raw: str) -> str:
    text = str(raw or "").lstrip()
    if text.startswith(("[", "{")):
        return "JSON"
    if "\t" in text:
        return "表格 / Netscape"
    if re.search(r"(?im)^\s*cookie\s*:", text) or "--cookie" in text or "-H 'cookie:" in text:
        return "请求头 / cURL"
    return "Cookie 字符串"
