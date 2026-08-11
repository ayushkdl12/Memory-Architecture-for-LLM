from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..database import SessionLocal
from ..demo import get_or_create_demo_user
from ..models import ChatSession, MemoryAtom, Message, UserSettings
from ..schemas import ChatRequest
from .. import provider
from ..services.context import build_memory_context, build_system_prompt
from ..services.extractor import MemoryExtractor
from ..services.retrieval import RetrievalEngine
from ..services.temporal import TemporalManager

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


@router.post("")
def chat(body: ChatRequest) -> StreamingResponse:
    def gen():
        db = SessionLocal()
        try:
            user = get_or_create_demo_user(db)

            # --- resolve session -------------------------------------------------
            if body.session_id:
                session = db.get(ChatSession, body.session_id)
                if session is None:
                    yield _sse({"type": "error", "message": "session not found"})
                    return
            else:
                session = ChatSession(
                    user_id=user.user_id, title=(body.text[:40] or "New chat")
                )
                db.add(session)
                db.flush()
            yield _sse({"type": "session", "session_id": str(session.session_id)})

            # store the user turn ------------------------------------------------
            user_msg = Message(
                session_id=session.session_id, role="user", content=body.text
            )
            db.add(user_msg)
            db.flush()

            # If a photo was attached, let the description inform retrieval and
            # the reply (without polluting the stored message content).
            user_text = body.text
            if body.attachment and body.attachment.description:
                user_text = (
                    f"{body.text}\n\n"
                    f"[Attached photo: {body.attachment.description}]"
                )

            # Stale user-set expiries take effect at the start of every turn.
            from ..services.retention import expire_due_atoms
            from ..provider import get_vector_store as _get_vs

            for expired in expire_due_atoms(db):
                _get_vs().delete(str(expired.memory_id))

            # 1. memory extraction ------------------------------------------------
            turn_context = "\n".join(
                f"{t.role}: {t.content}" for t in body.history[-6:]
            )
            atoms = MemoryExtractor(provider.get_llm()).extract(
                body.text, turn_context, expires_at=body.expires_at
            )

            # 3. temporal fact tracking --------------------------------------------
            tm = TemporalManager(db)
            created = tm.process_atoms(
                user.user_id, session.session_id, user_msg.message_id, atoms
            )
            db.commit()

            # embed new atoms, drop embeddings of closed versions ----------------
            vs = provider.get_vector_store()
            ids = [c.memory_id for c in created]
            rows = (
                db.scalars(select(MemoryAtom).where(MemoryAtom.memory_id.in_(ids))).all()
                if ids
                else []
            )
            for row in rows:
                vs.upsert(
                    str(row.memory_id),
                    row.content,
                    {
                        "memory_type": row.memory_type,
                        "subject": row.subject,
                        "attribute": row.attribute,
                        "priority": row.priority,
                        "is_active": row.is_active,
                    },
                )
            for c in created:
                if c.closed_memory_id:
                    vs.delete(str(c.closed_memory_id))

            # 5. retrieval (semantic + active filter + priority) ------------------
            engine = RetrievalEngine(db, vs, provider.get_llm())
            retrieved = engine.retrieve(
                user.user_id,
                user_text,
                top_k=8,
                session_id=session.session_id,
                message_id=user_msg.message_id,
            )
            db.commit()

            # 6. web search (optional live context, with citations) ---------------
            from ..config import settings as app_settings
            from ..services.websearch import should_search

            web_block = ""
            if app_settings.web_search_enabled and should_search(user_text):
                try:
                    search_results = provider.get_search_service().search(user_text)
                except Exception:
                    search_results = []
                if search_results:
                    from ..models import SearchLog

                    db.add(
                        SearchLog(
                            session_id=session.session_id,
                            message_id=user_msg.message_id,
                            query_text=user_text,
                            results=[r.to_dict() for r in search_results],
                        )
                    )
                    db.commit()
                    yield _sse({"type": "search", "count": len(search_results)})
                    web_block = provider.get_search_service().format_context(
                        search_results
                    )

            memory_block = build_memory_context(retrieved)
            settings_row = db.get(UserSettings, user.user_id)
            instructions = settings_row.custom_instructions if settings_row else ""
            system = build_system_prompt(instructions)
            if memory_block:
                system += "\n" + memory_block
            if web_block:
                system += "\n\n" + web_block

            # 9. LLM response generation (streamed) --------------------------------
            turns = [{"role": t.role, "content": t.content} for t in body.history]
            stream = provider.get_llm().stream_chat(
                system=system, turns=turns, new_user_text=user_text
            )
            pieces: list[str] = []
            for chunk in stream:
                txt = getattr(chunk, "text", None) or ""
                if txt:
                    pieces.append(txt)
                    yield _sse({"type": "delta", "delta": txt})

            reply = "".join(pieces)
            asst = Message(
                session_id=session.session_id, role="assistant", content=reply
            )
            db.add(asst)
            session.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(asst)

            yield _sse(
                {
                    "type": "done",
                    "message_id": str(asst.message_id),
                    "atoms_created": sum(1 for c in created if c.action.startswith(("INSERT","UPDATE"))),
                    "atoms_reinforced": sum(1 for c in created if c.action == "REINFORCE"),
                    "memory_context_count": len(retrieved),
                    "retrieved": [
                        {
                            "kind": "memory",
                            "subject": r["atom"].subject,
                            "attribute": r["atom"].attribute,
                            "value": r["atom"].value[:60],
                            "expires_at": (
                                r["atom"].expires_at.isoformat()
                                if r["atom"].expires_at else None
                            ),
                        }
                        for r in retrieved
                        if "atom" in r
                    ]
                    + [
                        {
                            "kind": "document",
                            "filename": r["document"].filename,
                        }
                        for r in retrieved
                        if "atom" not in r
                    ],
                }
            )
        except Exception as exc:  # keep SSE alive on errors
            yield _sse({"type": "error", "message": str(exc)})
        finally:
            db.close()

    return StreamingResponse(gen(), media_type="text/event-stream")