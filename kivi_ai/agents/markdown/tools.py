"""Markdown-specific tools for the MarkdownAgent."""
from __future__ import annotations

import json
from typing import Any

from kivi_ai.tools.markdown.tools import (
    markdown_analyzer_get_headers,
    markdown_analyzer_get_code_blocks,
    markdown_analyzer_get_tables_metadata,
    markdown_analyzer_get_table_by_line,
    markdown_analyzer_get_header_by_line,
    markdown_analyzer_get_intro,
    markdown_analyzer_get_links,
    markdown_analyzer_get_lists,
    markdown_analyzer_get_overview,
    markdown_analyzer_get_paragraphs,
)

from .store import (
    delete_document,
    get_overview,
    ingest_markdown,
    list_documents,
    resolve_source,
)

from kivi_ai.agent.context import Context
from kivi_ai.agent.tools import ToolInfo, ToolRequest, ToolResponse, _BaseTool

_OUTPUT_LIMIT = 12000

_SOURCE_DESC = "Pass a doc_id (12-char hex from md_ingest/web_fetch), a file path, or raw markdown. Always use the key 'source'."


def _truncate(text: str, limit: int = _OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _fmt(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def _src(request: ToolRequest) -> str:
    """Resolve source: accepts 'source' or 'doc_id' key."""
    val = request.arguments.get("source") or request.arguments.get("doc_id", "")
    return resolve_source(str(val))


# ── Store management tools ────────────────────────────────────────────

class IngestTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_ingest",
            description=(
                "Ingest a markdown file or raw markdown string into ChromaDB. "
                "Returns doc_id and chunk count. Use the doc_id with all other md_* tools."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "File path or raw markdown string."},
                    "label": {"type": "string", "description": "Human-readable name (optional)."},
                },
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            source = str(request.arguments["source"])
            label = request.arguments.get("label")
            result = ingest_markdown(source, source_label=label)
            return ToolResponse(_fmt(result))
        except Exception as exc:
            return self._fail("md_ingest", exc)


class ListDocsTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_list_docs",
            description="List all documents currently stored in ChromaDB with their doc_ids.",
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            docs = list_documents()
            if not docs:
                return ToolResponse("No documents ingested yet.")
            return ToolResponse(_fmt(docs))
        except Exception as exc:
            return self._fail("md_list_docs", exc)


class DeleteDocTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_delete_doc",
            description="Delete a document and all its chunks from ChromaDB by doc_id.",
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "doc_id from md_list_docs."},
                },
                "required": ["doc_id"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            n = delete_document(str(request.arguments["doc_id"]))
            return ToolResponse(f"Deleted {n} chunks.")
        except Exception as exc:
            return self._fail("md_delete_doc", exc)


# ── Overview / TOC ────────────────────────────────────────────────────

class GetOverviewTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_overview",
            description=(
                "Eagle-eye overview: structure, headers, stats, intro, tables, code blocks. "
                "Always call this first on a new document."
            ),
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string", "description": _SOURCE_DESC}},
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            import re
            raw_source = str(request.arguments["source"])
            # For doc_id, use the stored overview (fast path — no re-parsing)
            if re.fullmatch(r"[0-9a-f]{12}", raw_source.strip()):
                cached = get_overview(raw_source.strip())
                if cached:
                    return ToolResponse(_truncate(cached))
            text = resolve_source(raw_source)
            return ToolResponse(_truncate(_fmt(markdown_analyzer_get_overview(text))))
        except Exception as exc:
            return self._fail("md_overview", exc)


class GetTOCTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_toc",
            description=(
                "Full Table of Contents: every header with line number, indent level, "
                "and counts of tables/code/lists under it. Best first structural map."
            ),
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string", "description": _SOURCE_DESC}},
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            from kivi_ai.tools.markdown.mrkdwn_analysis import MarkdownAnalyzer
            text = _src(request)
            analyzer = MarkdownAnalyzer.from_string(text)
            tokens = analyzer.tokens
            headers = [t for t in tokens if t.type == "header"]
            if not headers:
                return ToolResponse("No headers found.")

            lines = []
            for i, h in enumerate(headers):
                start = h.line
                end = headers[i + 1].line if i + 1 < len(headers) else float("inf")
                n_tables = sum(1 for t in tokens if t.type == "table" and start < (t.line or 0) < end)
                n_code   = sum(1 for t in tokens if t.type == "code" and start < (t.line or 0) < end)
                n_lists  = sum(1 for t in tokens if t.type in ("ordered_list", "unordered_list") and start < (t.line or 0) < end)
                indent = "  " * (h.level - 1)
                extras = []
                if n_tables: extras.append(f"{n_tables} table{'s' if n_tables>1 else ''}")
                if n_code:   extras.append(f"{n_code} code block{'s' if n_code>1 else ''}")
                if n_lists:  extras.append(f"{n_lists} list{'s' if n_lists>1 else ''}")
                suffix = f"  [{', '.join(extras)}]" if extras else ""
                lines.append(f"{indent}L{start:>4}  H{h.level}  {h.content}{suffix}")

            return ToolResponse("\n".join(lines))
        except Exception as exc:
            return self._fail("md_toc", exc)


# ── Surgical extraction tools ─────────────────────────────────────────

class GetHeadersTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_get_headers",
            description="List all headers with line numbers and levels.",
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string", "description": _SOURCE_DESC}},
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            return ToolResponse(_truncate(_fmt(markdown_analyzer_get_headers(_src(request)))))
        except Exception as exc:
            return self._fail("md_get_headers", exc)


class GetSectionByHeaderTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_get_section",
            description="Extract full content of a section by its header line number. Call md_toc first to find line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": _SOURCE_DESC},
                    "line_number": {"type": "integer", "description": "Line number of the header."},
                },
                "required": ["source", "line_number"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            result = markdown_analyzer_get_header_by_line(_src(request), int(request.arguments["line_number"]))
            return ToolResponse(_truncate(_fmt(result)))
        except Exception as exc:
            return self._fail("md_get_section", exc)


class GetCodeBlocksTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_get_code_blocks",
            description="Extract all code blocks with language and line numbers.",
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string", "description": _SOURCE_DESC}},
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            return ToolResponse(_truncate(_fmt(markdown_analyzer_get_code_blocks(_src(request)))))
        except Exception as exc:
            return self._fail("md_get_code_blocks", exc)


class GetTablesMetaTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_get_tables",
            description="List all tables with line numbers, column counts and header previews.",
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string", "description": _SOURCE_DESC}},
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            return ToolResponse(_truncate(_fmt(markdown_analyzer_get_tables_metadata(_src(request)))))
        except Exception as exc:
            return self._fail("md_get_tables", exc)


class GetTableByLineTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_get_table",
            description="Extract and render a specific table as a grid. Call md_get_tables first to find the line number.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": _SOURCE_DESC},
                    "line_number": {"type": "integer", "description": "Line number where the table starts."},
                },
                "required": ["source", "line_number"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            result = markdown_analyzer_get_table_by_line(_src(request), int(request.arguments["line_number"]))
            return ToolResponse(_truncate(_fmt(result)))
        except Exception as exc:
            return self._fail("md_get_table", exc)


class GetLinksTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_get_links",
            description="Extract all HTTP/HTTPS links with line numbers.",
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string", "description": _SOURCE_DESC}},
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            return ToolResponse(_truncate(_fmt(markdown_analyzer_get_links(_src(request)))))
        except Exception as exc:
            return self._fail("md_get_links", exc)


class GetListsTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_get_lists",
            description="Extract all ordered and unordered lists with their items.",
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string", "description": _SOURCE_DESC}},
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            return ToolResponse(_truncate(_fmt(markdown_analyzer_get_lists(_src(request)))))
        except Exception as exc:
            return self._fail("md_get_lists", exc)


class GetIntroTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_get_intro",
            description="Extract the introduction/abstract/summary section.",
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string", "description": _SOURCE_DESC}},
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            return ToolResponse(_truncate(_fmt(markdown_analyzer_get_intro(_src(request)))))
        except Exception as exc:
            return self._fail("md_get_intro", exc)


class GetParagraphsTool(_BaseTool):
    def info(self) -> ToolInfo:
        return ToolInfo(
            name="md_get_paragraphs",
            description="Extract all paragraphs with their line numbers.",
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string", "description": _SOURCE_DESC}},
                "required": ["source"],
            },
        )

    def run(self, ctx: Context, request: ToolRequest) -> ToolResponse:
        try:
            return ToolResponse(_truncate(_fmt(markdown_analyzer_get_paragraphs(_src(request)))))
        except Exception as exc:
            return self._fail("md_get_paragraphs", exc)


# ── Tool list factory ─────────────────────────────────────────────────

def markdown_tools() -> list:
    return [
        IngestTool(),
        ListDocsTool(),
        DeleteDocTool(),
        GetOverviewTool(),
        GetTOCTool(),
        GetHeadersTool(),
        GetSectionByHeaderTool(),
        GetCodeBlocksTool(),
        GetTablesMetaTool(),
        GetTableByLineTool(),
        GetLinksTool(),
        GetListsTool(),
        GetIntroTool(),
        GetParagraphsTool(),
    ]
