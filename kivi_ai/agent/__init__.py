"""Kivi Agent — CLI agent framework with tool calling, sub-agents, and auto-compression."""
from .agent import Agent
from .context import Context, CancelledError
from .events import Event, TextDelta, ThinkingDelta, ThinkingComplete, ToolCallStart, ToolCallComplete, StepComplete, AgentDone, ErrorEvent
from .messages import Conversation, Message, Role
from .provider import OpenAIProvider, SamplingParams, MODES

__all__ = [
    "Agent", "Context", "CancelledError",
    "Event", "TextDelta", "ThinkingDelta", "ThinkingComplete",
    "ToolCallStart", "ToolCallComplete", "StepComplete", "AgentDone", "ErrorEvent",
    "Conversation", "Message", "Role",
    "OpenAIProvider", "SamplingParams", "MODES",
]
