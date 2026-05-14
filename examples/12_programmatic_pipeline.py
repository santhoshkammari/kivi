"""12_programmatic_pipeline.py — Programmatic pipeline without REPL.

Shows:
- Using MarkdownAgent.chat() in a loop (no REPL, no rich output)
- Batch processing multiple questions against the same document
- agent.reset() to clear conversation between independent questions
- Suitable for scripts, notebooks, CI pipelines
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agents.markdown import MarkdownAgent
from kivi_ai.agents.markdown.store import ingest_markdown, list_documents

# Ingest (idempotent — ChromaDB upserts, so safe to call repeatedly)
result = ingest_markdown(
    str(__import__("pathlib").Path(__file__).parents[1] / "README.md"),
    source_label="kivi-readme",
)
doc_id = result["doc_id"]
print(f"doc_id={doc_id}  chunks={result['chunks']}\n")

agent = MarkdownAgent()

QUESTIONS = [
    "What optional extras can I install with pip?",
    "Which providers support the thinking feature?",
    "What is the default host and port for the web server?",
    "How does auto-compaction work?",
    "List all API endpoints with their HTTP methods.",
]

for i, q in enumerate(QUESTIONS, 1):
    answer = agent.chat(f"doc_id: {doc_id}\n\n{q}")
    print(f"Q{i}: {q}")
    print(f"A{i}: {answer}\n{'─'*60}\n")
    agent.reset()

# Show all stored documents
print("\nAll stored documents:")
for doc in list_documents():
    print(f"  {doc['doc_id']}  {doc['source']}")
