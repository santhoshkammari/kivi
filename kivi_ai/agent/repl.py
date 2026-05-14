"""REPL loop for the Kivi CLI agent."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from .agent import Agent
from .context import CancelledError, Context
from .display import DisplayHandler, console, expand_thinking
from .events import ErrorEvent, Event
from .messages import Conversation, Role, ToolCallPart
from .provider import MODES, OpenAIProvider, is_thinking_mode, resolve_mode
from .sessions import PromptHistory, Session, SQLiteSessionStore, default_store, new_session_id, title_from_messages
from .tools import BashTool, ToolRegistry, ToolRequest, default_tools

__all__ = ["run_repl"]

_DEFAULT_BASE_URL = "http://192.168.170.49:8077/v1"
_MAX_CONTEXT = int(os.environ.get("KIVI_MAX_CONTEXT", "250000"))
_COMPACT_THRESHOLD = 0.75  # Auto-compact at 75% of max context
_COMPACT_SCHEDULE = [10, 8, 6, 4, 2, 1]

_IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build"}
_SLASH_COMMANDS = ["/help", "/modes", "/mode", "/clear", "/history", "/cwd", "/think", "/sessions", "/compact", "/quit"]


def _build_system_prompt(registry: ToolRegistry) -> str:
    lines = [
        "You are Kivi Agent, a powerful CLI assistant for software engineering.",
        "You can read, write, edit files, run shell commands, search codebases, and spawn sub-agents.",
        "When multiple independent tasks can be done in parallel, call multiple tools at once.",
        "",
        "## Tools",
    ]
    for schema in registry.schemas():
        fn = schema["function"]
        props = fn.get("parameters", {}).get("properties", {})
        required = set(fn.get("parameters", {}).get("required", []))
        sig = ", ".join(n if n in required else f"{n}=..." for n in props)
        desc = (fn.get("description") or "").split("\n")[0]
        lines.append(f"- **{fn['name']}**({sig}): {desc}")
    lines.extend(["", "Be concise. Use tools to act on files/shell instead of just describing what to do."])
    return "\n".join(lines)


def _make_kivi_tool(base_url: str):
    """Create a sub-agent tool that spawns a kivi sub-agent."""
    from .tools import ToolInfo, ToolResponse, Tool

    class KiviSubAgentTool:
        def info(self) -> ToolInfo:
            return ToolInfo(
                name="kivi",
                description="Spawn a kivi sub-agent to handle a task. Returns the agent's final output.",
                parameters={
                    "type": "object",
                    "properties": {"input": {"type": "string", "description": "Task prompt for the sub-agent."}},
                    "required": ["input"],
                },
            )

        def run(self, ctx, request) -> ToolResponse:
            try:
                sub_registry = ToolRegistry(default_tools())
                sub_system = _build_system_prompt(sub_registry)
                sub_agent = Agent(
                    provider=OpenAIProvider(base_url=base_url),
                    tools=sub_registry,
                    name="kivi-sub",
                )
                conv = Conversation(sub_system)
                conv.add_user(str(request.arguments.get("input", "")))
                sub_agent.task(conv, ctx=ctx.child(), mode="instruct_coding", tool_choice="auto")
                result = conv.last_assistant_text.strip()
                return ToolResponse(result[:16000] if result else "[no output]")
            except CancelledError:
                raise
            except Exception as exc:
                return ToolResponse(f"[kivi sub-agent error] {exc}", is_error=True)

    return KiviSubAgentTool()


def _is_context_limit_error(error: Exception) -> bool:
    msg = str(error).lower()
    return any(t in msg for t in ("context length", "context_length_exceeded", "maximum context", "too many tokens"))


def _process_turn(agent: Agent, conversation: Conversation, mode: str, ctx: Context) -> str:
    """Run one agent turn with display."""
    display = DisplayHandler()
    try:
        for event in agent.run(conversation, ctx=ctx, mode=mode, tool_choice="auto"):
            if isinstance(event, ErrorEvent) and _is_context_limit_error(event.error):
                display.close()
                raise event.error
            display.handle(event)
    except KeyboardInterrupt:
        display.close()
        console.print(Text("\n[interrupted]", style="kivi.dim"))
        return ""
    except CancelledError:
        display.close()
        console.print(Text("\n[interrupted]", style="kivi.dim"))
        return ""
    display.close()
    return display.last_thinking


def _autocompact(conversation: Conversation, level: int) -> Conversation | None:
    if level >= len(_COMPACT_SCHEDULE):
        return None
    keep_last = _COMPACT_SCHEDULE[level]
    compacted = conversation.compact(keep_last=keep_last)
    console.print(Text(f"[autocompact] level {level + 1}/{len(_COMPACT_SCHEDULE)}: kept last {keep_last} msgs", style="kivi.dim"))
    return compacted


def _should_autocompact(conversation: Conversation) -> bool:
    """Check if conversation tokens exceed 75% of max context."""
    estimated = conversation.token_estimate()
    threshold = int(_MAX_CONTEXT * _COMPACT_THRESHOLD)
    return estimated > threshold


def _process_turn_with_autocompact(agent: Agent, conversation: Conversation, mode: str, ctx: Context) -> tuple[Conversation, str]:
    """Run a turn, auto-compacting on context limit errors."""
    # Proactive auto-compression before hitting the limit
    if _should_autocompact(conversation):
        console.print(Text(f"[autocompact] proactive — tokens ~{conversation.token_estimate()} > {int(_MAX_CONTEXT * _COMPACT_THRESHOLD)} threshold", style="kivi.dim"))
        conversation = conversation.compact(keep_last=6)

    active = conversation
    for level in range(len(_COMPACT_SCHEDULE) + 1):
        try:
            return active, _process_turn(agent, active, mode, ctx)
        except Exception as exc:
            if not _is_context_limit_error(exc):
                console.print(Text(f"\n[error] {exc}", style="bold red"))
                return active, ""
            console.print(Text(f"[autocompact] context limit hit — level {level + 1}", style="kivi.dim"))
            compacted = _autocompact(active, level)
            if compacted is None:
                console.print(Text("[autocompact] exhausted — cannot reduce further", style="bold red"))
                return active, ""
            active = compacted
    return active, ""


def _generate_tree(root: str, max_depth: int = 3) -> str:
    lines = [os.path.basename(root) or root]

    def _walk(path: str, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            return
        visible = [e for e in entries if not e.startswith(".") and e not in _IGNORE_DIRS]
        for i, name in enumerate(visible):
            connector = "└── " if i == len(visible) - 1 else "├── "
            lines.append(f"{prefix}{connector}{name}")
            full = os.path.join(path, name)
            if os.path.isdir(full):
                ext = "    " if i == len(visible) - 1 else "│   "
                _walk(full, prefix + ext, depth + 1)

    _walk(root, "", 1)
    return "\n".join(lines)


def _expand_at_directives(prompt: str, work_dir: str) -> str:
    import re
    if "@tree" in prompt:
        prompt = prompt.replace("@tree", f"<tree>\n{_generate_tree(work_dir)}\n</tree>")
    if "@git" in prompt:
        try:
            recent = subprocess.check_output(["git", "-C", work_dir, "log", "--oneline", "-10"], text=True, stderr=subprocess.DEVNULL)
            diff = subprocess.check_output(["git", "-C", work_dir, "diff", "--stat", "HEAD"], text=True, stderr=subprocess.DEVNULL)
            prompt = prompt.replace("@git", f"<git>\n## Recent commits\n{recent}\n## Diff stat\n{diff}\n</git>")
        except Exception:
            prompt = prompt.replace("@git", "[git info unavailable]")

    def _expand_file(m):
        raw = m.group(1)
        full = Path(raw) if os.path.isabs(raw) else Path(work_dir) / raw
        try:
            return f'<file path="{raw}">\n{full.read_text(errors="replace")}\n</file>'
        except FileNotFoundError:
            return f"[file not found: {raw}]"

    prompt = re.sub(r"@file:(\S+)", _expand_file, prompt)
    return prompt


def _save_session(store: SQLiteSessionStore, session_id: str, work_dir: str, conversation: Conversation) -> None:
    messages = conversation.to_openai()
    if not any(m.get("role") != "system" for m in messages):
        return
    store.save(Session(id=session_id, title=title_from_messages(messages), messages=messages, work_dir=work_dir))


def run_repl(work_dir: str, session_id: str | None = None, initial_history: list[dict] | None = None) -> None:
    """Main REPL loop for the Kivi CLI agent."""
    store = default_store()
    prompt_history = PromptHistory(store)
    work_dir = str(Path(work_dir).resolve())
    base_url = os.environ.get("OPENAI_BASE_URL", _DEFAULT_BASE_URL)
    session_id = session_id or new_session_id()

    provider = OpenAIProvider(base_url=base_url)
    registry = ToolRegistry(default_tools())
    registry.register(_make_kivi_tool(base_url))

    conversation = Conversation.from_openai(initial_history) if initial_history else Conversation()
    conversation.set_system(_build_system_prompt(registry))

    current_mode = "instruct_coding"
    last_thinking = ""

    # Print banner
    banner = Text()
    banner.append("\n  ▐▛███▜▌   ", style="kivi.coral")
    banner.append("kivi", style="bold")
    banner.append(" v0.3.0 · AI Agent CLI\n")
    banner.append("  ▝▜█████▛▘  ", style="kivi.coral")
    banner.append(f"{work_dir}\n", style="kivi.dim")
    banner.append("    ▘▘ ▝▝    ", style="kivi.coral")
    banner.append(f"endpoint: {base_url}\n", style="kivi.dim")
    banner.append(f"              session: ", style="kivi.dim")
    banner.append(session_id, style="kivi.session")
    banner.append(f"  mode: ", style="kivi.dim")
    banner.append(current_mode, style="kivi.mode")
    banner.append(f"\n              max_context: {_MAX_CONTEXT:,} tokens  auto-compact: {int(_COMPACT_THRESHOLD*100)}%\n", style="kivi.dim")
    console.print(banner)

    # Try to use prompt_toolkit for nice input, fall back to basic input
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.completion import Completer, Completion

        pt_history = InMemoryHistory()
        for item in prompt_history.load(cwd=work_dir):
            pt_history.append_string(item)

        class _SlashCompleter(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                for cmd in _SLASH_COMMANDS:
                    if cmd.startswith(text):
                        yield Completion(cmd, start_position=-len(text))

        kb = KeyBindings()
        thinking_ref = [last_thinking]

        @kb.add("c-t")
        def _ctrl_t(event):
            if thinking_ref[0]:
                event.app.exit(result="\x00__ctrl_t__\x00")

        pt_session = PromptSession(history=pt_history, completer=_SlashCompleter(), key_bindings=kb, multiline=False)

        def _get_input() -> str:
            label = ANSI(f"\033[1m\033[38;2;217;119;87mkivi> \033[0m")
            return (pt_session.prompt(label) or "").strip()

        use_prompt_toolkit = True
    except ImportError:
        use_prompt_toolkit = False

        def _get_input() -> str:
            try:
                return input("\033[1m\033[38;2;217;119;87mkivi> \033[0m").strip()
            except EOFError:
                raise

    # Main loop
    while True:
        try:
            user_input = _get_input()
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            console.print(Text("\nbye", style="kivi.dim"))
            break

        if not user_input:
            continue

        if user_input == "\x00__ctrl_t__\x00":
            if last_thinking:
                expand_thinking(last_thinking)
            else:
                console.print(Text("no thinking from last response", style="kivi.dim"))
            continue

        # Bang shortcut for bash
        if user_input.startswith("!"):
            cmd = user_input[1:].strip()
            if cmd:
                req = ToolRequest(tool_id=f"call_{uuid.uuid4().hex[:8]}", name="bash", arguments={"command": cmd})
                result = BashTool().run(Context(work_dir=work_dir), req)
                console.print(Text(result.content, style="kivi.dim"))
            continue

        # Slash commands
        if user_input.startswith("/"):
            parts = user_input.split()
            cmd = parts[0].lower()

            if cmd == "/help":
                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_column(style="cyan")
                table.add_column()
                for name, desc in [
                    ("/modes", "list available modes"),
                    ("/mode <name>", "switch mode"),
                    ("/clear", "clear conversation, new session"),
                    ("/history", "message count + token estimate"),
                    ("/compact", "manually compact conversation"),
                    ("/cwd", "show working directory"),
                    ("/think", "expand last thinking (or Ctrl+T)"),
                    ("/sessions", "list saved sessions"),
                    ("/quit", "exit"),
                    ("!cmd", "run shell command directly"),
                    ("@tree", "inject file tree into prompt"),
                    ("@file:path", "inject file contents"),
                    ("@git", "inject recent git info"),
                ]:
                    table.add_row(name, desc)
                console.print()
                console.print(Text("Commands:", style="bold"))
                console.print(table)
                console.print()
            elif cmd == "/modes":
                for name, params in MODES.items():
                    think = "thinking" if is_thinking_mode(name) else "instruct"
                    marker = " *" if name == current_mode else ""
                    console.print(Text(f"  {name:<24} temp={params.temperature}  {think}{marker}", style="kivi.dim"))
            elif cmd == "/mode":
                if len(parts) >= 2 and parts[1] in MODES:
                    current_mode = parts[1]
                    console.print(Text(f"mode → {current_mode}", style="kivi.green"))
                else:
                    console.print(Text(f"unknown mode — valid: {', '.join(MODES)}", style="kivi.red"))
            elif cmd == "/clear":
                session_id = new_session_id()
                last_thinking = ""
                conversation = Conversation(_build_system_prompt(registry))
                console.print(Text(f"cleared — new session {session_id}", style="kivi.dim"))
            elif cmd == "/history":
                count = sum(1 for m in conversation if m.role is not Role.SYSTEM)
                tokens = conversation.token_estimate()
                console.print(Text(f"{count} messages, ~{tokens:,} tokens (max {_MAX_CONTEXT:,})", style="kivi.dim"))
            elif cmd == "/compact":
                conversation = conversation.compact(keep_last=6)
                tokens = conversation.token_estimate()
                console.print(Text(f"compacted — now ~{tokens:,} tokens", style="kivi.dim"))
            elif cmd == "/cwd":
                console.print(Text(work_dir, style="kivi.dim"))
            elif cmd == "/think":
                if last_thinking:
                    expand_thinking(last_thinking)
                else:
                    console.print(Text("no thinking from last response", style="kivi.dim"))
            elif cmd == "/sessions":
                rows = store.list_all()
                if not rows:
                    console.print(Text("no saved sessions", style="kivi.dim"))
                else:
                    table = Table(show_header=False, box=None, padding=(0, 1))
                    table.add_column(no_wrap=True)
                    table.add_column(style="cyan", no_wrap=True)
                    table.add_column(style="dim")
                    table.add_column(style="dim")
                    for row in rows[:20]:
                        marker = Text("*", style="green") if row.id == session_id else Text(" ")
                        table.add_row(marker, row.id, row.updated_at, row.title)
                    console.print(table)
            elif cmd in {"/quit", "/exit"}:
                console.print(Text("bye", style="kivi.dim"))
                break
            else:
                console.print(Text(f"unknown: {cmd}  (try /help)", style="kivi.red"))
            continue

        # Expand @ directives and send to agent
        expanded = _expand_at_directives(user_input, work_dir)
        conversation.add_user(expanded)

        # Save prompt
        prompt_history.save(session_id, work_dir, user_input)

        print()
        agent = Agent(provider=provider, tools=registry, name="kivi")
        ctx = Context(work_dir=work_dir, session_id=session_id)
        conversation, turn_thinking = _process_turn_with_autocompact(agent, conversation, current_mode, ctx)
        if turn_thinking:
            last_thinking = turn_thinking
            if use_prompt_toolkit:
                thinking_ref[0] = turn_thinking

        _save_session(store, session_id, work_dir, conversation)
        print()
