"""Temporal fact tracking.

Implements the versioning policy from the proposal (Section 4.3 / R.3):

- FACT / PREFERENCE / GOAL / RULE: at most one active version per
  (subject, attribute). New value -> close old (valid_until=now, is_active=false),
  insert new, log to fact_versions. Same value -> reinforce (touch updated_at).
- EVENT: point-in-time records that accumulate; identical events are reinforced.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FactVersion, MemoryAtom
from ..schemas import AtomCreated

logger = logging.getLogger(__name__)

VERSIONED_TYPES = {"FACT", "PREFERENCE", "GOAL", "RULE"}


class TemporalManager:
    def __init__(self, db: Session):
        self.db = db

    def process_atoms(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        source_message_id: uuid.UUID,
        atoms: list[dict],
    ) -> list[AtomCreated]:
        results: list[AtomCreated] = []
        for atom in atoms:
            results.append(
                self._upsert_atom(
                    user_id, session_id, source_message_id, atom
                )
            )
        self.db.flush()
        return results

    # -- helpers ----------------------------------------------------------------
    def _find_active(self, user_id, subject, attribute, mtype=None) -> MemoryAtom | None:
        stmt = select(MemoryAtom).where(
            MemoryAtom.user_id == user_id,
            MemoryAtom.subject == subject,
            MemoryAtom.attribute == attribute,
            MemoryAtom.is_active.is_(True),
        )
        if mtype == "EVENT":
            stmt = stmt.where(MemoryAtom.memory_type == "EVENT")
        return self.db.scalar(stmt.limit(1))

    def _close(self, atom: MemoryAtom, reason: str):
        from datetime import datetime, timezone

        atom.is_active = False
        atom.valid_until = datetime.now(timezone.utc)
        self.db.add(atom)

    def _insert_new(self, user_id, session_id, source_message_id, atom) -> MemoryAtom:
        from datetime import datetime, timezone

        from ..config import settings

        row = MemoryAtom(
            user_id=user_id,
            session_id=session_id,
            source_message_id=source_message_id,
            memory_type=atom["memory_type"],
            category=atom["category"],
            subject=atom["subject"],
            attribute=atom["attribute"],
            value=atom["value"],
            content=atom["content"],
            priority=atom["priority"],
            confidence_score=atom["confidence_score"],
            is_confirmed=atom["confidence_score"] >= settings.confidence_auto_commit,
            is_active=True,
            retention_status="ACTIVE",
            valid_from=datetime.now(timezone.utc),
            valid_until=None,
            expires_at=atom.get("expires_at") or None,
        )
        self.db.add(row)
        self.db.flush()  # assign PK
        return row

    def _log_version(self, user_id, subject, attribute, old_id, new_id, reason):
        self.db.add(
            FactVersion(
                user_id=user_id,
                subject=subject,
                attribute=attribute,
                old_memory_id=old_id,
                new_memory_id=new_id,
                change_reason=reason or None,
            )
        )

    def _upsert_atom(
        self, user_id, session_id, source_message_id, atom
    ) -> AtomCreated:
        mtype = atom["memory_type"]
        subject = atom["subject"]
        attribute = atom["attribute"]
        value = atom["value"]

        existing = self._find_active(user_id, subject, attribute)

        if existing is None:
            row = self._insert_new(user_id, session_id, source_message_id, atom)
            return AtomCreated(memory_id=row.memory_id, action="INSERT")

        if existing.value == value and existing.content == atom["content"]:
            # Same fact restated -> reinforcement: raise confidence, no duplicate
            # (R.3 "same value"). Repeated confirmation makes the fact stronger.
            existing.confidence_score = min(
                1.0, existing.confidence_score + 0.1
            )
            if existing.confidence_score >= 0.6:
                existing.is_confirmed = True
            if atom.get("expires_at"):
                existing.expires_at = atom["expires_at"]
            existing.updated_at = _utcnow()
            self.db.add(existing)
            return AtomCreated(memory_id=existing.memory_id, action="REINFORCE")

        # Value changed (or type transitioned) -> temporal versioning (R.3).
        if mtype in VERSIONED_TYPES or existing.memory_type in VERSIONED_TYPES:
            old_id = existing.memory_id
            self._close(existing, "superseded by newer value")
            row = self._insert_new(user_id, session_id, source_message_id, atom)
            self._log_version(
                user_id, subject, attribute, old_id, row.memory_id, atom.get("content")
            )
            return AtomCreated(
                memory_id=row.memory_id,
                action="UPDATE_NEW",
                closed_memory_id=old_id,
            )

        # Same (subject, attribute) but an unversioned accumulation type with a
        # new value -> just add a new active atom (e.g. multiple EVENTs).
        row = self._insert_new(user_id, session_id, source_message_id, atom)
        return AtomCreated(memory_id=row.memory_id, action="INSERT")


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
