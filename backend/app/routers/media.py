"""Media (photo) upload + vision understanding.

Flow: upload an image -> save to uploads/ -> caption it with the vision LLM
(Ollama vision model or Gemini) -> store the caption as a memorable memory atom
(EVENT user/photo) -> embed it -> return media metadata + description.

The frontend then sends the description along with the chat turn so the
assistant can answer questions grounded in the photo.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..demo import get_or_create_demo_user
from ..models import ChatSession, Media, MemoryAtom
from ..schemas import MediaOut, MediaUploadResult
from ..services.temporal import TemporalManager
from .. import provider

router = APIRouter(prefix="/api/media", tags=["media"])

ALLOWED_MIME = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}


@router.get("", response_model=list[MediaOut])
def list_media(db: Session = Depends(get_db)):
    from ..demo import demo_user_id

    rows = db.scalars(
        select(Media)
        .where(Media.user_id == demo_user_id())
        .order_by(Media.created_at.desc())
    ).all()
    return rows


@router.post("/upload", response_model=MediaUploadResult)
def upload_media(
    file: UploadFile = File(...),
    session_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    user = get_or_create_demo_user(db)

    mime = file.content_type or ""
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            400, "Only image uploads are supported (png/jpeg/gif/webp/bmp)"
        )
    data = file.file.read()
    if len(data) > settings.media_max_bytes:
        raise HTTPException(
            413,
            f"Image too large (max {settings.media_max_bytes // (1024 * 1024)} MB)",
        )

    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    media_id = uuid.uuid4()
    ext = Path(file.filename or "").suffix.lower() or ".jpg"
    filename = f"{media_id}{ext}"
    path = media_dir / filename
    path.write_bytes(data)

    try:
        description = provider.get_vision_llm().describe_image(str(path))
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(502, f"Photo understanding failed: {exc}")

    if session_id is not None:
        session = db.get(ChatSession, session_id)
        if session is None or session.user_id != user.user_id:
            session_id = None

    # Store the caption as a memorable memory atom (EVENTs accumulate, so
    # multiple photos coexist; identical uploads only reinforce).
    atom = {
        "memory_type": "EVENT",
        "category": "media",
        "subject": "user",
        "attribute": "photo",
        "value": description,
        "content": description,
        "priority": "MEDIUM",
        "confidence_score": 0.9,
    }
    created = TemporalManager(db).process_atoms(
        user.user_id, session_id, None, [atom]
    )[0]
    db.flush()

    vs = provider.get_vector_store()
    row = db.scalar(
        select(MemoryAtom).where(MemoryAtom.memory_id == created.memory_id)
    )
    if row is not None:
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
    if created.closed_memory_id:
        vs.delete(str(created.closed_memory_id))

    url = f"/media/{filename}"
    media = Media(
        user_id=user.user_id,
        session_id=session_id,
        memory_id=created.memory_id,
        filename=filename,
        url=url,
        mime_type=mime,
        description=description,
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    return MediaUploadResult(
        media_id=media.media_id,
        url=media.url,
        description=media.description,
        memory_id=media.memory_id,
    )
