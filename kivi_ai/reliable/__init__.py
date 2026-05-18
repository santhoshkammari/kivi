"""Reliable agent system — UserAgent + AssistantAgent with verification."""
from .agents import AssistantAgent, UserAgent, RunState, TodoResult, run, setup_logging
from .create_todos import create_todos

__all__ = [
    "AssistantAgent", "UserAgent", "RunState", "TodoResult",
    "run", "setup_logging", "create_todos",
]


def plan_and_run(
    goal: str,
    work_dir: str = ".",
    max_retries: int = 3,
    drift_every: int = 5,
) -> RunState:
    """Full pipeline: plan todos via LLM, then run with verification."""
    import logging
    from ..agent.provider import OpenAIProvider
    prov = OpenAIProvider()
    log = logging.getLogger("kivi.reliable")
    todos = create_todos(goal, provider=prov)
    log.info("Plan (%d todos):", len(todos))
    for i, t in enumerate(todos, 1):
        log.info("  %d. %s", i, t)
    return run(goal, todos, work_dir=work_dir, max_retries=max_retries,
               drift_every=drift_every, provider=prov)
