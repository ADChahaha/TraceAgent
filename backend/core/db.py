from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from backend.models.schema import SCHEMA_SQL


def connect_database(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=30.0, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


class ThreadLocalDatabase:
    """为同一个 SQLite 文件给每个工作线程创建独立连接。"""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._closed = False

    def connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection
        with self._connections_lock:
            if self._closed:
                raise RuntimeError("database is closed")
            connection = connect_database(self.database_path)
            self._connections.append(connection)
            self._local.connection = connection
            return connection

    def close(self) -> None:
        with self._connections_lock:
            self._closed = True
            connections = list(self._connections)
            self._connections.clear()
        for connection in connections:
            connection.close()


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode = WAL")
    for statement in SCHEMA_SQL:
        connection.execute(statement)
    _ensure_column(connection, "chat_resources", "size_bytes", "INTEGER NOT NULL DEFAULT 0")
    connection.commit()


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """给存量库补列：CREATE TABLE IF NOT EXISTS 不会更新旧表结构。"""
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)
