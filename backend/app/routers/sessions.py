from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..demo import demo_user_id, get_or_create_demo_user
from ..models import ChatSession, Message
from ..schemas import MessageOut, SessionCreate, SessionOut

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _get_session(db: Session, session_id: uuid.UUID) -> ChatSession:
    sess = db.get(ChatSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


@router.get("", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db)):
    get_or_create_demo_user(db)
    db.commit()
    rows = db.scalars(
        select(ChatSession)
        .where(ChatSession.user_id == demo_user_id())
        .order_by(ChatSession.updated_at.desc())
    ).all()
    return rows


@router.post("", response_model=SessionOut)
def create_session(body: SessionCreate, db: Session = Depends(get_db)):
    user = get_or_create_demo_user(db)
    sess = ChatSession(user_id=user.user_id, title=body.title or "New chat")
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


@router.get("/{session_id}", response_model=dict)
def get_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    sess = _get_session(db, session_id)
    msgs = db.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    ).all()
    return {
        "session": SessionOut.model_validate(sess),
        "messages": [MessageOut.model_validate(m) for m in msgs],
    }


@router.patch("/{session_id}", response_model=SessionOut)
def rename_session(session_id: uuid.UUID, title: str, db: Session = Depends(get_db)):
    sess = _get_session(db, session_id)
    sess.title = title
    db.commit()
    db.refresh(sess)
    return sess


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    sess = _get_session(db, session_id)
    db.delete(sess)
    db.commit()


@router.post("/{session_id}/touch", status_code=204)
def touch_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    sess = _get_session(db, session_id)
    db.execute(
        update(ChatSession)
        .where(ChatSession.session_id == sess.session_id)
        .values(updated_at=datetime.now(timezone.utc))
    )
    db.commit()
