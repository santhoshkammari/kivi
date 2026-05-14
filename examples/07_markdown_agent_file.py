"""07_markdown_agent_file.py — MarkdownAgent on a local file.

Shows:
- Ingesting a local .md file into ChromaDB
- Querying it with MarkdownAgent (never loads full text into LLM context)
- Tools: md_toc, md_get_section, md_get_tables, md_get_code_blocks
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agents.markdown import MarkdownAgent
from kivi_ai.agents.markdown.store import ingest_markdown

MD_FILE = str(__import__("pathlib").Path(__file__).parents[1] / "README.md")

# Step 1: ingest once — subsequent runs reuse the stored doc_id
result = ingest_markdown(MD_FILE, source_label="kivi-readme")
doc_id = result["doc_id"]
print(f"Ingested: {result['source']}  doc_id={doc_id}  chunks={result['chunks']}\n")

# Step 2: ask questions — agent works surgically via tools
agent = MarkdownAgent()

questions = [
    f"doc_id: {doc_id}\n\nWhat CLI flags does kivi support?",
    f"doc_id: {doc_id}\n\nList all providers and whether they support thinking mode.",
    f"doc_id: {doc_id}\n\nWhat is the default port and how do I change it?",
]

for q in questions:
    print("=" * 60)
    user_q = q.split("\n\n", 1)[1]
    print(f"Q: {user_q}")
    print(f"A: {agent.chat(q)}\n")
    agent.reset()  # fresh conversation each time
