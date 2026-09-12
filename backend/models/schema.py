from __future__ import annotations


SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        active_turn_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_resources (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        type TEXT NOT NULL,
        location TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES chat_sessions(id),
        UNIQUE(session_id, type, location)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_turns (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        status TEXT NOT NULL,
        agent_completion_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY(session_id) REFERENCES chat_sessions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_events (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_id TEXT,
        sequence INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES chat_sessions(id),
        UNIQUE(session_id, sequence)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_resources_session_id ON chat_resources(session_id)",
    # 复合外键保证消息的 session_id 与 turn 所属 session 一致。
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_turns_session_id_id ON chat_turns(session_id, id)",
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_id TEXT,
        sequence INTEGER NOT NULL CHECK(sequence > 0),
        group_id TEXT NOT NULL CHECK(length(group_id) > 0),
        group_index INTEGER NOT NULL CHECK(group_index >= 0),
        role TEXT NOT NULL CHECK(role IN ('user', 'system', 'assistant', 'tool')),
        content TEXT NOT NULL,
        tool_calls_json TEXT NOT NULL DEFAULT '[]',
        tool_call_id TEXT,
        name TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES chat_sessions(id),
        FOREIGN KEY(session_id, turn_id) REFERENCES chat_turns(session_id, id),
        UNIQUE(session_id, sequence),
        UNIQUE(session_id, group_id, group_index),
        CHECK(turn_id IS NOT NULL OR role = 'system'),
        CHECK(
            (role = 'tool' AND tool_call_id IS NOT NULL AND length(tool_call_id) > 0
             AND name IS NOT NULL AND length(name) > 0)
            OR (role <> 'tool' AND tool_call_id IS NULL AND name IS NULL)
        ),
        CHECK(CASE WHEN json_valid(tool_calls_json)
            THEN json_type(tool_calls_json) = 'array'
                 AND (role = 'assistant' OR json_array_length(tool_calls_json) = 0)
            ELSE 0 END)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_group_tool_call
    ON chat_messages(session_id, group_id, tool_call_id) WHERE tool_call_id IS NOT NULL
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_turns_session_id ON chat_turns(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_chat_events_session_sequence ON chat_events(session_id, sequence)",
]
