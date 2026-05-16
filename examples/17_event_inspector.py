"""17_event_inspector.py — Exhaustive tour of every Event type the agent emits.

Shows:
- Every Event subclass (TextDelta, ThinkingDelta, ThinkingComplete,
  ToolCallStart, ToolCallComplete, StepComplete, AgentDone, ErrorEvent)
- What each event carries — useful when wiring kivi into a custom UI/IDE
- Counts per event type at the end
"""
import sys
from collections import Counter

sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.tools import default_tools
from kivi_ai.agent.events import (
    AgentDone, ErrorEvent, StepComplete,
    TextDelta, ThinkingComplete, ThinkingDelta,
    ToolCallComplete, ToolCallStart,
)

agent = Agent(tools=default_tools())
conv = Conversation()
conv.add_user("Run `pwd` and `whoami` using bash, then tell me what you found.")

counts: Counter = Counter()
print(f"{'EVENT':<22} DETAILS")
print("─" * 80)

for event in agent.run(conv, mode="thinking"):
    name = type(event).__name__
    counts[name] += 1
    if isinstance(event, TextDelta):
        if counts[name] <= 3:
            print(f"{name:<22} content={repr(event.content)[:60]}")
    elif isinstance(event, ThinkingDelta):
        if counts[name] <= 3:
            print(f"{name:<22} content={repr(event.content)[:60]}")
    elif isinstance(event, ThinkingComplete):
        print(f"{name:<22} {len(event.content)} chars of reasoning")
    elif isinstance(event, ToolCallStart):
        print(f"{name:<22} tool={event.tool_name} args={str(event.arguments)[:60]}")
    elif isinstance(event, ToolCallComplete):
        flag = "ERR" if event.is_error else "OK"
        print(f"{name:<22} tool={event.tool_name} {flag} result={repr(event.result)[:60]}")
    elif isinstance(event, StepComplete):
        print(f"{name:<22} step={event.step} tool_calls={event.tool_calls} stop={event.stop_reason}")
    elif isinstance(event, AgentDone):
        print(f"{name:<22} steps={event.steps} tool_calls_total={event.tool_calls_total} elapsed={event.elapsed_s}s")
    elif isinstance(event, ErrorEvent):
        print(f"{name:<22} {event.message}")

print("\n── Event counts ──")
for name, n in sorted(counts.items(), key=lambda x: -x[1]):
    print(f"  {name:<22} ×{n}")
