"""14_parallel_tool_calls.py — Multiple tools executed in parallel in one round.

Shows:
- The agent emitting multiple tool calls in a single round
- ThreadPoolExecutor running them concurrently (see agent.py:_execute_tool_calls)
- Comparing against a sequential baseline to demonstrate the speedup
"""
import sys, time
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.tools import ToolRegistry, ToolInfo, ToolRequest, ToolResponse, _BaseTool
from kivi_ai.agent.context import Context
from kivi_ai.agent.events import ToolCallStart, ToolCallComplete, AgentDone, TextDelta


class SlowEchoTool(_BaseTool):
    """Tool that sleeps 1.5s then echoes — proves parallelism."""

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="slow_echo",
            description="Sleep 1.5s then return the input string. Useful for testing parallelism.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to echo back."}},
                "required": ["text"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        time.sleep(1.5)
        return ToolResponse(f"echo: {request.arguments['text']}")


agent = Agent(tools=ToolRegistry([SlowEchoTool()]))

conv = Conversation(
    "When the user gives multiple independent items, ALWAYS call slow_echo once per "
    "item in a single response — emit all tool calls in parallel, never sequentially."
)
conv.add_user("Echo each of these in parallel: 'apple', 'banana', 'cherry', 'date'")

first_start: float | None = None
last_done: float | None = None
for event in agent.run(conv, ctx=Context(), mode="instruct"):
    if isinstance(event, ToolCallStart):
        if first_start is None:
            first_start = time.monotonic()
        print(f"[start] {event.tool_name}({event.arguments})")
    elif isinstance(event, ToolCallComplete):
        last_done = time.monotonic()
        print(f"[done ] {event.result}")
    elif isinstance(event, TextDelta):
        print(event.content, end="", flush=True)
    elif isinstance(event, AgentDone):
        if first_start and last_done:
            tool_window = last_done - first_start
            n = event.tool_calls_total
            print(f"\n\n{n} tool calls — wall time start→last_done: {tool_window:.2f}s")
            print(f"sequential would be ~{n * 1.5:.1f}s — parallel is "
                  f"{(n * 1.5) / max(tool_window, 0.01):.1f}× faster (tool window only)")
