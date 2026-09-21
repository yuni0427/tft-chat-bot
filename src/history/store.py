"""Persistent conversation history for Streamlit sessions."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config


def _remote_store():
    if config.HISTORY_BACKEND != "supabase":
        return None
    from src.history import supabase_store

    return supabase_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    path = Path(config.HISTORY_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db() -> None:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.init_db()
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                title TEXT NOT NULL,
                context_turns INTEGER NOT NULL DEFAULT 0,
                context_epoch INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conversations_owner_updated
                ON conversations(owner_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                context_epoch INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id, id);
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "deleted_at" not in columns:
            connection.execute("ALTER TABLE conversations ADD COLUMN deleted_at TEXT")


def create_conversation(owner_id: str, title: str = "新しい相談") -> str:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.create_conversation(owner_id, title)
    conversation_id = str(uuid.uuid4())
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO conversations
                (id, owner_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, owner_id, title, now, now),
        )
    return conversation_id


def list_conversations(owner_id: str) -> list[dict]:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.list_conversations(owner_id)
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, title, context_turns, context_epoch, updated_at
            FROM conversations
            WHERE owner_id = ? AND deleted_at IS NULL
            ORDER BY updated_at DESC
            """,
            (owner_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_conversation(conversation_id: str, owner_id: str) -> dict | None:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.get_conversation(conversation_id, owner_id)
    with _connect() as connection:
        row = connection.execute(
                        "SELECT * FROM conversations WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
                        (conversation_id, owner_id),
        ).fetchone()
    return dict(row) if row else None


def load_messages(conversation_id: str, owner_id: str) -> list[dict]:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.load_messages(conversation_id, owner_id)
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT m.role, m.content, m.created_at, m.context_epoch
            FROM messages AS m
            JOIN conversations AS c ON c.id = m.conversation_id
            WHERE m.conversation_id = ? AND c.owner_id = ?
            ORDER BY m.id
            """,
            (conversation_id, owner_id),
        ).fetchall()
    return [dict(row) for row in rows]


def append_message(conversation_id: str, owner_id: str, role: str, content: str) -> None:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.append_message(conversation_id, owner_id, role, content)
    now = _now()
    with _connect() as connection:
        conversation = connection.execute(
            """
            SELECT context_turns, context_epoch
            FROM conversations
            WHERE id = ? AND owner_id = ?
            """,
            (conversation_id, owner_id),
        ).fetchone()
        if conversation is None:
            raise ValueError("会話が見つからないか、アクセス権がありません")

        connection.execute(
            """
            INSERT INTO messages
                (conversation_id, role, content, created_at, context_epoch)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, now, conversation["context_epoch"]),
        )
        turn_increment = 1 if role == "user" else 0
        connection.execute(
            """
            UPDATE conversations
            SET context_turns = context_turns + ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
            """,
            (turn_increment, now, conversation_id, owner_id),
        )


def reset_context(conversation_id: str, owner_id: str) -> None:
    """Start a new LLM context generation while retaining all stored messages."""
    remote_store = _remote_store()
    if remote_store:
        return remote_store.reset_context(conversation_id, owner_id)
    with _connect() as connection:
        connection.execute(
            """
            UPDATE conversations
            SET context_turns = 0, context_epoch = context_epoch + 1, updated_at = ?
            WHERE id = ? AND owner_id = ?
            """,
            (_now(), conversation_id, owner_id),
        )


def rename_conversation(conversation_id: str, owner_id: str, title: str) -> None:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.rename_conversation(conversation_id, owner_id, title)
    with _connect() as connection:
        connection.execute(
            """
            UPDATE conversations SET title = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
            """,
            (title.strip() or "無題の相談", _now(), conversation_id, owner_id),
        )


def delete_conversation(conversation_id: str, owner_id: str) -> None:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.delete_conversation(conversation_id, owner_id)
    with _connect() as connection:
        connection.execute(
            """
            UPDATE conversations
            SET deleted_at = ?, updated_at = ?
            WHERE id = ? AND owner_id = ? AND deleted_at IS NULL
            """,
            (_now(), _now(), conversation_id, owner_id),
        )


def admin_list_conversations() -> list[dict]:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.admin_list_conversations()
    with _connect() as connection:
        rows = connection.execute(
            """
                 SELECT id, owner_id, title, context_turns, context_epoch,
                     created_at, updated_at, deleted_at
                 FROM conversations
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def admin_load_messages(conversation_id: str) -> list[dict]:
    remote_store = _remote_store()
    if remote_store:
        return remote_store.admin_load_messages(conversation_id)
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT role, content, created_at, context_epoch
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id
            """,
            (conversation_id,),
        ).fetchall()
    return [dict(row) for row in rows]
