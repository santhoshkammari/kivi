"""Kivi CLI — unified AI chat with agent REPL and web server."""
import sys
import os
import argparse
from pathlib import Path


def _cmd_serve(argv):
    """Start the Kivi web UI server."""
    parser = argparse.ArgumentParser(prog="kivi serve", description="Start the Kivi web UI server")
    parser.add_argument("--port", "-p", type=int, default=int(os.environ.get("KIVI_PORT", "8899")))
    parser.add_argument("--host", "-H", type=str, default=os.environ.get("KIVI_HOST", "0.0.0.0"))
    parser.add_argument("--vllm-url", type=str, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    if args.vllm_url:
        os.environ["VLLM_URL"] = args.vllm_url
    import uvicorn
    uvicorn.run("kivi_ai.server:app", host=args.host, port=args.port, reload=args.reload)


def _cmd_cli(argv):
    """Start the Kivi agent REPL or run a single prompt."""
    parser = argparse.ArgumentParser(prog="kivi", description="Kivi AI Agent CLI")
    parser.add_argument("prompt", nargs="*", default=None, help="Optional one-shot prompt")
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--max-context", type=int, default=None)
    parser.add_argument("--dir", type=str, default=None)
    parser.add_argument("--think", action="store_true")
    args = parser.parse_args(argv)

    if args.base_url:
        os.environ["OPENAI_BASE_URL"] = args.base_url
    if args.max_context:
        os.environ["KIVI_MAX_CONTEXT"] = str(args.max_context)

    work_dir = str(Path(args.dir).resolve()) if args.dir else str(Path.cwd())
    prompt_text = " ".join(args.prompt) if args.prompt else None

    if prompt_text:
        # Single prompt mode
        from kivi_ai.agent.agent import Agent
        from kivi_ai.agent.provider import OpenAIProvider
        from kivi_ai.agent.tools import ToolRegistry, default_tools
        from kivi_ai.agent.messages import Conversation
        from kivi_ai.agent.context import Context
        from kivi_ai.agent.display import console
        from kivi_ai.agent.repl import _build_system_prompt, _make_kivi_tool, _process_turn_with_autocompact
        from rich.text import Text

        from kivi_ai.agent.web_tools import web_tools
        base_url = os.environ.get("OPENAI_BASE_URL", "http://192.168.170.49:8077/v1")
        provider = OpenAIProvider(base_url=base_url)
        registry = ToolRegistry(default_tools() + web_tools())
        registry.register(_make_kivi_tool(base_url))
        conversation = Conversation(_build_system_prompt(registry))
        conversation.add_user(prompt_text)

        banner = Text()
        banner.append("\n  ▐▛███▜▌   ", style="bold #DA7756")
        banner.append("kivi", style="bold")
        banner.append(" v0.3.0 · single prompt\n")
        banner.append("  ▝▜█████▛▘  ", style="#DA7756")
        banner.append(f"{work_dir}\n", style="dim")
        banner.append("    ▘▘ ▝▝\n", style="#DA7756")
        console.print(banner)

        agent = Agent(provider=provider, tools=registry)
        ctx = Context(work_dir=work_dir)
        mode = "thinking_coding" if args.think else "instruct_coding"
        _process_turn_with_autocompact(agent, conversation, mode, ctx)
        print()
        return

    from kivi_ai.agent.repl import run_repl
    run_repl(work_dir)


def run():
    """kivi — AI agent CLI and web server.

    Usage:
      kivi                          Start agent REPL (default)
      kivi "fix the bug"            Single prompt mode
      kivi serve                    Start web UI server
      kivi serve --port 9000        Custom port
      kivi cli                      Explicit REPL start
      kivi --think "explain auth"   Use thinking mode
    """
    # Route subcommands
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        _cmd_serve(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "cli":
        _cmd_cli(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("""kivi — AI Agent CLI & Web Server

Usage:
  kivi                          Start agent REPL (default)
  kivi "fix the bug in main.py" Single prompt mode
  kivi serve                    Start web UI server
  kivi serve --port 9000        Custom port
  kivi cli                      Explicit REPL start
  kivi --think "explain auth"   Use thinking mode

Commands:
  serve                         Start the web UI server
  cli                           Start the agent REPL

Options:
  --base-url URL                LLM endpoint override
  --max-context N               Max context window tokens
  --dir PATH                    Working directory
  --think                       Enable thinking mode

Environment:
  OPENAI_BASE_URL               LLM endpoint (default: http://192.168.170.49:8077/v1)
  KIVI_MAX_CONTEXT              Max context tokens (default: 250000)
  VLLM_URL                      vLLM URL for web server
  KIVI_PORT                     Web server port (default: 8899)
  KIVI_HOST                     Web server host (default: 0.0.0.0)
""")
    else:
        # Default: CLI mode
        _cmd_cli(sys.argv[1:])


if __name__ == "__main__":
    run()
