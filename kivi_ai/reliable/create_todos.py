"""Standalone todo planner — takes a goal, returns list[str] of todos.

Usage:
    python create_todos.py "build a REST API with auth and tests"
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# allow running standalone
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parents[2]))

from kivi_ai.agent.agent import Agent
from kivi_ai.agent.messages import Conversation
from kivi_ai.agent.provider import OpenAIProvider
from kivi_ai.agent.tools import BashTool
from kivi_ai.agent.events import ToolCallComplete, AgentDone

_PLAN_SOUL = (
    "You are a task planner. Your ONLY job: run ONE shell_bash call with a python3 command that writes "
    "a JSON array of todo strings to {plan_file}.\n\n"
    "Rules:\n"
    "- Each todo is a short, independently executable action string\n"
    "- Use python loops for repetitive items so the list is exact\n"
    "- CRITICAL: use single quotes inside the python3 -c string to avoid shell quoting conflicts\n"
    "- The python3 -c code MUST end with:\n"
    "  import json; open('{plan_file}','w').write(json.dumps(todos))\n"
    "- Example command:\n"
    "  python3 -c \"import json; todos=['step 1','step 2']; open('{plan_file}','w').write(json.dumps(todos))\"\n"
    "- Call bash exactly once. No prose. No extra output."
)


def create_todos(goal: str, provider: OpenAIProvider | None = None) -> list[str]:
    """Decompose *goal* into a list of todo strings via LLM planner + bash."""
    plan_file = "/tmp/_kivi_reliable_plan.json"
    soul = _PLAN_SOUL.format(plan_file=plan_file)

    prov = provider or OpenAIProvider()
    agent = Agent(provider=prov, tools=[BashTool()], name="planner")
    conv = Conversation(system_prompt=soul)
    conv.add_user(f"Goal: {goal}\n\nRun the python3 -c command now.")

    if os.path.exists(plan_file):
        os.remove(plan_file)

    # stop as soon as plan file appears (model may self-correct quoting on retry)
    for event in agent.run(conv, mode="instruct", max_steps=10):
        if isinstance(event, ToolCallComplete) and os.path.exists(plan_file):
            break

    if not os.path.exists(plan_file):
        raise RuntimeError("Planner did not write /tmp/_kivi_reliable_plan.json")

    with open(plan_file) as f:
        todos = json.load(f)
    os.remove(plan_file)

    if not isinstance(todos, list) or not todos:
        raise RuntimeError(f"Expected non-empty list, got: {type(todos)}")
    if not all(isinstance(t, str) for t in todos):
        raise RuntimeError("All todos must be strings")
    return todos


if __name__ == "__main__":
    goal = " ".join(sys.argv[1:]) or "Write a hello world Python script"
    print(f"Planning: {goal}\n")
    todos = create_todos(goal)
    print(f"Generated {len(todos)} todos:")
    for i, t in enumerate(todos, 1):
        print(f"  {i}. {t}")
