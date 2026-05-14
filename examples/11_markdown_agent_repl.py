"""11_markdown_agent_repl.py — Interactive MarkdownAgent REPL.

Shows:
- run_markdown_agent() interactive REPL with rich streaming output
- Pre-ingesting a file before starting the REPL
- How to use the REPL for exploratory document analysis

Usage:
    python examples/11_markdown_agent_repl.py
    python examples/11_markdown_agent_repl.py --file /path/to/doc.md
"""
import sys, argparse
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.agents.markdown import run_markdown_agent
from kivi_ai.agents.markdown.store import ingest_markdown

parser = argparse.ArgumentParser()
parser.add_argument("--file", default=None, help="Markdown file to pre-ingest before REPL")
parser.add_argument("--base-url", default="http://192.168.170.49:8077/v1")
args = parser.parse_args()

if args.file:
    result = ingest_markdown(args.file)
    print(f"Ingested: {result['source']}  doc_id={result['doc_id']}  chunks={result['chunks']}")
    print(f"Use doc_id '{result['doc_id']}' as the source argument in tools.\n")

run_markdown_agent(base_url=args.base_url)
