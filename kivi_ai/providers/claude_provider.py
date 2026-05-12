"""Claude Agent SDK provider — subprocess-based streaming."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from ..core.interfaces import BaseProvider
from ..core.types import (
    ChunkType, Message, ModelInfo, ProviderType, StreamChunk, ToolSchema,
)
from .config import get_context_window, COST_TABLE


class ClaudeProvider(BaseProvider):
    """Provider wrapping claude-agent-sdk (Claude Code CLI subprocess)."""

    name = "claude"
    supports_streaming = True
    supports_tools = True
    supports_thinking = True

    def __init__(self, vllm_url: str | None = None):
        self._vllm_url = vllm_url  # For qwen-claude mode

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

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
        model = model or "haiku"

        # Extract last user prompt
        prompt = ""
        for m in reversed(messages):
            if m.role.value == "user":
                prompt = m.content
                break
        if not prompt:
            yield StreamChunk(type=ChunkType.ERROR, content="No user message found")
            return

        client = None
        try:
            from claude_agent_sdk import (
                ClaudeSDKClient, ClaudeAgentOptions, StreamEvent,
                AssistantMessage, ResultMessage, TextBlock, ThinkingBlock,
                ToolUseBlock, ToolResultBlock, UserMessage,
            )
            try:
                from claude_agent_sdk import ServerToolUseBlock, ServerToolResultBlock
            except ImportError:
                ServerToolUseBlock = ServerToolResultBlock = None

            opts: dict[str, Any] = {
                "model": model,
                "permission_mode": "bypassPermissions",
                "max_turns": 250,
                "include_partial_messages": True,
            }

            if use_vllm and self._vllm_url:
                import httpx
                try:
                    resp = httpx.get(f"{self._vllm_url}/v1/models", timeout=5)
                    vllm_model = resp.json()["data"][0]["id"]
                except Exception:
                    vllm_model = model
                opts["model"] = vllm_model
                opts["env"] = {
                    "ANTHROPIC_BASE_URL": self._vllm_url,
                    "ANTHROPIC_API_KEY": "dummy",
                    "ANTHROPIC_AUTH_TOKEN": "dummy",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": vllm_model,
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": vllm_model,
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": vllm_model,
                }

            client = ClaudeSDKClient(ClaudeAgentOptions(**opts))
            await client.connect(prompt)

            total_cost = 0.0
            num_turns = 0

            async for msg in client.receive_messages():
                if isinstance(msg, StreamEvent):
                    evt = msg.event
                    etype = evt.get("type", "")

                    if etype == "content_block_delta":
                        delta = evt.get("delta", {})
                        dt = delta.get("type", "")
                        if dt == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield StreamChunk(type=ChunkType.DELTA, content=text)
                        elif dt == "thinking_delta":
                            text = delta.get("thinking", "")
                            if text:
                                yield StreamChunk(type=ChunkType.THINKING_DELTA, content=text)
                        elif dt == "input_json_delta":
                            partial = delta.get("partial_json", "")
                            if partial:
                                yield StreamChunk(type=ChunkType.TOOL_INPUT_DELTA, content=partial)

                    elif etype == "content_block_start":
                        cb = evt.get("content_block", {})
                        if cb.get("type") == "tool_use":
                            yield StreamChunk(
                                type=ChunkType.TOOL_START,
                                metadata={
                                    "tool_call_id": cb.get("id", ""),
                                    "name": cb.get("name", ""),
                                },
                            )

                elif isinstance(msg, AssistantMessage):
                    # Process complete message blocks
                    for block in msg.content:
                        if isinstance(block, ToolUseBlock):
                            yield StreamChunk(
                                type=ChunkType.TOOL_START,
                                metadata={
                                    "tool_call_id": block.id,
                                    "name": block.name,
                                    "arguments": block.input,
                                },
                            )
                        elif isinstance(block, ToolResultBlock):
                            rc = block.content
                            if isinstance(rc, list):
                                rc = "\n".join(
                                    p.get("text", str(p)) for p in rc if isinstance(p, dict)
                                )
                            yield StreamChunk(
                                type=ChunkType.TOOL_COMPLETE,
                                metadata={
                                    "tool_call_id": block.tool_use_id,
                                    "result": rc or "",
                                    "is_error": block.is_error or False,
                                },
                            )
                        elif ServerToolUseBlock and isinstance(block, ServerToolUseBlock):
                            yield StreamChunk(
                                type=ChunkType.TOOL_START,
                                metadata={
                                    "tool_call_id": block.id,
                                    "name": block.name,
                                    "arguments": block.input,
                                },
                            )
                        elif ServerToolResultBlock and isinstance(block, ServerToolResultBlock):
                            rc = block.content
                            if isinstance(rc, dict):
                                rc = rc.get("text", json.dumps(rc))
                            yield StreamChunk(
                                type=ChunkType.TOOL_COMPLETE,
                                metadata={
                                    "tool_call_id": block.tool_use_id,
                                    "result": rc or "",
                                    "is_error": False,
                                },
                            )

                elif isinstance(msg, UserMessage):
                    # Tool results from the Claude CLI's internal execution
                    if hasattr(msg, 'content') and isinstance(msg.content, list):
                        for block in msg.content:
                            if isinstance(block, ToolResultBlock):
                                rc = block.content
                                if isinstance(rc, list):
                                    rc = "\n".join(
                                        p.get("text", str(p)) for p in rc if isinstance(p, dict)
                                    )
                                yield StreamChunk(
                                    type=ChunkType.TOOL_COMPLETE,
                                    metadata={
                                        "tool_call_id": block.tool_use_id,
                                        "result": rc or "",
                                        "is_error": getattr(block, 'is_error', False) or False,
                                    },
                                )

                elif isinstance(msg, ResultMessage):
                    total_cost = msg.total_cost_usd or 0.0
                    num_turns = msg.num_turns or 0
                    yield StreamChunk(
                        type=ChunkType.DONE,
                        metadata={
                            "model": model,
                            "cost_usd": total_cost,
                            "num_turns": num_turns,
                        },
                    )
                    break

        except Exception as e:
            yield StreamChunk(type=ChunkType.ERROR, content=str(e))
        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    # ── Model listing ────────────────────────────────────────────────

    async def list_models(self) -> list[ModelInfo]:
        # For qwen-claude: list vLLM models instead of Claude models
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
                            provider=ProviderType.CLAUDE,
                            context_window=m.get("max_model_len", 128_000),
                            supports_thinking=True,
                        )
                        for m in data
                    ]
            except Exception:
                pass

        return [
            ModelInfo(
                id="haiku", name="Claude Haiku", provider=ProviderType.CLAUDE,
                context_window=200_000, supports_thinking=True,
                input_cost_per_m=0.80, output_cost_per_m=4.0,
            ),
            ModelInfo(
                id="sonnet", name="Claude Sonnet", provider=ProviderType.CLAUDE,
                context_window=200_000, supports_thinking=True,
                input_cost_per_m=3.0, output_cost_per_m=15.0,
            ),
            ModelInfo(
                id="opus", name="Claude Opus", provider=ProviderType.CLAUDE,
                context_window=200_000, supports_thinking=True,
                input_cost_per_m=15.0, output_cost_per_m=75.0,
            ),
        ]

    def get_context_window(self, model: str) -> int:
        return get_context_window(model)

    def count_tokens(self, text: str, model: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            return len(text.split()) * 4 // 3
