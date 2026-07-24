from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any

logger = logging.getLogger(__name__)

CREATE_TABLES_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS skills (
    name TEXT PRIMARY KEY NOT NULL CHECK (trim(name) <> ''),
    description TEXT NOT NULL,
    version TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    config TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS channels (
    name TEXT PRIMARY KEY NOT NULL CHECK (trim(name) <> ''),
    type TEXT NOT NULL CHECK (trim(type) <> ''),
    webhook_url TEXT NOT NULL CHECK (trim(webhook_url) <> ''),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY NOT NULL CHECK (trim(id) <> ''),
    prompt TEXT NOT NULL CHECK (trim(prompt) <> ''),
    size TEXT NOT NULL CHECK (trim(size) <> ''),
    style TEXT NOT NULL CHECK (trim(style) <> ''),
    format TEXT NOT NULL CHECK (trim(format) <> ''),
    created_at TEXT NOT NULL
);
"""

_UNSET = object()


class StorageError(Exception):
    """Base exception for SQLite storage errors."""


class DuplicateRecordError(StorageError):
    """Raised when attempting to create a duplicate record."""


class RecordNotFoundError(StorageError):
    """Raised when a record cannot be found."""


class SQLiteConnectionPool:
    """Very small connection pool for SQLite connections."""

    def __init__(self, db_path: str | Path, pool_size: int = 5) -> None:
        if pool_size < 1:
            raise ValueError("pool_size must be at least 1")

        self.db_path = str(db_path)
        self.pool_size = pool_size
        self._connections: Queue[sqlite3.Connection] = Queue(maxsize=pool_size)
        self._closed = False
        self._target, self._use_uri = self._resolve_target(self.db_path)

    @staticmethod
    def _resolve_target(db_path: str) -> tuple[str, bool]:
        if db_path == ":memory:":
            return "file::memory:?cache=shared", True
        if db_path.startswith("file:"):
            return db_path, True
        return db_path, False

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._target,
            check_same_thread=False,
            timeout=30.0,
            uri=self._use_uri,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _acquire(self) -> sqlite3.Connection:
        if self._closed:
            raise StorageError("Connection pool is closed")

        try:
            return self._connections.get_nowait()
        except Empty:
            return self._create_connection()

    def _release(self, conn: sqlite3.Connection) -> None:
        if self._closed:
            conn.close()
            return

        try:
            self._connections.put_nowait(conn)
        except Exception:
            conn.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._acquire()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._release(conn)

    def close(self) -> None:
        self._closed = True
        while True:
            try:
                conn = self._connections.get_nowait()
            except Empty:
                break
            conn.close()


class SQLiteStorage:
    """Persistent storage for skills, channels, and generated images."""

    def __init__(self, db_path: str | Path, pool_size: int = 5, *, initialize: bool = True) -> None:
        self.pool = SQLiteConnectionPool(db_path, pool_size=pool_size)
        if initialize:
            self.initialize()

    def __enter__(self) -> "SQLiteStorage":
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self.pool.connection() as conn:
            yield conn

    def initialize(self) -> None:
        try:
            with self.connection() as conn:
                conn.executescript(CREATE_TABLES_SQL)
        except sqlite3.Error as exc:
            logger.exception("Failed to initialize SQLite storage")
            raise StorageError("Failed to initialize SQLite storage") from exc

    # ------------------------------------------------------------------
    # Skills CRUD
    # ------------------------------------------------------------------
    def create_skill(
        self,
        name: str,
        description: str,
        version: str,
        enabled: bool = True,
        config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "name": name,
            "description": description,
            "version": version,
            "enabled": enabled,
            "config": dict(config or {}),
        }
        self._validate_skill_record(record)

        payload = (
            record["name"],
            record["description"],
            record["version"],
            int(record["enabled"]),
            json.dumps(record["config"], sort_keys=True),
        )
        try:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO skills (name, description, version, enabled, config)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    payload,
                )
        except sqlite3.IntegrityError as exc:
            self._raise_integrity_error("skill", name, exc)

        created = self.get_skill(name)
        if created is None:
            raise StorageError(f"Failed to create skill: {name}")
        return created

    def get_skill(self, name: str) -> dict[str, Any] | None:
        row = self._fetch_one("SELECT * FROM skills WHERE name = ?", (name,))
        return self._skill_from_row(row) if row else None

    def list_skills(self) -> list[dict[str, Any]]:
        return self._fetch_all("SELECT * FROM skills ORDER BY name", table="skill")

    def update_skill(
        self,
        name: str,
        *,
        description: str | object = _UNSET,
        version: str | object = _UNSET,
        enabled: bool | object = _UNSET,
        config: Mapping[str, Any] | None | object = _UNSET,
    ) -> dict[str, Any] | None:
        updates: list[str] = []
        params: list[Any] = []

        if description is not _UNSET:
            self._validate_text(description, "skill description")
            updates.append("description = ?")
            params.append(description)
        if version is not _UNSET:
            self._validate_text(version, "skill version")
            updates.append("version = ?")
            params.append(version)
        if enabled is not _UNSET:
            if not isinstance(enabled, bool):
                raise ValueError("skill enabled must be a boolean")
            updates.append("enabled = ?")
            params.append(int(enabled))
        if config is not _UNSET:
            normalized_config = dict(config or {})
            updates.append("config = ?")
            params.append(json.dumps(normalized_config, sort_keys=True))

        if not updates:
            return self.get_skill(name)

        params.append(name)
        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE skills SET {', '.join(updates)} WHERE name = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
        return self.get_skill(name)

    def delete_skill(self, name: str) -> bool:
        return self._delete_one("skills", name)

    # ------------------------------------------------------------------
    # Channels CRUD
    # ------------------------------------------------------------------
    def create_channel(
        self,
        name: str,
        type: str,
        webhook_url: str,
        enabled: bool = True,
    ) -> dict[str, Any]:
        record = {
            "name": name,
            "type": type,
            "webhook_url": webhook_url,
            "enabled": enabled,
        }
        self._validate_channel_record(record)

        payload = (
            record["name"],
            record["type"],
            record["webhook_url"],
            int(record["enabled"]),
        )
        try:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO channels (name, type, webhook_url, enabled)
                    VALUES (?, ?, ?, ?)
                    """,
                    payload,
                )
        except sqlite3.IntegrityError as exc:
            self._raise_integrity_error("channel", name, exc)

        created = self.get_channel(name)
        if created is None:
            raise StorageError(f"Failed to create channel: {name}")
        return created

    def get_channel(self, name: str) -> dict[str, Any] | None:
        row = self._fetch_one("SELECT * FROM channels WHERE name = ?", (name,))
        return self._channel_from_row(row) if row else None

    def list_channels(self) -> list[dict[str, Any]]:
        return self._fetch_all("SELECT * FROM channels ORDER BY name", table="channel")

    def update_channel(
        self,
        name: str,
        *,
        type: str | object = _UNSET,
        webhook_url: str | object = _UNSET,
        enabled: bool | object = _UNSET,
    ) -> dict[str, Any] | None:
        updates: list[str] = []
        params: list[Any] = []

        if type is not _UNSET:
            self._validate_text(type, "channel type")
            updates.append("type = ?")
            params.append(type)
        if webhook_url is not _UNSET:
            self._validate_text(webhook_url, "channel webhook_url")
            updates.append("webhook_url = ?")
            params.append(webhook_url)
        if enabled is not _UNSET:
            if not isinstance(enabled, bool):
                raise ValueError("channel enabled must be a boolean")
            updates.append("enabled = ?")
            params.append(int(enabled))

        if not updates:
            return self.get_channel(name)

        params.append(name)
        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE channels SET {', '.join(updates)} WHERE name = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
        return self.get_channel(name)

    def delete_channel(self, name: str) -> bool:
        return self._delete_one("channels", name)

    # ------------------------------------------------------------------
    # Images CRUD
    # ------------------------------------------------------------------
    def create_image(
        self,
        prompt: str,
        size: str,
        style: str,
        format: str,
        image_id: str | None = None,
        created_at: str | datetime | None = None,
    ) -> dict[str, Any]:
        record_id = image_id or uuid.uuid4().hex
        created_at_value = self._normalize_timestamp(created_at)
        record = {
            "id": record_id,
            "prompt": prompt,
            "size": size,
            "style": style,
            "format": format,
            "created_at": created_at_value,
        }
        self._validate_image_record(record)

        payload = (
            record["id"],
            record["prompt"],
            record["size"],
            record["style"],
            record["format"],
            record["created_at"],
        )
        try:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO images (id, prompt, size, style, format, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
        except sqlite3.IntegrityError as exc:
            self._raise_integrity_error("image", record_id, exc)

        created = self.get_image(record_id)
        if created is None:
            raise StorageError(f"Failed to create image: {record_id}")
        return created

    def get_image(self, image_id: str) -> dict[str, Any] | None:
        row = self._fetch_one("SELECT * FROM images WHERE id = ?", (image_id,))
        return self._image_from_row(row) if row else None

    def list_images(self) -> list[dict[str, Any]]:
        return self._fetch_all("SELECT * FROM images ORDER BY created_at, id", table="image")

    def update_image(
        self,
        image_id: str,
        *,
        prompt: str | object = _UNSET,
        size: str | object = _UNSET,
        style: str | object = _UNSET,
        format: str | object = _UNSET,
    ) -> dict[str, Any] | None:
        updates: list[str] = []
        params: list[Any] = []

        if prompt is not _UNSET:
            self._validate_text(prompt, "image prompt")
            updates.append("prompt = ?")
            params.append(prompt)
        if size is not _UNSET:
            self._validate_text(size, "image size")
            updates.append("size = ?")
            params.append(size)
        if style is not _UNSET:
            self._validate_text(style, "image style")
            updates.append("style = ?")
            params.append(style)
        if format is not _UNSET:
            self._validate_text(format, "image format")
            updates.append("format = ?")
            params.append(format)

        if not updates:
            return self.get_image(image_id)

        params.append(image_id)
        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE images SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
        return self.get_image(image_id)

    def delete_image(self, image_id: str) -> bool:
        return self._delete_one("images", image_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _fetch_one(self, query: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
        try:
            with self.connection() as conn:
                cursor = conn.execute(query, params)
                return cursor.fetchone()
        except sqlite3.Error as exc:
            logger.exception("SQLite query failed")
            raise StorageError("SQLite query failed") from exc

    def _fetch_all(self, query: str, *, table: str) -> list[dict[str, Any]]:
        try:
            with self.connection() as conn:
                cursor = conn.execute(query)
                rows = cursor.fetchall()
        except sqlite3.Error as exc:
            logger.exception("SQLite query failed")
            raise StorageError("SQLite query failed") from exc

        if table == "skill":
            return [self._skill_from_row(row) for row in rows]
        if table == "channel":
            return [self._channel_from_row(row) for row in rows]
        if table == "image":
            return [self._image_from_row(row) for row in rows]
        raise ValueError(f"Unsupported table type: {table}")

    def _delete_one(self, table: str, key: str) -> bool:
        column = "name" if table in {"skills", "channels"} else "id"
        try:
            with self.connection() as conn:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE {column} = ?",
                    (key,),
                )
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            logger.exception("SQLite delete failed")
            raise StorageError("SQLite delete failed") from exc

    @staticmethod
    def _validate_text(value: Any, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

    def _validate_skill_record(self, record: Mapping[str, Any]) -> None:
        self._validate_text(record["name"], "skill name")
        self._validate_text(record["description"], "skill description")
        self._validate_text(record["version"], "skill version")
        if not isinstance(record["enabled"], bool):
            raise ValueError("skill enabled must be a boolean")
        if not isinstance(record["config"], dict):
            raise ValueError("skill config must be a mapping")

    def _validate_channel_record(self, record: Mapping[str, Any]) -> None:
        self._validate_text(record["name"], "channel name")
        self._validate_text(record["type"], "channel type")
        self._validate_text(record["webhook_url"], "channel webhook_url")
        if not isinstance(record["enabled"], bool):
            raise ValueError("channel enabled must be a boolean")

    def _validate_image_record(self, record: Mapping[str, Any]) -> None:
        self._validate_text(record["id"], "image id")
        self._validate_text(record["prompt"], "image prompt")
        self._validate_text(record["size"], "image size")
        self._validate_text(record["style"], "image style")
        self._validate_text(record["format"], "image format")
        self._validate_text(record["created_at"], "image created_at")

    @staticmethod
    def _normalize_timestamp(value: str | datetime | None) -> str:
        if value is None:
            return datetime.now(timezone.utc).isoformat(timespec="seconds")
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat(timespec="seconds")
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError("created_at must be a non-empty string or datetime")

    @staticmethod
    def _raise_integrity_error(entity: str, identifier: str, exc: sqlite3.IntegrityError) -> None:
        message = str(exc).lower()
        if "unique" in message or "primary key" in message:
            raise DuplicateRecordError(f"{entity.capitalize()} already exists: {identifier}") from exc
        raise StorageError(f"Failed to save {entity}: {identifier}") from exc

    @staticmethod
    def _skill_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "name": row["name"],
            "description": row["description"],
            "version": row["version"],
            "enabled": bool(row["enabled"]),
            "config": json.loads(row["config"] or "{}"),
        }

    @staticmethod
    def _channel_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "name": row["name"],
            "type": row["type"],
            "webhook_url": row["webhook_url"],
            "enabled": bool(row["enabled"]),
        }

    @staticmethod
    def _image_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "prompt": row["prompt"],
            "size": row["size"],
            "style": row["style"],
            "format": row["format"],
            "created_at": row["created_at"],
        }
