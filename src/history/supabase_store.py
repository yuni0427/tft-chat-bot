"""Supabase REST adapter for conversation history.

The adapter is intentionally opt-in. Configure HISTORY_BACKEND=supabase and
provide SUPABASE_URL and SUPABASE_ANON_KEY after creating the SQL schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import requests

import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _headers() -> dict[str, str]:
    if not config.SUPABASE_URL or not config.SUPABASE_ANON_KEY:
        raise RuntimeError(
            "Supabaseを使うにはSUPABASE_URLとSUPABASE_ANON_KEYが必要です"
        )
    return {
        "apikey": config.SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {config.SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }


def _admin_headers() -> dict[str, str]:
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "管理画面にはSUPABASE_URLとSUPABASE_SERVICE_ROLE_KEYが必要です"
        )
    return {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _request(method: str, table: str, **kwargs: Any) -> Any:
    response = requests.request(
        method,
        f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/{table}",
        headers=_headers(),
        timeout=15,
        **kwargs,
    )
    if not response.ok:
        raise RuntimeError(f"Supabase {table} request failed: {response.status_code} {response.text}")
    if not response.content:
        return None
    return response.json()


def _admin_request(method: str, table: str, **kwargs: Any) -> Any:
    response = requests.request(
        method,
        f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/{table}",
        headers=_admin_headers(),
        timeout=15,
        **kwargs,
    )
    if not response.ok:
        raise RuntimeError(
            f"Supabase admin {table} request failed: {response.status_code} {response.text}"
        )
    if not response.content:
        return None
    return response.json()


def init_db() -> None:
    """The schema is managed in Supabase SQL Editor, so this is a no-op."""


def create_conversation(owner_id: str, title: str = "新しい相談") -> str:
    conversation_id = str(uuid.uuid4())
    now = _now()
    _request(
        "POST",
        "conversations",
        params={"select": "id"},
        json={
            "id": conversation_id,
            "owner_id": owner_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        },
    )
    return conversation_id


def list_conversations(owner_id: str) -> list[dict]:
    return _request(
        "GET",
        "conversations",
        params={
            "select": "id,title,context_turns,context_epoch,updated_at",
            "owner_id": f"eq.{owner_id}",
                "deleted_at": "is.null",
            "order": "updated_at.desc",
        },
    ) or []


def get_conversation(conversation_id: str, owner_id: str) -> dict | None:
    rows = _request(
        "GET",
        "conversations",
        params={
            "select": "*",
            "id": f"eq.{conversation_id}",
            "owner_id": f"eq.{owner_id}",
            "deleted_at": "is.null",
            "limit": "1",
        },
    ) or []
    return rows[0] if rows else None


def load_messages(conversation_id: str, owner_id: str) -> list[dict]:
    rows = _request(
        "GET",
        "messages",
        params={
            "select": "role,content,created_at,context_epoch",
            "conversation_id": f"eq.{conversation_id}",
            "owner_id": f"eq.{owner_id}",
            "order": "created_at.asc,id.asc",
        },
    ) or []
    return rows


def append_message(conversation_id: str, owner_id: str, role: str, content: str) -> None:
    conversation = get_conversation(conversation_id, owner_id)
    if conversation is None:
        raise ValueError("会話が見つからないか、アクセス権がありません")

    _request(
        "POST",
        "messages",
        json={
            "conversation_id": conversation_id,
            "owner_id": owner_id,
            "role": role,
            "content": content,
            "context_epoch": conversation.get("context_epoch", 0),
            "created_at": _now(),
        },
    )
    _request(
        "PATCH",
        "conversations",
        params={"id": f"eq.{conversation_id}", "owner_id": f"eq.{owner_id}"},
        json={
            "context_turns": conversation.get("context_turns", 0) + (1 if role == "user" else 0),
            "updated_at": _now(),
        },
    )


def reset_context(conversation_id: str, owner_id: str) -> None:
    conversation = get_conversation(conversation_id, owner_id)
    if conversation is None:
        raise ValueError("会話が見つからないか、アクセス権がありません")
    _request(
        "PATCH",
        "conversations",
        params={"id": f"eq.{conversation_id}", "owner_id": f"eq.{owner_id}"},
        json={
            "context_turns": 0,
            "context_epoch": conversation.get("context_epoch", 0) + 1,
            "updated_at": _now(),
        },
    )


def rename_conversation(conversation_id: str, owner_id: str, title: str) -> None:
    _request(
        "PATCH",
        "conversations",
        params={"id": f"eq.{conversation_id}", "owner_id": f"eq.{owner_id}"},
        json={"title": title.strip() or "無題の相談", "updated_at": _now()},
    )


def delete_conversation(conversation_id: str, owner_id: str) -> None:
    _request(
        "PATCH",
        "conversations",
        params={
            "id": f"eq.{conversation_id}",
            "owner_id": f"eq.{owner_id}",
            "deleted_at": "is.null",
        },
        json={"deleted_at": _now(), "updated_at": _now()},
    )


def admin_list_conversations() -> list[dict]:
    return _admin_request(
        "GET",
        "conversations",
        params={
            "select": "id,owner_id,title,context_turns,context_epoch,created_at,updated_at,deleted_at",
            "order": "updated_at.desc",
        },
    ) or []


def admin_load_messages(conversation_id: str) -> list[dict]:
    return _admin_request(
        "GET",
        "messages",
        params={
            "select": "role,content,created_at,context_epoch",
            "conversation_id": f"eq.{conversation_id}",
            "order": "created_at.asc,id.asc",
        },
    ) or []
