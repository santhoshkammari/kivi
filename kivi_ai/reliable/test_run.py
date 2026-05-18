"""Test the reliable agent system end-to-end."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from kivi_ai.reliable import plan_and_run, setup_logging

setup_logging()

goal = "Search for latest Python 3.13 release notes, summarize key new features, and write a markdown report to /tmp/py313_report.md"

state = plan_and_run(goal, work_dir="/tmp")

print(f"\nDone: {len(state.completed)} completed, {len(state.failed)} failed")
for r in state.completed:
    print(f"  ✓ #{r.todo_id} ({r.attempts} attempts): {r.description[:60]}")
for r in state.failed:
    print(f"  ✗ #{r.todo_id}: {r.description[:60]}")
