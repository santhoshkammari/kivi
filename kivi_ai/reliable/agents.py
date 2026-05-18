"""Reliable agent system: UserAgent + AssistantAgent with per-tool-call verification.

Architecture:
  UserAgent     — verifies EVERY tool call result inline, controls drift, drives loop
  AssistantAgent — executes tool calls; pauses after each for UserAgent to verify

Flow per todo:
  1. UserAgent sends todo to AssistantAgent
  2. AssistantAgent runs ONE tool call, yields (tool_name, args, result)
  3. UserAgent verifies that single tool result → ACCEPT or REJECT+reason
  4. If REJECT: inject feedback into AssistantAgent conv, retry the step
  5. AssistantAgent continues until todo done (final text, no more tool calls)
  6. Every drift_every todos, UserAgent checks if plan is still valid
  7. AssistantAgent auto-compacts at 75% estimated tokens
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Generator

from ..agent.agent import Agent
from ..agent.context import Context
from ..agent.events import (
    AgentDone, TextDelta, ToolCallComplete, ToolCallStart, StepComplete,
)
from ..agent.messages import Conversation
from ..agent.provider import OpenAIProvider
from ..agent.tools import default_tools
from ..agent.web_tools import web_tools

log = logging.getLogger("kivi.reliable")

for _n in ("scrapling", "httpx", "httpcore", "openai"):
    logging.getLogger(_n).setLevel(logging.WARNING)


def setup_logging(level: int = logging.INFO) -> None:
    if log.handlers:
        return  # already set up — don't add duplicate handlers
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(h)
    log.setLevel(level)
    log.propagate = False


# ── Souls ──────────────────────────────────────────────────────────────

_ASSISTANT_SOUL = """You are a task execution agent. You MUST use tools to complete every todo.

CRITICAL RULES:
- NEVER write code or file contents in your text response — use file_write or shell_bash tools instead
- NEVER describe what you will do — just call the tool and do it
- Every todo requires at least one tool call (file_write, shell_bash, web_search, etc.)
- After tool calls are done, give a one-line confirmation

Current plan:
{plan}
"""

_TOOL_VERIFY_SOUL = """You are a strict tool-call verifier. You see one tool call result.

Decide if the tool call result is valid/useful for the stated todo:
- ACCEPT: result looks correct and useful
- REJECT\\n<reason>: result is wrong, errored, or won't help

Be pragmatic — minor formatting issues = ACCEPT. Actual errors or empty results = REJECT.
Respond with ACCEPT or REJECT\\n<reason> only. No prose.
"""

_DRIFT_SOUL = """You are a plan auditor. Given the original goal and completed todos, decide if remaining todos are still valid.

Respond with JSON only:
{"valid": true}
or
{"valid": false, "updated_todos": ["todo1", "todo2", ...]}
"""


# ── Result types ───────────────────────────────────────────────────────

@dataclass
class ToolCallRecord:
    tool_name: str
    arguments: str
    result: str
    accepted: bool
    is_error: bool


@dataclass
class TodoResult:
    todo_id: int
    description: str
    final_text: str
    accepted: bool
    attempts: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass
class RunState:
    goal: str
    todos: list[str]
    completed: list[TodoResult] = field(default_factory=list)
    failed: list[TodoResult] = field(default_factory=list)

    @property
    def done_count(self) -> int:
        return len(self.completed)

    @property
    def progress(self) -> str:
        total = len(self.todos)
        return f"{self.done_count}/{total}"


# ── AssistantAgent ─────────────────────────────────────────────────────

@dataclass
class ToolEvent:
    tool_name: str
    tool_id: str
    arguments: str
    result: str
    is_error: bool


class AssistantAgent:
    """Executes todos step by step. Yields ToolEvent after each tool call so
    UserAgent can verify inline. Keeps conversation alive across todos."""

    MAX_TOKENS = 200_000
    COMPACT_AT = 0.75

    def __init__(self, plan: list[str], provider: OpenAIProvider | None = None):
        self._plan = plan
        self._provider = provider or OpenAIProvider()
        soul = _ASSISTANT_SOUL.format(plan="\n".join(f"- {t}" for t in plan))
        self._conv = Conversation(system_prompt=soul)
        self._tools = default_tools() + web_tools()
        self._agent = Agent(provider=self._provider, tools=self._tools, name="assistant")

    def run_todo(
        self,
        todo: str,
        feedback: str | None = None,
        work_dir: str = ".",
    ) -> Generator[ToolEvent, str | None, str]:
        """Generator that yields ToolEvent per tool call, then yields final str.

        Caller sends feedback via .send(reason) after a ToolEvent to inject
        a correction into the conversation before the next step.
        Final return value is the assistant's closing text.
        """
        if feedback:
            prompt = f"Previous attempt rejected: {feedback}\n\nRetry: {todo}"
        else:
            prompt = f"Execute this todo: {todo}"

        self._conv.add_user(prompt)
        ctx = Context(work_dir=work_dir)

        # We need to intercept per-step so UserAgent can inject between steps.
        # Run the agent step-by-step: each step = one round of tool calls.
        # We drive the inner agent manually by running max_steps=1 repeatedly.
        final_text = ""
        done = False
        step_count = 0

        while not done:
            step_count += 1
            step_tools: list[tuple[str, str, str]] = []  # (name, id, args)
            step_results: list[tuple[str, str, bool]] = []  # (name, result, is_error)
            step_text_parts: list[str] = []

            # force tool use on first step; auto after (allow final summary text)
            tc = "required" if step_count == 1 else "auto"
            for event in self._agent.run(self._conv, ctx=ctx, mode="instruct", max_steps=1,
                                        tool_choice=tc):
                if isinstance(event, TextDelta):
                    step_text_parts.append(event.content)
                elif isinstance(event, ToolCallStart):
                    step_tools.append((event.tool_name, event.tool_id, event.arguments))
                elif isinstance(event, ToolCallComplete):
                    step_results.append((event.tool_name, event.result, event.is_error))
                elif isinstance(event, AgentDone):
                    done = True

            step_text = "".join(step_text_parts).strip()
            if step_text:
                final_text = step_text

            # yield each tool call result to UserAgent for verification
            for (name, tid, args), (_, result, is_error) in zip(step_tools, step_results):
                tag = "✗" if is_error else "✓"
                log.info("  %s %-20s  %s", tag, name, result[:80].replace("\n", " "))
                feedback_back: str | None = yield ToolEvent(name, tid, args, result, is_error)
                if feedback_back:
                    # UserAgent rejected this tool result — inject correction
                    self._conv.add_user(
                        f"[UserAgent] Tool call `{name}` result was rejected: {feedback_back}\n"
                        f"Adjust your approach and continue."
                    )

            if done and not step_tools:
                break

        self._maybe_compact()
        return final_text

    def _maybe_compact(self) -> None:
        msgs = self._conv.messages
        approx_tokens = sum(len(m.text) for m in msgs if m.text) // 4
        if approx_tokens > self.MAX_TOKENS * self.COMPACT_AT:
            log.info("  [assistant] compacting context (~%d est. tokens)", approx_tokens)
            # use built-in compact (keeps last 4 messages + system)
            self._conv = self._conv.compact(keep_last=4)


# ── UserAgent ──────────────────────────────────────────────────────────

class UserAgent:
    """Verifies each tool call result inline and checks plan drift."""

    def __init__(self, goal: str, provider: OpenAIProvider | None = None):
        self._goal = goal
        self._provider = provider or OpenAIProvider()
        # fresh stateless agent for verification (no tools needed)
        self._agent = Agent(provider=self._provider, tools=[], name="verifier")

    def verify_tool_call(self, todo: str, tool_event: ToolEvent) -> tuple[bool, str]:
        """Returns (accepted, reason) for a single tool call result."""
        conv = Conversation(system_prompt=_TOOL_VERIFY_SOUL)
        conv.add_user(
            f"Todo: {todo}\n\n"
            f"Tool called: {tool_event.tool_name}\n"
            f"Arguments: {tool_event.arguments[:300]}\n\n"
            f"Result:\n{tool_event.result[:500]}\n\n"
            f"Accept or reject this tool result?"
        )
        parts: list[str] = []
        for event in self._agent.run(conv, mode="instruct", max_steps=2):
            if isinstance(event, TextDelta):
                parts.append(event.content)

        resp = "".join(parts).strip()
        if resp.upper().startswith("ACCEPT"):
            return True, ""
        reason = re.sub(r"^REJECT\s*", "", resp, flags=re.IGNORECASE).strip()
        return False, reason or "rejected without reason"

    def check_drift(self, remaining: list[str], completed: list[TodoResult]) -> list[str]:
        """Returns (possibly updated) remaining todos after drift check."""
        if not completed or not remaining:
            return remaining

        conv = Conversation(system_prompt=_DRIFT_SOUL)
        conv.add_user(
            f"Goal: {self._goal}\n\n"
            f"Completed:\n" + "\n".join(f"- {r.description}" for r in completed) +
            f"\n\nRemaining:\n" + "\n".join(f"- {t}" for t in remaining) +
            "\n\nAre remaining todos still valid? Respond with JSON."
        )
        parts: list[str] = []
        for event in self._agent.run(conv, mode="instruct", max_steps=2):
            if isinstance(event, TextDelta):
                parts.append(event.content)

        resp = "".join(parts).strip()
        try:
            m = re.search(r'\{.*\}', resp, re.DOTALL)
            data = json.loads(m.group()) if m else {}
            if not data.get("valid", True):
                updated = [t for t in data.get("updated_todos", []) if isinstance(t, str)]
                if updated:
                    log.info("  [user] drift detected — plan updated (%d todos)", len(updated))
                    return updated
        except Exception:
            pass
        return remaining


# ── Main runner ────────────────────────────────────────────────────────

def run(
    goal: str,
    todos: list[str],
    work_dir: str = ".",
    max_retries: int = 3,
    drift_every: int = 5,
    provider: OpenAIProvider | None = None,
) -> RunState:
    """Run goal: AssistantAgent executes, UserAgent verifies every tool call."""
    from pathlib import Path as _Path
    work_dir = str(_Path(work_dir).resolve())

    prov = provider or OpenAIProvider()
    state = RunState(goal=goal, todos=list(todos))
    remaining = list(todos)
    assistant = AssistantAgent(plan=todos, provider=prov)
    user = UserAgent(goal=goal, provider=prov)

    log.info("━━ Reliable Run ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  goal: %s", goal)
    log.info("  todos: %d  work_dir: %s", len(todos), work_dir)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    todo_idx = 0
    done_count = 0

    while remaining:
        if done_count > 0 and done_count % drift_every == 0:
            log.info("[user] drift check at %d completed...", done_count)
            remaining = user.check_drift(remaining, state.completed)
            if not remaining:
                break

        todo = remaining[0]
        todo_idx += 1
        log.info("┌─ Todo #%d/%d: %s", todo_idx, len(todos), todo[:80])

        accepted_todo = False
        final_text = ""
        attempt_num = 0
        tool_records: list[ToolCallRecord] = []
        feedback: str | None = None

        for attempt in range(1, max_retries + 1):
            attempt_num = attempt
            log.info("│  attempt %d/%d", attempt, max_retries)
            t0 = time.monotonic()

            gen = assistant.run_todo(todo, feedback=feedback, work_dir=work_dir)
            tool_records = []
            todo_rejected = False
            reject_reason = ""

            try:
                feedback_to_send: str | None = None
                item = gen.send(None)  # start generator (same as next(gen))
                while True:
                    if isinstance(item, ToolEvent):
                        log.info("  [user] verifying tool: %s", item.tool_name)
                        tc_accepted, reason = user.verify_tool_call(todo, item)
                        tool_records.append(ToolCallRecord(
                            tool_name=item.tool_name,
                            arguments=item.arguments,
                            result=item.result,
                            accepted=tc_accepted,
                            is_error=item.is_error,
                        ))
                        if tc_accepted:
                            log.info("  [user] ✓ tool accepted")
                            feedback_to_send = None
                        else:
                            log.info("  [user] ✗ tool rejected: %s", reason[:80])
                            feedback_to_send = reason
                        item = gen.send(feedback_to_send)
            except StopIteration as e:
                # generator exhausted — final text is return value
                final_text = e.value or ""

            elapsed = time.monotonic() - t0
            failed_tools = [r for r in tool_records if not r.accepted]

            # require at least one successful tool call (assistant must DO work, not just talk)
            successful_tools = [r for r in tool_records if r.accepted and not r.is_error]
            if not successful_tools:
                todo_rejected = True
                reject_reason = (
                    "No tool calls were made or all tools failed. "
                    "You must use tools (file_write, shell_bash, etc.) to complete this todo. Do not just describe what you would do."
                )
                log.info("│  ✗ no successful tools  (%.1fs)", elapsed)
            elif failed_tools:
                todo_rejected = True
                reject_reason = f"{len(failed_tools)} tool call(s) rejected by verifier"
                log.info("│  ✗ %d rejected tools  (%.1fs)", len(failed_tools), elapsed)
            else:
                accepted_todo = True
                log.info("│  ✓ todo done (%.1fs)  tools=%d", elapsed, len(tool_records))
                break

            if todo_rejected:
                log.info("│  ✗ attempt %d failed: %s", attempt, reject_reason[:80])
                feedback = reject_reason

        todo_result = TodoResult(
            todo_id=todo_idx,
            description=todo,
            final_text=final_text,
            accepted=accepted_todo,
            attempts=attempt_num,
            tool_calls=tool_records,
        )

        if accepted_todo:
            state.completed.append(todo_result)
            done_count += 1
            log.info("└─ done  progress=%s\n", state.progress)
        else:
            state.failed.append(todo_result)
            log.info("└─ FAILED after %d attempts\n", attempt_num)

        remaining.pop(0)

    log.info("━━ Complete ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  done=%d  failed=%d  progress=%s", len(state.completed), len(state.failed), state.progress)
    return state
