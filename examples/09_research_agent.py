"""09_research_agent.py — Full research pipeline: search → fetch → markdown analysis.

Shows:
- Outer agent with web_search + web_fetch + run_markdown_agent
- Automatic pipeline: search → fetch (→ ChromaDB) → extract via markdown agent
- LLM never sees raw web page content; markdown agent loads from ChromaDB on demand
- The cricket example from the README
"""
import sys, asyncio
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.tools import ToolRegistry, _BaseTool, ToolInfo, ToolRequest, ToolResponse
from kivi_ai.agent.context import Context
from kivi_ai.agent.events import TextDelta, ToolCallStart, ToolCallComplete, AgentDone, ErrorEvent
from kivi_ai.tools.builtins import WebSearchTool, WebFetchTool, RunMarkdownAgentTool, register_builtin_tools
from kivi_ai.core.registry import Registry

register_builtin_tools()


def _wrap(builtin_instance):
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


tools = [
    _wrap(WebSearchTool()),
    _wrap(WebFetchTool()),
    _wrap(RunMarkdownAgentTool()),
]

agent = Agent(tools=ToolRegistry(tools))

SYSTEM = (
    "You are a research agent. Work step by step, one action at a time. "
    "Use web_search to find pages, web_fetch to store them (returns doc_id), "
    "then run_markdown_agent with the doc_id to extract specific facts. "
    "The LLM inside run_markdown_agent never sees the full page — it uses structural "
    "tools to surgically extract only what it needs."
)

conv = Conversation(SYSTEM)
conv.add_user(
    "Find the highest individual Test innings score for Rohit Sharma AND Virat Kohli. "
    "Step by step: search Rohit first → fetch page → extract score via run_markdown_agent, "
    "then search Virat → fetch → extract, then compute difference and percentage difference."
)

print("=" * 60)
for event in agent.run(conv, ctx=Context(), mode="instruct"):
    if isinstance(event, ToolCallStart):
        print(f"\n[{event.tool_name}] {event.arguments[:120]}")
    elif isinstance(event, ToolCallComplete):
        status = "ERR" if event.is_error else "OK"
        print(f"  → {status}: {event.result[:250]}")
    elif isinstance(event, TextDelta):
        print(event.content, end="", flush=True)
    elif isinstance(event, AgentDone):
        print(f"\n{'=' * 60}")
        print(f"Done: {event.steps} steps · {event.tool_calls_total} tool calls · {event.elapsed_s}s")
    elif isinstance(event, ErrorEvent):
        print(f"\n[ERROR] {event.message}")
