"""Tool system for the Kivi CLI agent."""
from __future__ import annotations

import difflib
import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .context import Context

__all__ = [
    "ToolInfo", "ToolRequest", "ToolResponse", "Tool", "ToolRegistry",
    "BashTool", "ReadTool", "WriteTool", "EditTool", "GlobTool", "GrepTool",
    "FinalAnswerTool", "default_tools", "filter_tools",
]

_OUTPUT_LIMIT = 8000


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ToolRequest:
    tool_id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolResponse:
    content: str
    is_error: bool = False


@runtime_checkable
class Tool(Protocol):
    def info(self) -> ToolInfo: ...
    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse: ...


class _BaseTool:
    def _fail(self, name: str, exc: Exception) -> ToolResponse:
        return ToolResponse(f"[{name} error] {exc}", is_error=True)


def _truncate(text: str, limit: int = _OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated {len(text) - limit} chars]"


def _tool_env() -> dict[str, str]:
    env = os.environ.copy()
    kivi_env = env.get("KIVI_ENV_PATH", "")
    if kivi_env:
        p = Path(kivi_env)
        bin_dir = str(p.parent if p.suffix else p / "bin")
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


def _display_path(path: Path, ctx: Context) -> str:
    try:
        return str(path.relative_to(Path(ctx.work_dir)))
    except ValueError:
        return str(path)


# ── Tool implementations ──────────────────────────────────────────────


@dataclass
class BashTool(_BaseTool):
    timeout: int = 120

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="shell_bash",
            description="Execute a shell command and return stdout+stderr.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds.", "default": self.timeout},
                },
                "required": ["command"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            ctx.check()
            cmd = str(request.arguments["command"])
            timeout = min(int(request.arguments.get("timeout", self.timeout)), 300)
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=ctx.work_dir, env=_tool_env(),
            )
            ctx.check()
            output = ((result.stdout or "") + (result.stderr or "")).strip()
            if not output:
                output = f"[exit code {result.returncode}]" if result.returncode != 0 else "[no output]"
            elif result.returncode != 0:
                output = f"{output}\n[exit code {result.returncode}]"
            return ToolResponse(_truncate(output), is_error=result.returncode != 0)
        except subprocess.TimeoutExpired as exc:
            partial = ((exc.stdout or "") + (exc.stderr or "")).strip() if exc.stdout or exc.stderr else ""
            msg = f"timed out ({request.arguments.get('timeout', self.timeout)}s)"
            return ToolResponse(_truncate(f"[shell_bash error] {msg}\n{partial}".strip()), is_error=True)
        except Exception as exc:
            return self._fail("shell_bash", exc)


class ReadTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="file_read",
            description="Read a file and return its contents.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path to read."}},
                "required": ["path"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            ctx.check()
            path = ctx.resolve_path(str(request.arguments["path"]))
            content = path.read_text()
            return ToolResponse(_truncate(content))
        except Exception as exc:
            return self._fail("file_read", exc)


class WriteTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="file_write",
            description="Write content to a file, creating parent directories.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "content": {"type": "string", "description": "Content to write."},
                },
                "required": ["path", "content"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            ctx.check()
            path = ctx.resolve_path(str(request.arguments["path"]))
            content = str(request.arguments["content"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return ToolResponse(f"[wrote {len(content.encode())} bytes to {_display_path(path, ctx)}]")
        except Exception as exc:
            return self._fail("file_write", exc)


class EditTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="file_edit",
            description="Replace the first occurrence of old_string with new_string in a file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "old_string": {"type": "string", "description": "Text to find."},
                    "new_string": {"type": "string", "description": "Replacement."},
                },
                "required": ["path", "old_string", "new_string"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            ctx.check()
            path = ctx.resolve_path(str(request.arguments["path"]))
            old = str(request.arguments["old_string"])
            new = str(request.arguments["new_string"])
            original = path.read_text()
            if old not in original:
                return ToolResponse(f"[file_edit error] old_string not found in {_display_path(path, ctx)}", is_error=True)
            updated = original.replace(old, new, 1)
            path.write_text(updated)
            diff = "".join(difflib.unified_diff(
                original.splitlines(keepends=True), updated.splitlines(keepends=True),
                f"a/{_display_path(path, ctx)}", f"b/{_display_path(path, ctx)}",
            ))
            return ToolResponse(diff or "[no changes]")
        except Exception as exc:
            return self._fail("file_edit", exc)


class GlobTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="file_glob",
            description="Find files matching a glob pattern under the working directory.",
            parameters={
                "type": "object",
                "properties": {"pattern": {"type": "string", "description": "Glob pattern."}},
                "required": ["pattern"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            ctx.check()
            root = Path(ctx.work_dir)
            matches = sorted(str(p.relative_to(root)) for p in root.glob(request.arguments["pattern"]) if p.is_file())
            return ToolResponse("\n".join(matches[:200]) if matches else "[glob] no matches")
        except Exception as exc:
            return self._fail("file_glob", exc)


class GrepTool(_BaseTool):
    timeout: int = 30

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="file_grep",
            description="Search for a regex pattern in files using grep -rn.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern."},
                    "path": {"type": "string", "description": "File/directory to search.", "default": "."},
                },
                "required": ["pattern"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            ctx.check()
            pattern = str(request.arguments["pattern"])
            search_path = str(ctx.resolve_path(request.arguments.get("path", ".")))
            result = subprocess.run(
                ["grep", "-rn", "--", pattern, search_path],
                capture_output=True, text=True, timeout=30, cwd=ctx.work_dir, env=_tool_env(),
            )
            ctx.check()
            output = ((result.stdout or "") + (result.stderr or "")).strip()
            if result.returncode == 1 and not output:
                return ToolResponse("[file_grep] no matches")
            return ToolResponse(_truncate(output) if output else "[no output]", is_error=result.returncode not in (0, 1))
        except subprocess.TimeoutExpired:
            return ToolResponse("[file_grep error] timed out", is_error=True)
        except Exception as exc:
            return self._fail("file_grep", exc)


# ── Registry ──────────────────────────────────────────────────────────


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.info().name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        return [
            {"type": "function", "function": {"name": t.info().name, "description": t.info().description, "parameters": t.info().parameters}}
            for t in self._tools.values()
        ]

    def execute(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        tool = self.get(request.name)
        if tool is None:
            return ToolResponse(f"[tool error] unknown tool: {request.name}", is_error=True)
        try:
            return tool.run(ctx, request)
        except Exception as exc:
            return ToolResponse(f"[{request.name} error] {exc}", is_error=True)

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)


class FinalAnswerTool(_BaseTool):
    """Escape hatch when tool_choice=required — agent calls this to return its final answer."""

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="final_answer",
            description="Call this when you have completed all work and are ready to return the final answer to the user.",
            parameters={
                "type": "object",
                "properties": {"answer": {"type": "string", "description": "The final answer or summary to return."}},
                "required": ["answer"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        return ToolResponse(str(request.arguments.get("answer", "")))


def filter_tools(tools: list[Tool], patterns: list[str]) -> list[Tool]:
    """Filter tools by name glob patterns, e.g. ['file_*', 'shell_bash']."""
    result = []
    for tool in tools:
        name = tool.info().name
        if any(fnmatch.fnmatch(name, p) for p in patterns):
            result.append(tool)
    return result


def default_tools() -> list[Tool]:
    return [BashTool(), ReadTool(), WriteTool(), EditTool(), GlobTool(), GrepTool()]


def all_tools() -> list[Tool]:
    from .web_tools import web_tools
    return default_tools() + web_tools()
