"""CRUD 统一聚合出口，按会话、资源与轮次/消息分模块维护实现。"""

from __future__ import annotations

from backend.crud.resources import (
    create_resource,
    delete_resource,
    delete_resources,
    get_resource,
    list_resources,
)
from backend.crud.sessions import (
    create_session,
    get_session,
    list_sessions,
    list_sessions_needing_recovery,
    list_sessions_with_title_context,
    set_session_title_if_empty,
    transaction,
    update_session,
)
from backend.crud.turns import (
    create_message,
    create_turn,
    get_active_turn,
    get_next_message_sequence,
    get_turn,
    list_messages,
    list_turns,
    list_unfinished_turns,
    update_turn,
    update_turn_status_if_current,
)

__all__ = [
    "create_message",
    "create_resource",
    "create_session",
    "create_turn",
    "delete_resource",
    "delete_resources",
    "get_active_turn",
    "get_next_message_sequence",
    "get_resource",
    "get_session",
    "get_turn",
    "list_messages",
    "list_resources",
    "list_sessions",
    "list_sessions_needing_recovery",
    "list_sessions_with_title_context",
    "list_turns",
    "list_unfinished_turns",
    "set_session_title_if_empty",
    "transaction",
    "update_session",
    "update_turn",
    "update_turn_status_if_current",
]
