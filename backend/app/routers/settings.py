"""User settings: custom instructions (ChatGPT-style / persona support)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..demo import get_or_create_demo_user
from ..models import UserSettings
from ..schemas import UserSettingsOut, UserSettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserSettingsOut)
def get_settings(db: Session = Depends(get_db)):
    user = get_or_create_demo_user(db)
    row = db.get(UserSettings, user.user_id)
    if row is None:
        return UserSettingsOut(custom_instructions="")
    return row


@router.put("", response_model=UserSettingsOut)
def update_settings(body: UserSettingsUpdate, db: Session = Depends(get_db)):
    user = get_or_create_demo_user(db)
    row = db.get(UserSettings, user.user_id)
    if row is None:
        row = UserSettings(user_id=user.user_id)
        db.add(row)
    row.custom_instructions = body.custom_instructions.strip()
    db.commit()
    db.refresh(row)
    return row
