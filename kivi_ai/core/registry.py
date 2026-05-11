"""Provider and tool registry with dynamic loading."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .interfaces import BaseProvider, ToolInterface


class Registry:
    """Singleton registry for providers and tools."""

    _providers: dict[str, BaseProvider] = {}
    _tools: dict[str, ToolInterface] = {}

    @classmethod
    def register_provider(cls, name: str, provider: BaseProvider) -> None:
        cls._providers[name] = provider

    @classmethod
    def get_provider(cls, name: str) -> BaseProvider:
        if name not in cls._providers:
            raise KeyError(f"Provider '{name}' not registered. Available: {list(cls._providers.keys())}")
        return cls._providers[name]

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._providers.keys())

    @classmethod
    def register_tool(cls, tool: ToolInterface) -> None:
        cls._tools[tool.schema.name] = tool

    @classmethod
    def get_tool(cls, name: str) -> ToolInterface:
        if name not in cls._tools:
            raise KeyError(f"Tool '{name}' not registered. Available: {list(cls._tools.keys())}")
        return cls._tools[name]

    @classmethod
    def list_tools(cls) -> list[ToolInterface]:
        return list(cls._tools.values())

    @classmethod
    def get_tool_schemas(cls) -> list:
        from .types import ToolSchema
        return [t.schema for t in cls._tools.values()]

    @classmethod
    async def initialize_all(cls) -> None:
        for p in cls._providers.values():
            await p.initialize()

    @classmethod
    async def shutdown_all(cls) -> None:
        for p in cls._providers.values():
            await p.shutdown()
