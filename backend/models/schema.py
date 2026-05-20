from __future__ import annotations


SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        task_type TEXT NOT NULL,
        status TEXT NOT NULL,
        stage TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_type TEXT NOT NULL,
        content_type TEXT,
        upload_size_bytes INTEGER NOT NULL,
        upload_sha256 TEXT NOT NULL,
        markdown TEXT NOT NULL,
        md_list_json TEXT NOT NULL,
        blocks_json TEXT NOT NULL,
        processor_meta_json TEXT NOT NULL,
        warnings_json TEXT NOT NULL,
        processed_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        agent_status TEXT NOT NULL,
        failure_reason TEXT,
        request_json TEXT NOT NULL,
        result_json TEXT NOT NULL,
        trace_json TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_stage_runs (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        stage TEXT NOT NULL,
        agent_name TEXT NOT NULL,
        status TEXT NOT NULL,
        failure_reason TEXT,
        request_json TEXT NOT NULL,
        response_json TEXT NOT NULL,
        trace_json TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_events (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        status TEXT NOT NULL,
        stage TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES tasks(id),
        UNIQUE(task_id, sequence)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS extracted_fields (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        field_name TEXT NOT NULL,
        display_name TEXT NOT NULL,
        field_type TEXT NOT NULL,
        agent_status TEXT NOT NULL,
        agent_value_json TEXT,
        final_value_json TEXT,
        source TEXT NOT NULL,
        reason TEXT,
        failure_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS field_traces (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        field_name TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        related_fields_json TEXT NOT NULL,
        actions_json TEXT NOT NULL,
        trace_status TEXT NOT NULL,
        reason TEXT,
        failure_reason TEXT,
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS field_commits (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        field_name TEXT NOT NULL,
        final_value_json TEXT,
        agent_value_json TEXT,
        evidence_refs_json TEXT NOT NULL,
        used_global_lookup INTEGER NOT NULL,
        used_validation_rule INTEGER NOT NULL,
        related_fields_json TEXT NOT NULL,
        committed_by TEXT NOT NULL,
        committed_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_documents_task_id ON documents(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_task_id ON agent_runs(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_stage_runs_task_id ON agent_stage_runs(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_events_task_sequence ON task_events(task_id, sequence)",
    "CREATE INDEX IF NOT EXISTS idx_extracted_fields_task_id ON extracted_fields(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_field_traces_task_id ON field_traces(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_field_commits_task_id ON field_commits(task_id)",
]
