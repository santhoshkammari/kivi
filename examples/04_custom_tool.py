"""04_custom_tool.py — Writing and registering a custom tool.

Shows:
- Implementing the Tool protocol (info + run)
- Registering custom tools alongside defaults
- Agent using your custom tool automatically
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

import math
from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.tools import ToolRegistry, ToolInfo, ToolRequest, ToolResponse, _BaseTool, default_tools
from kivi_ai.agent.context import Context
from kivi_ai.agent.events import TextDelta, ToolCallStart, ToolCallComplete, AgentDone


class PrimeTool(_BaseTool):
    """Check if a number is prime."""

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="is_prime",
            description="Check whether a given integer is a prime number.",
            parameters={
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "The number to check."},
                },
                "required": ["n"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        n = int(request.arguments["n"])
        if n < 2:
            return ToolResponse(f"{n} is not prime")
        for i in range(2, int(math.isqrt(n)) + 1):
            if n % i == 0:
                return ToolResponse(f"{n} is not prime (divisible by {i})")
        return ToolResponse(f"{n} is prime")


registry = ToolRegistry([PrimeTool()])

agent = Agent(tools=registry)
conv = Conversation()
conv.add_user("Are 17, 18, 97, and 100 prime numbers? Check each one.")

for event in agent.run(conv, mode="instruct"):
    if isinstance(event, ToolCallStart):
        print(f"\n→ is_prime({event.arguments})")
    elif isinstance(event, ToolCallComplete):
        print(f"  → {event.result}")
    elif isinstance(event, TextDelta):
        print(event.content, end="", flush=True)
    elif isinstance(event, AgentDone):
        print(f"\n[{event.tool_calls_total} tool calls]")
