"""02_streaming_chat.py — Multi-turn streaming conversation.

Shows:
- Maintaining conversation history across turns
- Streaming token-by-token output
- Thinking mode (extended reasoning)
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.events import TextDelta, ThinkingDelta, ThinkingComplete, AgentDone

agent = Agent()
conv = Conversation("You are a concise math tutor.")

turns = [
    "What is the Fibonacci sequence?",
    "Give me the first 10 numbers.",
    "What is the ratio between consecutive terms called?",
]

for user_msg in turns:
    print(f"\n[user] {user_msg}")
    print("[assistant] ", end="")
    conv.add_user(user_msg)

    for event in agent.run(conv, mode="instruct"):
        if isinstance(event, ThinkingDelta):
            pass  # thinking is internal — skip printing
        elif isinstance(event, TextDelta):
            print(event.content, end="", flush=True)
        elif isinstance(event, AgentDone):
            print(f"  ({event.elapsed_s}s)")
