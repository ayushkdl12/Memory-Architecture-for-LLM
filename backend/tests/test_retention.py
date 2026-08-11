from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.demo import get_or_create_demo_user
from app.models import MemoryAtom, RetentionLog
from app.services.retention import RetentionManager

NOW = datetime.now(timezone.utc)


def _atom(db, user_id, *, mtype, priority, valid_from, value="v", access_count=0):
    row = MemoryAtom(
        user_id=user_id,
        memory_type=mtype,
        category="c",
        subject="user",
        attribute="x",
        value=value,
        content="some memory content",
        priority=priority,
        is_active=True,
        retention_status="ACTIVE",
        access_count=access_count,
        valid_from=valid_from,
    )
    db.add(row)
    db.flush()
    return row


def test_rule_always_kept(db):
    user = get_or_create_demo_user(db)
    m = _atom(db, user.user_id, mtype="RULE", priority="MEDIUM",
              valid_from=NOW - timedelta(days=500))
    mgr = RetentionManager(db, event_threshold_days=30, score_threshold=0.25)
    action, _ = mgr.decision(m, NOW)
    assert action == "KEEP"


def test_critical_always_kept(db):
    user = get_or_create_demo_user(db)
    m = _atom(db, user.user_id, mtype="EVENT", priority="CRITICAL",
             value="v", valid_from=NOW - timedelta(days=500))
    mgr = RetentionManager(db, event_threshold_days=30, score_threshold=0.25)
    action, _ = mgr.decision(m, NOW)
    assert action == "KEEP"


def test_old_event_archived(db):
    user = get_or_create_demo_user(db)
    m = _atom(db, user.user_id, mtype="EVENT", priority="LOW",
             value="v", valid_from=NOW - timedelta(days=60))
    mgr = RetentionManager(db, event_threshold_days=30, score_threshold=0.25)
    action, _ = mgr.decision(m, NOW)
    assert action == "ARCHIVE"


def test_recent_atom_kept(db):
    user = get_or_create_demo_user(db)
    m = _atom(db, user.user_id, mtype="FACT", priority="HIGH",
             value="v", valid_from=NOW)
    mgr = RetentionManager(db, event_threshold_days=30, score_threshold=0.25)
    action, _ = mgr.decision(m, NOW)
    assert action == "KEEP"


def test_sweep_archives_and_logs(db):
    user = get_or_create_demo_user(db)
    keep = _atom(db, user.user_id, mtype="RULE", priority="HIGH",
                 valid_from=NOW - timedelta(days=500))
    arch = _atom(db, user.user_id, mtype="EVENT", priority="LOW",
                 value="w", valid_from=NOW - timedelta(days=60))

    mgr = RetentionManager(db, event_threshold_days=30, score_threshold=0.25)
    archived, logs = mgr.run_sweep(dry_run=False)
    db.flush()

    assert arch.memory_id in [a.memory_id for a in archived]
    assert arch.retention_status == "ARCHIVED"
    assert arch.is_active is False
    assert keep.retention_status == "ACTIVE"

    log_rows = db.scalars(select(RetentionLog)).all()
    assert any(l.memory_id == arch.memory_id and l.action == "ARCHIVE" for l in log_rows)