from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.demo import get_or_create_demo_user
from app.models import ChatSession, FactVersion, MemoryAtom, Message
from app.services.temporal import TemporalManager

FAST = {
    "memory_type": "FACT",
    "category": "project",
    "subject": "user",
    "attribute": "language",
    "value": "Python",
    "content": "The user prefers Python.",
    "priority": "HIGH",
    "confidence_score": 0.9,
}


def _run(db, atoms):
    user = get_or_create_demo_user(db)
    sess = ChatSession(user_id=user.user_id, title="test")
    db.add(sess)
    db.flush()
    msg = Message(session_id=sess.session_id, role="user", content="hi")
    db.add(msg)
    db.flush()
    mgr = TemporalManager(db)
    created = mgr.process_atoms(user.user_id, sess.session_id, msg.message_id, atoms)
    db.flush()
    return created


def test_new_fact_inserted_as_active(db):
    created = _run(db, [FAST])
    assert created[0].action == "INSERT"
    row = db.get(MemoryAtom, created[0].memory_id)
    assert row.is_active is True
    assert row.valid_until is None


def test_same_value_reinforces_without_duplicate(db):
    first = _run(db, [FAST])[0]
    second = _run(db, [FAST])[0]
    assert second.action == "REINFORCE"
    assert second.memory_id == first.memory_id
    active = db.scalars(
        select(MemoryAtom).where(MemoryAtom.is_active.is_(True))
    ).all()
    assert len(active) == 1


def test_reinforcement_bumps_confidence_and_confirms(db):
    low = dict(FAST, confidence_score=0.5)
    first = _run(db, [low])[0]
    row = db.get(MemoryAtom, first.memory_id)
    assert row.is_confirmed is False  # below auto-commit threshold (0.6)

    _run(db, [low])  # restate the same fact
    row = db.get(MemoryAtom, first.memory_id)
    assert row.confidence_score == pytest.approx(0.6)
    assert row.is_confirmed is True


def test_low_confidence_atom_starts_unconfirmed(db):
    low = dict(FAST, confidence_score=0.4)
    created = _run(db, [low])[0]
    row = db.get(MemoryAtom, created.memory_id)
    assert row.is_confirmed is False

    high = dict(FAST, attribute="language2", confidence_score=0.8)
    created = _run(db, [high])[0]
    row = db.get(MemoryAtom, created.memory_id)
    assert row.is_confirmed is True


def test_value_change_versions_fact(db):
    first = _run(db, [FAST])[0]
    changed = dict(FAST, value="Go", content="Actually prefers Go now.")
    second = _run(db, [changed])[0]

    assert second.action == "UPDATE_NEW"
    assert second.closed_memory_id == first.memory_id
    assert second.memory_id != first.memory_id

    old = db.get(MemoryAtom, first.memory_id)
    new = db.get(MemoryAtom, second.memory_id)
    assert old.is_active is False
    assert old.valid_until is not None
    assert new.is_active is True
    assert new.valid_until is None

    version = db.scalars(select(FactVersion)).all()
    assert len(version) == 1
    assert version[0].old_memory_id == first.memory_id
    assert version[0].new_memory_id == second.memory_id


def test_events_accumulate_same_subject_attribute(db):
    e1 = {"memory_type": "EVENT", "category": "meeting", "subject": "user",
          "attribute": "event", "value": "defended proposal",
          "content": "User defended the proposal.", "priority": "MEDIUM",
          "confidence_score": 0.8}
    e2 = dict(e1, value="midterm", content="User had a midterm.")
    created = _run(db, [e1, e2])
    assert [c.action for c in created] == ["INSERT", "INSERT"]
    active = db.scalars(
        select(MemoryAtom).where(MemoryAtom.is_active.is_(True))
    ).all()
    assert len(active) == 2
