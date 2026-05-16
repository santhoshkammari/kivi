"""06_web_search_agent.py — Web search + fetch agent.

Shows:
- Using web_search and web_fetch builtins (async → sync wrapped)
- Agent browsing the web to answer a question
- doc_id returned by web_fetch for later use
"""
import sys, asyncio
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.tools import ToolRegistry, _BaseTool, ToolInfo, ToolRequest, ToolResponse
from kivi_ai.agent.context import Context
from kivi_ai.agent.events import TextDelta, ToolCallStart, ToolCallComplete, AgentDone
from kivi_ai.tools.builtins import WebSearchTool, WebFetchTool, register_builtin_tools
from kivi_ai.core.registry import Registry

register_builtin_tools()


def _wrap(builtin_instance):
    """Wrap an async ToolInterface into a sync Tool for the agent."""
    class Wrapped(_BaseTool):
        def info(self):
            s = builtin_instance.schema
            props = {p.name: {"type": p.type, "description": p.description} for p in s.parameters}
            req = [p.name for p in s.parameters if p.required]
            return ToolInfo(name=s.name, description=s.description,
                            parameters={"type": "object", "properties": props, "required": req})
        def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
            loop = asyncio.new_event_loop()
            try:
                r = loop.run_until_complete(builtin_instance.execute(request.arguments, work_dir=ctx.work_dir))
            finally:
                loop.close()
            return ToolResponse(r.content, is_error=r.is_error)
    return Wrapped()


tools = [_wrap(WebSearchTool()), _wrap(WebFetchTool())]
agent = Agent(tools=ToolRegistry(tools))

conv = Conversation("You are a web research agent. Search, fetch pages (get doc_ids), and report findings.")
conv.add_user("What is the latest stable Python version? Search for it and fetch the python.org downloads page.")

for event in agent.run(conv, mode="instruct"):
    if isinstance(event, ToolCallStart):
        print(f"\n→ {event.tool_name}({event.arguments[:100]})")
    elif isinstance(event, ToolCallComplete):
        status = "✗" if event.is_error else "✓"
        print(f"  {status} {event.result[:200]}")
    elif isinstance(event, TextDelta):
        print(event.content, end="", flush=True)
    elif isinstance(event, AgentDone):
        print(f"\n[{event.tool_calls_total} tool calls, {event.elapsed_s}s]")
