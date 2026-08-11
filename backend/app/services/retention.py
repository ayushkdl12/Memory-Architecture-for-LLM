"""Rule-based selective retention engine.

Deterministic, auditable retention policy (proposal Section 5 / R.5):

  Score(m,t) = a*I(m) + b*R(m,t) + c*F(m) + d*U(m)

  - I  importance (from priority)
  - R  recency: e^{-age/S}
  - F  access frequency: sigmoid over access_count
  - U  future utility (type-based prior)

- Non-retention-backbone types below the threshold tau are archived.
- RULE / CRITICAL atoms are always exempt (KEEP).
- EVENT atoms are archived after a threshold period unless high priority.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MemoryAtom, RetentionLog
from ..schemas import AtomOut

logger = logging.getLogger(__name__)

PRIORITY_IMPORTANCE = {
    "CRITICAL": 1.0,
    "HIGH": 0.8,
    "MEDIUM": 0.5,
    "LOW": 0.25,
}

TYPE_UTILITY = {
    "RULE": 0.9,
    "GOAL": 0.7,
    "PREFERENCE": 0.6,
    "FACT": 0.5,
    "EVENT": 0.3,
}


class RetentionManager:
    def __init__(
        self,
        db: Session,
        *,
        event_threshold_days: int = 30,
        score_threshold: float = 0.25,
        alpha: float = 0.4,
        beta: float = 0.3,
        gamma: float = 0.2,
        delta: float = 0.1,
        stability_days: float = 30.0,
    ):
        self.db = db
        self.event_threshold_days = event_threshold_days
        self.score_threshold = score_threshold
        self.alpha, self.beta, self.gamma, self.delta = alpha, beta, gamma, delta
        self.stability_days = stability_days

    # -- scoring -----------------------------------------------------------------
    def score(self, atom: MemoryAtom, now: datetime = None) -> float:
        now = now or datetime.now(timezone.utc)
        importance = PRIORITY_IMPORTANCE.get(atom.priority, 0.5)
        recency = math.exp(-_age_days(atom.valid_from, now) / self.stability_days)
        frequency = _frequency(atom.access_count)
        utility = TYPE_UTILITY.get(atom.memory_type, 0.4)

        return (
            self.alpha * importance
            + self.beta * recency
            + self.gamma * frequency
            + self.delta * utility
        )

    def is_exempt(self, atom: MemoryAtom) -> bool:
        # R.5.1: RULE atoms and CRITICAL priority are exempt from archiving.
        if atom.memory_type == "RULE":
            return True
        if atom.priority == "CRITICAL":
            return True
        return False

    def decision(self, atom: MemoryAtom, now: datetime = None) -> tuple[str, str | None]:
        """Return (action, reason)."""
        now = now or datetime.now(timezone.utc)
        # User-set expiry overrides everything; pinning overrides expiry
        # (a user who pins wants the memory kept).
        if atom.is_pinned:
            return "KEEP", "pinned by user; exempt from expiry and sweep"
        if atom.expires_at is not None and atom.expires_at <= now:
            return "ARCHIVE", f"expired on {atom.expires_at:%Y-%m-%d} per user request"
        if self.is_exempt(atom):
            return "KEEP", "RULE/CRITICAL exempt from archiving"

        # R.5.3: EVENT atoms past their threshold are archived.
        if atom.memory_type == "EVENT" and (now - atom.valid_from) > timedelta(
            days=self.event_threshold_days
        ):
            return "ARCHIVE", "EVENT older than threshold period"

        s = self.score(atom, now)
        if s < self.score_threshold:
            return "ARCHIVE", f"retention score {s:.2f} below threshold {self.score_threshold:.2f}"

        return "KEEP", f"retention score {s:.2f} >= threshold"

    # -- sweep -------------------------------------------------------------------
    def run_sweep(self, *, dry_run: bool = False) -> tuple[list[AtomOut], list[RetentionLog]]:
        now = datetime.now(timezone.utc)
        atoms = self.db.scalars(
            select(MemoryAtom).where(
                MemoryAtom.is_active.is_(True),
                MemoryAtom.retention_status == "ACTIVE",
            )
        ).all()

        archived: list[AtomOut] = []
        logs: list[RetentionLog] = []
        for atom in atoms:
            action, reason = self.decision(atom, now)
            score = self.score(atom, now)
            if action == "KEEP":
                if not dry_run:
                    self.db.add(
                        RetentionLog(
                            memory_id=atom.memory_id, action="KEEP",
                            reason=reason, score=round(score, 3),
                        )
                    )
                continue
            # ARCHIVE
            if not dry_run:
                atom.retention_status = "ARCHIVED"
                atom.is_active = False
                self.db.add(atom)
            archived.append(AtomOut.model_validate(atom))
            if not dry_run:
                self.db.add(
                    RetentionLog(
                        memory_id=atom.memory_id, action="ARCHIVE",
                        reason=reason, score=round(score, 3),
                    )
                )

        if not dry_run:
            self.db.flush()
            logs = self.db.scalars(
                select(RetentionLog).order_by(RetentionLog.created_at.desc())
            ).all()
        return archived, logs


def expire_due_atoms(db: Session, now: datetime | None = None) -> list[MemoryAtom]:
    """Archive every active memory whose user-set expiry has passed.

    Runs at the start of each chat turn and inside the retention sweep, so
    "remember X until <date>" memories disappear from retrieval automatically.
    Pinned atoms are exempt (the user chose to keep them indefinitely).
    """
    now = now or datetime.now(timezone.utc)
    due = db.scalars(
        select(MemoryAtom).where(
            MemoryAtom.is_active.is_(True),
            MemoryAtom.retention_status == "ACTIVE",
            MemoryAtom.is_pinned.is_(False),
            MemoryAtom.expires_at.is_not(None),
            MemoryAtom.expires_at <= now,
        )
    ).all()
    expired: list[MemoryAtom] = []
    for atom in due:
        atom.retention_status = "ARCHIVED"
        atom.is_active = False
        db.add(
            RetentionLog(
                memory_id=atom.memory_id,
                action="ARCHIVE",
                reason=f"expired on {atom.expires_at:%Y-%m-%d} per user request",
                score=round(0.0, 3),
            )
        )
        expired.append(atom)
    if due:
        db.flush()
    return expired


def _age_days(dt: datetime, now: datetime) -> float:
    if dt is None:
        return 0.0
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def _frequency(access_count: int) -> float:
    # sigmoid squashed into (0, 1): ~frequent access -> utility
    return 1.0 / (1.0 + math.exp(-0.5 * (access_count - 3)))