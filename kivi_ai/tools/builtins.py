"""Tool interface and built-in tool implementations."""
from __future__ import annotations

import asyncio
import difflib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from ..core.interfaces import ToolInterface
from ..core.types import ToolParameter, ToolResult, ToolSchema

MAX_OUTPUT = 8000


def _truncate(text: str, max_len: int = MAX_OUTPUT) -> str:
    if len(text) <= max_len:
        return text
    h = max_len // 2
    return text[:h] + f"\n\n... [{len(text) - max_len} chars truncated] ...\n\n" + text[-h:]


def _resolve(p: str, wd: str) -> Path:
    p = os.path.expanduser(p)
    path = Path(p)
    return (path if path.is_absolute() else Path(wd) / path).resolve()


# ── Built-in tools ───────────────────────────────────────────────────

class BashTool(ToolInterface):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="bash",
            description="Execute a bash command",
            parameters=[
                ToolParameter(name="command", type="string", description="The bash command to run", required=True),
                ToolParameter(name="timeout", type="integer", description="Timeout in seconds (max 300)", required=False),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        cmd = arguments.get("command", "")
        timeout = min(int(arguments.get("timeout", 120)), 300)
        try:
            env = {**os.environ, "TERM": "dumb"}
            kivi_env = os.environ.get("KIVI_ENV_PATH", "")
            if kivi_env:
                p = Path(kivi_env)
                bin_dir = str(p.parent if p.suffix else p / "bin")
                env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
            r = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["bash", "-c", cmd], capture_output=True, text=True,
                    timeout=timeout, cwd=work_dir or None,
                    env=env,
                ),
            )
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            return ToolResult(tool_call_id="", content=_truncate(out) if out else f"[exit code: {r.returncode}]")
        except subprocess.TimeoutExpired:
            return ToolResult(tool_call_id="", content=f"[bash error] timed out ({timeout}s)", is_error=True)


class ReadTool(ToolInterface):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="read",
            description="Read a file",
            parameters=[
                ToolParameter(name="path", type="string", description="Path to the file", required=True),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        try:
            content = _resolve(arguments.get("path", ""), work_dir).read_text()
            return ToolResult(tool_call_id="", content=_truncate(content))
        except Exception as e:
            return ToolResult(tool_call_id="", content=f"[read error] {e}", is_error=True)


class WriteTool(ToolInterface):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="write",
            description="Write content to a file",
            parameters=[
                ToolParameter(name="path", type="string", description="Path to the file", required=True),
                ToolParameter(name="content", type="string", description="Content to write", required=True),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        try:
            p = _resolve(arguments.get("path", ""), work_dir)
            c = arguments.get("content", "")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(c)
            return ToolResult(tool_call_id="", content=f"[wrote {len(c.encode())} bytes to {p}]")
        except Exception as e:
            return ToolResult(tool_call_id="", content=f"[write error] {e}", is_error=True)


class EditTool(ToolInterface):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="edit",
            description="Edit a file by replacing old_string with new_string",
            parameters=[
                ToolParameter(name="path", type="string", description="Path to the file", required=True),
                ToolParameter(name="old_string", type="string", description="String to find", required=True),
                ToolParameter(name="new_string", type="string", description="Replacement string", required=True),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        try:
            p = _resolve(arguments.get("path", ""), work_dir)
            old, new = arguments.get("old_string", ""), arguments.get("new_string", "")
            orig = p.read_text()
            if old not in orig:
                return ToolResult(tool_call_id="", content=f"[edit error] old_string not found in {p}", is_error=True)
            updated = orig.replace(old, new, 1)
            p.write_text(updated)
            diff = "".join(difflib.unified_diff(
                orig.splitlines(True), updated.splitlines(True),
                f"a/{p.name}", f"b/{p.name}",
            ))
            return ToolResult(tool_call_id="", content=diff or "[no changes]")
        except Exception as e:
            return ToolResult(tool_call_id="", content=f"[edit error] {e}", is_error=True)


class GlobTool(ToolInterface):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="glob",
            description="Find files matching a glob pattern",
            parameters=[
                ToolParameter(name="pattern", type="string", description="Glob pattern", required=True),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        root = Path(work_dir) if work_dir else Path.cwd()
        matches = sorted(str(p.relative_to(root)) for p in root.glob(arguments.get("pattern", "*")) if p.is_file())
        return ToolResult(tool_call_id="", content="\n".join(matches[:200]) if matches else "[glob] no matches")


class GrepTool(ToolInterface):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="grep",
            description="Search file contents using ripgrep",
            parameters=[
                ToolParameter(name="pattern", type="string", description="Search pattern (regex)", required=True),
                ToolParameter(name="path", type="string", description="Path to search in", required=False),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        try:
            search_path = str(_resolve(arguments.get("path", "."), work_dir))
            r = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["rg", "--line-number", "--no-heading", "--color=never", "--no-messages",
                     "-e", arguments.get("pattern", ""), search_path],
                    capture_output=True, text=True, timeout=30, cwd=work_dir or None,
                ),
            )
            out = (r.stdout or "").strip()
            if r.returncode == 1 and not out:
                return ToolResult(tool_call_id="", content="[grep] no matches")
            return ToolResult(tool_call_id="", content=_truncate(out) if out else "[no output]")
        except FileNotFoundError:
            return ToolResult(tool_call_id="", content="[grep error] ripgrep (rg) not installed", is_error=True)
        except subprocess.TimeoutExpired:
            return ToolResult(tool_call_id="", content="[grep error] timed out", is_error=True)


class WebSearchTool(ToolInterface):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_search",
            description="Search the web using DuckDuckGo",
            parameters=[
                ToolParameter(name="query", type="string", description="Search query", required=True),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        try:
            from ddgs import DDGS
            with DDGS() as d:
                res = list(d.text(arguments.get("query", ""), max_results=5))
            text = "\n\n".join(
                f"{i}. {r.get('title', '')}\n{r.get('href', '')}\n{r.get('body', '')}"
                for i, r in enumerate(res, 1)
            )
            return ToolResult(tool_call_id="", content=text if res else "[no results]")
        except ImportError:
            return ToolResult(tool_call_id="", content="[web_search] Install: pip install duckduckgo-search", is_error=True)


class WebFetchTool(ToolInterface):
    """Fetch a URL, save as Markdown to ChromaDB, return doc_id."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_fetch",
            description=(
                "Fetch a webpage, convert to Markdown, and store it in ChromaDB. "
                "Returns a doc_id you can pass to run_markdown_agent to query the content."
            ),
            parameters=[
                ToolParameter(name="url", type="string", description="URL to fetch", required=True),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        url = arguments.get("url", "")
        try:
            from scrapling.fetchers import Fetcher
            from scrapling.core.shell import Convertor

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: Fetcher.get(url, timeout=30, retries=3, retry_delay=1, impersonate="chrome"),
            )
            content = list(
                Convertor._extract_content(result, css_selector=None, extraction_type="markdown", main_content_only=True)
            )
            if not content or result.status != 200:
                return ToolResult(tool_call_id="", content=f"[web_fetch error] status {result.status}", is_error=True)

            markdown = "".join(content)

            # Ingest into ChromaDB
            from ..agents.markdown.store import ingest_markdown
            info = ingest_markdown(markdown, source_label=url)
            doc_id = info["doc_id"]
            chunks = info["chunks"]
            preview = markdown[:300].replace("\n", " ")

            return ToolResult(
                tool_call_id="",
                content=(
                    f"Fetched and stored: {url}\n"
                    f"doc_id: {doc_id}\n"
                    f"chunks: {chunks}\n"
                    f"preview: {preview}...\n\n"
                    f"Use run_markdown_agent(prompt, doc_id='{doc_id}') to query this content."
                ),
            )
        except ImportError:
            return ToolResult(tool_call_id="", content="[web_fetch] Install: pip install scrapling", is_error=True)
        except Exception as e:
            return ToolResult(tool_call_id="", content=f"[web_fetch error] {e}", is_error=True)


class RunMarkdownAgentTool(ToolInterface):
    """Run the MarkdownAgent on a stored doc_id and return the answer."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="run_markdown_agent",
            description=(
                "Run the MarkdownAgent on a previously fetched/ingested document. "
                "Pass the doc_id returned by web_fetch or md_ingest, and a natural language prompt. "
                "The agent will surgically analyse the document and return a precise answer."
            ),
            parameters=[
                ToolParameter(name="prompt", type="string", description="Question or task about the document", required=True),
                ToolParameter(name="doc_id", type="string", description="doc_id from web_fetch or md_ingest", required=True),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        prompt = arguments.get("prompt", "")
        doc_id = arguments.get("doc_id", "")
        try:
            from ..agents.markdown.store import list_documents
            from ..agents.markdown import MarkdownAgent

            docs = list_documents()
            match = next((d for d in docs if d["doc_id"] == doc_id), None)
            if not match:
                return ToolResult(tool_call_id="", content=f"[run_markdown_agent] doc_id '{doc_id}' not found. Run web_fetch first.", is_error=True)

            # Pass only doc_id — agent loads text via tools (never sees full content)
            agent = MarkdownAgent(base_url=os.environ.get("OPENAI_BASE_URL", "http://192.168.170.49:8077/v1"))
            full_prompt = f"doc_id: {doc_id}  (source: {match['source']})\n\n{prompt}"
            answer = await asyncio.get_event_loop().run_in_executor(None, lambda: agent.chat(full_prompt))
            return ToolResult(tool_call_id="", content=answer)
        except Exception as e:
            return ToolResult(tool_call_id="", content=f"[run_markdown_agent error] {e}", is_error=True)


# ── Registration helper ──────────────────────────────────────────────

ALL_BUILTIN_TOOLS: list[type[ToolInterface]] = [
    BashTool, ReadTool, WriteTool, EditTool, GlobTool, GrepTool, WebSearchTool, WebFetchTool, RunMarkdownAgentTool,
]


def register_builtin_tools() -> None:
    from ..core.registry import Registry
    for tool_cls in ALL_BUILTIN_TOOLS:
        Registry.register_tool(tool_cls())
