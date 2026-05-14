"""03_bash_tool.py — Agent with bash tool: runs shell commands to answer questions.

Shows:
- Using default_tools() (bash, read, write, edit, glob, grep)
- Agent autonomously deciding when to call tools
- ToolCallStart / ToolCallComplete events
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.tools import ToolRegistry, default_tools
from kivi_ai.agent.events import TextDelta, ToolCallStart, ToolCallComplete, AgentDone

agent = Agent(tools=default_tools())
conv = Conversation()
conv.add_user(
    "What Python version is installed? Also show me the top 5 largest files in /tmp."
)

for event in agent.run(conv, mode="instruct_coding"):
    if isinstance(event, ToolCallStart):
        print(f"\n→ calling {event.tool_name}({event.arguments[:80]})")
    elif isinstance(event, ToolCallComplete):
        status = "✗" if event.is_error else "✓"
        print(f"  {status} {event.result[:120]}")
    elif isinstance(event, TextDelta):
        print(event.content, end="", flush=True)
    elif isinstance(event, AgentDone):
        print(f"\n[{event.steps} steps, {event.tool_calls_total} tool calls, {event.elapsed_s}s]")
