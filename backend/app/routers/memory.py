from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..demo import demo_user_id
from ..models import (
    ChatSession,
    FactVersion,
    MemoryAtom,
    Message,
    RetentionLog,
    RetrievalLog,
)
from ..schemas import (
    AtomIn,
    AtomOut,
    AtomUpdate,
    DashboardSummary,
    FactVersionOut,
    RetentionLogOut,
    RetentionSweepRequest,
    RetentionSweepResult,
    RetrievalLogOut,
)
from ..services.retention import RetentionManager
from ..services.temporal import TemporalManager

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _owned_atom(db: Session, memory_id: uuid.UUID) -> MemoryAtom:
    row = db.get(MemoryAtom, memory_id)
    if row is None or row.user_id != demo_user_id():
        raise HTTPException(status_code=404, detail="Atom not found")
    return row


def _embed(row: MemoryAtom):
    from ..provider import get_vector_store

    get_vector_store().upsert(
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


@router.get("/summary", response_model=DashboardSummary)
def summary(db: Session = Depends(get_db)):
    uid = demo_user_id()
    total = db.scalar(
        select(func.count()).select_from(MemoryAtom).where(MemoryAtom.user_id == uid)
    ) or 0
    active = db.scalar(
        select(func.count())
        .select_from(MemoryAtom)
        .where(MemoryAtom.user_id == uid, MemoryAtom.is_active.is_(True))
    ) or 0
    archived = db.scalar(
        select(func.count())
        .select_from(MemoryAtom)
        .where(MemoryAtom.user_id == uid, MemoryAtom.retention_status == "ARCHIVED")
    ) or 0
    sessions = db.scalar(
        select(func.count()).select_from(ChatSession).where(ChatSession.user_id == uid)
    ) or 0
    retr = db.scalar(select(func.count()).select_from(RetrievalLog)) or 0
    retn = db.scalar(select(func.count()).select_from(RetentionLog)) or 0
    from datetime import datetime, timedelta, timezone

    expiring = db.scalar(
        select(func.count())
        .select_from(MemoryAtom)
        .where(
            MemoryAtom.user_id == uid,
            MemoryAtom.is_active.is_(True),
            MemoryAtom.expires_at.is_not(None),
            MemoryAtom.expires_at <= datetime.now(timezone.utc) + timedelta(days=7),
        )
    ) or 0
    return DashboardSummary(
        active_atoms=active,
        archived_atoms=archived,
        total_atoms=total,
        total_sessions=sessions,
        retrieval_count=retr,
        retention_count=retn,
        expiring_soon=expiring,
    )


@router.get("/atoms", response_model=list[AtomOut])
def list_atoms(
    filter: str = Query("active", pattern="^(active|archived|all|ignored|pinned)$"),
    memory_type: str | None = Query(None),
    priority: str | None = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(MemoryAtom).where(MemoryAtom.user_id == demo_user_id())
    if filter == "active":
        stmt = stmt.where(MemoryAtom.is_active.is_(True))
    elif filter == "archived":
        stmt = stmt.where(MemoryAtom.retention_status == "ARCHIVED")
    elif filter == "ignored":
        stmt = stmt.where(MemoryAtom.retention_status == "IGNORED")
    elif filter == "pinned":
        stmt = stmt.where(MemoryAtom.is_pinned.is_(True))
    if memory_type:
        stmt = stmt.where(MemoryAtom.memory_type == memory_type.upper())
    if priority:
        stmt = stmt.where(MemoryAtom.priority == priority.upper())
    stmt = stmt.order_by(MemoryAtom.created_at.desc())
    return db.scalars(stmt).all()


@router.post("/atoms", response_model=AtomOut)
def create_atom(body: AtomIn, db: Session = Depends(get_db)):
    """Manually add a memory atom; runs through TemporalManager so versioning
    and the active-uniqueness invariant stay intact."""
    tm = TemporalManager(db)
    result = tm.process_atoms(
        demo_user_id(), session_id=None, source_message_id=None, atoms=[body.model_dump()]
    )[0]
    row = db.get(MemoryAtom, result.memory_id)
    if result.closed_memory_id:
        from ..provider import get_vector_store

        get_vector_store().delete(str(result.closed_memory_id))
    _embed(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/atoms/{memory_id}", response_model=AtomOut)
def update_atom(
    memory_id: uuid.UUID, body: AtomUpdate, db: Session = Depends(get_db)
):
    row = _owned_atom(db, memory_id)
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Another active atom already uses this subject/attribute",
        )
    db.commit()
    _embed(row)
    db.refresh(row)
    return row


@router.delete("/atoms/{memory_id}", status_code=204)
def delete_atom(memory_id: uuid.UUID, db: Session = Depends(get_db)):
    row = _owned_atom(db, memory_id)
    db.delete(row)
    db.commit()
    from ..provider import get_vector_store

    get_vector_store().delete(str(memory_id))


@router.post("/atoms/{memory_id}/restore", response_model=AtomOut)
def restore_atom(memory_id: uuid.UUID, db: Session = Depends(get_db)):
    """Re-activate an archived or superseded atom and re-embed it."""
    row = _owned_atom(db, memory_id)
    row.is_active = True
    row.retention_status = "ACTIVE"
    row.valid_until = None
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An active atom already exists for this subject/attribute",
        )
    db.commit()
    _embed(row)
    db.refresh(row)
    return row


@router.get("/atoms/{memory_id}/versions", response_model=list[FactVersionOut])
def atom_versions(memory_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.scalars(
        select(FactVersion).where(
            (FactVersion.old_memory_id == memory_id)
            | (FactVersion.new_memory_id == memory_id)
        )
    ).all()


@router.get("/fact-versions", response_model=list[FactVersionOut])
def list_fact_versions(db: Session = Depends(get_db)):
    return db.scalars(
        select(FactVersion)
        .where(FactVersion.user_id == demo_user_id())
        .order_by(FactVersion.changed_at.desc())
        .limit(200)
    ).all()


@router.get("/retrieval-logs", response_model=list[RetrievalLogOut])
def list_retrieval_logs(
    limit: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)
):
    return db.scalars(
        select(RetrievalLog).order_by(RetrievalLog.created_at.desc()).limit(limit)
    ).all()


@router.get("/retention-logs", response_model=list[RetentionLogOut])
def list_retention_logs(db: Session = Depends(get_db)):
    return db.scalars(
        select(RetentionLog).order_by(RetentionLog.created_at.desc()).limit(200)
    ).all()


@router.post("/retention/sweep", response_model=RetentionSweepResult)
def retention_sweep(body: RetentionSweepRequest, db: Session = Depends(get_db)):
    mgr = RetentionManager(
        db,
        event_threshold_days=30,
        score_threshold=0.25,
    )
    archived, logs = mgr.run_sweep(dry_run=body.dry_run)
    db.commit()
    return RetentionSweepResult(
        archived=[AtomOut.model_validate(a) for a in archived],
        logged=[RetentionLogOut.model_validate(l) for l in logs],
    )