"""ChromaDB-backed content store for markdown documents."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from kivi_ai.tools.markdown.mrkdwn_analysis import MarkdownAnalyzer
from kivi_ai.tools.markdown.tools import markdown_analyzer_get_overview

_CHROMA_PATH = str(Path.home() / ".kivi" / "markdown_store")

_client: chromadb.Client | None = None


def _get_client() -> chromadb.Client:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=_CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def _collection(name: str = "markdown_chunks") -> chromadb.Collection:
    return _get_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def _doc_id(source: str) -> str:
    return hashlib.md5(source.encode()).hexdigest()[:12]


# ── Ingestion ─────────────────────────────────────────────────────────

def ingest_markdown(source: str, source_label: str | None = None) -> dict[str, Any]:
    """Parse markdown and store chunks in ChromaDB.

    source: file path or raw markdown string
    Returns summary dict with chunk count and doc_id.
    """
    p = Path(source)
    if len(source) <= 260 and p.exists():
        analyzer = MarkdownAnalyzer(source)
        label = source_label or str(p)
        raw_text = p.read_text(encoding="utf-8")
    else:
        analyzer = MarkdownAnalyzer.from_string(source)
        label = source_label or "inline"
        raw_text = source

    doc_id = _doc_id(label)
    col = _collection()

    chunks: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []

    for i, token in enumerate(analyzer.tokens):
        if token.type == "header":
            text = f"{'#' * token.level} {token.content}"
            chunk_type = f"header{token.level}"
        elif token.type == "paragraph":
            text = token.content.strip()
            chunk_type = "paragraph"
        elif token.type == "code":
            lang = token.meta.get("language") or "text"
            text = f"```{lang}\n{token.content}\n```"
            chunk_type = "code"
        elif token.type == "table":
            headers = token.meta.get("header", [])
            rows = token.meta.get("rows", [])
            lines = ["| " + " | ".join(headers) + " |"]
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in rows:
                lines.append("| " + " | ".join(row) + " |")
            text = "\n".join(lines)
            chunk_type = "table"
        elif token.type in ("ordered_list", "unordered_list"):
            items = token.meta.get("items", [])
            prefix = "1. " if token.type == "ordered_list" else "- "
            text = "\n".join(prefix + it.get("text", str(it)) for it in items)
            chunk_type = "list"
        elif token.type == "blockquote":
            text = "> " + token.content.strip().replace("\n", "\n> ")
            chunk_type = "blockquote"
        else:
            continue

        if not text.strip():
            continue

        chunk_id = f"{doc_id}_{i}"
        chunks.append(text)
        metadatas.append({
            "doc_id": doc_id,
            "source": label,
            "type": chunk_type,
            "line": token.line or 0,
            "chunk_index": i,
        })
        ids.append(chunk_id)

    if not chunks:
        return {"doc_id": doc_id, "source": label, "chunks": 0}

    # Upsert in batches of 100
    batch = 100
    for start in range(0, len(chunks), batch):
        col.upsert(
            documents=chunks[start:start + batch],
            metadatas=metadatas[start:start + batch],
            ids=ids[start:start + batch],
        )

    # Store overview and raw text as special chunks
    overview = markdown_analyzer_get_overview(raw_text)
    col.upsert(
        documents=[overview],
        metadatas=[{"doc_id": doc_id, "source": label, "type": "overview", "line": 0, "chunk_index": -1}],
        ids=[f"{doc_id}_overview"],
    )
    col.upsert(
        documents=[raw_text],
        metadatas=[{"doc_id": doc_id, "source": label, "type": "raw", "line": 0, "chunk_index": -2}],
        ids=[f"{doc_id}_raw"],
    )

    return {"doc_id": doc_id, "source": label, "chunks": len(chunks)}


# ── Retrieval ─────────────────────────────────────────────────────────

def query_chunks(
    query: str,
    doc_id: str | None = None,
    chunk_types: list[str] | None = None,
    n_results: int = 8,
) -> list[dict[str, Any]]:
    """Semantic search over stored chunks.

    Returns list of {text, source, type, line, score} dicts.
    """
    col = _collection()
    where: dict | None = None

    conditions = []
    if doc_id:
        conditions.append({"doc_id": {"$eq": doc_id}})
    if chunk_types:
        conditions.append({"type": {"$in": chunk_types}})

    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}

    try:
        results = col.query(
            query_texts=[query],
            n_results=min(n_results, col.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    hits = []
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    dists = results["distances"][0] if results["distances"] else []

    for doc, meta, dist in zip(docs, metas, dists):
        hits.append({
            "text": doc,
            "source": meta.get("source", ""),
            "type": meta.get("type", ""),
            "line": meta.get("line", 0),
            "doc_id": meta.get("doc_id", ""),
            "score": round(1.0 - dist, 4),
        })

    return hits


def list_documents() -> list[dict[str, Any]]:
    """List all ingested documents with their doc_ids."""
    col = _collection()
    results = col.get(where={"type": {"$eq": "overview"}}, include=["metadatas"])
    docs = []
    for meta in results.get("metadatas", []):
        docs.append({"doc_id": meta.get("doc_id", ""), "source": meta.get("source", "")})
    return docs


def get_overview(doc_id: str) -> str | None:
    """Retrieve the stored overview for a document."""
    col = _collection()
    results = col.get(ids=[f"{doc_id}_overview"], include=["documents"])
    docs = results.get("documents", [])
    return docs[0] if docs else None


def get_raw_text(doc_id: str) -> str | None:
    """Retrieve the original raw markdown text for a document."""
    col = _collection()
    results = col.get(ids=[f"{doc_id}_raw"], include=["documents"])
    docs = results.get("documents", [])
    return docs[0] if docs else None


def resolve_source(source: str) -> str:
    """Resolve source to raw markdown text.

    Accepts:
    - doc_id (12-char hex) → loads raw text from ChromaDB
    - file path            → reads file
    - raw markdown string  → returns as-is
    """
    import re
    # doc_id: 12 hex chars, no spaces, no newlines
    if re.fullmatch(r"[0-9a-f]{12}", source.strip()):
        raw = get_raw_text(source.strip())
        if raw:
            return raw
    # file path
    p = Path(source)
    if len(source) <= 260 and p.exists():
        return p.read_text(encoding="utf-8")
    # raw markdown
    return source


def delete_document(doc_id: str) -> int:
    """Delete all chunks for a document. Returns number of deleted chunks."""
    col = _collection()
    results = col.get(where={"doc_id": {"$eq": doc_id}}, include=["metadatas"])
    ids = results.get("ids", [])
    if ids:
        col.delete(ids=ids)
    return len(ids)
