"""Abstract base classes for the unified framework."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from .types import Message, ModelInfo, StreamChunk, ToolCall, ToolResult, ToolSchema


class BaseProvider(ABC):
    """Abstract provider — every AI backend implements this."""

    name: str
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_thinking: bool = False

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        model: str,
        *,
        tools: list[ToolSchema] | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a response. Yields normalized StreamChunks."""
        ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return available models for this provider."""
        ...

    @abstractmethod
    def get_context_window(self, model: str) -> int:
        """Return context window size in tokens for a model."""
        ...

    @abstractmethod
    def count_tokens(self, text: str, model: str) -> int:
        """Count tokens in text for the given model."""
        ...

    async def initialize(self) -> None:
        """Optional startup hook (connect clients, etc.)."""

    async def shutdown(self) -> None:
        """Optional cleanup hook."""


class ToolInterface(ABC):
    """Abstract tool that can be invoked by any provider."""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """Tool name, description, and parameter schema."""
        ...

    @abstractmethod
    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        """Run the tool and return a result."""
        ...


class SessionStore(ABC):
    """Abstract session persistence layer."""

    @abstractmethod
    async def create_session(self, session_id: str, title: str, provider: str, model: str) -> None:
        ...

    @abstractmethod
    async def get_session(self, session_id: str) -> dict | None:
        ...

    @abstractmethod
    async def list_sessions(self) -> list[dict]:
        ...

    @abstractmethod
    async def update_session(self, session_id: str, **fields: Any) -> None:
        ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        ...

    @abstractmethod
    async def add_message(self, session_id: str, message: Message) -> None:
        ...

    @abstractmethod
    async def get_messages(self, session_id: str) -> list[Message]:
        ...

    @abstractmethod
    async def replace_messages(self, session_id: str, messages: list[Message]) -> None:
        """Replace all messages (used after compaction)."""
        ...

    @abstractmethod
    async def log_usage(self, session_id: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        ...
