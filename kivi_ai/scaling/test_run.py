"""Quick test: plan and run a goal end-to-end."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from kivi_ai.scaling import plan_and_run
from kivi_ai.scaling.agent import setup_logging

setup_logging()

goal  = "Search openai news only today, read neatly and get importnat tables and also cite exactly and wreite to task_openai folder a md file"
work_dir = "."

state = plan_and_run(
    goal,
    max_parallel=3,
    work_dir=work_dir,
)
print(f"\nFinal: {state['progress']} done, {state['failed']} failed, all_done={state['all_done']}")
