"""GitHub Copilot provider — event-based streaming via copilot SDK."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from ..core.interfaces import BaseProvider
from ..core.types import (
    ChunkType, Message, ModelInfo, ProviderType, StreamChunk, ToolSchema,
)
from .config import get_context_window


class CopilotProvider(BaseProvider):
    """Provider wrapping the GitHub Copilot SDK (github-copilot-sdk)."""

    name = "copilot"
    supports_streaming = True
    supports_tools = True
    supports_thinking = False

    def __init__(self, vllm_url: str | None = None):
        self._vllm_url = vllm_url  # For qwen-copilot mode
        self._client = None
        self._lock = asyncio.Lock()

    async def _get_client(self):
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    from copilot import CopilotClient
                    self._client = CopilotClient(auto_start=True)
                    await self._client.start()
        return self._client

    async def initialize(self) -> None:
        await self._get_client()

    async def shutdown(self) -> None:
        if self._client:
            try:
                await self._client.stop()
            except Exception:
                pass
            self._client = None

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
        use_vllm: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        client = await self._get_client()
        model = model or "gpt-4.1"

        # Extract last user prompt
        prompt = ""
        for m in reversed(messages):
            if m.role.value == "user":
                prompt = m.content
                break
        if not prompt:
            yield StreamChunk(type=ChunkType.ERROR, content="No user message found")
            return

        try:
            from copilot import ProviderConfig

            provider = None
            if use_vllm and self._vllm_url:
                provider = ProviderConfig(
                    type="openai",
                    base_url=f"{self._vllm_url}/v1",
                    api_key="sk-xxx",
                )

            session = await client.create_session(
                on_permission_request=lambda *a, **k: True,
                model=model,
                provider=provider,
                streaming=True,
            )

            collected: list[tuple] = []
            done_event = asyncio.Event()

            def on_evt(evt):
                t = evt.type.value if hasattr(evt.type, "value") else str(evt.type)
                if t == "assistant.message_delta":
                    delta = evt.data.delta_content if hasattr(evt.data, "delta_content") else ""
                    if delta:
                        collected.append(("delta", delta))
                elif t == "assistant.message":
                    content = evt.data.content if hasattr(evt.data, "content") else ""
                    reasoning = evt.data.reasoning_text if hasattr(evt.data, "reasoning_text") else None
                    collected.append(("message", content, reasoning))
                elif t == "assistant.turn_end":
                    done_event.set()
                elif t == "tool.execution_start":
                    d = evt.data
                    collected.append(("tool_start", {
                        "tool_call_id": d.tool_call_id,
                        "name": d.tool_name,
                        "arguments": d.arguments,
                    }))
                elif t == "tool.execution_progress":
                    d = evt.data
                    collected.append(("tool_progress", {
                        "tool_call_id": d.tool_call_id,
                        "message": d.progress_message,
                    }))
                elif t == "tool.execution_complete":
                    d = evt.data
                    result_text = ""
                    if d.result:
                        result_text = d.result.content or ""
                        if not result_text and d.result.detailed_content:
                            result_text = d.result.detailed_content
                    error_text = ""
                    if d.error:
                        error_text = d.error.message if hasattr(d.error, "message") else str(d.error)
                    collected.append(("tool_complete", {
                        "tool_call_id": d.tool_call_id,
                        "success": d.success,
                        "result": result_text,
                        "error": error_text,
                    }))

            unsub = session.on(on_evt)
            await session.send(prompt)

            # Stream events as they arrive
            sent_idx = 0
            timeout_at = asyncio.get_event_loop().time() + 120
            while not done_event.is_set():
                if asyncio.get_event_loop().time() > timeout_at:
                    yield StreamChunk(type=ChunkType.ERROR, content="Timeout after 120s")
                    break
                await asyncio.sleep(0.03)
                while sent_idx < len(collected):
                    item = collected[sent_idx]
                    sent_idx += 1
                    chunk = self._map_event(item, model)
                    if chunk:
                        yield chunk

            # Flush remaining
            while sent_idx < len(collected):
                item = collected[sent_idx]
                sent_idx += 1
                chunk = self._map_event(item, model)
                if chunk:
                    yield chunk

            yield StreamChunk(type=ChunkType.DONE, metadata={"model": model})
            unsub()
            await session.disconnect()

        except Exception as e:
            yield StreamChunk(type=ChunkType.ERROR, content=str(e))

    @staticmethod
    def _map_event(item: tuple, model: str) -> StreamChunk | None:
        kind = item[0]
        if kind == "delta":
            return StreamChunk(type=ChunkType.DELTA, content=item[1])
        elif kind == "message":
            return StreamChunk(type=ChunkType.DELTA, content=item[1],
                               metadata={"reasoning": item[2]} if item[2] else {})
        elif kind == "tool_start":
            return StreamChunk(type=ChunkType.TOOL_START, metadata=item[1])
        elif kind == "tool_progress":
            return StreamChunk(type=ChunkType.TOOL_PROGRESS, content=item[1].get("message", ""),
                               metadata=item[1])
        elif kind == "tool_complete":
            return StreamChunk(type=ChunkType.TOOL_COMPLETE, metadata=item[1])
        return None

    # ── Model listing ────────────────────────────────────────────────

    async def list_models(self) -> list[ModelInfo]:
        try:
            client = await self._get_client()
            models = await client.list_models()
            result = []
            for m in models:
                ctx = 128_000
                if m.capabilities and m.capabilities.limits:
                    ctx = m.capabilities.limits.max_context_window_tokens or ctx
                result.append(ModelInfo(
                    id=m.id,
                    name=m.name or m.id,
                    provider=ProviderType.COPILOT,
                    context_window=ctx,
                    supports_vision=m.capabilities.supports.vision if m.capabilities else False,
                    supports_thinking=m.capabilities.supports.reasoning_effort if m.capabilities else False,
                ))
            return result
        except Exception:
            return []

    def get_context_window(self, model: str) -> int:
        return get_context_window(model)

    def count_tokens(self, text: str, model: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            return len(text.split()) * 4 // 3
