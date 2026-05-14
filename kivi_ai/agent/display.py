"""Rich terminal display for Kivi agent events."""
from __future__ import annotations

import json

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.status import Status
from rich.text import Text
from rich.theme import Theme

from .events import (
    AgentDone, ErrorEvent, Event, StepComplete,
    TextDelta, ThinkingComplete, ThinkingDelta, ToolCallComplete, ToolCallStart,
)

__all__ = ["DisplayHandler", "expand_thinking", "console"]

_THEME = Theme({
    "markdown.h1": "bold #DA7756",
    "markdown.h2": "bold #5EC5A2",
    "markdown.h3": "bold #C4A2FF",
    "markdown.code": "#A78BFA",
    "markdown.code_block": "#A78BFA",
    "markdown.link": "underline #86DAB9",
    "dim": "dim white",
    "tool.name": "bold yellow",
    "tool.args": "dim white",
    "tool.ok": "green",
    "tool.err": "red",
    "diff.add": "green",
    "diff.rem": "red",
    "diff.hunk": "cyan",
    "kivi.dim": "dim white",
    "kivi.coral": "#DA7756",
    "kivi.green": "green",
    "kivi.red": "red",
    "kivi.session": "bold cyan",
    "kivi.mode": "bold yellow",
})

console = Console(theme=_THEME, highlight=False)


def expand_thinking(text: str) -> None:
    console.print(Text("┌─ thinking ──────────────────────────────", style="dim"))
    for line in text.splitlines():
        console.print(Text(f"│ {line}", style="dim"))
    console.print(Text("└─────────────────────────────────────────", style="dim"))


def _fmt_args(name: str, arguments: str) -> str:
    try:
        args = json.loads(arguments) if arguments else {}
    except Exception:
        s = arguments[:60]
        return f"({s}…)" if len(arguments) > 60 else f"({s})"
    if name in {"edit", "write"}:
        return f"({args.get('path', '')})"
    if name == "bash":
        cmd = str(args.get("command", ""))
        return f"({cmd[:60]}…)" if len(cmd) > 60 else f"({cmd})"
    parts = []
    for k, v in args.items():
        sv = str(v)
        parts.append(f"{k}={sv[:40]!r}" if len(sv) > 40 else f"{k}={sv!r}")
    return f"({', '.join(parts)})"


class DisplayHandler:
    """Renders agent events in the terminal using Rich."""

    def __init__(self) -> None:
        self._thinking_buf = ""
        self._thinking_active = False
        self._status: Status | None = None
        self._stream_buf: list[str] = []
        self._stream_active = False
        self._live: Live | None = None
        self._last_thinking = ""

    def handle(self, event: Event) -> None:
        if isinstance(event, TextDelta):
            self._on_text(event)
        elif isinstance(event, ThinkingDelta):
            self._on_thinking(event)
        elif isinstance(event, ThinkingComplete):
            self._on_thinking_complete(event)
        elif isinstance(event, ToolCallStart):
            self._on_tool_start(event)
        elif isinstance(event, ToolCallComplete):
            self._on_tool_complete(event)
        elif isinstance(event, StepComplete):
            self._on_step_complete(event)
        elif isinstance(event, AgentDone):
            self._on_done(event)
        elif isinstance(event, ErrorEvent):
            self._on_error(event)

    @property
    def last_thinking(self) -> str:
        return self._last_thinking

    def _on_thinking(self, event: ThinkingDelta) -> None:
        if not self._thinking_active:
            self._thinking_buf = ""
            self._thinking_active = True
            self._status = Status("thinking…", console=console, spinner="dots")
            self._status.start()
        self._thinking_buf += event.content
        self._status.update(f"thinking… [dim]({len(self._thinking_buf)} chars)[/dim]")

    def _on_thinking_complete(self, event: ThinkingComplete) -> None:
        final = event.content or self._thinking_buf
        self._last_thinking = final
        self._thinking_active = False
        if self._status:
            self._status.stop()
            self._status = None
        if final:
            console.print(Text(f"▶ thinking ({len(final)} chars) — Ctrl+T to expand", style="dim"))
        self._thinking_buf = ""

    def _finish_thinking(self) -> None:
        if self._status:
            self._status.stop()
            self._status = None
        if self._thinking_active and self._thinking_buf:
            self._last_thinking = self._thinking_buf
            console.print(Text(f"▶ thinking ({len(self._thinking_buf)} chars) — Ctrl+T to expand", style="dim"))
        self._thinking_buf = ""
        self._thinking_active = False

    def _on_text(self, event: TextDelta) -> None:
        if self._thinking_active:
            self._finish_thinking()
        if not self._stream_active:
            self._stream_buf = []
            self._stream_active = True
            self._live = Live(console=console, refresh_per_second=15, vertical_overflow="visible")
            self._live.__enter__()
        self._stream_buf.append(event.content)
        self._live.update(Markdown("".join(self._stream_buf)))

    def _finish_stream(self) -> None:
        if self._stream_active and self._live:
            final_text = "".join(self._stream_buf)
            # Render final state before exiting Live
            if final_text.strip():
                self._live.update(Markdown(final_text))
            self._live.__exit__(None, None, None)
            self._live = None
            self._stream_buf = []
            self._stream_active = False

    def _on_tool_start(self, event: ToolCallStart) -> None:
        self._finish_stream()
        self._finish_thinking()
        args_hint = _fmt_args(event.tool_name, event.arguments)
        line = Text()
        line.append("▶ ", style="tool.name")
        line.append(event.tool_name, style="tool.name")
        line.append(args_hint, style="tool.args")
        console.print(line)

    def _on_tool_complete(self, event: ToolCallComplete) -> None:
        result = event.result or ""
        symbol = "✗" if event.is_error else "✓"
        sym_style = "tool.err" if event.is_error else "tool.ok"
        # Show diff output colored
        has_diff = any(
            l.startswith(("+", "-", "@@")) and not l.startswith(("+++", "---"))
            for l in result.splitlines()
        )
        if has_diff and not event.is_error:
            for line in result.splitlines()[:20]:
                if line.startswith("+") and not line.startswith("+++"):
                    console.print(Text(line, style="diff.add"))
                elif line.startswith("-") and not line.startswith("---"):
                    console.print(Text(line, style="diff.rem"))
                elif line.startswith("@@"):
                    console.print(Text(line, style="diff.hunk"))
                else:
                    console.print(Text(line, style="dim"))
            console.print(Text(f"  {symbol}", style=sym_style))
        else:
            preview = result[:120].replace("\n", " ").strip()
            ellip = "…" if len(result) > 120 else ""
            line = Text()
            line.append(f"  {symbol} ", style=sym_style)
            if preview:
                line.append(f"{preview}{ellip}", style="dim")
            console.print(line)

    def _on_step_complete(self, event: StepComplete) -> None:
        if event.tool_calls == 0 and event.stop_reason == "end_turn":
            self._finish_stream()

    def _on_done(self, event: AgentDone) -> None:
        self._finish_thinking()
        self._finish_stream()

    def _on_error(self, event: ErrorEvent) -> None:
        self._finish_thinking()
        self._finish_stream()
        console.print(Text(f"\n[error] {event.message or event.error}", style="bold red"))

    def close(self) -> None:
        self._finish_thinking()
        self._finish_stream()
