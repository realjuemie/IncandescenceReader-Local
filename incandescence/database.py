from __future__ import annotations

import base64
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_username(value: str) -> str:
    username = (value or "").strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9_]{1,15}", username):
        raise ValueError("X 用户名只能包含字母、数字、下划线，长度为 1–15 个字符")
    return username


class Database:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    x_user_id TEXT,
                    display_name TEXT,
                    bio TEXT NOT NULL DEFAULT '',
                    avatar_path TEXT,
                    banner_path TEXT,
                    profile_image_url TEXT,
                    profile_banner_url TEXT,
                    is_protected INTEGER NOT NULL DEFAULT 0,
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    public_metrics_json TEXT NOT NULL DEFAULT '{}',
                    include_replies INTEGER NOT NULL DEFAULT 1,
                    include_reposts INTEGER NOT NULL DEFAULT 0,
                    is_public INTEGER NOT NULL DEFAULT 1,
                    last_tweet_id TEXT,
                    last_synced_at TEXT,
                    last_sync_started_at TEXT,
                    last_sync_failed_at TEXT,
                    last_error TEXT,
                    syncing INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tweets (
                    id TEXT PRIMARY KEY,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    author_id TEXT,
                    author_username TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    author_avatar_url TEXT,
                    author_avatar_path TEXT,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    conversation_id TEXT,
                    reply_to_id TEXT,
                    reply_to_username TEXT,
                    lang TEXT,
                    is_reply INTEGER NOT NULL DEFAULT 0,
                    is_repost INTEGER NOT NULL DEFAULT 0,
                    is_quote INTEGER NOT NULL DEFAULT 0,
                    possibly_sensitive INTEGER NOT NULL DEFAULT 0,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    links_json TEXT NOT NULL DEFAULT '[]',
                    quoted_json TEXT,
                    source_url TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tweets_account_created
                    ON tweets(account_id, created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_tweets_account_kind
                    ON tweets(account_id, is_reply, is_repost);

                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tweet_id TEXT NOT NULL REFERENCES tweets(id) ON DELETE CASCADE,
                    media_key TEXT NOT NULL,
                    type TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    preview_source_url TEXT,
                    local_path TEXT,
                    preview_local_path TEXT,
                    mime_type TEXT,
                    width INTEGER,
                    height INTEGER,
                    duration_ms INTEGER,
                    alt_text TEXT,
                    download_error TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(tweet_id, media_key)
                );

                CREATE INDEX IF NOT EXISTS idx_media_pending
                    ON media(local_path, download_error);

                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_salt TEXT NOT NULL,
                    password_digest TEXT NOT NULL,
                    password_rounds INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    bark_enabled INTEGER NOT NULL DEFAULT 0,
                    bark_server_url TEXT NOT NULL DEFAULT 'https://api.day.app',
                    bark_device_key TEXT NOT NULL DEFAULT '',
                    bark_group TEXT NOT NULL DEFAULT 'Incandescence',
                    last_login_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS member_account_access (
                    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(member_id, account_id)
                );

                CREATE TABLE IF NOT EXISTS member_notification_accounts (
                    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(member_id, account_id)
                );
                """
            )
            account_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(accounts)").fetchall()
            }
            if "is_public" not in account_columns:
                db.execute(
                    "ALTER TABLE accounts ADD COLUMN is_public INTEGER NOT NULL DEFAULT 1"
                )
            if "last_sync_failed_at" not in account_columns:
                db.execute("ALTER TABLE accounts ADD COLUMN last_sync_failed_at TEXT")
            tweet_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(tweets)").fetchall()
            }
            for column, definition in (
                ("author_avatar_url", "TEXT"),
                ("author_avatar_path", "TEXT"),
                ("reply_to_username", "TEXT"),
            ):
                if column not in tweet_columns:
                    db.execute(f"ALTER TABLE tweets ADD COLUMN {column} {definition}")
            member_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(members)").fetchall()
            }
            for column, definition in (
                ("bark_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("bark_server_url", "TEXT NOT NULL DEFAULT 'https://api.day.app'"),
                ("bark_device_key", "TEXT NOT NULL DEFAULT ''"),
                ("bark_group", "TEXT NOT NULL DEFAULT 'Incandescence'"),
            ):
                if column not in member_columns:
                    db.execute(f"ALTER TABLE members ADD COLUMN {column} {definition}")
            db.execute("UPDATE accounts SET syncing = 0")
            db.commit()

    def create_account(self, username: str) -> dict[str, Any]:
        username = normalize_username(username)
        now = utc_now()
        try:
            with self.connection() as db:
                cursor = db.execute(
                    """INSERT INTO accounts(username, display_name, created_at, updated_at)
                       VALUES (?, ?, ?, ?)""",
                    (username, username, now, now),
                )
                db.commit()
                return self.get_account(int(cursor.lastrowid))
        except sqlite3.IntegrityError as error:
            raise ValueError(f"账号 @{username} 已存在") from error

    def get_account(self, account_id: int) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            raise KeyError("账号不存在")
        return dict(row)

    def list_accounts(
        self, *, public_only: bool = False, member_id: int | None = None
    ) -> list[dict[str, Any]]:
        if member_id is not None:
            visibility = """WHERE a.is_public = 1 OR EXISTS (
                SELECT 1 FROM member_account_access maa
                JOIN members mm ON mm.id = maa.member_id
                WHERE maa.account_id = a.id AND maa.member_id = ? AND mm.active = 1
            )"""
            query_params: tuple[Any, ...] = (member_id,)
        else:
            visibility = "WHERE a.is_public = 1" if public_only else ""
            query_params = ()
        with self.connection() as db:
            rows = db.execute(
                f"""
                SELECT a.*,
                       COUNT(t.id) AS tweet_count,
                       MAX(t.created_at) AS newest_tweet_at,
                       (SELECT COUNT(*) FROM media m
                        JOIN tweets mt ON mt.id = m.tweet_id
                        WHERE mt.account_id = a.id AND m.local_path IS NOT NULL) AS media_count,
                       (SELECT COUNT(*) FROM media m
                        JOIN tweets mt ON mt.id = m.tweet_id
                        WHERE mt.account_id = a.id
                          AND (m.local_path IS NULL OR m.download_error IS NOT NULL)) AS pending_media_count
                FROM accounts a
                LEFT JOIN tweets t ON t.account_id = a.id
                {visibility}
                GROUP BY a.id
                ORDER BY lower(a.username)
                """,
                query_params,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_account_options(
        self,
        account_id: int,
        *,
        include_replies: bool,
        include_reposts: bool,
        is_public: bool | None = None,
    ) -> dict[str, Any]:
        with self.connection() as db:
            changed = db.execute(
                """UPDATE accounts
                   SET include_replies = ?, include_reposts = ?,
                       is_public = COALESCE(?, is_public), updated_at = ?
                   WHERE id = ?""",
                (
                    int(include_replies),
                    int(include_reposts),
                    int(is_public) if is_public is not None else None,
                    utc_now(),
                    account_id,
                ),
            ).rowcount
            db.commit()
        if not changed:
            raise KeyError("账号不存在")
        return self.get_account(account_id)

    def update_profile(
        self,
        account_id: int,
        profile: dict[str, Any],
        avatar_path: str | None,
        banner_path: str | None,
    ) -> None:
        with self.connection() as db:
            db.execute(
                """
                UPDATE accounts SET
                    username = ?, x_user_id = ?, display_name = ?, bio = ?,
                    avatar_path = COALESCE(?, avatar_path),
                    banner_path = COALESCE(?, banner_path),
                    profile_image_url = ?, profile_banner_url = ?,
                    is_protected = ?, is_verified = ?, public_metrics_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    normalize_username(profile["username"]),
                    str(profile.get("id") or ""),
                    profile.get("display_name") or profile["username"],
                    profile.get("bio") or "",
                    avatar_path,
                    banner_path,
                    profile.get("avatar_url"),
                    profile.get("banner_url"),
                    int(bool(profile.get("protected"))),
                    int(bool(profile.get("verified"))),
                    json.dumps(profile.get("metrics") or {}, ensure_ascii=False),
                    utc_now(),
                    account_id,
                ),
            )
            db.commit()

    def mark_sync_started(self, account_id: int) -> None:
        with self.connection() as db:
            changed = db.execute(
                """UPDATE accounts SET syncing = 1, last_sync_started_at = ?,
                   last_error = NULL, updated_at = ? WHERE id = ?""",
                (utc_now(), utc_now(), account_id),
            ).rowcount
            db.commit()
        if not changed:
            raise KeyError("账号不存在")

    def mark_sync_succeeded(self, account_id: int, newest_id: str | None) -> None:
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """UPDATE accounts SET syncing = 0, last_tweet_id = COALESCE(?, last_tweet_id),
                   last_synced_at = ?, last_sync_failed_at = NULL,
                   last_error = NULL, updated_at = ? WHERE id = ?""",
                (newest_id, now, now, account_id),
            )
            db.commit()

    def mark_sync_failed(self, account_id: int, error: str) -> None:
        message = (error or "同步失败")[:1000]
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """UPDATE accounts SET syncing = 0, last_error = ?,
                   last_sync_failed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (message, now, now, account_id),
            )
            db.commit()

    def insert_tweets(self, account_id: int, tweets: list[dict[str, Any]]) -> int:
        inserted = 0
        now = utc_now()
        with self.connection() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                for tweet in tweets:
                    result = db.execute(
                        """
                        INSERT OR IGNORE INTO tweets(
                            id, account_id, author_id, author_username, author_name,
                            author_avatar_url, author_avatar_path, text,
                            created_at, conversation_id, reply_to_id, reply_to_username, lang, is_reply,
                            is_repost, is_quote, possibly_sensitive, metrics_json, links_json,
                            quoted_json, source_url, synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(tweet["id"]), account_id, str(tweet.get("author_id") or ""),
                            tweet.get("author_username") or "", tweet.get("author_name") or "",
                            tweet.get("author_avatar_url"), tweet.get("author_avatar_path"),
                            tweet.get("text") or "", tweet["created_at"],
                            str(tweet.get("conversation_id") or ""),
                            str(tweet.get("reply_to_id") or "") or None,
                            tweet.get("reply_to_username"),
                            tweet.get("lang"), int(bool(tweet.get("is_reply"))),
                            int(bool(tweet.get("is_repost"))), int(bool(tweet.get("is_quote"))),
                            int(bool(tweet.get("possibly_sensitive"))),
                            json.dumps(tweet.get("metrics") or {}, ensure_ascii=False),
                            json.dumps(tweet.get("links") or [], ensure_ascii=False),
                            json.dumps(tweet.get("quoted"), ensure_ascii=False)
                            if tweet.get("quoted") else None,
                            tweet.get("source_url") or "", now,
                        ),
                    )
                    inserted += int(result.rowcount > 0)
                    if result.rowcount == 0:
                        db.execute(
                            """UPDATE tweets SET
                                   author_username = ?, author_name = ?,
                                   author_avatar_url = COALESCE(?, author_avatar_url),
                                   author_avatar_path = COALESCE(?, author_avatar_path),
                                   reply_to_username = COALESCE(?, reply_to_username)
                               WHERE id = ?""",
                            (
                                tweet.get("author_username") or "",
                                tweet.get("author_name") or "",
                                tweet.get("author_avatar_url"),
                                tweet.get("author_avatar_path"),
                                tweet.get("reply_to_username"),
                                str(tweet["id"]),
                            ),
                        )
                    for media in tweet.get("media") or []:
                        db.execute(
                            """
                            INSERT INTO media(
                                tweet_id, media_key, type, source_url, preview_source_url,
                                width, height, duration_ms, alt_text, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(tweet_id, media_key) DO UPDATE SET
                                source_url = excluded.source_url,
                                preview_source_url = excluded.preview_source_url,
                                width = excluded.width,
                                height = excluded.height,
                                duration_ms = excluded.duration_ms,
                                alt_text = excluded.alt_text
                            """,
                            (
                                str(tweet["id"]), media["key"], media["type"], media["url"],
                                media.get("preview_url"), media.get("width"), media.get("height"),
                                media.get("duration_ms"), media.get("alt_text"), now,
                            ),
                        )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return inserted

    def pending_media(self, account_id: int, limit: int = 5000) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT m.*, t.account_id, a.username
                FROM media m
                JOIN tweets t ON t.id = m.tweet_id
                JOIN accounts a ON a.id = t.account_id
                WHERE t.account_id = ?
                  AND (m.local_path IS NULL OR m.download_error IS NOT NULL)
                ORDER BY t.created_at DESC, m.id ASC
                LIMIT ?
                """,
                (account_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def missing_author_usernames(self, account_id: int, limit: int = 50) -> list[str]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT author_username, COUNT(*) AS uses
                   FROM tweets
                   WHERE account_id = ? AND author_avatar_path IS NULL
                     AND author_username <> ''
                   GROUP BY lower(author_username)
                   ORDER BY uses DESC, lower(author_username)
                   LIMIT ?""",
                (account_id, max(1, min(100, int(limit)))),
            ).fetchall()
        return [str(row["author_username"]) for row in rows]

    def update_author_avatar(
        self, account_id: int, username: str, source_url: str, local_path: str
    ) -> None:
        with self.connection() as db:
            db.execute(
                """UPDATE tweets SET author_avatar_url = ?, author_avatar_path = ?
                   WHERE account_id = ? AND lower(author_username) = lower(?)""",
                (source_url, local_path, account_id, username),
            )
            db.commit()

    def media_downloaded(
        self,
        media_id: int,
        local_path: str,
        preview_local_path: str | None,
        mime_type: str | None,
    ) -> None:
        with self.connection() as db:
            db.execute(
                """UPDATE media SET local_path = ?, preview_local_path = ?, mime_type = ?,
                   download_error = NULL WHERE id = ?""",
                (local_path, preview_local_path, mime_type, media_id),
            )
            db.commit()

    def media_failed(self, media_id: int, error: str) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE media SET download_error = ? WHERE id = ?",
                ((error or "下载失败")[:500], media_id),
            )
            db.commit()

    def list_tweets(
        self,
        account_id: int,
        *,
        limit: int = 30,
        cursor: str | None = None,
        query: str = "",
        kind: str = "all",
        year: int | str | None = None,
        month: int | str | None = None,
    ) -> dict[str, Any]:
        limit = min(100, max(1, int(limit)))
        clauses = ["t.account_id = ?"]
        params: list[Any] = [account_id]
        if query.strip():
            clauses.append("t.text LIKE ? ESCAPE '\\'")
            escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        if kind == "replies":
            clauses.append("t.is_reply = 1")
        elif kind == "reposts":
            clauses.append("t.is_repost = 1")
        elif kind == "media":
            clauses.append("EXISTS (SELECT 1 FROM media em WHERE em.tweet_id = t.id)")
        elif kind == "originals":
            clauses.append("t.is_reply = 0 AND t.is_repost = 0")
        if year not in (None, ""):
            year_value = int(year)
            if not 2006 <= year_value <= 2100:
                raise ValueError("年份筛选无效")
            if month not in (None, ""):
                month_value = int(month)
                if not 1 <= month_value <= 12:
                    raise ValueError("月份筛选无效")
                start = f"{year_value:04d}-{month_value:02d}-01T00:00:00Z"
                if month_value == 12:
                    end = f"{year_value + 1:04d}-01-01T00:00:00Z"
                else:
                    end = f"{year_value:04d}-{month_value + 1:02d}-01T00:00:00Z"
            else:
                start = f"{year_value:04d}-01-01T00:00:00Z"
                end = f"{year_value + 1:04d}-01-01T00:00:00Z"
            clauses.append("t.created_at >= ? AND t.created_at < ?")
            params.extend([start, end])
        elif month not in (None, ""):
            raise ValueError("请选择年份后再筛选月份")
        decoded = self._decode_cursor(cursor)
        if decoded:
            clauses.append("(t.created_at < ? OR (t.created_at = ? AND t.id < ?))")
            params.extend([decoded[0], decoded[0], decoded[1]])
        params.append(limit + 1)
        with self.connection() as db:
            rows = db.execute(
                f"""SELECT t.*,
                           CASE
                             WHEN t.author_avatar_path IS NOT NULL THEN t.author_avatar_path
                             WHEN lower(t.author_username) = lower(a.username) THEN a.avatar_path
                             ELSE NULL
                           END AS resolved_author_avatar_path
                    FROM tweets t
                    JOIN accounts a ON a.id = t.account_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY t.created_at DESC, t.id DESC LIMIT ?""",
                params,
            ).fetchall()
            page = rows[:limit]
            tweet_rows = {str(row["id"]): row for row in page}
            missing_parent_ids = sorted(
                {
                    str(row["reply_to_id"])
                    for row in page
                    if row["reply_to_id"]
                    and str(row["reply_to_id"]) not in tweet_rows
                }
            )
            if missing_parent_ids:
                parent_placeholders = ",".join("?" for _ in missing_parent_ids)
                parent_rows = db.execute(
                    f"""SELECT t.*,
                               CASE
                                 WHEN t.author_avatar_path IS NOT NULL THEN t.author_avatar_path
                                 WHEN lower(t.author_username) = lower(a.username) THEN a.avatar_path
                                 ELSE NULL
                               END AS resolved_author_avatar_path
                        FROM tweets t
                        JOIN accounts a ON a.id = t.account_id
                        WHERE t.account_id = ? AND t.id IN ({parent_placeholders})""",
                    [account_id, *missing_parent_ids],
                ).fetchall()
                tweet_rows.update({str(row["id"]): row for row in parent_rows})
            ids = list(tweet_rows)
            media_map: dict[str, list[dict[str, Any]]] = {
                tweet_id: [] for tweet_id in ids
            }
            if ids:
                placeholders = ",".join("?" for _ in ids)
                media_rows = db.execute(
                    f"SELECT * FROM media WHERE tweet_id IN ({placeholders}) ORDER BY id", ids
                ).fetchall()
                for media in media_rows:
                    media_map[media["tweet_id"]].append(self._media_public(dict(media)))
        items = []
        for row in page:
            item = self._tweet_public(dict(row), media_map[str(row["id"])])
            parent_id = str(row["reply_to_id"] or "")
            parent = tweet_rows.get(parent_id)
            item["repliedTo"] = (
                self._tweet_public(dict(parent), media_map[parent_id])
                if parent is not None and parent_id != str(row["id"])
                else None
            )
            items.append(item)
        next_cursor = None
        if len(rows) > limit and page:
            last = page[-1]
            next_cursor = self._encode_cursor(last["created_at"], last["id"])
        return {"items": items, "nextCursor": next_cursor}

    def list_tweet_months(self, account_id: int) -> list[dict[str, int]]:
        self.get_account(account_id)
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT CAST(substr(created_at, 1, 4) AS INTEGER) AS year,
                       CAST(substr(created_at, 6, 2) AS INTEGER) AS month,
                       COUNT(*) AS count
                FROM tweets
                WHERE account_id = ?
                  AND created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-*'
                GROUP BY substr(created_at, 1, 7)
                ORDER BY substr(created_at, 1, 7) DESC
                """,
                (account_id,),
            ).fetchall()
        return [
            {"year": int(row["year"]), "month": int(row["month"]), "count": int(row["count"])}
            for row in rows
        ]

    def file_owner_accounts(self, relative_path: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT id, is_public FROM accounts
                WHERE avatar_path = ? OR banner_path = ?
                UNION
                SELECT a.id, a.is_public FROM media m
                JOIN tweets t ON t.id = m.tweet_id
                JOIN accounts a ON a.id = t.account_id
                WHERE m.local_path = ? OR m.preview_local_path = ?
                UNION
                SELECT a.id, a.is_public FROM tweets t
                JOIN accounts a ON a.id = t.account_id
                WHERE t.author_avatar_path = ?
                """,
                (relative_path, relative_path, relative_path, relative_path, relative_path),
            ).fetchall()
        return [dict(row) for row in rows]

    def file_is_public(self, relative_path: str) -> bool | None:
        owners = self.file_owner_accounts(relative_path)
        return any(bool(item["is_public"]) for item in owners) if owners else None

    def member_can_access(self, member_id: int, account_id: int) -> bool:
        with self.connection() as db:
            row = db.execute(
                """SELECT 1 FROM member_account_access maa
                   JOIN members m ON m.id = maa.member_id
                   WHERE maa.member_id = ? AND maa.account_id = ? AND m.active = 1""",
                (member_id, account_id),
            ).fetchone()
        return row is not None

    def member_accessible_account_ids(self, member_id: int) -> list[int]:
        """Return every account a member may read, including public accounts."""

        with self.connection() as db:
            rows = db.execute(
                """SELECT a.id FROM accounts a
                   WHERE a.is_public = 1 OR EXISTS (
                       SELECT 1 FROM member_account_access maa
                       JOIN members m ON m.id = maa.member_id
                       WHERE maa.member_id = ? AND maa.account_id = a.id AND m.active = 1
                   )
                   ORDER BY lower(a.username)""",
                (member_id,),
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def get_member_notification_settings(self, member_id: int) -> dict[str, Any]:
        member = self.get_member(member_id)
        accessible = set(self.member_accessible_account_ids(member_id))
        with self.connection() as db:
            rows = db.execute(
                """SELECT account_id FROM member_notification_accounts
                   WHERE member_id = ? ORDER BY account_id""",
                (member_id,),
            ).fetchall()
        return {
            "enabled": bool(member.get("bark_enabled")),
            "server_url": str(member.get("bark_server_url") or "https://api.day.app"),
            "device_key": str(member.get("bark_device_key") or ""),
            "group": str(member.get("bark_group") or "Incandescence"),
            "account_ids": [
                int(row["account_id"])
                for row in rows
                if int(row["account_id"]) in accessible
            ],
        }

    def update_member_notification_settings(
        self,
        member_id: int,
        *,
        enabled: bool,
        server_url: str,
        device_key: str | None,
        group: str,
        account_ids: list[int],
    ) -> dict[str, Any]:
        unique_ids = sorted({int(value) for value in account_ids})
        accessible = set(self.member_accessible_account_ids(member_id))
        if any(account_id not in accessible for account_id in unique_ids):
            raise ValueError("通知账号中包含当前会员无权访问的账号")
        with self.connection() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                changed = db.execute(
                    """UPDATE members SET bark_enabled = ?, bark_server_url = ?,
                           bark_device_key = COALESCE(?, bark_device_key), bark_group = ?,
                           updated_at = ? WHERE id = ?""",
                    (int(enabled), server_url, device_key, group, utc_now(), member_id),
                ).rowcount
                if not changed:
                    raise KeyError("会员不存在")
                db.execute(
                    "DELETE FROM member_notification_accounts WHERE member_id = ?",
                    (member_id,),
                )
                for account_id in unique_ids:
                    db.execute(
                        """INSERT INTO member_notification_accounts(
                               member_id, account_id, created_at
                           ) VALUES (?, ?, ?)""",
                        (member_id, account_id, utc_now()),
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return self.get_member_notification_settings(member_id)

    def list_member_notification_targets(self, account_id: int) -> list[dict[str, Any]]:
        """Return enabled Bark destinations that remain authorized for an account."""

        with self.connection() as db:
            rows = db.execute(
                """SELECT m.id AS member_id, m.username, m.bark_server_url,
                          m.bark_device_key, m.bark_group
                   FROM member_notification_accounts mna
                   JOIN members m ON m.id = mna.member_id
                   JOIN accounts a ON a.id = mna.account_id
                   WHERE mna.account_id = ? AND m.active = 1 AND m.bark_enabled = 1
                     AND m.bark_device_key <> ''
                     AND (a.is_public = 1 OR EXISTS (
                         SELECT 1 FROM member_account_access maa
                         WHERE maa.member_id = m.id AND maa.account_id = a.id
                     ))
                   ORDER BY lower(m.username)""",
                (account_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_member(
        self, username: str, password_salt: str, password_digest: str, rounds: int
    ) -> dict[str, Any]:
        now = utc_now()
        try:
            with self.connection() as db:
                cursor = db.execute(
                    """INSERT INTO members(
                           username, password_salt, password_digest, password_rounds,
                           active, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, 1, ?, ?)""",
                    (username, password_salt, password_digest, rounds, now, now),
                )
                db.commit()
                return self.get_member(int(cursor.lastrowid))
        except sqlite3.IntegrityError as error:
            raise ValueError(f"会员 {username} 已存在") from error

    def get_member(self, member_id: int) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
        if not row:
            raise KeyError("会员不存在")
        return dict(row)

    def get_member_by_username(self, username: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM members WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
        return dict(row) if row else None

    def list_members(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT m.*, COUNT(maa.account_id) AS account_count
                   FROM members m
                   LEFT JOIN member_account_access maa ON maa.member_id = m.id
                   GROUP BY m.id ORDER BY lower(m.username)"""
            ).fetchall()
            access_rows = db.execute(
                "SELECT member_id, account_id FROM member_account_access ORDER BY account_id"
            ).fetchall()
        access: dict[int, list[int]] = {}
        for row in access_rows:
            access.setdefault(int(row["member_id"]), []).append(int(row["account_id"]))
        result = []
        for row in rows:
            item = dict(row)
            item["account_ids"] = access.get(int(row["id"]), [])
            result.append(item)
        return result

    def update_member(
        self,
        member_id: int,
        *,
        active: bool,
        account_ids: list[int],
        password_salt: str | None = None,
        password_digest: str | None = None,
        password_rounds: int | None = None,
    ) -> dict[str, Any]:
        unique_ids = sorted({int(value) for value in account_ids})
        with self.connection() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                changed = db.execute(
                    """UPDATE members SET active = ?,
                           password_salt = COALESCE(?, password_salt),
                           password_digest = COALESCE(?, password_digest),
                           password_rounds = COALESCE(?, password_rounds),
                           updated_at = ? WHERE id = ?""",
                    (
                        int(active), password_salt, password_digest, password_rounds,
                        utc_now(), member_id,
                    ),
                ).rowcount
                if not changed:
                    raise KeyError("会员不存在")
                db.execute("DELETE FROM member_account_access WHERE member_id = ?", (member_id,))
                for account_id in unique_ids:
                    db.execute(
                        """INSERT INTO member_account_access(member_id, account_id, created_at)
                           VALUES (?, ?, ?)""",
                        (member_id, account_id, utc_now()),
                    )
                db.execute(
                    """DELETE FROM member_notification_accounts
                       WHERE member_id = ? AND account_id IN (
                           SELECT a.id FROM accounts a
                           WHERE a.is_public = 0 AND NOT EXISTS (
                               SELECT 1 FROM member_account_access maa
                               WHERE maa.member_id = ? AND maa.account_id = a.id
                           )
                       )""",
                    (member_id, member_id),
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return self.get_member(member_id)

    def mark_member_login(self, member_id: int) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE members SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (utc_now(), utc_now(), member_id),
            )
            db.commit()

    def delete_member(self, member_id: int) -> None:
        with self.connection() as db:
            changed = db.execute("DELETE FROM members WHERE id = ?", (member_id,)).rowcount
            db.commit()
        if not changed:
            raise KeyError("会员不存在")

    def delete_account(self, account_id: int) -> dict[str, Any]:
        account = self.get_account(account_id)
        with self.connection() as db:
            db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            db.commit()
        return account

    @staticmethod
    def _encode_cursor(created_at: str, tweet_id: str) -> str:
        payload = json.dumps([created_at, tweet_id], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
        if not cursor:
            return None
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded).decode())
            if isinstance(value, list) and len(value) == 2:
                return str(value[0]), str(value[1])
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        raise ValueError("分页游标无效")

    @staticmethod
    def _media_public(media: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": media["type"],
            "url": _file_url(media.get("local_path")),
            "previewUrl": _file_url(media.get("preview_local_path")),
            "width": media.get("width"),
            "height": media.get("height"),
            "durationMs": media.get("duration_ms"),
            "alt": media.get("alt_text") or "",
            "downloadError": media.get("download_error"),
        }

    @staticmethod
    def _tweet_public(tweet: dict[str, Any], media: list[dict[str, Any]]) -> dict[str, Any]:
        def parse_json(value: str | None, default: Any) -> Any:
            try:
                return json.loads(value) if value else default
            except json.JSONDecodeError:
                return default

        return {
            "id": tweet["id"],
            "authorUsername": tweet["author_username"],
            "authorName": tweet["author_name"],
            "authorAvatarUrl": _file_url(tweet.get("resolved_author_avatar_path")),
            "text": tweet["text"],
            "createdAt": tweet["created_at"],
            "replyToId": tweet.get("reply_to_id"),
            "replyToUsername": tweet.get("reply_to_username") or _leading_mention(tweet.get("text")),
            "isReply": bool(tweet["is_reply"]),
            "isRepost": bool(tweet["is_repost"]),
            "isQuote": bool(tweet["is_quote"]),
            "possiblySensitive": bool(tweet["possibly_sensitive"]),
            "metrics": parse_json(tweet.get("metrics_json"), {}),
            "links": parse_json(tweet.get("links_json"), []),
            "quoted": parse_json(tweet.get("quoted_json"), None),
            "sourceUrl": tweet["source_url"],
            "media": media,
        }


def _file_url(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    from urllib.parse import quote

    return "/files/" + "/".join(quote(part) for part in relative_path.replace("\\", "/").split("/"))


def _leading_mention(text: str | None) -> str | None:
    match = re.match(r"^@([A-Za-z0-9_]{1,15})(?:\s|$)", str(text or ""))
    return match.group(1) if match else None
