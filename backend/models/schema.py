from __future__ import annotations


SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS qa_tasks (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        stage TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        active_turn_id TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_documents (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_type TEXT NOT NULL,
        content_type TEXT,
        upload_size_bytes INTEGER NOT NULL,
        upload_sha256 TEXT NOT NULL,
        html TEXT NOT NULL,
        display_html TEXT NOT NULL,
        markdown TEXT NOT NULL,
        md_list_json TEXT NOT NULL,
        blocks_json TEXT NOT NULL,
        processor_meta_json TEXT NOT NULL,
        warnings_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES qa_tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_messages (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        turn_id TEXT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES qa_tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_turns (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        status TEXT NOT NULL,
        agent_completion_id TEXT,
        user_message_id TEXT,
        error_message TEXT,
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
        status TEXT NOT NULL,
        stage TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES qa_tasks(id),
        UNIQUE(task_id, sequence)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_qa_documents_task_id ON qa_documents(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_qa_messages_task_id ON qa_messages(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_qa_turns_task_id ON qa_turns(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_qa_events_task_sequence ON qa_events(task_id, sequence)",
]
