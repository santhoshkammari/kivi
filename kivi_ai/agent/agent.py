"""Core agent loop — streaming, tool execution, parallel calls."""
from __future__ import annotations

import concurrent.futures
import json
import time
from typing import Iterator

from .context import CancelledError, Context
from .events import (
    AgentDone, ErrorEvent, Event, StepComplete,
    TextDelta, ThinkingComplete, ThinkingDelta, ToolCallComplete, ToolCallStart,
)
from .messages import Conversation, Message, Role, TextPart, ToolCallPart
from .provider import (
    ContentDelta, OpenAIProvider, SamplingParams, StreamComplete,
    ThinkingDelta as ProvThinkingDelta, ToolCallDelta, is_thinking_mode, resolve_mode,
)
from .tools import FinalAnswerTool, Tool, ToolInfo, ToolRegistry, ToolRequest, ToolResponse, default_tools, filter_tools

__all__ = ["Agent"]

_CONTINUATION_NUDGE = (
    "You stopped before completing the task. If there are remaining steps, continue now. "
    "If the task is fully done, say so briefly."
)


class Agent:
    """The Kivi CLI agent: provider + tools + event loop."""

    def __init__(
        self,
        provider: OpenAIProvider | None = None,
        tools: list[Tool] | ToolRegistry | None = None,
        tool_names: list[str] | None = None,
        name: str = "kivi",
        force_tool_use: bool = False,
    ):
        resolved = default_tools() if tools is None else tools
        if not isinstance(resolved, ToolRegistry):
            if tool_names is not None:
                resolved = filter_tools(resolved, tool_names)
            if force_tool_use and not any(isinstance(t, FinalAnswerTool) for t in resolved):
                resolved = list(resolved) + [FinalAnswerTool()]
        self._registry = resolved if isinstance(resolved, ToolRegistry) else ToolRegistry(resolved)
        self._force_tool_use = force_tool_use
        self.name = name
        self._provider = provider or OpenAIProvider()
        self._ctx: Context | None = None

    def run(
        self,
        conversation: Conversation,
        ctx: Context | None = None,
        mode: str | SamplingParams = "instruct",
        max_steps: int | None = None,
        tool_choice: str = "auto",
        **kwargs,
    ) -> Iterator[Event]:
        """Stream events: text deltas, thinking, tool calls. Loops until done."""
        ctx = ctx or Context()
        params = resolve_mode(mode)
        mode_name = mode if isinstance(mode, str) else ""
        tool_schemas = self._registry.schemas()
        effective_tool_choice = "required" if self._force_tool_use else tool_choice
        step = retries = total_tool_calls = 0
        started = time.monotonic()
        self._ctx = ctx

        try:
            while True:
                ctx.check()
                if max_steps is not None and step >= max_steps:
                    yield AgentDone(step, conversation.last_assistant_text, total_tool_calls, round(time.monotonic() - started, 3))
                    return
                step += 1
                text_parts: list[str] = []
                thinking_parts: list[str] = []
                pending: dict[int, dict[str, str]] = {}
                finish_reason = ""

                call_kwargs = dict(kwargs)
                if tool_schemas:
                    call_kwargs.setdefault("tool_choice", effective_tool_choice)
                else:
                    call_kwargs.pop("tool_choice", None)

                try:
                    for item in self._provider.stream(
                        conversation, tool_schemas, ctx, params,
                        enable_thinking=is_thinking_mode(mode_name),
                        **call_kwargs,
                    ):
                        ctx.check()
                        if isinstance(item, ContentDelta) and item.text:
                            text_parts.append(item.text)
                            yield TextDelta(item.text)
                        elif isinstance(item, ProvThinkingDelta) and item.text:
                            thinking_parts.append(item.text)
                            yield ThinkingDelta(item.text)
                        elif isinstance(item, ToolCallDelta):
                            _accumulate_tool_call(pending, item)
                        elif isinstance(item, StreamComplete):
                            finish_reason = item.finish_reason
                except CancelledError:
                    raise
                except Exception as exc:
                    yield ErrorEvent(exc, str(exc))
                    return

                if thinking_parts:
                    yield ThinkingComplete("".join(thinking_parts))

                assistant_text = "".join(text_parts)
                tool_calls = _finalize_tool_calls(pending, step)
                stop_reason = finish_reason or ("tool_use" if tool_calls else "end_turn")

                if tool_calls:
                    # Intercept final_answer — emit as text and stop
                    final_calls = [c for c in tool_calls if c.tool_name == "final_answer"]
                    if final_calls:
                        import json as _json
                        try:
                            answer = _json.loads(final_calls[0].arguments).get("answer", "")
                        except Exception:
                            answer = final_calls[0].arguments
                        if answer:
                            yield TextDelta(answer)
                        conversation.add_assistant(answer)
                        yield StepComplete(step=step, text=answer, tool_calls=0, stop_reason="end_turn")
                        yield AgentDone(step, answer, total_tool_calls, round(time.monotonic() - started, 3))
                        return

                    parts = ([TextPart(assistant_text)] if assistant_text else []) + tool_calls
                    conversation._append(Message(role=Role.ASSISTANT, parts=parts))
                    for call in tool_calls:
                        yield ToolCallStart(call.tool_name, call.tool_id, call.arguments)
                    # Execute tools (parallel if multiple)
                    results = _execute_tool_calls(self._registry, ctx, tool_calls)
                    for call, response in zip(tool_calls, results):
                        conversation.add_tool_result(call.tool_id, response.content, is_error=response.is_error)
                        yield ToolCallComplete(call.tool_name, call.tool_id, call.arguments, response.content, response.is_error)
                    total_tool_calls += len(tool_calls)
                    yield StepComplete(step=step, text=assistant_text, tool_calls=len(tool_calls), stop_reason=stop_reason)
                    # If every call was "unknown tool", inject valid tool names so model self-corrects
                    all_unknown = all(
                        r.is_error and "unknown tool" in r.content
                        for r in results
                    )
                    if all_unknown:
                        valid = ", ".join(s["function"]["name"] for s in tool_schemas)
                        conversation.add_user(
                            f"Those tool names don't exist. Valid tools: {valid}. Use the exact names."
                        )
                    continue

                conversation.add_assistant(assistant_text)
                yield StepComplete(step=step, text=assistant_text, tool_calls=0, stop_reason=stop_reason)
                # Continuation nudge if agent stopped without content after tool use
                if total_tool_calls > 0 and retries < 1 and not assistant_text.strip():
                    retries += 1
                    conversation.add_user(_CONTINUATION_NUDGE)
                    continue
                yield AgentDone(step, assistant_text, total_tool_calls, round(time.monotonic() - started, 3))
                return
        finally:
            if self._ctx is ctx:
                self._ctx = None

    def cancel(self) -> None:
        if self._ctx:
            self._ctx.cancel()

    def task(self, prompt: str | Conversation, **kwargs) -> Conversation:
        """Run agent to completion, return conversation."""
        conv = self._ensure_conversation(prompt)
        for _ in self.run(conv, **kwargs):
            pass
        return conv

    def to_tool(self, name: str | None = None, description: str | None = None) -> Tool:
        """Convert this agent into a tool callable by another agent."""
        tool_name = name or self.name
        return _AgentTool(self, tool_name, description or f"Run the {tool_name} sub-agent.")

    @staticmethod
    def _ensure_conversation(prompt: str | Conversation | list[dict]) -> Conversation:
        if isinstance(prompt, Conversation):
            return prompt
        if isinstance(prompt, str):
            conv = Conversation()
            conv.add_user(prompt)
            return conv
        if isinstance(prompt, list):
            return Conversation.from_openai(prompt)
        raise TypeError(f"Unsupported prompt type: {type(prompt)}")


class _AgentTool:
    """Wraps an Agent as a Tool for sub-agent calls."""

    def __init__(self, agent: Agent, name: str, description: str):
        self._agent = agent
        self._name = name
        self._description = description

    def info(self) -> ToolInfo:
        return ToolInfo(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {"input": {"type": "string", "description": "Prompt for the sub-agent."}},
                "required": ["input"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            conv = Conversation()
            conv.add_user(str(request.arguments.get("input", "")))
            self._agent.task(conv, ctx=ctx.child())
            result = conv.last_assistant_text
            return ToolResponse(result[:16000] if result else "[no output]")
        except CancelledError:
            raise
        except Exception as exc:
            return ToolResponse(f"[{self._name} error] {exc}", is_error=True)


def _accumulate_tool_call(pending: dict[int, dict[str, str]], delta: ToolCallDelta) -> None:
    entry = pending.get(delta.index)
    if delta.name is not None or entry is None:
        pending[delta.index] = {
            "tool_id": delta.tool_id or (entry or {}).get("tool_id", ""),
            "name": delta.name or (entry or {}).get("name", ""),
            "arguments": delta.arguments_delta or "",
        }
        return
    if delta.tool_id:
        entry["tool_id"] = delta.tool_id
    entry["arguments"] += delta.arguments_delta or ""


def _finalize_tool_calls(pending: dict[int, dict[str, str]], step: int) -> list[ToolCallPart]:
    return [
        ToolCallPart(call["name"], call.get("tool_id") or f"call-{step}-{idx}", call.get("arguments", ""))
        for idx, call in sorted(pending.items())
        if call.get("name")
    ]


def _execute_tool_calls(registry: ToolRegistry, ctx: Context, calls: list[ToolCallPart]) -> list[ToolResponse]:
    """Execute tools — parallel if more than one."""
    if len(calls) == 1:
        return [_execute_single(registry, ctx, calls[0])]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(_execute_single, registry, ctx, call) for call in calls]
        return [f.result() for f in futures]


def _execute_single(registry: ToolRegistry, ctx: Context, call: ToolCallPart) -> ToolResponse:
    try:
        arguments = json.loads(call.arguments) if call.arguments.strip() else {}
        if not isinstance(arguments, dict):
            raise TypeError("tool arguments must be a JSON object")
        return registry.execute(ctx, ToolRequest(call.tool_id, call.tool_name, arguments))
    except Exception as exc:
        return ToolResponse(f"[{call.tool_name} error] {exc}", is_error=True)
