"""Ensure a stable demo user exists so the whole stack works without auth."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from .config import settings
from .models import User


def demo_user_id() -> uuid.UUID:
    return uuid.UUID(settings.default_user_id)


def get_or_create_demo_user(db: Session) -> User:
    uid = demo_user_id()
    user = db.get(User, uid)
    if user is None:
        user = User(user_id=uid, name="Demo User")
        db.add(user)
        db.flush()
    return user