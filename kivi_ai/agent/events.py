"""Event types for the Kivi agent framework."""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Event", "TextDelta", "ThinkingDelta", "ThinkingComplete",
    "ToolCallStart", "ToolCallComplete", "StepComplete", "AgentDone", "ErrorEvent",
]


@dataclass(frozen=True)
class Event:
    """Marker base class for all agent events."""


@dataclass(frozen=True)
class TextDelta(Event):
    content: str


@dataclass(frozen=True)
class ThinkingDelta(Event):
    content: str


@dataclass(frozen=True)
class ThinkingComplete(Event):
    content: str


@dataclass(frozen=True)
class ToolCallStart(Event):
    tool_name: str
    tool_id: str
    arguments: str


@dataclass(frozen=True)
class ToolCallComplete(Event):
    tool_name: str
    tool_id: str
    arguments: str
    result: str
    is_error: bool = False


@dataclass(frozen=True)
class StepComplete(Event):
    step: int
    text: str
    tool_calls: int
    stop_reason: str


@dataclass(frozen=True)
class AgentDone(Event):
    steps: int
    answer: str
    tool_calls_total: int
    elapsed_s: float


@dataclass(frozen=True)
class ErrorEvent(Event):
    error: Exception
    message: str = ""
