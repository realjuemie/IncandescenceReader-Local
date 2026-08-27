from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

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
from incandescence.sync_service import SyncService


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
                        "avatar_url": "https://pbs.twimg.com/profile_images/example.jpg",
                    },
                    tweets=[sample_tweet("301", "这是最新内容")],
                    inserted=1,
                )
            )
            self.assertTrue(result["sent"])
            self.assertEqual(captured["title"], "@example 有 1 条新内容")
            self.assertIn("这是最新内容", captured["body"])
            self.assertEqual(
                captured["icon"], "https://pbs.twimg.com/profile_images/example.jpg"
            )
            self.assertEqual(captured["url"], "http://192.168.1.20:8787/reader?account=7")
            self.assertEqual(captured["group"], "本地阅读更新")


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
            auth.update_member(
                member["id"], active=False, account_ids=[private["id"]]
            )
            self.assertIsNone(auth.current(cookie))


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

    async def notify_account_update(self, **kwargs):
        self.calls.append(kwargs)
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


if __name__ == "__main__":
    unittest.main()
