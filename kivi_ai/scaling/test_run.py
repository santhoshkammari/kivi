"""Quick test: plan and run a goal end-to-end."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from kivi_ai.scaling import plan_and_run
from kivi_ai.scaling.agent import setup_logging

setup_logging()

state = plan_and_run(
    input("Task: "),
    max_parallel=3,
)
print(f"\nFinal: {state['progress']} done, {state['failed']} failed, all_done={state['all_done']}")
