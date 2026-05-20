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
    _remove_legacy_route_schema(connection)
    for statement in SCHEMA_SQL:
        connection.execute(statement)
    _remove_legacy_route_schema(connection)
    connection.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _remove_legacy_route_schema(connection: sqlite3.Connection) -> None:
    foreign_keys_enabled = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    connection.execute("PRAGMA foreign_keys = OFF")
    for table_name in ("review_fields", "reviews", "field_routes"):
        connection.execute(f"DROP TABLE IF EXISTS {table_name}")
    for index_name in ("idx_review_fields_task_id", "idx_reviews_task_id", "idx_field_routes_task_id"):
        connection.execute(f"DROP INDEX IF EXISTS {index_name}")
    _drop_columns_if_present(connection, "tasks", ("route", "route_reason"))
    _drop_columns_if_present(
        connection,
        "field_commits",
        ("route", "reviewed", "review_decision", "review_value_json"),
    )
    connection.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys_enabled else 'OFF'}")


def _drop_columns_if_present(
    connection: sqlite3.Connection,
    table_name: str,
    column_names: tuple[str, ...],
) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if not existing_columns:
        return
    for column_name in column_names:
        if column_name not in existing_columns:
            continue
        connection.execute(f"ALTER TABLE {table_name} DROP COLUMN {column_name}")
        existing_columns.remove(column_name)
