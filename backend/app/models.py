from datetime import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# ENUMs (mirror the PostgreSQL types created in db/schema.sql)
# ---------------------------------------------------------------------------
MemoryType = ("FACT", "PREFERENCE", "GOAL", "RULE", "EVENT")
PriorityLevel = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
RetentionStatus = ("ACTIVE", "ARCHIVED", "IGNORED")
RetentionAction = ("KEEP", "ARCHIVE", "IGNORE", "UPDATE")

MTYPE = Enum(
    *MemoryType,
    name="memory_type",
    native_enum=True,
    create_type=True,
)
PRIORITY = Enum(
    *PriorityLevel,
    name="priority_level",
    native_enum=True,
    create_type=True,
)
RSTATUS = Enum(
    *RetentionStatus,
    name="retention_status",
    native_enum=True,
    create_type=True,
)
RACTION = Enum(
    *RetentionAction,
    name="retention_action",
    native_enum=True,
    create_type=True,
)
MROLE = Enum(
    "user",
    "assistant",
    name="message_role",
    native_enum=True,
    create_type=True,
)


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    name: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, default="New chat", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_sessions_user", "user_id"),
        Index("idx_sessions_updated", "updated_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(MROLE, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_messages_session", "session_id", "created_at"),)


class MemoryAtom(Base):
    __tablename__ = "memory_atoms"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_sessions.session_id", ondelete="SET NULL")
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.message_id", ondelete="SET NULL")
    )

    memory_type: Mapped[str] = mapped_column(MTYPE, nullable=False)
    category: Mapped[str] = mapped_column(Text, default="general", nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    attribute: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    priority: Mapped[str] = mapped_column(PRIORITY, default="MEDIUM", nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    retention_status: Mapped[str] = mapped_column(
        RSTATUS, default="ACTIVE", nullable=False
    )
    access_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # At most ONE active version per (user, subject, attribute) for
        # versioned types (FACT, PREFERENCE, GOAL). EVENT/RULE may accumulate.
        Index(
            "uq_memory_active_subject_attribute",
            "user_id",
            "subject",
            "attribute",
            unique=True,
            postgresql_where=(
                "is_active AND memory_type IN ('FACT','PREFERENCE','GOAL')"
            ),
        ),
        Index("idx_memory_user", "user_id"),
        Index("idx_memory_session", "session_id"),
        Index("idx_memory_source_msg", "source_message_id"),
        Index("idx_memory_active", "is_active", "valid_until", postgresql_where="is_active"),
        Index("idx_memory_type_prio", "memory_type", "priority"),
        Index("idx_memory_subject", "subject", "attribute"),
    )


class FactVersion(Base):
    __tablename__ = "fact_versions"

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    attribute: Mapped[str] = mapped_column(Text, nullable=False)
    old_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memory_atoms.memory_id", ondelete="SET NULL")
    )
    new_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memory_atoms.memory_id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    change_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_fact_versions_user", "user_id"),
        Index("idx_fact_versions_subj", "subject", "attribute"),
    )


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    retrieval_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_sessions.session_id", ondelete="CASCADE")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.message_id", ondelete="SET NULL")
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_memory_ids: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )
    retrieval_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_retrieval_logs_session", "session_id", "created_at"),)


class RetentionLog(Base):
    __tablename__ = "retention_logs"

    retention_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memory_atoms.memory_id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(RACTION, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)  # numeric retention score
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_retention_logs_memory", "memory_id"),
        Index("idx_retention_logs_created", "created_at"),
    )


class Media(Base):
    __tablename__ = "media"

    media_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_sessions.session_id", ondelete="SET NULL")
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.message_id", ondelete="SET NULL")
    )
    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memory_atoms.memory_id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_media_user", "user_id"),
        Index("idx_media_session", "session_id"),
        Index("idx_media_memory", "memory_id"),
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    custom_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SearchLog(Base):
    __tablename__ = "search_logs"

    search_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_sessions.session_id", ondelete="CASCADE")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.message_id", ondelete="SET NULL")
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    results: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_search_logs_session", "session_id"),
        Index("idx_search_logs_created", "created_at"),
    )


class Document(Base):
    __tablename__ = "documents"

    doc_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_sessions.session_id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    preview: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_documents_user", "user_id"),
        Index("idx_documents_session", "session_id"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=new_uuid
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_doc_chunks_doc", "doc_id", "chunk_index"),
    )
