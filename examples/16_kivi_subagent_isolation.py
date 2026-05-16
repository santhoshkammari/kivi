"""16_kivi_subagent_isolation.py — Outer agent delegates a contained task to a sub-agent.

Shows:
- Wrapping an Agent as a Tool via `Agent.to_tool(name, description)`
- Sub-agent has its OWN tool set and conversation — isolated from the outer
- Useful for keeping the outer context lean: sub-agent does noisy work,
  returns just its final answer
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.tools import ToolRegistry, BashTool, GrepTool, GlobTool, ReadTool
from kivi_ai.agent.context import Context
from kivi_ai.agent.events import ToolCallStart, ToolCallComplete, TextDelta, AgentDone

# Sub-agent: file-system specialist with read-only tools
fs_specialist = Agent(
    tools=ToolRegistry([ReadTool(), GlobTool(), GrepTool()]),
    name="fs_specialist",
)
fs_tool = fs_specialist.to_tool(
    name="fs_specialist",
    description=(
        "Sub-agent specialised in read-only filesystem inspection. "
        "Pass a natural-language question about files/code in the working directory "
        "as `input` and it will use glob/grep/read internally and return a concise answer."
    ),
)

# Outer agent: only has bash + the sub-agent (no direct file tools)
outer = Agent(tools=ToolRegistry([BashTool(), fs_tool]), name="outer")

conv = Conversation(
    "You are an outer coordinator. For any question about the codebase, "
    "delegate to the fs_specialist sub-agent — do NOT use bash to read files."
)
conv.add_user(
    "How many Python files are in kivi_ai/agent/, and which file defines the Agent class?"
)

print("── outer agent run ──\n")
for event in outer.run(conv, ctx=Context(work_dir="."), mode="instruct"):
    if isinstance(event, ToolCallStart):
        print(f"\n[outer→{event.tool_name}] {str(event.arguments)[:150]}")
    elif isinstance(event, ToolCallComplete):
        status = "ERR" if event.is_error else "OK"
        print(f"  ↳ {status}: {event.result[:200]}")
    elif isinstance(event, TextDelta):
        print(event.content, end="", flush=True)
    elif isinstance(event, AgentDone):
        print(f"\n\n[outer done: {event.steps} steps · {event.tool_calls_total} tool calls · {event.elapsed_s}s]")
