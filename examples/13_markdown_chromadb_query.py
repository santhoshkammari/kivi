"""13_markdown_chromadb_query.py — Direct ChromaDB semantic search over ingested docs.

Shows:
- Bypassing the agent: query stored chunks directly with `query_chunks`
- Filter by `chunk_types` (header, paragraph, code, table, list, blockquote)
- Inspecting hit metadata (source, line number, similarity score)
- Useful for building retrieval pipelines without an LLM in the loop
"""
import sys
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from pathlib import Path
from kivi_ai.agents.markdown.store import ingest_markdown, query_chunks, list_documents

# Ingest the project README
result = ingest_markdown(
    str(Path(__file__).parents[1] / "README.md"),
    source_label="kivi-readme",
)
doc_id = result["doc_id"]
print(f"ingested: doc_id={doc_id} chunks={result['chunks']}\n")

# Semantic search — broad
print("── Semantic search: 'web server port and host config' ──")
hits = query_chunks("web server port and host config", doc_id=doc_id, n_results=5)
for h in hits:
    print(f"  [{h['type']:<10}] L{h['line']:<4} score={h['score']}  {h['text'][:80]}")

# Filter by chunk type — only code blocks
print("\n── Code blocks about installation ──")
for h in query_chunks("install pip extras", doc_id=doc_id, chunk_types=["code"], n_results=3):
    print(f"  L{h['line']}  score={h['score']}\n{h['text']}\n")

# Filter by chunk type — only headers (TOC-like)
print("── Headers matching 'agent' ──")
for h in query_chunks("agent", doc_id=doc_id, chunk_types=["header1", "header2", "header3"], n_results=10):
    print(f"  L{h['line']:<4} {h['text']}")

# Show all stored docs
print("\n── All stored documents ──")
for d in list_documents():
    print(f"  {d['doc_id']}  {d['source']}")
