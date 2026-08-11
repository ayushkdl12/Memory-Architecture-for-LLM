"""Retrieval engine.

Five-stage pipeline (proposal Section 4.6):

  1. Semantic pre-retrieval  -> vector store top-k candidates
  2. Active status filter    -> is_active AND valid_until IS NULL
  3. Type-relevance filter   -> RULE always; GOAL on task queries; rest by score
  4. Priority ranking        -> CRITICAL > HIGH > MEDIUM > LOW
  5. Context assembly        -> (done by ContextBuilder)

Uploaded document chunks (vector ids `doc:<chunk_id>`) are resolved from
`document_chunks` and injected as `<document filename>` passages alongside
memory atoms, so questions can be answered from file contents (RAG).
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Document, DocumentChunk, MemoryAtom, RetrievalLog
from ..vectorstore import VectorStore
from .llm import LLMService

PRIORITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

TASK_KEYWORDS = ("task", "goal", "objective", "todo", "plan", "finish", "complete",
                 "deadline", "progress", "next")

RECENCY_HALF_LIFE_DAYS = 30.0

MAX_DOC_CHUNKS = 3


def _recency(atom: MemoryAtom, now: datetime) -> float:
    """Decay by age of valid_from; fresher facts rank higher (0..1)."""
    age = max(0.0, (now - atom.valid_from).total_seconds() / 86400.0)
    return math.exp(-age / RECENCY_HALF_LIFE_DAYS)


class RetrievalEngine:
    def __init__(self, db: Session, vector_store: VectorStore, llm: LLMService):
        self.db = db
        self.vector_store = vector_store
        self.llm = llm

    def retrieve(
        self,
        user_id: uuid.UUID,
        query: str,
        *,
        top_k: int = 8,
        session_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """Return list of {"atom": MemoryAtom, "score": float} and/or
        {"kind": "document", "document": Document, "chunk": DocumentChunk,
        "score": float}."""
        # 1. Semantic pre-retrieval
        try:
            qv = self.llm.embed([query])[0]
        except Exception:
            qv = None
        if qv is None:
            return []
        candidates = self.vector_store.query(qv, top_k=top_k)

        # Optional cosine threshold: drop clearly irrelevant candidates so the
        # model's context is not wasted (R.4.4).
        min_score = settings.retrieval_min_score
        if min_score > 0:
            candidates = [c for c in candidates if c.get("score", 0.0) >= min_score]

        atom_ids: list[uuid.UUID] = []
        doc_ids: list[str] = []
        for c in candidates:
            cid = c.get("memory_id")
            if isinstance(cid, str) and cid.startswith("doc:"):
                doc_ids.append(cid[4:])
            else:
                try:
                    atom_ids.append(uuid.UUID(str(cid)))
                except (TypeError, ValueError):
                    continue

        # 2. Active-status filter for memory atoms (R.4.2 / R.4.3)
        active: dict[str, MemoryAtom] = {}
        if atom_ids:
            active = {
                str(a.memory_id): a
                for a in self.db.scalars(
                    select(MemoryAtom).where(
                        MemoryAtom.memory_id.in_(atom_ids),
                        MemoryAtom.user_id == user_id,
                        MemoryAtom.is_active.is_(True),
                        MemoryAtom.valid_until.is_(None),
                    )
                ).all()
            }

        results: list[dict] = []
        for c in candidates:
            cid = c.get("memory_id")
            if isinstance(cid, str) and cid.startswith("doc:"):
                if cid[4:] in doc_ids:
                    chunk = self.db.get(DocumentChunk, uuid.UUID(cid[4:]))
                    if chunk is not None:
                        document = self.db.get(Document, chunk.doc_id)
                        results.append(
                            {
                                "kind": "document",
                                "document": document,
                                "chunk": chunk,
                                "score": c.get("score", 0.0),
                            }
                        )
            else:
                atom = active.get(str(cid))
                if atom is not None:
                    results.append({"atom": atom, "score": c.get("score", 0.0)})

        # 3. Type-relevance filter (R.4.4) — atoms only; docs always kept.
        is_task = any(k in query.lower() for k in TASK_KEYWORDS)
        kept: list[dict] = []
        for r in results:
            if "atom" not in r:
                kept.append(r)
                continue
            t = r["atom"].memory_type
            if t == "RULE":
                kept.append(r)                       # always included
            elif t == "GOAL" and is_task:
                kept.append(r)
            elif t in ("FACT", "PREFERENCE", "EVENT"):
                kept.append(r)                        # decided by semantic score
            # GOAL on non-task queries -> dropped

        # 4. Priority + recency + score ranking (R.4.4); doc chunks after
        #    atoms, ranked by similarity, capped.
        now = datetime.now(timezone.utc)
        atoms = [r for r in kept if "atom" in r]
        docs = sorted(
            (r for r in kept if "atom" not in r),
            key=lambda r: -r["score"],
        )[:MAX_DOC_CHUNKS]
        atoms.sort(
            key=lambda r: (
                PRIORITY_RANK.get(r["atom"].priority, 9),
                -_recency(r["atom"], now),
                -r["score"],
            )
        )
        kept = atoms + docs

        # Track access frequency for retention scoring.
        retrieved_ids: list[str] = []
        for r in kept:
            if "atom" in r:
                r["atom"].access_count += 1
                self.db.add(r["atom"])
                retrieved_ids.append(str(r["atom"].memory_id))
            else:
                retrieved_ids.append(f"doc:{r['chunk'].chunk_id}")

        # 5. Log the retrieval event (R.6.2).
        self.db.add(
            RetrievalLog(
                session_id=session_id,
                message_id=message_id,
                query_text=query,
                retrieved_memory_ids=retrieved_ids,
                retrieval_reason="semantic + active-filter + priority-rank",
            )
        )
        self.db.flush()
        return kept
