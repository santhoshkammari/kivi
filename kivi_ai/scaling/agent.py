"""Scaling agent — runs long tasks using todo-list state in agent.db."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from ..agent.agent import Agent
from ..agent.context import Context
from ..agent.messages import Conversation, Message, Role, TextPart
from ..agent.provider import OpenAIProvider
from ..agent.tools import default_tools
from . import db

log = logging.getLogger("kivi.scaling")

# Silence noisy third-party loggers immediately at import time
for _noisy in ("scrapling", "httpx", "httpcore", "openai"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure kivi.scaling logger with structured output."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False


def _fmt_result(result: str, is_error: bool) -> str:
    """Trim and clean a tool result for display."""
    result = result.replace("\n", " ").strip()
    if len(result) > 100:
        result = result[:100] + "…"
    return result

DB_PATH = Path(__file__).parent / "agent.db"


# ── Soul / prompt ─────────────────────────────────────────────────────

SOUL = """You are a persistent task agent. You work from a SQLite todo list.

On each wake:
1. Read <state> to see your current batch of todos
2. For EACH todo: do the work (use tools), then IMMEDIATELY call mark_done or mark_failed
3. You MUST call mark_done or mark_failed for every single todo_id in your batch — no exceptions
4. Do not respond with prose summaries. Use tool calls only.

CRITICAL: After completing work for a todo, you MUST call mark_done(todo_id=<id>, result=<summary>).
Failure to call mark_done means the todo will be retried forever. Always mark every todo."""


def _build_messages(task_id: int, session_id: int) -> list[Message]:
    state = db.get_state(task_id)
    todos = db.pick_todos(session_id, task_id, n=state["max_parallel"])

    if not todos:
        state_text = f"<state>\nprogress: {state['progress']}\nstatus: ALL DONE\n</state>"
        content = f"{state_text}\n\nAll todos complete. Nothing left to do."
    else:
        todos_text = "\n".join(
            f"  todo_id={t['id']}: {t['description']}" for t in todos
        )
        state_text = (
            f"<state>\n"
            f"goal: {state['goal']}\n"
            f"progress: {state['progress']} done, {state['pending']} pending\n"
            f"your batch:\n{todos_text}\n"
            f"</state>"
        )
        content = f"{state_text}\n\nWork on your batch. Mark each todo done or failed."

    return [Message(role=Role.USER, parts=[TextPart(content)])]


# ── mark_done / mark_failed tools ────────────────────────────────────

from ..agent.tools import ToolInfo, ToolRequest, ToolResponse


class MarkDoneTool:
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="mark_done",
            description="Mark a todo as done with a result summary.",
            parameters={
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer", "description": "The todo id"},
                    "result": {"type": "string", "description": "Brief result or output"},
                },
                "required": ["todo_id", "result"],
            },
        )

    def run(self, ctx: Context, req: ToolRequest) -> ToolResponse:
        db.mark_todo_done(req.arguments["todo_id"], req.arguments["result"])
        return ToolResponse(f"todo {req.arguments['todo_id']} marked done")


class MarkFailedTool:
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="mark_failed",
            description="Mark a todo as failed with an error reason.",
            parameters={
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer", "description": "The todo id"},
                    "error": {"type": "string", "description": "Why it failed"},
                },
                "required": ["todo_id", "error"],
            },
        )

    def run(self, ctx: Context, req: ToolRequest) -> ToolResponse:
        db.mark_todo_failed(req.arguments["todo_id"], req.arguments["error"])
        return ToolResponse(f"todo {req.arguments['todo_id']} marked failed")


# ── Session runner ────────────────────────────────────────────────────

def run_session(task_id: int) -> dict:
    """Run one session: pick a batch, execute, mark results. Returns state."""
    import time
    db.DB_PATH = DB_PATH

    session_id = db.session_start(task_id)
    state = db.get_state(task_id)

    if state["all_done"]:
        db.session_end(session_id, [])
        return state

    messages = _build_messages(task_id, session_id)
    picked_todos = [
        t for t in db.get_todos(task_id, status="picked")
        if t.get("session_id") == session_id
    ]
    picked_ids = [t["id"] for t in picked_todos]

    # ── Session banner ────────────────────────────────────────────────
    log.info("┌─ Session #%d  task=%d  progress=%s  batch=%d todos",
             session_id, task_id, state["progress"], len(picked_todos))
    for t in picked_todos:
        log.info("│  [todo #%d] %s", t["id"], t["description"][:80])
    log.info("│")

    provider = OpenAIProvider()
    from ..agent.web_tools import web_tools
    tools = default_tools() + web_tools() + [MarkDoneTool(), MarkFailedTool()]
    agent = Agent(provider=provider, tools=tools)

    conv = Conversation(system_prompt=SOUL)
    for msg in messages:
        conv._messages.append(msg)
    ctx = Context()

    from ..agent.events import AgentDone, StepComplete, TextDelta, ToolCallStart, ToolCallComplete

    final_text_parts: list[str] = []
    step_tool_buffer: list[tuple[str, str, bool]] = []  # (name, result, is_error) per step
    t0 = time.monotonic()

    for event in agent.run(conv, ctx=ctx, mode="instruct"):
        if isinstance(event, TextDelta):
            final_text_parts.append(event.content)

        elif isinstance(event, ToolCallStart):
            final_text_parts.clear()
            step_tool_buffer.append((event.tool_name, "", False))

        elif isinstance(event, ToolCallComplete):
            # update last matching entry in buffer
            for i in range(len(step_tool_buffer) - 1, -1, -1):
                if step_tool_buffer[i][0] == event.tool_name and step_tool_buffer[i][1] == "":
                    step_tool_buffer[i] = (event.tool_name, event.result, event.is_error)
                    break

        elif isinstance(event, StepComplete):
            n = event.tool_calls
            if n == 0:
                pass  # text-only step, no tool log
            elif n == 1:
                name, result, is_error = step_tool_buffer[0]
                tag = "✗" if is_error else "✓"
                log.info("│  %s %-20s  %s", tag, name, _fmt_result(result, is_error))
            else:
                log.info("│  ┬ %d parallel tool calls:", n)
                for name, result, is_error in step_tool_buffer:
                    tag = "✗" if is_error else "✓"
                    log.info("│  ├ %s %-20s  %s", tag, name, _fmt_result(result, is_error))
                log.info("│  ┘")
            step_tool_buffer.clear()

        elif isinstance(event, AgentDone):
            elapsed = time.monotonic() - t0
            log.info("│")
            log.info("└─ done  steps=%d  tool_calls=%d  elapsed=%.1fs",
                     event.steps, event.tool_calls_total, elapsed)

    # Auto-mark any todos the model forgot to mark_done/mark_failed
    final_text = "".join(final_text_parts).strip()
    still_picked = [
        t for t in db.get_todos(task_id, status="picked")
        if t.get("session_id") == session_id
    ]
    if still_picked:
        fallback_result = final_text or "completed (no explicit result)"
        for t in still_picked:
            db.mark_todo_done(t["id"], fallback_result)
        log.warning("  ! auto-marked %d todos done (model skipped mark_done)", len(still_picked))

    db.session_end(session_id, picked_ids)
    for msg in conv.messages:
        db.save_message(session_id, msg.role.value, msg.text or "")

    final_state = db.get_state(task_id)
    log.info("  progress: %s done  %d pending  %d failed\n",
             final_state["progress"], final_state["pending"], final_state["failed"])
    return final_state


# ── Task creation helper ──────────────────────────────────────────────

def create_task(goal: str, todos: list[str], max_parallel: int = 4) -> int:
    """Create a task with todos in agent.db. Returns task_id."""
    db.DB_PATH = DB_PATH
    db.init_db()
    task_id = db.create_task(goal=goal, soul=SOUL, max_parallel=max_parallel)
    db.create_todos(task_id, todos)
    return task_id


# ── Planner: agent runs python3 -c via bash, we capture JSON output ───

_PLAN_SOUL = (
    "You are a task planner. Your ONLY job: run a python3 -c command via bash that writes "
    "a JSON array of todo strings to /tmp/_kivi_plan.json.\n\n"
    "Rules:\n"
    "- Use python loops/comprehensions for repetitive tasks so the count is exact\n"
    "- Each todo must be a distinct, independently executable string\n"
    "- The python3 -c code must end with:\n"
    "  import json; open('/tmp/_kivi_plan.json','w').write(json.dumps(todos))\n"
    "- Call bash exactly once. Print nothing else."
)


def _plan_todos(provider: OpenAIProvider, goal: str) -> list[str]:
    import json as _json
    from ..agent.tools import BashTool
    from ..agent.events import ToolCallComplete, AgentDone
    from ..agent.messages import Conversation

    agent = Agent(provider=provider, tools=[BashTool()], name="planner")
    conv = Conversation(system_prompt=_PLAN_SOUL)
    conv.add_user(f"Goal: {goal}\n\nRun the python3 -c command now.")

    import os, tempfile
    plan_file = "/tmp/_kivi_plan.json"
    if os.path.exists(plan_file):
        os.remove(plan_file)

    for event in agent.run(conv, mode="instruct", max_steps=6):
        pass  # just let it run

    if not os.path.exists(plan_file):
        raise RuntimeError("Planner did not write /tmp/_kivi_plan.json")

    with open(plan_file) as f:
        todos = _json.load(f)
    os.remove(plan_file)

    if not isinstance(todos, list) or not todos:
        raise RuntimeError(f"Expected non-empty list, got: {type(todos).__name__}")
    if not all(isinstance(t, str) for t in todos):
        raise RuntimeError("All todos must be strings")
    return todos


# ── Single-call entry point ───────────────────────────────────────────

def plan_and_run(goal: str, max_parallel: int = 4) -> dict:
    """Decompose goal into todos via LLM planner, then run sessions until all done."""
    log.info("━━ Planning ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  goal: %s", goal)
    provider = OpenAIProvider()
    todos = _plan_todos(provider, goal)
    log.info("  plan: %d todos (batch_size=%d)", len(todos), max_parallel)
    for i, t in enumerate(todos, 1):
        log.info("    %d. %s", i, t)

    task_id = create_task(goal=goal, todos=todos, max_parallel=max_parallel)
    log.info("  task_id=%d created\n", task_id)

    while True:
        state = run_session(task_id)
        if state["all_done"]:
            break

    log.info("━━ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  task=%d  %s done  %d failed", task_id, state["progress"], state["failed"])
    return state
