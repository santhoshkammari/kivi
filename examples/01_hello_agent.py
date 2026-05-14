"""01_hello_agent.py — Simplest possible agent: single prompt, no tools.

Shows:
- Creating an Agent with default vLLM provider
- Running a single prompt and collecting the response
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.events import TextDelta, AgentDone

agent = Agent()

conv = Conversation()
conv.add_user("What is 17 * 43? Just give the number.")

for event in agent.run(conv, mode="instruct_coding"):
    if isinstance(event, TextDelta):
        print(event.content, end="", flush=True)
    elif isinstance(event, AgentDone):
        print(f"\n[done in {event.elapsed_s}s]")
