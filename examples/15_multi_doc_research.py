"""15_multi_doc_research.py — Fetch multiple URLs, cross-document Q&A.

Shows:
- Programmatically fetching N pages with WebFetchTool → list of doc_ids
- Running MarkdownAgent on each separately, then combining
- Useful for comparison/aggregation tasks ('compare X across these N sources')
"""
import sys, asyncio
sys.path.insert(0, __import__("pathlib").Path(__file__).parents[1].__str__())

from kivi_ai.tools.builtins import WebFetchTool
from kivi_ai.agents.markdown import MarkdownAgent

URLS = [
    "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "https://en.wikipedia.org/wiki/Rust_(programming_language)",
    "https://en.wikipedia.org/wiki/Go_(programming_language)",
]

QUESTION = "Who is the original designer/creator and what year was it first released?"


async def fetch_all(urls):
    fetcher = WebFetchTool()
    results = []
    for url in urls:
        r = await fetcher.execute({"url": url})
        # web_fetch result text contains 'doc_id: <hex>'
        line = next((l for l in r.content.splitlines() if l.startswith("doc_id:")), "")
        doc_id = line.split(":", 1)[1].strip() if line else ""
        results.append((url, doc_id))
        print(f"  fetched {url} → doc_id={doc_id}")
    return results


print("── Fetching pages ──")
fetched = asyncio.run(fetch_all(URLS))

print("\n── Asking MarkdownAgent on each ──")
agent = MarkdownAgent()
answers = []
for url, doc_id in fetched:
    if not doc_id:
        print(f"\n[skip] {url} — no doc_id"); continue
    answer = agent.chat(f"doc_id: {doc_id}\n\n{QUESTION}")
    print(f"\n{url}\n  {answer.strip()}")
    answers.append((url, answer))
    agent.reset()

print("\n── Summary ──")
for url, ans in answers:
    name = url.rsplit("/", 1)[-1].replace("_", " ").replace("(programming language)", "").strip()
    print(f"  {name:<8} {ans.strip().splitlines()[0][:120]}")
