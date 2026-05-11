"""Core package — types, interfaces, registry."""
from .types import (
    Role, ChunkType, ProviderType,
    Message, StreamChunk, ToolCall, ToolResult, ToolSchema, ToolParameter,
    ModelInfo, SessionMeta,
)

__all__ = [
    "Role", "ChunkType", "ProviderType",
    "Message", "StreamChunk", "ToolCall", "ToolResult", "ToolSchema", "ToolParameter",
    "ModelInfo", "SessionMeta",
]
