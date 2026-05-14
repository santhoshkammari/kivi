"""10_thinking_mode.py — Extended reasoning / thinking mode.

Shows:
- thinking_coding mode for hard problems (vLLM models that support it)
- Displaying thinking blocks vs final answer separately
- ThinkingComplete event carrying the full reasoning trace
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.tools import default_tools
from kivi_ai.agent.events import TextDelta, ThinkingDelta, ThinkingComplete, AgentDone

agent = Agent(tools=default_tools())
conv = Conversation()
conv.add_user(
    "Write a Python function that finds all prime factors of a number "
    "using trial division, with a docstring and a test for n=360."
)

thinking_buf = []
print("[ thinking... ]")

for event in agent.run(conv, mode="thinking_coding"):
    if isinstance(event, ThinkingDelta):
        thinking_buf.append(event.content)
        print(".", end="", flush=True)
    elif isinstance(event, ThinkingComplete):
        print(f"\n[ thought for {len(''.join(thinking_buf))} chars ]\n")
    elif isinstance(event, TextDelta):
        print(event.content, end="", flush=True)
    elif isinstance(event, AgentDone):
        print(f"\n[done in {event.elapsed_s}s]")
