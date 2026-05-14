"""Typed message primitives for Kivi agent conversations."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

__all__ = ["Role", "TextPart", "ToolCallPart", "ToolResultPart", "Message", "Conversation"]


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ToolCallPart:
    tool_name: str
    tool_id: str
    arguments: str


@dataclass(frozen=True)
class ToolResultPart:
    tool_call_id: str
    content: str
    is_error: bool = False


ContentPart = TextPart | ToolCallPart | ToolResultPart


@dataclass
class Message:
    role: Role
    parts: list[ContentPart] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid4().hex[:12])

    def __post_init__(self):
        if isinstance(self.role, str):
            self.role = Role(self.role)

    @property
    def text(self) -> str:
        return "".join(p.text for p in self.parts if isinstance(p, TextPart))

    @property
    def tool_calls(self) -> list[ToolCallPart]:
        return [p for p in self.parts if isinstance(p, ToolCallPart)]

    @property
    def has_tool_calls(self) -> bool:
        return any(isinstance(p, ToolCallPart) for p in self.parts)

    def to_openai(self) -> dict:
        if self.role is Role.TOOL:
            part = next(p for p in self.parts if isinstance(p, ToolResultPart))
            return {"role": "tool", "tool_call_id": part.tool_call_id, "content": part.content}
        if self.role is Role.ASSISTANT and self.has_tool_calls:
            return {
                "role": "assistant",
                "content": self.text,
                "tool_calls": [
                    {"id": tc.tool_id, "type": "function", "function": {"name": tc.tool_name, "arguments": tc.arguments}}
                    for tc in self.tool_calls
                ],
            }
        return {"role": self.role.value, "content": self.text}

    @classmethod
    def from_openai(cls, data: dict) -> Message:
        role = Role(data["role"])
        if role is Role.TOOL:
            return cls(role=role, parts=[ToolResultPart(
                tool_call_id=str(data.get("tool_call_id", "")),
                content=str(data.get("content", "")),
            )])
        parts: list[ContentPart] = []
        content = data.get("content", "")
        if content:
            parts.append(TextPart(str(content) if not isinstance(content, str) else content))
        for tc in data.get("tool_calls") or []:
            fn = tc.get("function", {})
            parts.append(ToolCallPart(
                tool_name=fn.get("name", ""),
                tool_id=tc.get("id", ""),
                arguments=fn.get("arguments", ""),
            ))
        return cls(role=role, parts=parts)


class Conversation:
    """Typed conversation container."""

    def __init__(self, system_prompt: str | None = None):
        self._messages: list[Message] = []
        if system_prompt:
            self.set_system(system_prompt)

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    @property
    def last_assistant_text(self) -> str:
        for m in reversed(self._messages):
            if m.role is Role.ASSISTANT:
                return m.text
        return ""

    def add_user(self, text: str) -> Message:
        return self._append(Message(role=Role.USER, parts=[TextPart(text)]))

    def add_assistant(self, text: str) -> Message:
        return self._append(Message(role=Role.ASSISTANT, parts=[TextPart(text)] if text else []))

    def add_tool_result(self, tool_call_id: str, content: str, is_error: bool = False) -> Message:
        return self._append(Message(role=Role.TOOL, parts=[ToolResultPart(tool_call_id, content, is_error)]))

    def set_system(self, text: str) -> None:
        remaining = [m for m in self._messages if m.role is not Role.SYSTEM]
        self._messages = [Message(role=Role.SYSTEM, parts=[TextPart(text)]), *remaining]

    def to_openai(self) -> list[dict]:
        return [m.to_openai() for m in self._messages]

    @classmethod
    def from_openai(cls, messages: list[dict]) -> Conversation:
        conv = cls()
        conv._messages = [Message.from_openai(m) for m in messages]
        return conv

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self):
        return iter(self._messages.copy())

    def compact(self, keep_last: int = 4) -> Conversation:
        """Compact conversation by summarizing older messages."""
        clone = Conversation()
        clone._messages = [Message(role=m.role, parts=list(m.parts), id=m.id) for m in self._messages]

        system = [m for m in clone._messages if m.role is Role.SYSTEM]
        non_system = [m for m in clone._messages if m.role is not Role.SYSTEM]

        if len(non_system) <= keep_last:
            return clone

        old = non_system[:-keep_last] if keep_last > 0 else non_system
        recent = non_system[-keep_last:] if keep_last > 0 else []

        summary_lines = []
        for m in old[:12]:
            snippet = m.text[:200] if m.text else ("tool_call" if m.has_tool_calls else "tool_result")
            summary_lines.append(f"- {m.role.value}: {snippet}")

        summary_text = f"[Conversation compacted: dropped {len(old)} messages]\n" + "\n".join(summary_lines)
        summary_user = Message(role=Role.USER, parts=[TextPart(summary_text)])
        summary_asst = Message(role=Role.ASSISTANT, parts=[TextPart("Understood. I'll continue with the recent context.")])
        clone._messages = [*system, summary_user, summary_asst, *recent]
        return clone

    def token_estimate(self) -> int:
        """Rough token count estimate (chars/4)."""
        total = 0
        for m in self._messages:
            total += len(m.text) // 4
            for p in m.parts:
                if isinstance(p, ToolCallPart):
                    total += len(p.arguments) // 4
                elif isinstance(p, ToolResultPart):
                    total += len(p.content) // 4
        return total

    def _append(self, msg: Message) -> Message:
        self._messages.append(msg)
        return msg
