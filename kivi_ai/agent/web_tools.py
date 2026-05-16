"""Sync wrappers for async web builtins — usable in the CLI agent registry."""
from __future__ import annotations

import asyncio

from .context import Context
from .tools import ToolInfo, ToolRequest, ToolResponse, _BaseTool


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _wrap(builtin_cls, name_override: str | None = None):
    class Wrapped(_BaseTool):
        _instance = builtin_cls()
        _name_override = name_override

        def info(self) -> ToolInfo:
            s = self._instance.schema
            props = {p.name: {"type": p.type, "description": p.description} for p in s.parameters}
            req = [p.name for p in s.parameters if p.required]
            return ToolInfo(
                name=self._name_override or s.name,
                description=s.description,
                parameters={"type": "object", "properties": props, "required": req},
            )

        def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
            try:
                r = _run(self._instance.execute(request.arguments, work_dir=ctx.work_dir))
                return ToolResponse(r.content, is_error=r.is_error)
            except Exception as exc:
                return ToolResponse(f"[{self._name_override or self._instance.schema.name} error] {exc}", is_error=True)

    Wrapped.__name__ = builtin_cls.__name__
    return Wrapped


def web_tools():
    """Return sync-wrapped web_search, web_fetch, web_markdown_query for the CLI agent."""
    from ..tools.builtins import WebSearchTool, WebFetchTool, RunMarkdownAgentTool, register_builtin_tools
    register_builtin_tools()
    return [
        _wrap(WebSearchTool, "web_search")(),
        _wrap(WebFetchTool, "web_fetch")(),
        _wrap(RunMarkdownAgentTool, "web_markdown_query")(),
    ]
