"""08_markdown_agent_url.py — Fetch a URL → ChromaDB → MarkdownAgent query.

Shows:
- web_fetch storing page as markdown in ChromaDB, returning doc_id
- MarkdownAgent querying the stored doc via doc_id (LLM never sees full page)
- md_toc + md_get_section working on a fetched web page
"""
import sys, asyncio
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.tools.builtins import WebFetchTool, register_builtin_tools
from kivi_ai.core.registry import Registry
from kivi_ai.agents.markdown import MarkdownAgent

register_builtin_tools()

URL = "https://docs.python.org/3/library/asyncio.html"


async def fetch(url: str) -> str:
    tool = WebFetchTool()
    result = await tool.execute({"url": url})
    if result.is_error:
        raise RuntimeError(result.content)
    return result.content


# Fetch & store
print(f"Fetching {URL} ...")
fetch_result = asyncio.run(fetch(URL))
print(fetch_result[:300])

# Extract doc_id from result message
import re
m = re.search(r"doc_id: ([0-9a-f]{12})", fetch_result)
if not m:
    print("Could not extract doc_id from fetch result")
    sys.exit(1)

doc_id = m.group(1)
print(f"\ndoc_id: {doc_id}\n")

# Query with MarkdownAgent
agent = MarkdownAgent()

questions = [
    "What is asyncio used for? Give a one-paragraph summary.",
    "What are the main classes or functions available in this module?",
]

for q in questions:
    print(f"Q: {q}")
    print(f"A: {agent.chat(f'doc_id: {doc_id}\n\n{q}')}\n")
    agent.reset()
