from __future__ import annotations


SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS qa_tasks (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        active_turn_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_resources (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        type TEXT NOT NULL,
        location TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES qa_tasks(id),
        UNIQUE(task_id, type, location)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_turns (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY(task_id) REFERENCES qa_tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_events (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        turn_id TEXT,
        sequence INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES qa_tasks(id),
        UNIQUE(task_id, sequence)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_qa_resources_task_id ON qa_resources(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_qa_turns_task_id ON qa_turns(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_qa_events_task_sequence ON qa_events(task_id, sequence)",
]