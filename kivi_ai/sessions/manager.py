"""Session lifecycle manager — provider switching, history, token tracking."""
from __future__ import annotations

import uuid
from typing import Any

from ..core.interfaces import BaseProvider
from ..core.registry import Registry
from ..core.types import Message, ProviderType, Role, SessionMeta, StreamChunk
from .store import SQLiteSessionStore


class SessionManager:
    """Manages session lifecycle, provider switching, and message history."""

    def __init__(self, store: SQLiteSessionStore | None = None):
        self._store = store or SQLiteSessionStore()

    @property
    def store(self) -> SQLiteSessionStore:
        return self._store

    # ── Session CRUD ─────────────────────────────────────────────────

    async def create_session(
        self,
        provider: str = "openai",
        model: str = "",
        title: str = "Untitled",
    ) -> str:
        session_id = uuid.uuid4().hex[:16]
        await self._store.create_session(session_id, title, provider, model)
        return session_id

    async def get_session(self, session_id: str) -> dict | None:
        return await self._store.get_session(session_id)

    async def list_sessions(self) -> list[dict]:
        return await self._store.list_sessions()

    async def delete_session(self, session_id: str) -> None:
        await self._store.delete_session(session_id)

    async def update_session(self, session_id: str, **fields: Any) -> None:
        await self._store.update_session(session_id, **fields)

    # ── Provider switching ───────────────────────────────────────────

    async def switch_provider(self, session_id: str, provider: str, model: str = "") -> None:
        """Switch a session to a different provider. Messages are preserved."""
        await self._store.update_session(session_id, provider=provider, model=model)

    # ── Message management ───────────────────────────────────────────

    async def add_message(self, session_id: str, message: Message) -> None:
        await self._store.add_message(session_id, message)

    async def get_messages(self, session_id: str) -> list[Message]:
        return await self._store.get_messages(session_id)

    async def get_context_token_count(self, session_id: str, provider: BaseProvider) -> int:
        """Count total tokens in the session's message history."""
        messages = await self._store.get_messages(session_id)
        session = await self._store.get_session(session_id)
        model = session.get("model", "") if session else ""
        total = 0
        for msg in messages:
            total += provider.count_tokens(msg.content, model)
            if msg.thinking:
                total += provider.count_tokens(msg.thinking, model)
        return total

    # ── Auto-title ───────────────────────────────────────────────────

    @staticmethod
    def generate_title(content: str) -> str:
        """Generate a short title from the first user message."""
        text = content.strip()[:100]
        # First line or first sentence
        for sep in ["\n", ". ", "? ", "! "]:
            if sep in text:
                text = text[:text.index(sep)]
                break
        return text[:60] if text else "Untitled"

    # ── Usage tracking ───────────────────────────────────────────────

    async def log_usage(
        self, session_id: str, model: str,
        input_tokens: int, output_tokens: int, cost_usd: float,
    ) -> None:
        await self._store.log_usage(session_id, model, input_tokens, output_tokens, cost_usd)
