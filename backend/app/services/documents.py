"""Document parsing + chunking for file upload & analysis (RAG).

Supported: PDF (pypdf), plain text, Markdown, CSV, JSON.
Text is split into overlapping chunks sized to the embedding model; each chunk
is embedded into the vector store so `RetrievalEngine` can find the passages a
question needs (Claude Projects / ChatGPT file-analysis style).
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ..config import settings

PDF_MIME = "application/pdf"
TEXT_MIMES = {
    "text/plain": "txt",
    "text/markdown": "md",
    "text/csv": "csv",
    "application/json": "json",
    "text/x-python": "py",
    "application/x-python-code": "py",
}

ALLOWED_EXTS = {".pdf", ".txt", ".md", ".csv", ".json", ".py", ".js", ".sql"}


def is_supported(filename: str, mime: str) -> bool:
    ext = Path(filename).suffix.lower()
    return mime == PDF_MIME or ext in ALLOWED_EXTS


def extract_text(filename: str, mime: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" or mime == PDF_MIME:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    text = data.decode("utf-8", errors="replace")
    if ext == ".csv" or mime == "text/csv":
        rows = list(csv.reader(io.StringIO(text)))
        if rows:
            header = rows[0]
            lines = [", ".join(header)]
            for row in rows[1:]:
                lines.append(", ".join(row))
            return "\n".join(lines)
    if ext == ".json" or mime == "application/json":
        try:
            return json.dumps(json.loads(text), indent=2)
        except ValueError:
            return text
    return text


def chunk_text(text: str) -> list[str]:
    """Split into ~CHUNK_SIZE-char chunks with overlap (paragraph-friendly)."""
    size = settings.document_chunk_size
    overlap = settings.document_chunk_overlap
    step = max(1, size - overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks
