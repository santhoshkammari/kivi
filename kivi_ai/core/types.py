"""Unified AI Chat Framework — Core type definitions."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


# ── Enums ────────────────────────────────────────────────────────────

class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ChunkType(str, Enum):
    DELTA = "delta"
    THINKING_DELTA = "thinking_delta"
    TOOL_START = "tool_start"
    TOOL_PROGRESS = "tool_progress"
    TOOL_INPUT_DELTA = "tool_input_delta"
    TOOL_COMPLETE = "tool_complete"
    DONE = "done"
    ERROR = "error"
    COMPACTION = "compaction"


class ProviderType(str, Enum):
    OPENAI = "openai"
    COPILOT = "copilot"
    CLAUDE = "claude"


# ── Tool types ───────────────────────────────────────────────────────

@dataclass
class ToolParameter:
    name: str
    type: str
    description: str = ""
    required: bool = False
    enum: list[str] | None = None


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI function-calling JSON schema."""
        props = {}
        required = []
        for p in self.parameters:
            props[p.name] = {"type": p.type, "description": p.description}
            if p.enum:
                props[p.name]["enum"] = p.enum
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool_call_id: str
    content: str = ""
    is_error: bool = False


# ── Message ──────────────────────────────────────────────────────────

@dataclass
class Message:
    """Provider-agnostic message. The universal currency of the framework."""
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None
    thinking: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "id": self.id,
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.thinking:
            d["thinking"] = self.thinking
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ]
        if self.tool_results:
            d["tool_results"] = [
                {"tool_call_id": tr.tool_call_id, "content": tr.content, "is_error": tr.is_error}
                for tr in self.tool_results
            ]
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        tool_calls = None
        if d.get("tool_calls"):
            tool_calls = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("arguments", {}))
                for tc in d["tool_calls"]
            ]
        tool_results = None
        if d.get("tool_results"):
            tool_results = [
                ToolResult(tool_call_id=tr["tool_call_id"], content=tr.get("content", ""), is_error=tr.get("is_error", False))
                for tr in d["tool_results"]
            ]
        return cls(
            role=Role(d["role"]),
            content=d.get("content", ""),
            tool_calls=tool_calls,
            tool_results=tool_results,
            thinking=d.get("thinking"),
            metadata=d.get("metadata", {}),
            id=d.get("id", uuid.uuid4().hex[:12]),
            timestamp=d.get("timestamp", time.time()),
        )


# ── Stream chunk ─────────────────────────────────────────────────────

@dataclass
class StreamChunk:
    """Normalized streaming event emitted by all providers."""
    type: ChunkType
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_sse_dict(self) -> dict:
        d: dict[str, Any] = {"type": self.type.value, "content": self.content}
        if self.metadata:
            d.update(self.metadata)
        return d


# ── Model info ───────────────────────────────────────────────────────

@dataclass
class ModelInfo:
    id: str
    name: str
    provider: ProviderType
    context_window: int = 128_000
    max_output_tokens: int = 8_192
    supports_vision: bool = False
    supports_thinking: bool = False
    supports_tools: bool = True
    input_cost_per_m: float = 0.0   # USD per 1M input tokens
    output_cost_per_m: float = 0.0  # USD per 1M output tokens

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider.value,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_vision": self.supports_vision,
            "supports_thinking": self.supports_thinking,
            "supports_tools": self.supports_tools,
            "input_cost_per_m": self.input_cost_per_m,
            "output_cost_per_m": self.output_cost_per_m,
        }


# ── Session metadata ────────────────────────────────────────────────

@dataclass
class SessionMeta:
    id: str
    title: str = "Untitled"
    provider: ProviderType = ProviderType.OPENAI
    model: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    total_tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "provider": self.provider.value,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
        }
