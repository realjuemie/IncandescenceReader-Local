from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

from incandescence.auth import AdminAuth
from incandescence.config import ConfigStore, normalize_proxy_url
from incandescence.database import Database, normalize_username
from incandescence.member_auth import MemberAuth
from incandescence.notifications import BarkNotifier
from incandescence.scraper import (
    FreeXScraper,
    extract_cookie_user_id,
    extract_session_cookies,
    inspect_cookie_input,
)
from incandescence.share_auth import ShareAuth
from incandescence.sync_service import SyncService
from incandescence.web import Application, create_server


def sample_tweet(tweet_id: str, text: str) -> dict:
    return {
        "id": tweet_id,
        "author_id": "42",
        "author_username": "example",
        "author_name": "Example",
        "text": text,
        "created_at": f"2026-01-01T00:00:{int(tweet_id) % 60:02d}Z",
        "conversation_id": tweet_id,
        "reply_to_id": None,
        "lang": "zh",
        "is_reply": False,
        "is_repost": False,
        "is_quote": False,
        "possibly_sensitive": False,
        "metrics": {"likes": 1},
        "links": [],
        "quoted": None,
        "source_url": f"https://x.com/example/status/{tweet_id}",
        "media": [],
    }


class ConfigTests(unittest.TestCase):
    def test_settings_are_bounded_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            value = store.update({"scheduleMinutes": 1, "mediaConcurrency": 99})
            self.assertEqual(value["scheduleMinutes"], 5)
            self.assertEqual(value["mediaConcurrency"], 6)
            self.assertEqual(ConfigStore(Path(directory)).get(), value)

    def test_username_validation(self):
        self.assertEqual(normalize_username("@OpenAI"), "openai")
        for invalid in ("", "a-b", "用户", "a" * 16):
            with self.assertRaises(ValueError):
                normalize_username(invalid)

    def test_proxy_settings_are_validated_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            value = store.update(
                {"proxyEnabled": True, "proxyUrl": "http://127.0.0.1:7890"}
            )
            self.assertEqual(store.proxy_url(), "http://127.0.0.1:7890")
            self.assertTrue(value["proxyEnabled"])
            store.update({"proxyEnabled": False})
            self.assertIsNone(store.proxy_url())
        self.assertEqual(
            normalize_proxy_url("socks5://user:pass@localhost:1080"),
            "socks5://user:pass@localhost:1080",
        )
        for invalid in ("127.0.0.1:7890", "ftp://localhost:21", "http://localhost"):
            with self.assertRaises(ValueError):
                normalize_proxy_url(invalid)

    def test_bark_settings_require_a_key_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            with self.assertRaises(ValueError):
                store.update({"barkEnabled": True})
            settings = store.update(
                {
                    "barkEnabled": True,
                    "barkServerUrl": "https://api.day.app/",
                    "barkDeviceKey": "device-key-123",
                    "barkGroup": "本地阅读更新",
                    "siteBaseUrl": "http://192.168.1.20:8787/",
                }
            )
            self.assertEqual(settings["barkServerUrl"], "https://api.day.app")
            self.assertEqual(settings["siteBaseUrl"], "http://192.168.1.20:8787")


class BarkNotifierTests(unittest.TestCase):
    def test_update_payload_has_title_summary_avatar_and_reader_link(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            store.update(
                {
                    "barkEnabled": True,
                    "barkDeviceKey": "device-key-123",
                    "barkGroup": "本地阅读更新",
                    "siteBaseUrl": "http://192.168.1.20:8787",
                }
            )
            captured = {}

            def handle(request: httpx.Request) -> httpx.Response:
                captured.update(json.loads(request.content.decode("utf-8")))
                self.assertEqual(str(request.url), "https://api.day.app/push")
                return httpx.Response(200, json={"code": 200, "message": "success"})

            notifier = BarkNotifier(store, transport=httpx.MockTransport(handle))
            result = asyncio.run(
                notifier.notify_account_update(
                    account_id=7,
                    profile={
                        "username": "example",
                        "display_name": "Example User",
                        "avatar_url": "https://pbs.twimg.com/profile_images/example_400x400.jpg",
                        "avatar_icon_url": "https://pbs.twimg.com/profile_images/example_normal.jpg",
                    },
                    tweets=[sample_tweet("301", "这是最新内容")],
                    inserted=1,
                )
            )
            self.assertTrue(result["sent"])
            self.assertEqual(captured["title"], "@example 有 1 条新内容")
            self.assertIn("这是最新内容", captured["body"])
            self.assertEqual(
                captured["icon"], "https://pbs.twimg.com/profile_images/example_normal.jpg"
            )
            self.assertEqual(captured["url"], "http://192.168.1.20:8787/reader?account=7")
            self.assertEqual(captured["group"], "本地阅读更新")

    def test_update_payload_falls_back_to_large_avatar(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            store.update({"barkEnabled": True, "barkDeviceKey": "device-key-123"})
            captured = {}

            def handle(request: httpx.Request) -> httpx.Response:
                captured.update(json.loads(request.content.decode("utf-8")))
                return httpx.Response(200, json={"code": 200})

            notifier = BarkNotifier(store, transport=httpx.MockTransport(handle))
            asyncio.run(
                notifier.notify_account_update(
                    account_id=7,
                    profile={
                        "username": "example",
                        "avatar_url": "https://pbs.twimg.com/profile_images/example_400x400.jpg",
                    },
                    tweets=[sample_tweet("302", "头像回退测试")],
                    inserted=1,
                )
            )
            self.assertEqual(
                captured["icon"],
                "https://pbs.twimg.com/profile_images/example_400x400.jpg",
            )

    def test_public_account_exposes_tracking_start_time(self):
        payload = Application.account_public(
            object(),
            {
                "id": 7,
                "username": "example",
                "created_at": "2026-08-27T02:04:00Z",
            },
        )
        self.assertEqual(payload["trackingStartedAt"], "2026-08-27T02:04:00Z")

    def test_invalid_credential_payload_links_to_admin_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            store.update(
                {
                    "barkEnabled": True,
                    "barkDeviceKey": "device-key-123",
                    "siteBaseUrl": "http://192.168.1.20:8787",
                }
            )
            captured = {}

            def handle(request: httpx.Request) -> httpx.Response:
                captured.update(json.loads(request.content.decode("utf-8")))
                return httpx.Response(200, json={"code": 200, "message": "success"})

            notifier = BarkNotifier(store, transport=httpx.MockTransport(handle))
            result = asyncio.run(
                notifier.notify_invalid_credentials(
                    sessions=[
                        {
                            "label": "main-session",
                            "verifiedUsername": "owner",
                            "error": "Cookie 已失效",
                        }
                    ],
                    cause="没有可用的 X 登录会话",
                )
            )
            self.assertTrue(result["sent"])
            self.assertEqual(captured["title"], "X 登录凭证失效（1）")
            self.assertIn("main-session（@owner）", captured["body"])
            self.assertIn("Cookie 已失效", captured["body"])
            self.assertEqual(
                captured["url"],
                "http://192.168.1.20:8787/admin#credential-panel",
            )


class CookieParsingTests(unittest.TestCase):
    def test_extracts_required_values_from_large_cookie_header(self):
        value = extract_session_cookies(
            "guest_id=guest; personalization_id=personal; auth_token=token-value; "
            "lang=zh-cn; ct0=csrf-value; twid=user"
        )
        self.assertEqual(value, {"auth_token": "token-value", "ct0": "csrf-value"})

    def test_extracts_from_cookie_editor_json_and_curl(self):
        json_value = extract_session_cookies(
            '[{"domain":".x.com","name":"auth_token","value":"json-token"},'
            '{"domain":".x.com","name":"ct0","value":"json-csrf"}]'
        )
        curl_value = extract_session_cookies(
            "curl 'https://x.com/home' -H 'accept: text/html' "
            "-H 'cookie: guest_id=x; auth_token=curl-token; ct0=curl-csrf; lang=zh'"
        )
        self.assertEqual(json_value["auth_token"], "json-token")
        self.assertEqual(json_value["ct0"], "json-csrf")
        self.assertEqual(curl_value["auth_token"], "curl-token")
        self.assertEqual(curl_value["ct0"], "curl-csrf")

    def test_inspection_reports_missing_without_exposing_values(self):
        result = inspect_cookie_input("auth_token=secret-token; guest_id=x")
        self.assertFalse(result["ready"])
        self.assertEqual(result["detected"], ["auth_token"])
        self.assertEqual(result["missing"], ["ct0"])
        self.assertNotIn("secret-token", str(result))

    def test_reads_twid_identity_without_adding_it_to_saved_cookies(self):
        raw = (
            ".x.com\tTRUE\t/\tTRUE\t0\tauth_token\ttoken\n"
            ".x.com\tTRUE\t/\tTRUE\t0\tct0\tcsrf\n"
            ".x.com\tTRUE\t/\tTRUE\t0\ttwid\tu%3D123456789"
        )
        self.assertEqual(extract_cookie_user_id(raw), 123456789)
        self.assertEqual(
            extract_session_cookies(raw), {"auth_token": "token", "ct0": "csrf"}
        )


class AdminAuthTests(unittest.TestCase):
    def test_first_run_setup_login_and_logout(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = AdminAuth(Path(directory))
            self.assertFalse(auth.is_configured())
            token = auth.setup("a-strong-local-password")
            self.assertTrue(auth.is_configured())
            cookie = f"{auth.COOKIE_NAME}={token}"
            self.assertTrue(auth.authenticated(cookie))
            auth.logout(cookie)
            self.assertFalse(auth.authenticated(cookie))
            next_token = AdminAuth(Path(directory)).login("a-strong-local-password")
            self.assertTrue(next_token)
            with self.assertRaises(ValueError):
                AdminAuth(Path(directory)).login("incorrect-password")


class MemberAuthTests(unittest.TestCase):
    def test_member_only_receives_assigned_private_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            public = db.create_account("public_user")
            private = db.create_account("private_user")
            db.update_account_options(
                private["id"],
                include_replies=True,
                include_reposts=False,
                is_public=False,
            )
            auth = MemberAuth(db)
            member = auth.create_member(
                "reader_one", "member-password", [private["id"]]
            )
            token, logged_in = auth.login("reader_one", "member-password")
            cookie = f"{auth.COOKIE_NAME}={token}"
            self.assertEqual(logged_in["username"], "reader_one")
            self.assertEqual(auth.current(cookie)["id"], member["id"])
            visible = db.list_accounts(member_id=member["id"])
            self.assertEqual({item["id"] for item in visible}, {public["id"], private["id"]})
            self.assertTrue(db.member_can_access(member["id"], private["id"]))
            flags = {item["id"]: bool(item.get("is_assigned")) for item in visible}
            self.assertFalse(flags[public["id"]])
            self.assertTrue(flags[private["id"]])
            auth.update_member(member["id"], active=True, account_ids=[private["id"], public["id"]])
            assigned = db.list_accounts(member_id=member["id"])
            assigned_flags = {item["id"]: bool(item.get("is_assigned")) for item in assigned}
            self.assertTrue(assigned_flags[public["id"]])
            self.assertTrue(assigned_flags[private["id"]])
            self.assertTrue(bool(next(item for item in assigned if item["id"] == public["id"])["is_public"]))
            auth.update_member(
                member["id"], active=False, account_ids=[private["id"]]
            )
            self.assertIsNone(auth.current(cookie))

    def test_member_bark_settings_are_scoped_to_accessible_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            public = db.create_account("public_user")
            private = db.create_account("private_user")
            forbidden = db.create_account("forbidden_user")
            for account in (private, forbidden):
                db.update_account_options(
                    account["id"],
                    include_replies=True,
                    include_reposts=False,
                    is_public=False,
                )
            auth = MemberAuth(db)
            member = auth.create_member(
                "reader_one", "member-password", [private["id"]]
            )
            saved = auth.update_notification_settings(
                member["id"],
                enabled=True,
                server_url="https://api.day.app/",
                device_key="member-device-key",
                clear_device_key=False,
                group="我的订阅",
                account_ids=[public["id"], private["id"]],
            )
            self.assertTrue(saved["enabled"])
            self.assertTrue(saved["deviceKeyConfigured"])
            self.assertNotIn("deviceKey", saved)
            self.assertEqual(set(saved["accountIds"]), {public["id"], private["id"]})
            self.assertEqual(
                db.list_member_notification_targets(private["id"])[0]["member_id"],
                member["id"],
            )
            with self.assertRaises(ValueError):
                auth.update_notification_settings(
                    member["id"],
                    enabled=True,
                    server_url="https://api.day.app",
                    device_key=None,
                    clear_device_key=False,
                    group="我的订阅",
                    account_ids=[forbidden["id"]],
                )
            auth.update_member(member["id"], active=True, account_ids=[])
            after_revoke = auth.notification_settings(member["id"])
            self.assertEqual(after_revoke["accountIds"], [public["id"]])
            self.assertEqual(db.list_member_notification_targets(private["id"]), [])

    def test_member_can_change_password_and_other_sessions_are_invalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            auth = MemberAuth(db)
            member = auth.create_member("reader_one", "member-password", [])
            current_token, _ = auth.login("reader_one", "member-password")
            other_token, _ = auth.login("reader_one", "member-password")
            current_cookie = f"{auth.COOKIE_NAME}={current_token}"
            other_cookie = f"{auth.COOKIE_NAME}={other_token}"

            with self.assertRaisesRegex(ValueError, "当前密码不正确"):
                auth.change_password(
                    member["id"],
                    current_password="wrong-password",
                    new_password="updated-password",
                    cookie_header=current_cookie,
                )
            auth.change_password(
                member["id"],
                current_password="member-password",
                new_password="updated-password",
                cookie_header=current_cookie,
            )

            self.assertIsNotNone(auth.current(current_cookie))
            self.assertIsNone(auth.current(other_cookie))
            with self.assertRaises(ValueError):
                auth.login("reader_one", "member-password")
            self.assertTrue(auth.login("reader_one", "updated-password")[0])


class FakeValidCredentialScraper(FreeXScraper):
    async def validate_cookies(self, cookies, *, user_id=None):
        self.validated = cookies
        self.validated_user_id = user_id
        return {
            "valid": True,
            "username": "verified_user",
            "verifiedAt": "2026-01-01T00:00:00Z",
            "detectedCookies": sorted(cookies),
        }


class CredentialSaveTests(unittest.TestCase):
    def test_session_is_extracted_validated_then_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            scraper = FakeValidCredentialScraper(Path(directory) / "sessions.db")
            result = asyncio.run(
                scraper.add_session(
                    "",
                    "guest_id=x; auth_token=token; lang=zh; ct0=csrf; twid=u%3D42",
                )
            )
            self.assertEqual(scraper.validated, {"auth_token": "token", "ct0": "csrf"})
            self.assertEqual(scraper.validated_user_id, 42)
            self.assertEqual(result["label"], "verified_user")
            self.assertEqual(result["credentialState"], "valid")
            self.assertEqual(result["verifiedUsername"], "verified_user")


class ScraperMappingTests(unittest.TestCase):
    def test_cookie_pool_prefers_least_recently_used(self):
        class FakePool:
            _order_by = "username"

        class FakeAPI:
            def __init__(self):
                self.pool = FakePool()

        FreeXScraper._enable_round_robin(FakeAPI)
        api = FakeAPI()
        self.assertIn("last_used ASC", api.pool._order_by)
        FreeXScraper._enable_round_robin(FakeAPI)
        self.assertTrue(FakeAPI._incandescence_round_robin)

    def test_profile_keeps_original_avatar_for_bark(self):
        user = SimpleNamespace(
            id="42",
            username="example",
            displayname="Example",
            rawDescription="",
            profileImageUrl="https://pbs.twimg.com/profile_images/42/avatar_normal.jpg",
            profileBannerUrl=None,
            protected=False,
            verified=False,
            blue=False,
            followersCount=1,
            friendsCount=2,
            statusesCount=3,
            mediaCount=4,
        )

        mapped = FreeXScraper._user_to_dict(user)

        self.assertEqual(
            mapped["avatar_icon_url"],
            "https://pbs.twimg.com/profile_images/42/avatar_normal.jpg",
        )
        self.assertEqual(
            mapped["avatar_url"],
            "https://pbs.twimg.com/profile_images/42/avatar_400x400.jpg",
        )

    def test_reply_is_detected_when_x_omits_the_parent_tweet_id(self):
        media = SimpleNamespace(photos=[], videos=[], animated=[])
        user = SimpleNamespace(
            id="42",
            username="example",
            displayname="Example",
            profileImageUrl=None,
        )
        tweet = SimpleNamespace(
            id="301",
            user=user,
            rawContent="@target reply",
            date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            conversationId="300",
            inReplyToTweetId=None,
            inReplyToUser=None,
            inReplyToScreenName="target",
            lang="zh",
            retweetedTweet=None,
            quotedTweet=None,
            possibly_sensitive=False,
            replyCount=0,
            retweetCount=0,
            likeCount=0,
            quoteCount=0,
            bookmarkedCount=0,
            viewCount=0,
            links=[],
            url="https://x.com/example/status/301",
            media=media,
        )

        mapped = FreeXScraper._tweet_to_dict(tweet)

        self.assertTrue(mapped["is_reply"])
        self.assertEqual(mapped["reply_to_username"], "target")

    def test_fetch_latest_resolves_the_original_post_for_a_reply(self):
        media = SimpleNamespace(photos=[], videos=[], animated=[])

        def user(username: str, user_id: str):
            return SimpleNamespace(
                id=user_id,
                username=username,
                displayname=username.title(),
                rawDescription="",
                profileImageUrl=None,
                profileBannerUrl=None,
                protected=False,
                verified=False,
                blue=False,
                followersCount=1,
                friendsCount=2,
                statusesCount=3,
                mediaCount=0,
            )

        monitored = user("monitored", "42")
        other = user("other", "99")

        def tweet(tweet_id, author, text, *, parent_id=None, parent_user=None):
            return SimpleNamespace(
                id=tweet_id,
                user=author,
                rawContent=text,
                date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                conversationId=parent_id or tweet_id,
                inReplyToTweetId=parent_id,
                inReplyToUser=parent_user,
                inReplyToScreenName=parent_user.username if parent_user else None,
                lang="zh",
                retweetedTweet=None,
                quotedTweet=None,
                possibly_sensitive=False,
                replyCount=0,
                retweetCount=0,
                likeCount=0,
                quoteCount=0,
                bookmarkedCount=0,
                viewCount=0,
                links=[],
                url=f"https://x.com/{author.username}/status/{tweet_id}",
                media=media,
            )

        reply = tweet("301", monitored, "@other reply", parent_id="300", parent_user=other)
        parent = tweet("300", other, "original post")

        class NoAccountError(RuntimeError):
            pass

        class FakeAPI:
            def __init__(self, *args, **kwargs):
                pass

            async def user_by_login(self, username):
                return monitored

            async def user_tweets_and_replies(self, user_id, limit=-1):
                yield reply

            async def user_tweets(self, user_id, limit=-1):
                yield reply

            async def tweet_details(self, tweet_id):
                return parent if tweet_id == 300 else None

        class FakeReplyScraper(FreeXScraper):
            @staticmethod
            def _imports():
                return FakeAPI, NoAccountError

        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(
                FakeReplyScraper(Path(directory) / "sessions.db").fetch_latest(
                    username="monitored",
                    last_tweet_id=None,
                    include_replies=True,
                    include_reposts=False,
                    initial_limit=20,
                    incremental_limit=20,
                )
            )

        self.assertEqual(result["replyContextCount"], 1)
        mapped = {item["id"]: item for item in result["tweets"]}
        self.assertTrue(mapped["300"]["context_only"])
        self.assertEqual(mapped["300"]["author_username"], "other")
        self.assertEqual(mapped["301"]["reply_to_id"], "300")

    def _timeline_user(self):
        return SimpleNamespace(
            id="42",
            username="monitored",
            displayname="Monitored",
            rawDescription="",
            profileImageUrl=None,
            profileBannerUrl=None,
            protected=False,
            verified=False,
            blue=False,
            followersCount=1,
            friendsCount=2,
            statusesCount=3,
            mediaCount=0,
        )

    def _timeline_tweet(self, tweet_id, author, text="post", *, retweeted=None):
        media = SimpleNamespace(photos=[], videos=[], animated=[])
        return SimpleNamespace(
            id=tweet_id,
            user=author,
            rawContent=text,
            date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            conversationId=tweet_id,
            inReplyToTweetId=None,
            inReplyToUser=None,
            inReplyToScreenName=None,
            lang="zh",
            retweetedTweet=retweeted,
            quotedTweet=None,
            possibly_sensitive=False,
            replyCount=0,
            retweetCount=0,
            likeCount=0,
            quoteCount=0,
            bookmarkedCount=0,
            viewCount=0,
            links=[],
            url=f"https://x.com/{author.username}/status/{tweet_id}",
            media=media,
        )

    def _timeline_scraper(self, items):
        monitored = self._timeline_user()

        class NoAccountError(RuntimeError):
            pass

        class FakeAPI:
            def __init__(self, *args, **kwargs):
                pass

            async def user_by_login(self, username):
                return monitored

            async def user_tweets_and_replies(self, user_id, limit=-1):
                for item in items:
                    yield item

            async def user_tweets(self, user_id, limit=-1):
                for item in items:
                    yield item

            async def tweet_details(self, tweet_id):
                return None

        class TimelineScraper(FreeXScraper):
            @staticmethod
            def _imports():
                return FakeAPI, NoAccountError

        return TimelineScraper

    def test_incremental_backfills_hole_behind_newest_id(self):
        author = self._timeline_user()
        timeline = [
            self._timeline_tweet("104", author, "4"),
            self._timeline_tweet("103", author, "3"),
            self._timeline_tweet("102", author, "2"),
            self._timeline_tweet("101", author, "1"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(
                self._timeline_scraper(timeline)(Path(directory) / "sessions.db").fetch_latest(
                    username="monitored",
                    last_tweet_id="104",
                    include_replies=True,
                    include_reposts=False,
                    initial_limit=20,
                    incremental_limit=20,
                    known_tweet_ids=["104", "103", "101"],
                )
            )
        self.assertEqual([item["id"] for item in result["tweets"]], ["102"])
        self.assertEqual(result["newestSeenId"], "104")

    def test_skipped_reposts_do_not_hide_older_originals(self):
        author = self._timeline_user()
        dummy = self._timeline_tweet("1", author, "origin")
        timeline = [
            self._timeline_tweet("200", author, "rt", retweeted=dummy),
            self._timeline_tweet("150", author, "original"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(
                self._timeline_scraper(timeline)(Path(directory) / "sessions.db").fetch_latest(
                    username="monitored",
                    last_tweet_id="100",
                    include_replies=True,
                    include_reposts=False,
                    initial_limit=20,
                    incremental_limit=20,
                    known_tweet_ids=["100"],
                )
            )
        self.assertEqual([item["id"] for item in result["tweets"]], ["150"])
        self.assertEqual(result["newestSeenId"], "150")

    def test_incremental_stops_after_known_streak_not_id_boundary(self):
        author = self._timeline_user()
        newest = [self._timeline_tweet(str(20 - i), author) for i in range(10)]
        buried_hole = self._timeline_tweet("5", author, "hole")
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(
                self._timeline_scraper(newest + [buried_hole])(
                    Path(directory) / "sessions.db"
                ).fetch_latest(
                    username="monitored",
                    last_tweet_id="20",
                    include_replies=True,
                    include_reposts=False,
                    initial_limit=20,
                    incremental_limit=20,
                    known_tweet_ids=[str(20 - i) for i in range(10)],
                )
            )
        self.assertEqual(result["tweets"], [])

    def test_protected_account_empty_timeline_is_not_success(self):
        media = SimpleNamespace(photos=[], videos=[], animated=[])
        monitored = SimpleNamespace(
            id="42", username="secretuser", displayname="Secret",
            rawDescription="", profileImageUrl=None, profileBannerUrl=None,
            protected=True, verified=False, blue=False, followersCount=1,
            friendsCount=2, statusesCount=12, mediaCount=0,
        )

        class NoAccountError(RuntimeError):
            pass

        class FakePool:
            async def get_all(self):
                return []

            async def accounts_info(self):
                return []

        class BlindAPI:
            def __init__(self, *args, **kwargs):
                self.pool = FakePool()

            async def user_by_login(self, username):
                return monitored

            async def user_tweets_and_replies(self, user_id, limit=-1):
                if False:
                    yield None

            async def user_tweets(self, user_id, limit=-1):
                if False:
                    yield None

        class BlindScraper(FreeXScraper):
            @staticmethod
            def _imports():
                return BlindAPI, NoAccountError

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError) as raised:
                asyncio.run(
                    BlindScraper(Path(directory) / "sessions.db").fetch_latest(
                        username="secretuser",
                        last_tweet_id=None,
                        include_replies=True,
                        include_reposts=False,
                        initial_limit=20,
                        incremental_limit=20,
                    )
                )
        self.assertIn("私密账号", str(raised.exception))
        self.assertIn("未关注", str(raised.exception))

    def test_protected_account_tries_other_cookie_instead_of_empty_success(self):
        media = SimpleNamespace(photos=[], videos=[], animated=[])
        monitored = SimpleNamespace(
            id="42", username="secretuser", displayname="Secret",
            rawDescription="", profileImageUrl=None, profileBannerUrl=None,
            protected=True, verified=False, blue=False, followersCount=1,
            friendsCount=2, statusesCount=12, mediaCount=0,
        )
        visible = SimpleNamespace(
            id="99", user=monitored, rawContent="secret tweet",
            date=datetime(2026, 1, 1, tzinfo=timezone.utc), conversationId="99",
            inReplyToTweetId=None, inReplyToUser=None, inReplyToScreenName=None,
            lang="zh", retweetedTweet=None, quotedTweet=None, possibly_sensitive=False,
            replyCount=0, retweetCount=0, likeCount=0, quoteCount=0,
            bookmarkedCount=0, viewCount=0, links=[],
            url="https://x.com/secretuser/status/99", media=media,
        )

        class NoAccountError(RuntimeError):
            pass

        class FakePool:
            async def get_all(self):
                return [SimpleNamespace(username="viewer-b", cookies={"auth_token": "t", "ct0": "c"})]

            async def add_account_cookies(self, *args, **kwargs):
                return None

            async def accounts_info(self):
                return [{"username": "viewer-b"}]

        class SwitchingAPI:
            timeline_calls = 0

            def __init__(self, *args, **kwargs):
                self.pool = FakePool()

            async def user_by_login(self, username):
                return monitored

            async def user_tweets_and_replies(self, user_id, limit=-1):
                SwitchingAPI.timeline_calls += 1
                if SwitchingAPI.timeline_calls == 1:
                    if False:
                        yield None
                    return
                yield visible

            async def user_tweets(self, user_id, limit=-1):
                if False:
                    yield None

            async def tweet_details(self, tweet_id):
                return None

        class SwitchingScraper(FreeXScraper):
            @staticmethod
            def _imports():
                return SwitchingAPI, NoAccountError

        SwitchingAPI.timeline_calls = 0
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(
                SwitchingScraper(Path(directory) / "sessions.db").fetch_latest(
                    username="secretuser",
                    last_tweet_id=None,
                    include_replies=True,
                    include_reposts=False,
                    initial_limit=20,
                    incremental_limit=20,
                )
            )
        self.assertEqual([item["id"] for item in result["tweets"]], ["99"])
        self.assertGreaterEqual(SwitchingAPI.timeline_calls, 2)

    def test_no_account_with_saved_session_is_rate_limit_not_missing_cookie(self):
        class NoAccountError(RuntimeError):
            pass

        class FakePool:
            def __init__(self, sessions):
                self._sessions = sessions

            async def accounts_info(self):
                return self._sessions

        class LockedAPI:
            def __init__(self, *args, **kwargs):
                self.pool = FakePool(
                    [{"username": "session-1", "active": True, "logged_in": False}]
                )

            async def user_by_login(self, username):
                raise NoAccountError("No account available for queue")

        class LockedScraper(FreeXScraper):
            @staticmethod
            def _imports():
                return LockedAPI, NoAccountError

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError) as raised:
                asyncio.run(
                    LockedScraper(Path(directory) / "sessions.db").fetch_latest(
                        username="monitored",
                        last_tweet_id="1",
                        include_replies=True,
                        include_reposts=False,
                        initial_limit=20,
                        incremental_limit=20,
                    )
                )
        self.assertIn("Cookie 仍有效", str(raised.exception))
        self.assertNotIn("请在设置中添加 Cookie", str(raised.exception))

    def test_no_account_without_any_session_asks_for_cookie(self):
        class NoAccountError(RuntimeError):
            pass

        class FakePool:
            async def accounts_info(self):
                return []

        class EmptyAPI:
            def __init__(self, *args, **kwargs):
                self.pool = FakePool()

            async def user_by_login(self, username):
                raise NoAccountError("No account available")

        class EmptyScraper(FreeXScraper):
            @staticmethod
            def _imports():
                return EmptyAPI, NoAccountError

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError) as raised:
                asyncio.run(
                    EmptyScraper(Path(directory) / "sessions.db").fetch_latest(
                        username="monitored",
                        last_tweet_id=None,
                        include_replies=False,
                        include_reposts=False,
                        initial_limit=20,
                        incremental_limit=20,
                    )
                )
        self.assertIn("请在设置中添加 Cookie", str(raised.exception))

    def test_reply_context_rate_limit_does_not_fail_primary_timeline(self):
        media = SimpleNamespace(photos=[], videos=[], animated=[])
        monitored = SimpleNamespace(
            id="42", username="monitored", displayname="Monitored",
            rawDescription="", profileImageUrl=None, profileBannerUrl=None,
            protected=False, verified=False, blue=False, followersCount=1,
            friendsCount=2, statusesCount=3, mediaCount=0,
        )
        other = SimpleNamespace(
            id="99", username="other", displayname="Other", profileImageUrl=None,
        )
        reply = SimpleNamespace(
            id="301", user=monitored, rawContent="@other reply",
            date=datetime(2026, 1, 1, tzinfo=timezone.utc), conversationId="300",
            inReplyToTweetId="300", inReplyToUser=other,
            inReplyToScreenName="other", lang="zh", retweetedTweet=None,
            quotedTweet=None, possibly_sensitive=False, replyCount=0,
            retweetCount=0, likeCount=0, quoteCount=0, bookmarkedCount=0,
            viewCount=0, links=[], url="https://x.com/monitored/status/301",
            media=media,
        )

        class NoAccountError(RuntimeError):
            pass

        class FakeAPI:
            def __init__(self, *args, **kwargs):
                pass

            async def user_by_login(self, username):
                return monitored

            async def user_tweets_and_replies(self, user_id, limit=-1):
                yield reply

            async def user_tweets(self, user_id, limit=-1):
                yield reply

            async def tweet_details(self, tweet_id):
                raise NoAccountError("TweetDetail is rate-limited")

        class RateLimitedContextScraper(FreeXScraper):
            @staticmethod
            def _imports():
                return FakeAPI, NoAccountError

        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(
                RateLimitedContextScraper(Path(directory) / "sessions.db").fetch_latest(
                    username="monitored", last_tweet_id=None, include_replies=True,
                    include_reposts=False, initial_limit=20, incremental_limit=20,
                )
            )

        self.assertEqual([item["id"] for item in result["tweets"]], ["301"])
        self.assertEqual(result["replyContextCount"], 0)
        self.assertEqual(result["replyContextsDeferred"], 1)


class DatabaseTests(unittest.TestCase):
    def test_tweet_pagination_and_duplicate_insert(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("example")
            tweets = [sample_tweet(str(100 + index), f"tweet {index}") for index in range(4)]
            self.assertEqual(db.insert_tweets(account["id"], tweets), 4)
            self.assertEqual(db.insert_tweets(account["id"], tweets), 0)
            first = db.list_tweets(account["id"], limit=2)
            self.assertEqual(len(first["items"]), 2)
            self.assertIsNotNone(first["nextCursor"])
            second = db.list_tweets(account["id"], limit=2, cursor=first["nextCursor"])
            self.assertEqual(len(second["items"]), 2)
            self.assertFalse({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})

    def test_account_visibility_defaults_public_and_can_be_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("example")
            self.assertTrue(bool(account["is_public"]))
            db.update_account_options(
                account["id"],
                include_replies=True,
                include_reposts=False,
                is_public=False,
            )
            self.assertEqual(db.list_accounts(public_only=True), [])
            self.assertFalse(bool(db.get_account(account["id"])["is_public"]))
            self.assertEqual(len(db.list_accounts()), 1)

    def test_stored_files_follow_their_account_visibility(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("example")
            tweet = sample_tweet("210", "with media")
            tweet["media"] = [
                {
                    "key": "photo-key",
                    "type": "photo",
                    "url": "https://pbs.twimg.com/media/example.jpg",
                }
            ]
            db.insert_tweets(account["id"], [tweet])
            pending = db.pending_media(account["id"])[0]
            path = "media/example/210/photo-key.jpg"
            db.media_downloaded(pending["id"], path, None, "image/jpeg")
            self.assertTrue(db.file_is_public(path))
            self.assertEqual(db.file_owner_accounts("media/example/orphan.jpg"), [])
            self.assertIsNone(db.file_is_public("media/example/orphan.jpg"))
            db.update_account_options(
                account["id"],
                include_replies=True,
                include_reposts=False,
                is_public=False,
            )
            self.assertFalse(db.file_is_public(path))

    def test_existing_database_receives_public_visibility_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reader.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    """CREATE TABLE accounts (
                        id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                        syncing INTEGER NOT NULL DEFAULT 0
                    )"""
                )
                connection.execute(
                    "INSERT INTO accounts(id, username, syncing) VALUES (1, 'legacy', 0)"
                )
                connection.commit()
            finally:
                connection.close()
            db = Database(path)
            self.assertTrue(bool(db.get_account(1)["is_public"]))
            self.assertIn("last_sync_failed_at", db.get_account(1))

    def test_sync_failure_records_time_and_success_clears_it(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("example")
            db.mark_sync_started(account["id"])
            db.mark_sync_failed(account["id"], "X request timed out")
            failed = db.get_account(account["id"])
            self.assertEqual(failed["last_error"], "X request timed out")
            self.assertIsNotNone(failed["last_sync_failed_at"])
            db.mark_sync_started(account["id"])
            db.mark_sync_succeeded(account["id"], None)
            recovered = db.get_account(account["id"])
            self.assertIsNone(recovered["last_error"])
            self.assertIsNone(recovered["last_sync_failed_at"])

    def test_public_update_time_only_tracks_newly_inserted_content(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("example")
            db.insert_tweets(account["id"], [sample_tweet("204", "new content")])
            content_time = db.get_account(account["id"])["last_content_at"]
            self.assertIsNotNone(content_time)

            # A later successful scan with no inserted tweets must not make the
            # public page look as if the account received new content.
            with db.connection() as connection:
                connection.execute(
                    "UPDATE accounts SET last_synced_at = ? WHERE id = ?",
                    ("2099-01-01T00:00:00Z", account["id"]),
                )
                connection.commit()

            listed = db.list_accounts()[0]
            self.assertEqual(listed["last_content_at"], content_time)
            self.assertEqual(
                Application.account_public(object(), listed)["lastSyncedAt"],
                content_time,
            )

    def test_tweets_can_be_filtered_by_year_and_month(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("example")
            january = sample_tweet("200", "january")
            february = sample_tweet("201", "february")
            previous_year = sample_tweet("202", "previous")
            january["created_at"] = "2026-01-18T12:00:00Z"
            february["created_at"] = "2026-02-03T12:00:00Z"
            previous_year["created_at"] = "2025-12-31T12:00:00Z"
            db.insert_tweets(account["id"], [january, february, previous_year])
            year_page = db.list_tweets(account["id"], year=2026)
            month_page = db.list_tweets(account["id"], year=2026, month=2)
            self.assertEqual({item["id"] for item in year_page["items"]}, {"200", "201"})
            self.assertEqual([item["id"] for item in month_page["items"]], ["201"])
            self.assertEqual(
                db.list_tweet_months(account["id"]),
                [
                    {"year": 2026, "month": 2, "count": 1},
                    {"year": 2026, "month": 1, "count": 1},
                    {"year": 2025, "month": 12, "count": 1},
                ],
            )

    def test_originals_only_include_posts_authored_by_the_account(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("example")
            db.update_profile(
                account["id"],
                {
                    "id": "42",
                    "username": "example",
                    "display_name": "Example",
                },
                None,
                None,
            )
            original = sample_tweet("210", "own original")
            reply = sample_tweet("211", "own reply")
            reply.update({"is_reply": True, "reply_to_id": "212"})
            foreign_parent = sample_tweet("212", "foreign parent")
            foreign_parent.update(
                {"author_id": "99", "author_username": "other", "author_name": "Other"}
            )
            reused_handle = sample_tweet("213", "same handle, different X user ID")
            reused_handle["author_id"] = "100"
            db.insert_tweets(
                account["id"], [original, reply, foreign_parent, reused_handle]
            )

            page = db.list_tweets(account["id"], kind="originals")

            self.assertEqual([item["id"] for item in page["items"]], ["210"])

    def test_media_only_includes_owned_media_and_hides_reply_parent_media(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("example")
            db.update_profile(
                account["id"],
                {
                    "id": "42",
                    "username": "example",
                    "display_name": "Example",
                },
                None,
                None,
            )

            def attach_photo(tweet: dict, key: str) -> dict:
                tweet["media"] = [
                    {
                        "key": key,
                        "type": "photo",
                        "url": f"https://pbs.twimg.com/media/{key}.jpg",
                    }
                ]
                return tweet

            parent = attach_photo(sample_tweet("220", "foreign parent"), "parent-photo")
            parent.update(
                {"author_id": "99", "author_username": "other", "author_name": "Other"}
            )
            reply = attach_photo(sample_tweet("221", "own reply media"), "reply-photo")
            reply.update(
                {
                    "is_reply": True,
                    "reply_to_id": "220",
                    "reply_to_username": "other",
                }
            )
            repost = attach_photo(sample_tweet("222", "reposted media"), "repost-photo")
            repost["is_repost"] = True
            original = attach_photo(sample_tweet("223", "own original media"), "own-photo")
            db.insert_tweets(account["id"], [parent, reply, repost, original])

            all_page = db.list_tweets(account["id"], kind="all")
            page = db.list_tweets(account["id"], kind="media")
            items = {item["id"]: item for item in page["items"]}

            self.assertEqual(
                [item["id"] for item in all_page["items"]],
                ["223", "222", "221", "220"],
            )
            self.assertEqual(set(items), {"221", "223"})
            self.assertEqual(len(items["221"]["media"]), 1)
            self.assertEqual(items["221"]["media"][0]["type"], "photo")
            self.assertEqual(items["221"]["repliedTo"]["id"], "220")
            self.assertEqual(items["221"]["repliedTo"]["media"], [])

    def test_tweet_uses_its_own_author_avatar_and_reply_target(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("monitored")
            parent = sample_tweet("219", "original post")
            parent.update(
                {
                    "author_username": "target",
                    "author_name": "Target Author",
                    "author_avatar_path": "profiles/monitored/authors/target/a.jpg",
                }
            )
            tweet = sample_tweet("220", "@target hello")
            tweet.update(
                {
                    "author_username": "original_author",
                    "author_name": "Original",
                    "author_avatar_url": "https://pbs.twimg.com/profile_images/a.jpg",
                    "author_avatar_path": "profiles/monitored/authors/original_author/a.jpg",
                    "reply_to_id": "219",
                    "reply_to_username": "target",
                    "is_reply": True,
                }
            )
            db.insert_tweets(account["id"], [parent, tweet])
            item = db.list_tweets(account["id"])["items"][0]
            self.assertEqual(item["authorUsername"], "original_author")
            self.assertIn("original_author", item["authorAvatarUrl"])
            self.assertEqual(item["replyToUsername"], "target")
            self.assertEqual(item["repliedTo"]["id"], "219")
            self.assertEqual(item["repliedTo"]["authorUsername"], "target")
            self.assertIn("authors/target", item["repliedTo"]["authorAvatarUrl"])

    def test_reply_context_is_embedded_but_not_listed_as_monitored_content(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("monitored")
            parent = sample_tweet("230", "another blogger's original post")
            parent.update(
                {
                    "author_id": "99",
                    "author_username": "other",
                    "author_name": "Other",
                    "context_only": True,
                }
            )
            reply = sample_tweet("231", "@other my reply")
            reply.update(
                {
                    "reply_to_id": "230",
                    "reply_to_username": "other",
                    "is_reply": True,
                }
            )

            self.assertEqual(db.insert_tweets(account["id"], [reply]), 1)
            self.assertEqual(db.missing_reply_context_ids(account["id"]), ["230"])
            self.assertEqual(db.insert_tweets(account["id"], [parent]), 0)
            self.assertEqual(db.missing_reply_context_ids(account["id"]), [])
            page = db.list_tweets(account["id"])

            self.assertEqual([item["id"] for item in page["items"]], ["231"])
            self.assertEqual(page["items"][0]["repliedTo"]["id"], "230")
            self.assertEqual(page["items"][0]["repliedTo"]["authorUsername"], "other")

    def test_reply_without_reply_to_id_uses_conversation_original(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("monitored")
            parent = sample_tweet("240", "conversation original")
            parent.update(
                {
                    "author_username": "other",
                    "author_name": "Other",
                    "context_only": True,
                }
            )
            reply = sample_tweet("241", "a reply in the thread")
            reply.update(
                {
                    "is_reply": True,
                    "conversation_id": "240",
                    "reply_to_id": "",
                    "reply_to_username": "other",
                }
            )
            db.insert_tweets(account["id"], [parent, reply])
            page = db.list_tweets(account["id"], kind="all")
            self.assertEqual([item["id"] for item in page["items"]], ["241"])
            self.assertEqual(page["items"][0]["repliedTo"]["id"], "240")
            self.assertEqual(page["items"][0]["repliedTo"]["authorUsername"], "other")

    def test_same_conversation_replies_collapse_into_one_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "reader.db")
            account = db.create_account("monitored")
            original = sample_tweet("240", "original post")
            original.update({"conversation_id": "240"})
            other_reply = sample_tweet("241", "@monitored hi")
            other_reply.update(
                {
                    "author_username": "other",
                    "author_name": "Other",
                    "is_reply": True,
                    "conversation_id": "240",
                    "reply_to_id": "240",
                    "reply_to_username": "monitored",
                }
            )
            own_reply = sample_tweet("242", "@other thanks")
            own_reply.update(
                {
                    "is_reply": True,
                    "conversation_id": "240",
                    "reply_to_id": "241",
                    "reply_to_username": "other",
                }
            )
            db.insert_tweets(account["id"], [original, other_reply, own_reply])
            page = db.list_tweets(account["id"], kind="all")
            self.assertEqual(len(page["items"]), 1)
            item = page["items"][0]
            self.assertEqual(item["id"], "242")
            self.assertEqual([entry["id"] for entry in item["thread"]], ["240", "241", "242"])
            replies_page = db.list_tweets(account["id"], kind="replies")
            self.assertEqual(len(replies_page["items"]), 1)
            self.assertEqual(
                [entry["id"] for entry in replies_page["items"][0]["thread"]],
                ["240", "241", "242"],
            )


class WebRoutingTests(unittest.TestCase):
    def test_member_login_outranks_admin_on_public_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "reader.db")
            public = database.create_account("public_user")
            exclusive = database.create_account("exclusive_user")
            database.update_account_options(
                exclusive["id"],
                include_replies=True,
                include_reposts=False,
                is_public=False,
            )
            member_auth = MemberAuth(database)
            member = member_auth.create_member(
                "reader_one", "member-password", [exclusive["id"]]
            )
            member_token, _ = member_auth.login("reader_one", "member-password")
            admin_auth = AdminAuth(root)
            admin_token = admin_auth.setup("test-admin-password")
            application = Application(
                data_dir=root,
                public_dir=Path(__file__).resolve().parents[1] / "public",
                database=database,
                config=ConfigStore(root),
                admin_auth=admin_auth,
                member_auth=member_auth,
                share_auth=ShareAuth(database),
                notifier=SimpleNamespace(),
                scraper=SimpleNamespace(),
                sync_service=SimpleNamespace(),
                scheduler=SimpleNamespace(),
                scraper_runtime=SimpleNamespace(),
            )
            server = create_server(("127.0.0.1", 0), application)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                cookie = (
                    f"{admin_auth.COOKIE_NAME}={admin_token}; "
                    f"{member_auth.COOKIE_NAME}={member_token}"
                )
                listed = httpx.get(
                    f"{base_url}/api/public/accounts",
                    headers={"Cookie": cookie},
                    timeout=3,
                )
                self.assertEqual(listed.status_code, 200)
                items = {item["id"]: item for item in listed.json()["items"]}
                self.assertIn(public["id"], items)
                self.assertIn(exclusive["id"], items)
                self.assertTrue(items[exclusive["id"]]["isExclusive"])
                self.assertFalse(items[public["id"]]["isExclusive"])
                self.assertTrue(items[public["id"]]["isPublic"])
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_reader_account_validation_and_html_not_found_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "reader.db")
            account = database.create_account("visible_account")
            config = ConfigStore(root)
            share_auth = ShareAuth(database)
            admin_auth = AdminAuth(root)
            admin_token = admin_auth.setup("test-admin-password")
            application = Application(
                data_dir=root,
                public_dir=Path(__file__).resolve().parents[1] / "public",
                database=database,
                config=config,
                admin_auth=admin_auth,
                member_auth=MemberAuth(database),
                share_auth=share_auth,
                notifier=SimpleNamespace(),
                scraper=SimpleNamespace(),
                sync_service=SimpleNamespace(),
                scheduler=SimpleNamespace(),
                scraper_runtime=SimpleNamespace(),
            )
            server = create_server(("127.0.0.1", 0), application)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                valid = httpx.get(
                    f"{base_url}/reader?account={account['id']}", timeout=3
                )
                self.assertEqual(valid.status_code, 200)
                self.assertIn("X拾光", valid.text)

                for invalid in ("abc", "99999", "", "1&account=2"):
                    response = httpx.get(
                        f"{base_url}/reader?account={invalid}", timeout=3
                    )
                    self.assertEqual(response.status_code, 404)
                    self.assertTrue(response.headers["content-type"].startswith("text/html"))
                    self.assertIn("返回账号导航", response.text)

                missing = httpx.get(f"{base_url}/path-that-does-not-exist", timeout=3)
                self.assertEqual(missing.status_code, 404)
                self.assertTrue(missing.headers["content-type"].startswith("text/html"))
                self.assertIn('href="/"', missing.text)

                missing_api = httpx.get(f"{base_url}/api/does-not-exist", timeout=3)
                self.assertEqual(missing_api.status_code, 404)
                self.assertTrue(
                    missing_api.headers["content-type"].startswith("application/json")
                )

                private = database.create_account("private_account")
                database.update_account_options(
                    private["id"],
                    include_replies=True,
                    include_reposts=False,
                    is_public=False,
                )
                private_tweet = sample_tweet("990", "private post with media")
                private_tweet["media"] = [
                    {
                        "key": "private-photo",
                        "type": "photo",
                        "url": "https://pbs.twimg.com/media/private.jpg",
                    }
                ]
                database.insert_tweets(private["id"], [private_tweet])
                pending = database.pending_media(private["id"])[0]
                database.media_downloaded(
                    pending["id"],
                    "media/private_account/990/private-photo.jpg",
                    None,
                    "image/jpeg",
                )
                blocked = httpx.get(
                    f"{base_url}/reader?account={private['id']}", timeout=3
                )
                self.assertEqual(blocked.status_code, 200)
                self.assertIn("X拾光", blocked.text)
                hidden_tweets = httpx.get(
                    f"{base_url}/api/public/accounts/{private['id']}/tweets", timeout=3
                )
                self.assertEqual(hidden_tweets.status_code, 404)
                denied_share = httpx.post(
                    f"{base_url}/api/admin/accounts/{private['id']}/shares",
                    json={"expiresInMinutes": 60},
                    timeout=3,
                )
                self.assertEqual(denied_share.status_code, 401)
                created_share = httpx.post(
                    f"{base_url}/api/admin/accounts/{private['id']}/shares",
                    json={"expiresInMinutes": 60},
                    headers={"Cookie": f"{admin_auth.COOKIE_NAME}={admin_token}"},
                    timeout=3,
                )
                self.assertEqual(created_share.status_code, 201)
                share_url = created_share.json()["url"]
                with httpx.Client(follow_redirects=False, timeout=3) as client:
                    opened = client.get(f"{base_url}{share_url}")
                    self.assertEqual(opened.status_code, 302)
                    self.assertEqual(
                        opened.headers["location"], f"/reader?account={private['id']}"
                    )
                    shared_reader = client.get(f"{base_url}{opened.headers['location']}")
                    self.assertEqual(shared_reader.status_code, 200)
                    shared_accounts = client.get(f"{base_url}/api/public/accounts")
                    shared_item = next(
                        item
                        for item in shared_accounts.json()["items"]
                        if item["id"] == private["id"]
                    )
                    self.assertFalse(shared_item["isPublic"])
                    self.assertTrue(shared_item["isShared"])
                    self.assertEqual(shared_item["tweetCount"], 1)
                    self.assertEqual(shared_item["mediaCount"], 1)
                expired = httpx.get(f"{base_url}/s/not-a-real-share-token-1234567890", timeout=3)
                self.assertEqual(expired.status_code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


class FakeScraper:
    def __init__(self):
        self.seen_cursors = []

    async def fetch_latest(self, **kwargs):
        cursor = kwargs["last_tweet_id"]
        self.seen_cursors.append(cursor)
        tweet_id = "100" if cursor is None else "101"
        return {
            "profile": {
                "id": "42",
                "username": "example",
                "display_name": "Example",
                "bio": "bio",
                "avatar_url": None,
                "banner_url": None,
                "protected": False,
                "verified": False,
                "metrics": {},
            },
            "tweets": [sample_tweet(tweet_id, "new")],
            "newestSeenId": tweet_id,
        }


class FailingScraper:
    async def fetch_latest(self, **kwargs):
        raise RuntimeError("Could not find user")


class FailingInvalidCredentialScraper:
    def __init__(self):
        self.alerted = False

    async def fetch_latest(self, **kwargs):
        raise RuntimeError("没有可用的 X 登录会话，请在设置中添加 Cookie")

    async def pending_invalid_session_alerts(self):
        if self.alerted:
            return []
        return [
            {
                "label": "main-session",
                "verifiedUsername": "owner",
                "active": False,
                "loggedIn": False,
                "credentialState": "invalid",
                "error": "Cookie 已失效",
            }
        ]

    def mark_invalid_session_alerted(self, labels):
        self.alerted = labels == ["main-session"]


class FakeMedia:
    async def download_profile_assets(self, *args, **kwargs):
        return None, None

    async def download_pending(self, *args, **kwargs):
        return {"downloaded": 0, "failed": 0, "pending": 0}

    async def download_author_avatars(self, *args, **kwargs):
        return {}


class FakeNotifier:
    def __init__(self):
        self.calls = []
        self.invalid_calls = []

    async def notify_account_update(self, **kwargs):
        self.calls.append(kwargs)
        return {"sent": True, "status": 200, "elapsedMs": 1}

    async def notify_invalid_credentials(self, **kwargs):
        self.invalid_calls.append(kwargs)
        return {"sent": True, "status": 200, "elapsedMs": 1}


class SyncTests(unittest.TestCase):
    def test_second_sync_uses_saved_incremental_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "reader.db")
            account = db.create_account("example")
            scraper = FakeScraper()
            notifier = FakeNotifier()
            service = SyncService(
                db, ConfigStore(root), scraper, FakeMedia(), notifier=notifier
            )
            first = asyncio.run(service.sync_account(account["id"]))
            second = asyncio.run(service.sync_account(account["id"]))
            self.assertEqual(first["inserted"], 1)
            self.assertEqual(first["username"], "example")
            self.assertEqual(second["inserted"], 1)
            self.assertEqual(scraper.seen_cursors, [None, "100"])
            self.assertEqual(db.get_account(account["id"])["last_tweet_id"], "101")
            self.assertNotIn("notification", first)
            self.assertTrue(second["notification"]["sent"])
            self.assertEqual(len(notifier.calls), 1)

    def test_incremental_sync_sends_selected_member_notification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "reader.db")
            account = db.create_account("example")
            auth = MemberAuth(db)
            member = auth.create_member("reader_one", "member-password", [])
            auth.update_notification_settings(
                member["id"],
                enabled=True,
                server_url="https://api.day.app",
                device_key="member-device-key",
                clear_device_key=False,
                group="我的订阅",
                account_ids=[account["id"]],
            )
            notifier = FakeNotifier()
            service = SyncService(
                db, ConfigStore(root), FakeScraper(), FakeMedia(), notifier=notifier
            )
            asyncio.run(service.sync_account(account["id"]))
            second = asyncio.run(service.sync_account(account["id"]))
            self.assertEqual(second["memberNotifications"]["sent"], 1)
            self.assertEqual(second["memberNotifications"]["failed"], 0)
            self.assertEqual(len(notifier.calls), 2)
            member_call = next(call for call in notifier.calls if "settings" in call)
            self.assertEqual(member_call["settings"]["barkDeviceKey"], "member-device-key")
            self.assertEqual(member_call["settings"]["barkGroup"], "我的订阅")

    def test_sync_all_failure_identifies_account_and_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "reader.db")
            account = db.create_account("missing_user")
            service = SyncService(db, ConfigStore(root), FailingScraper(), FakeMedia())
            result = asyncio.run(service.sync_all())
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["results"][0]["accountId"], account["id"])
            self.assertEqual(result["results"][0]["username"], "missing_user")
            self.assertEqual(result["results"][0]["error"], "Could not find user")
            failed = db.get_account(account["id"])
            self.assertEqual(failed["last_error"], "Could not find user")
            self.assertIsNotNone(failed["last_sync_failed_at"])


    def test_sync_all_skips_remaining_after_rate_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "reader.db")
            first = db.create_account("alpha")
            second = db.create_account("beta")
            third = db.create_account("gamma")

            class QuotaScraper:
                async def fetch_latest(self, **kwargs):
                    raise RuntimeError("X 请求额度暂时耗尽或会话被短暂锁定，Cookie 仍有效，请稍后再试")

                async def pending_invalid_session_alerts(self):
                    return []

            service = SyncService(db, ConfigStore(root), QuotaScraper(), FakeMedia())
            service.account_sync_gap_seconds = 0
            result = asyncio.run(service.sync_all())
            self.assertEqual(result["failed"], 3)
            self.assertEqual(result["succeeded"], 0)
            errors = [item["error"] for item in result["results"]]
            self.assertIn("Cookie 仍有效", errors[0])
            self.assertEqual(errors[1], "已跳过：抓取额度已用尽，等待解锁后再试")
            self.assertEqual(errors[2], "已跳过：抓取额度已用尽，等待解锁后再试")
            self.assertEqual(db.get_account(first["id"])["last_error"], errors[0])
            self.assertIsNone(db.get_account(second["id"])["last_error"])
            self.assertIsNone(db.get_account(third["id"])["last_error"])

    def test_sync_failed_only_retries_accounts_with_unresolved_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "reader.db")
            healthy = db.create_account("healthy")
            failed = db.create_account("failed")
            db.mark_sync_failed(failed["id"], "temporary rate limit")
            scraper = FakeScraper()
            service = SyncService(db, ConfigStore(root), scraper, FakeMedia())

            result = asyncio.run(service.sync_failed())

            self.assertEqual(result["succeeded"], 1)
            self.assertEqual(result["failed"], 0)
            self.assertEqual([item["accountId"] for item in result["results"]], [failed["id"]])
            self.assertIsNone(db.get_account(failed["id"])["last_error"])
            self.assertIsNone(db.get_account(healthy["id"])["last_synced_at"])

    def test_invalid_credential_bark_alert_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "reader.db")
            account = db.create_account("example")
            scraper = FailingInvalidCredentialScraper()
            notifier = FakeNotifier()
            service = SyncService(
                db, ConfigStore(root), scraper, FakeMedia(), notifier=notifier
            )

            first = asyncio.run(service.sync_all(reason="schedule"))
            second = asyncio.run(service.sync_all(reason="schedule"))

            self.assertEqual(first["failed"], 1)
            self.assertEqual(second["failed"], 1)
            self.assertEqual(len(notifier.invalid_calls), 1)
            self.assertEqual(
                notifier.invalid_calls[0]["sessions"][0]["label"], "main-session"
            )
            self.assertTrue(scraper.alerted)
            self.assertIsNotNone(db.get_account(account["id"])["last_sync_failed_at"])


if __name__ == "__main__":
    unittest.main()
