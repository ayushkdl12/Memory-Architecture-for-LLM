from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field

MemoryType = Literal["FACT", "PREFERENCE", "GOAL", "RULE", "EVENT"]
Priority = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


# ---- session / message ------------------------------------------------------
class SessionCreate(BaseModel):
    title: str = "New chat"


class SessionOut(BaseModel):
    session_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    message_id: uuid.UUID
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- chat -------------------------------------------------------------------
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatAttachment(BaseModel):
    url: str
    description: str


class ChatRequest(BaseModel):
    session_id: uuid.UUID | None = None
    text: str = Field(min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)
    attachment: ChatAttachment | None = None
    # Optional explicit expiry (calendar picker): applied to every atom
    # extracted from this turn.
    expires_at: datetime | None = None


class ChatChunk(BaseModel):
    session_id: uuid.UUID
    delta: str


class ChatDone(BaseModel):
    session_id: uuid.UUID
    message_id: uuid.UUID
    atoms_created: int = 0
    atoms_updated: int = 0
    retained: int = 0


# ---- memory atoms -----------------------------------------------------------
class AtomIn(BaseModel):
    memory_type: MemoryType
    category: str = "general"
    subject: str
    attribute: str
    value: str
    content: str
    priority: Priority = "MEDIUM"
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    expires_at: datetime | None = None


class AtomUpdate(BaseModel):
    memory_type: MemoryType | None = None
    category: str | None = None
    subject: str | None = None
    attribute: str | None = None
    value: str | None = None
    content: str | None = None
    priority: Priority | None = None
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    is_pinned: bool | None = None
    expires_at: datetime | None = None


class AtomCreated(BaseModel):
    memory_id: uuid.UUID
    action: str  # INSERT | REINFORCE | UPDATE_NEW | SKIPPED
    closed_memory_id: uuid.UUID | None = None


class AtomOut(BaseModel):
    memory_id: uuid.UUID
    memory_type: str
    category: str
    subject: str
    attribute: str
    value: str
    content: str
    priority: str
    confidence_score: float
    is_confirmed: bool = True
    is_active: bool
    retention_status: str
    access_count: int = 0
    is_pinned: bool = False
    valid_from: datetime
    valid_until: datetime | None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FactVersionOut(BaseModel):
    version_id: uuid.UUID
    subject: str
    attribute: str
    old_memory_id: uuid.UUID | None
    new_memory_id: uuid.UUID | None
    changed_at: datetime
    change_reason: str | None

    model_config = {"from_attributes": True}


class RetrievalLogOut(BaseModel):
    retrieval_id: uuid.UUID
    query_text: str
    retrieved_memory_ids: list[uuid.UUID]
    retrieval_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RetentionLogOut(BaseModel):
    retention_id: uuid.UUID
    memory_id: uuid.UUID
    action: str
    reason: str | None
    score: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RetentionSweepRequest(BaseModel):
    dry_run: bool = True


class RetentionSweepResult(BaseModel):
    archived: list[AtomOut]
    logged: list[RetentionLogOut]


class DashboardSummary(BaseModel):
    active_atoms: int
    archived_atoms: int
    total_atoms: int
    total_sessions: int
    retrieval_count: int
    retention_count: int
    expiring_soon: int = 0


# ---- media / photo uploads -------------------------------------------------
class MediaOut(BaseModel):
    media_id: uuid.UUID
    url: str
    mime_type: str
    description: str
    memory_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MediaUploadResult(BaseModel):
    media_id: uuid.UUID
    url: str
    description: str
    memory_id: uuid.UUID | None = None


# ---- user settings / custom instructions -----------------------------------
class UserSettingsOut(BaseModel):
    custom_instructions: str = ""

    model_config = {"from_attributes": True}


class UserSettingsUpdate(BaseModel):
    custom_instructions: str = ""


# ---- web search ------------------------------------------------------------
class SearchLogOut(BaseModel):
    search_id: uuid.UUID
    query_text: str
    results: list[dict]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- documents --------------------------------------------------------------
class DocumentOut(BaseModel):
    doc_id: uuid.UUID
    filename: str
    mime_type: str
    char_count: int
    preview: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentUploadResult(BaseModel):
    doc_id: uuid.UUID
    filename: str
    char_count: int
    chunk_count: int
    preview: str