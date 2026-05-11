"""OpenAI / vLLM provider — token-level streaming via openai SDK."""
from __future__ import annotations

import os
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ..core.interfaces import BaseProvider
from ..core.types import (
    ChunkType, Message, ModelInfo, ProviderType, Role,
    StreamChunk, ToolCall, ToolSchema,
)
from .config import CONTEXT_WINDOWS, COST_TABLE, get_context_window


class OpenAIProvider(BaseProvider):
    """Provider for OpenAI API and any OpenAI-compatible server (vLLM, Ollama, etc.)."""

    name = "openai"
    supports_streaming = True
    supports_tools = True
    supports_thinking = False

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "gpt-4.1",
        provider_label: str = "openai",
    ):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url
        self._default_model = default_model
        self._label = provider_label
        self._client: AsyncOpenAI | None = None

    async def initialize(self) -> None:
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = AsyncOpenAI(**kwargs)

    async def shutdown(self) -> None:
        if self._client:
            await self._client.close()

    def _get_client(self) -> AsyncOpenAI:
        if not self._client:
            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    # ── Streaming ────────────────────────────────────────────────────

    async def stream(
        self,
        messages: list[Message],
        model: str | None = None,
        *,
        tools: list[ToolSchema] | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_client()
        model = model or self._default_model

        # Build OpenAI messages
        oai_messages = self._to_openai_messages(messages, system_prompt)

        # Build request
        req: dict[str, Any] = {
            "model": model,
            "messages": oai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if temperature is not None:
            req["temperature"] = temperature
        if max_tokens:
            req["max_tokens"] = max_tokens
        if tools:
            req["tools"] = [t.to_openai_schema() for t in tools]

        # Accumulate tool calls across chunks
        tool_calls_acc: dict[int, dict] = {}
        full_content = ""
        usage_meta: dict[str, Any] = {}

        try:
            stream = await client.chat.completions.create(**req)
            async for chunk in stream:
                if not chunk.choices:
                    # Usage-only chunk at end — merge with existing metadata
                    if chunk.usage:
                        usage_meta["input_tokens"] = chunk.usage.prompt_tokens or 0
                        usage_meta["output_tokens"] = chunk.usage.completion_tokens or 0
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # Text delta (token-level)
                if delta and delta.content:
                    full_content += delta.content
                    yield StreamChunk(type=ChunkType.DELTA, content=delta.content)

                # Tool call streaming
                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc_delta.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        acc = tool_calls_acc[idx]
                        if tc_delta.id:
                            acc["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                acc["name"] = tc_delta.function.name
                                yield StreamChunk(
                                    type=ChunkType.TOOL_START,
                                    metadata={"tool_call_id": acc["id"], "name": acc["name"]},
                                )
                            if tc_delta.function.arguments:
                                acc["arguments"] += tc_delta.function.arguments
                                yield StreamChunk(
                                    type=ChunkType.TOOL_INPUT_DELTA,
                                    content=tc_delta.function.arguments,
                                    metadata={"tool_call_id": acc["id"]},
                                )

                # Accumulate tool_calls on finish, but don't emit DONE yet (wait for usage chunk)
                if choice.finish_reason == "tool_calls":
                    import json as _json
                    for tc_acc in tool_calls_acc.values():
                        try:
                            args = _json.loads(tc_acc["arguments"]) if tc_acc["arguments"] else {}
                        except _json.JSONDecodeError:
                            args = {"_raw": tc_acc["arguments"]}
                        usage_meta.setdefault("tool_calls", []).append(
                            {"id": tc_acc["id"], "name": tc_acc["name"], "arguments": args}
                        )

            # Emit single merged DONE at the end
            usage_meta["model"] = model
            yield StreamChunk(type=ChunkType.DONE, metadata=usage_meta)

        except Exception as e:
            yield StreamChunk(type=ChunkType.ERROR, content=str(e))

    # ── Model listing ────────────────────────────────────────────────

    async def list_models(self) -> list[ModelInfo]:
        client = self._get_client()
        try:
            resp = await client.models.list()
            models = []
            for m in resp.data:
                ctx = get_context_window(m.id)
                cost = COST_TABLE.get(m.id, (0.0, 0.0))
                # Use last path component as friendly name
                friendly = m.id.split("/")[-1] if "/" in m.id else m.id
                models.append(ModelInfo(
                    id=m.id,
                    name=friendly,
                    provider=ProviderType.OPENAI,
                    context_window=ctx,
                    input_cost_per_m=cost[0],
                    output_cost_per_m=cost[1],
                ))
            return models
        except Exception:
            return []

    def get_context_window(self, model: str) -> int:
        return get_context_window(model)

    def count_tokens(self, text: str, model: str) -> int:
        try:
            import tiktoken
            try:
                enc = tiktoken.encoding_for_model(model)
            except KeyError:
                enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            return len(text.split()) * 4 // 3

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _to_openai_messages(messages: list[Message], system_prompt: str | None = None) -> list[dict]:
        oai: list[dict] = []
        if system_prompt:
            oai.append({"role": "system", "content": system_prompt})
        for msg in messages:
            if msg.role == Role.TOOL and msg.tool_results:
                for tr in msg.tool_results:
                    oai.append({
                        "role": "tool",
                        "tool_call_id": tr.tool_call_id,
                        "content": tr.content,
                    })
            elif msg.role == Role.ASSISTANT and msg.tool_calls:
                oai.append({
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": __import__("json").dumps(tc.arguments)},
                        }
                        for tc in msg.tool_calls
                    ],
                })
            else:
                oai.append({"role": msg.role.value, "content": msg.content})
        return oai
