"""OpenAI-compatible provider for Kivi agent (supports vLLM)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterator

from openai import OpenAI

from .context import Context
from .messages import Conversation

__all__ = ["SamplingParams", "MODES", "ContentDelta", "ThinkingDelta", "ToolCallDelta", "StreamComplete", "OpenAIProvider"]


@dataclass
class SamplingParams:
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 20
    presence_penalty: float = 0.0
    repetition_penalty: float = 1.0
    max_tokens: int | None = None


MODES: dict[str, SamplingParams] = {
    "thinking_general": SamplingParams(temperature=1.0, top_p=0.95, top_k=20, presence_penalty=1.5),
    "thinking_coding": SamplingParams(temperature=0.6, top_p=0.95, top_k=20),
    "instruct_general": SamplingParams(temperature=0.7, top_p=0.8, top_k=20, presence_penalty=1.5),
    "instruct_coding": SamplingParams(temperature=0.3, top_p=0.85, top_k=10, repetition_penalty=1.05),
    "instruct_reasoning": SamplingParams(temperature=1.0, top_p=0.95, top_k=20, presence_penalty=1.5),
}


@dataclass(frozen=True)
class ProviderEvent:
    pass


@dataclass(frozen=True)
class ContentDelta(ProviderEvent):
    text: str


@dataclass(frozen=True)
class ThinkingDelta(ProviderEvent):
    text: str


@dataclass(frozen=True)
class ToolCallDelta(ProviderEvent):
    index: int
    tool_id: str | None
    name: str | None
    arguments_delta: str


@dataclass(frozen=True)
class StreamComplete(ProviderEvent):
    finish_reason: str = ""


def is_thinking_mode(mode_name: str) -> bool:
    return mode_name.startswith("thinking_")


def resolve_mode(mode: str | SamplingParams) -> SamplingParams:
    if isinstance(mode, SamplingParams):
        return mode
    return MODES[mode]


class OpenAIProvider:
    def __init__(self, base_url: str | None = None, api_key: str = "EMPTY", model: str = ""):
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL", "http://192.168.170.49:8077/v1")
        self._api_key = api_key
        self._model = model
        self.client = OpenAI(base_url=self._base_url, api_key=self._api_key)

    def model_name(self) -> str:
        if self._model:
            return self._model
        try:
            models = self.client.models.list()
            if models.data:
                return models.data[0].id
        except Exception:
            pass
        return ""

    def stream(
        self,
        conversation: Conversation,
        tools: list[dict],
        ctx: Context,
        params: SamplingParams,
        enable_thinking: bool = False,
        **kwargs,
    ) -> Iterator[ProviderEvent]:
        ctx.check()
        extra_body: dict[str, Any] = {
            "top_k": params.top_k,
            "repetition_penalty": params.repetition_penalty,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }

        request_kwargs: dict[str, Any] = {
            "model": kwargs.pop("model", None) or self._model or self.model_name(),
            "messages": conversation.to_openai(),
            "temperature": params.temperature,
            "top_p": params.top_p,
            "presence_penalty": params.presence_penalty,
            "extra_body": extra_body,
            "stream": True,
        }
        if params.max_tokens:
            request_kwargs["max_tokens"] = params.max_tokens
        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = kwargs.get("tool_choice", "auto")
        request_kwargs.update({k: v for k, v in kwargs.items() if k not in ("tool_choice",)})

        response = self.client.chat.completions.create(**request_kwargs)
        finish_reason = ""
        parser = _ThinkingTagParser()

        try:
            for chunk in response:
                ctx.check()
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                delta = choice.delta
                if delta is None:
                    continue

                # Thinking content (reasoning_content field)
                for field_name in ("reasoning_content", "reasoning", "thinking"):
                    reasoning = getattr(delta, field_name, None)
                    if reasoning:
                        yield ThinkingDelta(reasoning)

                # Content with <think> tag parsing
                content = getattr(delta, "content", None) or ""
                for event in parser.feed(content):
                    yield event

                # Tool calls
                for tc in getattr(delta, "tool_calls", None) or []:
                    fn = getattr(tc, "function", None) or {}
                    yield ToolCallDelta(
                        index=getattr(tc, "index", 0) or 0,
                        tool_id=getattr(tc, "id", None),
                        name=getattr(fn, "name", None) if not isinstance(fn, dict) else fn.get("name"),
                        arguments_delta=getattr(fn, "arguments", "") if not isinstance(fn, dict) else fn.get("arguments", ""),
                    )
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        for event in parser.flush():
            yield event
        yield StreamComplete(finish_reason=finish_reason)


class _ThinkingTagParser:
    """Parses <think>...</think> tags from streaming content."""
    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self):
        self._buffer = ""
        self._in_thinking = False

    def feed(self, text: str) -> list[ProviderEvent]:
        if not text:
            return []
        self._buffer += text
        events: list[ProviderEvent] = []
        while self._buffer:
            marker = self._CLOSE if self._in_thinking else self._OPEN
            idx = self._buffer.find(marker)
            if idx >= 0:
                fragment = self._buffer[:idx]
                if fragment:
                    events.append(self._event(fragment))
                self._buffer = self._buffer[idx + len(marker):]
                self._in_thinking = not self._in_thinking
                continue
            # Check for partial marker at end
            partial = self._partial_len(self._buffer, marker)
            emit_upto = len(self._buffer) - partial
            if emit_upto <= 0:
                break
            fragment = self._buffer[:emit_upto]
            self._buffer = self._buffer[emit_upto:]
            if fragment:
                events.append(self._event(fragment))
            break
        return events

    def flush(self) -> list[ProviderEvent]:
        if not self._buffer:
            return []
        fragment = self._buffer
        self._buffer = ""
        return [self._event(fragment)]

    def _event(self, text: str) -> ProviderEvent:
        return ThinkingDelta(text) if self._in_thinking else ContentDelta(text)

    @staticmethod
    def _partial_len(text: str, marker: str) -> int:
        max_len = min(len(text), len(marker) - 1)
        for size in range(max_len, 0, -1):
            if marker.startswith(text[-size:]):
                return size
        return 0
