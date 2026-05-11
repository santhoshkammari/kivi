"""Tool interface and built-in tool implementations."""
from __future__ import annotations

import asyncio
import difflib
import os
import re
import subprocess
import urllib.request
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
            r = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["bash", "-c", cmd], capture_output=True, text=True,
                    timeout=timeout, cwd=work_dir or None,
                    env={**os.environ, "TERM": "dumb"},
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
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_fetch",
            description="Fetch a webpage and extract text",
            parameters=[
                ToolParameter(name="url", type="string", description="URL to fetch", required=True),
            ],
        )

    async def execute(self, arguments: dict[str, Any], *, work_dir: str = "") -> ToolResult:
        try:
            req = urllib.request.Request(arguments.get("url", ""), headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            return ToolResult(tool_call_id="", content=_truncate(re.sub(r"\s+", " ", text).strip(), 6000))
        except Exception as e:
            return ToolResult(tool_call_id="", content=f"[web_fetch error] {e}", is_error=True)


# ── Registration helper ──────────────────────────────────────────────

ALL_BUILTIN_TOOLS: list[type[ToolInterface]] = [
    BashTool, ReadTool, WriteTool, EditTool, GlobTool, GrepTool, WebSearchTool, WebFetchTool,
]


def register_builtin_tools() -> None:
    from ..core.registry import Registry
    for tool_cls in ALL_BUILTIN_TOOLS:
        Registry.register_tool(tool_cls())
