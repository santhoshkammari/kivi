"""MarkdownAgent — ChromaDB-backed markdown Q&A agent."""
from __future__ import annotations

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.context import Context
from kivi_ai.agent.display import console
from kivi_ai.agent.events import AgentDone, ErrorEvent, TextDelta, ThinkingDelta, ToolCallComplete, ToolCallStart
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.provider import OpenAIProvider
from kivi_ai.agent.tools import ToolRegistry

from .tools import markdown_tools

_SYSTEM_PROMPT = """\
You are a markdown document analyst.

## Rules
- ALWAYS invoke tools via the function calling API; never write tool calls as text or XML.
- NEVER invent tool names — only use tools provided in the tools list.
- Workflow: call md_toc first to map the document, then md_get_section / md_get_table / md_get_code_blocks to read specific parts.
- The user message contains a doc_id (12-char hex). Pass it as the `source` argument to every md_* tool.
- Never guess content — only answer from what tools return.
- After tools return, give a concise final answer.
"""


class MarkdownAgent:
    """Agent that analyses markdown documents using ChromaDB-backed retrieval."""

    def __init__(self, base_url: str = "http://192.168.170.49:8077/v1", model: str = ""):
        provider = OpenAIProvider(base_url=base_url, model=model)
        registry = ToolRegistry(markdown_tools())
        self._agent = Agent(provider=provider, tools=registry, name="markdown-agent")
        self._conversation = Conversation(_SYSTEM_PROMPT)

    def chat(self, user_message: str, work_dir: str = ".") -> str:
        """Send a message and return the final text response."""
        self._conversation.add_user(user_message)
        ctx = Context(work_dir=work_dir)
        full_text = ""
        for event in self._agent.run(self._conversation, ctx=ctx, mode="instruct_coding"):
            if isinstance(event, TextDelta):
                full_text += event.content
            elif isinstance(event, ErrorEvent):
                return f"[error] {event.message}"
        return full_text

    def reset(self) -> None:
        """Start a fresh conversation."""
        self._conversation = Conversation(_SYSTEM_PROMPT)


# ── Rich streaming REPL ───────────────────────────────────────────────

def run_markdown_agent(
    base_url: str = "http://192.168.170.49:8077/v1",
    model: str = "",
    work_dir: str = ".",
) -> None:
    """Interactive REPL for the MarkdownAgent with rich streaming output."""
    from rich.text import Text
    from rich.rule import Rule

    provider = OpenAIProvider(base_url=base_url, model=model)
    registry = ToolRegistry(markdown_tools())
    agent = Agent(provider=provider, tools=registry, name="markdown-agent")
    conversation = Conversation(_SYSTEM_PROMPT)
    ctx = Context(work_dir=work_dir)

    banner = Text()
    banner.append("\n  MarkdownAgent", style="bold #DA7756")
    banner.append(" — ChromaDB-powered markdown analyst\n", style="dim")
    banner.append(f"  endpoint: {base_url}\n", style="dim")
    banner.append("  Type 'exit' or Ctrl-C to quit.\n", style="dim")
    console.print(banner)

    while True:
        try:
            user_input = console.input("[bold cyan]you>[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]bye[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            console.print("[dim]bye[/dim]")
            break

        conversation.add_user(user_input)
        console.print()

        try:
            for event in agent.run(conversation, ctx=ctx, mode="instruct_coding"):
                if isinstance(event, TextDelta):
                    console.print(event.content, end="", markup=False, highlight=False)
                elif isinstance(event, ThinkingDelta):
                    console.print(f"[dim]{event.content}[/dim]", end="")
                elif isinstance(event, ToolCallStart):
                    console.print(f"\n[bold yellow]→ {event.tool_name}[/bold yellow] ", end="")
                    args_preview = str(event.arguments)[:80]
                    console.print(f"[dim]{args_preview}[/dim]")
                elif isinstance(event, ToolCallComplete):
                    status = "[red]error[/red]" if event.is_error else "[green]ok[/green]"
                    preview = (event.result or "")[:120].replace("\n", " ")
                    console.print(f"  [dim]↳ {status} {preview}[/dim]")
                elif isinstance(event, AgentDone):
                    console.print(f"\n[dim]steps={event.steps} tool_calls={event.tool_calls_total} time={event.elapsed_s}s[/dim]")
                elif isinstance(event, ErrorEvent):
                    console.print(f"\n[red]error: {event.message}[/red]")
        except KeyboardInterrupt:
            console.print("\n[yellow]interrupted[/yellow]")

        console.print()
        console.print(Rule(style="dim"))
        console.print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MarkdownAgent REPL")
    parser.add_argument("--base-url", default="http://192.168.170.49:8077/v1")
    parser.add_argument("--model", default="")
    parser.add_argument("--dir", default=".")
    parser.add_argument("--ingest", help="Ingest a markdown file before starting the REPL")
    args = parser.parse_args()

    if args.ingest:
        from .markdown_store import ingest_markdown
        result = ingest_markdown(args.ingest)
        print(f"Ingested: {result}")

    run_markdown_agent(base_url=args.base_url, model=args.model, work_dir=args.dir)
