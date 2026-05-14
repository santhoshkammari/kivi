"""05_sub_agent.py — Agent as a tool: orchestrator + specialist sub-agents.

Shows:
- Converting an Agent into a Tool with agent.to_tool()
- Orchestrator agent calling a specialist sub-agent
- Parallel tool execution across sub-agents
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.tools import ToolRegistry, default_tools
from kivi_ai.agent.provider import OpenAIProvider
from kivi_ai.agent.events import TextDelta, ToolCallStart, ToolCallComplete, AgentDone

# Specialist: knows only bash
bash_specialist = Agent(
    tools=default_tools(),
    name="system_info_agent",
)

# Convert specialist into a callable tool
specialist_tool = bash_specialist.to_tool(
    name="system_info_agent",
    description="Ask this agent system-level questions. It can run shell commands.",
)

# Orchestrator uses the specialist as a tool
orchestrator = Agent(tools=ToolRegistry([specialist_tool]))
conv = Conversation()
conv.add_user(
    "Ask the system_info_agent: what OS and kernel version is this machine running? "
    "Then summarise the answer in one sentence."
)

for event in orchestrator.run(conv, mode="instruct_coding"):
    if isinstance(event, ToolCallStart):
        print(f"\n→ [{event.tool_name}] {event.arguments[:100]}")
    elif isinstance(event, ToolCallComplete):
        print(f"  ← {event.result[:200]}")
    elif isinstance(event, TextDelta):
        print(event.content, end="", flush=True)
    elif isinstance(event, AgentDone):
        print(f"\n[done in {event.elapsed_s}s]")
