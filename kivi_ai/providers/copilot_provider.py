"""GitHub Copilot provider — event-based streaming via copilot SDK."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

logger = logging.getLogger("kivi.copilot_provider")

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
        """Get or create a Copilot client, restarting if the subprocess died."""
        async with self._lock:
            if self._client is not None:
                # Check if the subprocess is still alive
                try:
                    proc = getattr(self._client, '_process', None) or getattr(self._client, 'process', None)
                    if proc and hasattr(proc, 'returncode') and proc.returncode is not None:
                        logger.warning("Copilot CLI subprocess died, restarting...")
                        self._client = None
                except Exception:
                    pass
            if self._client is None:
                from copilot import CopilotClient
                self._client = CopilotClient(auto_start=True)
                await self._client.start()
        return self._client

    async def initialize(self) -> None:
        pass  # Lazy init on first use to avoid startup failures

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
        logger.info(f"COPILOT STREAM CALLED: model={model} use_vllm={use_vllm} vllm_url={self._vllm_url}")
        
        # On BrokenPipeError, reset client and retry once
        for attempt in range(2):
            try:
                client = await self._get_client()
                async for chunk in self._do_stream(client, messages, model, tools=tools,
                        system_prompt=system_prompt, temperature=temperature,
                        max_tokens=max_tokens, use_vllm=use_vllm, **kwargs):
                    yield chunk
                return
            except (BrokenPipeError, ConnectionError, OSError) as e:
                if attempt == 0:
                    logger.warning(f"Copilot pipe error, resetting client: {e}")
                    self._client = None
                else:
                    yield StreamChunk(type=ChunkType.ERROR, content=str(e))
            except Exception as e:
                yield StreamChunk(type=ChunkType.ERROR, content=str(e))
                return

    async def _do_stream(
        self,
        client,
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
        model = model or "gpt-4.1"

        # For qwen-copilot: resolve actual vLLM model name
        if use_vllm and self._vllm_url:
            model = await self._resolve_vllm_model(model)

        # Build full conversation context for the Copilot session
        # The SDK's session.send() only takes a single string, so we
        # prepend conversation history as context
        history_parts = []
        last_user_prompt = ""
        for m in messages:
            if m.role.value == "user":
                last_user_prompt = m.content if isinstance(m.content, str) else str(m.content)
                history_parts.append(f"User: {last_user_prompt}")
            elif m.role.value == "assistant" and m.content:
                history_parts.append(f"Assistant: {m.content}")
        if not last_user_prompt:
            yield StreamChunk(type=ChunkType.ERROR, content="No user message found")
            return

        # If multi-turn, build a context-aware prompt
        if len(history_parts) > 1:
            prompt = "Conversation so far:\n" + "\n".join(history_parts[:-1]) + "\n\nUser: " + last_user_prompt
        else:
            prompt = last_user_prompt

        try:
            from copilot import ProviderConfig
            from copilot.session import PermissionHandler

            provider = None
            if use_vllm and self._vllm_url:
                provider = ProviderConfig(
                    type="openai",
                    base_url=f"{self._vllm_url}/v1",
                    api_key="sk-xxx",
                )

            session = await client.create_session(
                on_permission_request=PermissionHandler.approve_all,
                model=model,
                provider=provider,
                streaming=True,
            )

            collected: list[tuple] = []
            done_event = asyncio.Event()

            def on_evt(evt):
                t = evt.type.value if hasattr(evt.type, "value") else str(evt.type)
                logger.debug(f"COPILOT EVENT: {t}")
                if t == "assistant.message_delta":
                    delta = evt.data.delta_content if hasattr(evt.data, "delta_content") else ""
                    if delta:
                        collected.append(("delta", delta))
                elif t == "assistant.message":
                    content = evt.data.content if hasattr(evt.data, "content") else ""
                    reasoning = evt.data.reasoning_text if hasattr(evt.data, "reasoning_text") else None
                    collected.append(("message", content, reasoning))
                elif t == "session.idle":
                    # session.idle fires when all turns (including tool round-trips) are complete
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
            logger.info(f"COPILOT: sending prompt to model={model} use_vllm={use_vllm} provider={provider}")
            await session.send(prompt)

            # Stream events as they arrive
            sent_idx = 0
            had_deltas = False
            timeout_at = asyncio.get_event_loop().time() + 180
            while not done_event.is_set():
                if asyncio.get_event_loop().time() > timeout_at:
                    yield StreamChunk(type=ChunkType.ERROR, content="Timeout after 180s")
                    break
                await asyncio.sleep(0.03)
                while sent_idx < len(collected):
                    item = collected[sent_idx]
                    sent_idx += 1
                    if item[0] == "delta":
                        had_deltas = True
                    chunk = self._map_event(item, model, had_deltas=had_deltas)
                    if chunk:
                        yield chunk

            # Flush remaining
            while sent_idx < len(collected):
                item = collected[sent_idx]
                sent_idx += 1
                if item[0] == "delta":
                    had_deltas = True
                chunk = self._map_event(item, model, had_deltas=had_deltas)
                if chunk:
                    yield chunk

            yield StreamChunk(type=ChunkType.DONE, metadata={"model": model})
            unsub()
            await session.disconnect()

        except Exception as e:
            yield StreamChunk(type=ChunkType.ERROR, content=str(e))

    @staticmethod
    def _map_event(item: tuple, model: str, *, had_deltas: bool = False) -> StreamChunk | None:
        kind = item[0]
        if kind == "delta":
            return StreamChunk(type=ChunkType.DELTA, content=item[1])
        elif kind == "message":
            # Skip full message if we already streamed deltas (avoids duplication)
            if had_deltas and not item[2]:
                return None
            content = "" if had_deltas else item[1]
            return StreamChunk(type=ChunkType.DELTA, content=content,
                               metadata={"reasoning": item[2]} if item[2] else {})
        elif kind == "tool_start":
            return StreamChunk(type=ChunkType.TOOL_START, metadata=item[1])
        elif kind == "tool_progress":
            return StreamChunk(type=ChunkType.TOOL_PROGRESS, content=item[1].get("message", ""),
                               metadata=item[1])
        elif kind == "tool_complete":
            return StreamChunk(type=ChunkType.TOOL_COMPLETE, metadata=item[1])
        return None

    # ── vLLM model resolution ────────────────────────────────────────

    async def _resolve_vllm_model(self, fallback: str = "default") -> str:
        """Fetch actual model ID from vLLM server."""
        if not self._vllm_url:
            return fallback
        try:
            import httpx
            async with httpx.AsyncClient() as c:
                resp = await c.get(f"{self._vllm_url}/v1/models", timeout=5)
                return resp.json()["data"][0]["id"]
        except Exception:
            return fallback

    # ── Model listing ────────────────────────────────────────────────

    async def list_models(self) -> list[ModelInfo]:
        # For qwen-copilot: list vLLM models instead of Copilot models
        if self._vllm_url:
            try:
                import httpx
                async with httpx.AsyncClient() as c:
                    resp = await c.get(f"{self._vllm_url}/v1/models", timeout=5)
                    data = resp.json().get("data", [])
                    return [
                        ModelInfo(
                            id=m["id"],
                            name=m["id"].split("/")[-1] if "/" in m["id"] else m["id"],
                            provider=ProviderType.COPILOT,
                            context_window=m.get("max_model_len", 128_000),
                        )
                        for m in data
                    ]
            except Exception:
                pass

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
