"""Document upload & analysis (RAG).

Flow: upload a file -> parse text -> chunk it -> embed every chunk into the
vector store under synthetic ids `doc:<chunk_id>` -> the chunk rows live in
`document_chunks`. `RetrievalEngine` resolves those ids and injects the
relevant passages into the prompt, so the assistant can answer questions about
uploaded documents with citations to the filename.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..demo import get_or_create_demo_user
from ..models import ChatSession, Document, DocumentChunk
from ..schemas import DocumentOut, DocumentUploadResult
from ..services.documents import chunk_text, extract_text, is_supported
from .. import provider

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    from ..demo import demo_user_id

    rows = db.scalars(
        select(Document)
        .where(Document.user_id == demo_user_id())
        .order_by(Document.created_at.desc())
    ).all()
    return rows


@router.post("/upload", response_model=DocumentUploadResult)
def upload_document(
    file: UploadFile = File(...),
    session_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    user = get_or_create_demo_user(db)
    filename = file.filename or "document"
    mime = file.content_type or ""

    if not is_supported(filename, mime):
        raise HTTPException(
            400,
            "Unsupported file type. Use .pdf, .txt, .md, .csv, .json, "
            ".py, .js or .sql",
        )

    data = file.file.read()
    if len(data) > settings.document_max_bytes:
        raise HTTPException(
            413,
            f"File too large (max {settings.document_max_bytes // (1024 * 1024)} MB)",
        )

    text = extract_text(filename, mime, data).strip()
    if not text:
        raise HTTPException(422, "No readable text found in the file")

    if session_id is not None:
        session = db.get(ChatSession, session_id)
        if session is None or session.user_id != user.user_id:
            session_id = None

    chunks = chunk_text(text)
    doc = Document(
        user_id=user.user_id,
        session_id=session_id,
        filename=filename,
        mime_type=mime or "application/octet-stream",
        char_count=len(text),
        preview=text[:500],
    )
    db.add(doc)
    db.flush()

    vs = provider.get_vector_store()
    for i, chunk_text_value in enumerate(chunks):
        chunk = DocumentChunk(
            doc_id=doc.doc_id, chunk_index=i, text=chunk_text_value
        )
        db.add(chunk)
        db.flush()
        vs.upsert(
            f"doc:{chunk.chunk_id}",
            chunk_text_value,
            {
                "kind": "document",
                "doc_id": str(doc.doc_id),
                "filename": filename,
                "chunk_index": i,
                "is_active": True,
            },
        )

    db.commit()
    db.refresh(doc)

    return DocumentUploadResult(
        doc_id=doc.doc_id,
        filename=doc.filename,
        char_count=doc.char_count,
        chunk_count=len(chunks),
        preview=doc.preview,
    )


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: uuid.UUID, db: Session = Depends(get_db)):
    from ..demo import demo_user_id

    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != demo_user_id():
        raise HTTPException(404, "Document not found")
    vs = provider.get_vector_store()
    chunks = db.scalars(
        select(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
    ).all()
    for chunk in chunks:
        vs.delete(f"doc:{chunk.chunk_id}")
    db.delete(doc)
    db.commit()
