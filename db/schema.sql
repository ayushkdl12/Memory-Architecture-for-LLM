-- ============================================================================
-- Memory Architecture for LLM Agents
-- PostgreSQL Schema (v1.1)
--
-- Implements: structured memory atoms, temporal fact versioning, selective
-- retention, retrieval/retention audit, media, custom instructions, web
-- search logging, document RAG, and user-set atom expiry. 12 relational
-- tables + enums + indexes.
--
-- Source: "A Memory Architecture for LLM with Temporal Fact Tracking and
--         Selective Retention" (Major Project Proposal, July 2026).
--
-- Demo data: see seed.sql (same directory, run after this file).
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Extensions
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- trigram index on text search

-- ----------------------------------------------------------------------------
-- ENUM types
-- ----------------------------------------------------------------------------
CREATE TYPE memory_type AS ENUM (
    'FACT', 'PREFERENCE', 'GOAL', 'RULE', 'EVENT'
);

CREATE TYPE priority_level AS ENUM (
    'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
);

CREATE TYPE retention_status AS ENUM (
    'ACTIVE', 'ARCHIVED', 'IGNORED'
);

CREATE TYPE message_role AS ENUM (
    'user', 'assistant'
);

CREATE TYPE retention_action AS ENUM (
    'KEEP', 'ARCHIVE', 'IGNORE', 'UPDATE'
);

-- ----------------------------------------------------------------------------
-- Table: users
-- ----------------------------------------------------------------------------
CREATE TABLE users (
    user_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE users IS 'Agent/client that owns memory atoms.';

-- ----------------------------------------------------------------------------
-- Table: chat_sessions
-- ----------------------------------------------------------------------------
CREATE TABLE chat_sessions (
    session_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT 'New chat',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sessions_user   ON chat_sessions(user_id);
CREATE INDEX idx_sessions_updated ON chat_sessions(updated_at DESC);

COMMENT ON TABLE chat_sessions IS 'A multi-turn conversation for a user.';

-- ----------------------------------------------------------------------------
-- Table: messages
-- ----------------------------------------------------------------------------
CREATE TABLE messages (
    message_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role        message_role NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_session ON messages(session_id, created_at);

COMMENT ON TABLE messages IS 'Raw interaction log; the source for memory extraction.';

-- ----------------------------------------------------------------------------
-- Table: memory_atoms  (the core structured memory store)
-- ----------------------------------------------------------------------------
CREATE TABLE memory_atoms (
    memory_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id          UUID REFERENCES chat_sessions(session_id) ON DELETE SET NULL,
    source_message_id   UUID REFERENCES messages(message_id) ON DELETE SET NULL,

    memory_type         memory_type NOT NULL,
    category            TEXT NOT NULL DEFAULT 'general',
    subject             TEXT NOT NULL,
    attribute           TEXT NOT NULL,
    value               TEXT NOT NULL,
    content             TEXT NOT NULL,            -- natural-language memory text

    priority            priority_level NOT NULL DEFAULT 'MEDIUM',
    confidence_score    DOUBLE PRECISION NOT NULL DEFAULT 0.5
                        CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    is_confirmed        BOOLEAN NOT NULL DEFAULT TRUE,   -- auto-confirmed when confidence >= threshold
    is_pinned           BOOLEAN NOT NULL DEFAULT FALSE,  -- user-pinned; never swept/archived

    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    retention_status    retention_status NOT NULL DEFAULT 'ACTIVE',
    access_count        INTEGER NOT NULL DEFAULT 0,   -- retrieval frequency (scoring)

    valid_from          TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_until         TIMESTAMPTZ,               -- NULL == currently active
    expires_at          TIMESTAMPTZ,               -- user-set expiry; atom auto-archived after this

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- At most ONE active version per (user, subject, attribute) for versioned
-- memory types (FACT, PREFERENCE, GOAL). Partial: only enforces on active rows
-- of those types, so closed historical versions and multiple active EVENT
-- atoms (point-in-time records) may coexist.
CREATE UNIQUE INDEX uq_memory_active_subject_attribute
    ON memory_atoms (user_id, subject, attribute)
    WHERE is_active = TRUE
      AND memory_type IN ('FACT', 'PREFERENCE', 'GOAL');

CREATE INDEX idx_memory_user        ON memory_atoms(user_id);
CREATE INDEX idx_memory_session     ON memory_atoms(session_id);
CREATE INDEX idx_memory_source_msg  ON memory_atoms(source_message_id);
CREATE INDEX idx_memory_active      ON memory_atoms(is_active, valid_until)
    WHERE is_active;
CREATE INDEX idx_memory_type_prio   ON memory_atoms(memory_type, priority);
CREATE INDEX idx_memory_subject     ON memory_atoms(subject, attribute);
CREATE INDEX idx_memory_expires     ON memory_atoms(expires_at);
CREATE INDEX idx_memory_content_trgm ON memory_atoms
    USING gin (content gin_trgm_ops);

COMMENT ON TABLE memory_atoms IS
    'Structured memory atoms. Each atom is a versioned (subject, attribute) fact.';

-- ----------------------------------------------------------------------------
-- Table: fact_versions
-- ----------------------------------------------------------------------------
CREATE TABLE fact_versions (
    version_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    subject         TEXT NOT NULL,
    attribute       TEXT NOT NULL,
    old_memory_id   UUID REFERENCES memory_atoms(memory_id) ON DELETE SET NULL,
    new_memory_id   UUID REFERENCES memory_atoms(memory_id) ON DELETE SET NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_reason   TEXT
);

CREATE INDEX idx_fact_versions_user ON fact_versions(user_id);
CREATE INDEX idx_fact_versions_subj ON fact_versions(subject, attribute);

COMMENT ON TABLE fact_versions IS
    'Temporal change log: records when an active fact was superseded.';

-- ----------------------------------------------------------------------------
-- Table: retrieval_logs
-- ----------------------------------------------------------------------------
CREATE TABLE retrieval_logs (
    retrieval_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    message_id          UUID REFERENCES messages(message_id) ON DELETE SET NULL,
    query_text          TEXT NOT NULL,
    retrieved_memory_ids JSONB NOT NULL DEFAULT '[]',
    retrieval_reason    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_retrieval_logs_session ON retrieval_logs(session_id, created_at);

COMMENT ON TABLE retrieval_logs IS 'Audit trail of every retrieval event.';

-- ----------------------------------------------------------------------------
-- Table: retention_logs
-- ----------------------------------------------------------------------------
CREATE TABLE retention_logs (
    retention_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id       UUID REFERENCES memory_atoms(memory_id) ON DELETE CASCADE,
    action          retention_action NOT NULL,
    reason          TEXT,
    score           DOUBLE PRECISION,             -- numeric retention score at decision time
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_retention_logs_memory ON retention_logs(memory_id);
CREATE INDEX idx_retention_logs_created ON retention_logs(created_at);

COMMENT ON TABLE retention_logs IS 'Audit trail of every retention decision.';

-- ----------------------------------------------------------------------------
-- Table: media (photo uploads)
-- ----------------------------------------------------------------------------
CREATE TABLE media (
    media_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID REFERENCES users(user_id) ON DELETE CASCADE NOT NULL,
    session_id       UUID REFERENCES chat_sessions(session_id) ON DELETE SET NULL,
    source_message_id UUID REFERENCES messages(message_id) ON DELETE SET NULL,
    memory_id        UUID REFERENCES memory_atoms(memory_id) ON DELETE SET NULL,
    filename         TEXT NOT NULL,               -- on-disk name under uploads/
    url              TEXT NOT NULL,               -- /media/<filename>
    mime_type        TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',    -- vision caption (also the atom value)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_media_user ON media(user_id);
CREATE INDEX idx_media_session ON media(session_id);
CREATE INDEX idx_media_memory ON media(memory_id);

COMMENT ON TABLE media IS 'Uploaded photos with their vision captions.';

-- ----------------------------------------------------------------------------
-- Table: user_settings
-- ----------------------------------------------------------------------------
CREATE TABLE user_settings (
    user_id             UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    custom_instructions TEXT NOT NULL DEFAULT '',
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE user_settings IS
    'Per-user custom instructions injected into the system prompt.';

-- ----------------------------------------------------------------------------
-- Table: search_logs
-- ----------------------------------------------------------------------------
CREATE TABLE search_logs (
    search_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    message_id      UUID REFERENCES messages(message_id) ON DELETE SET NULL,
    query_text      TEXT NOT NULL,
    provider        TEXT NOT NULL DEFAULT 'duckduckgo',
    results         JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_search_logs_session ON search_logs(session_id, created_at);

COMMENT ON TABLE search_logs IS 'Audit trail of every web search the agent runs.';

-- ----------------------------------------------------------------------------
-- Table: documents
-- ----------------------------------------------------------------------------
CREATE TABLE documents (
    doc_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id      UUID REFERENCES chat_sessions(session_id) ON DELETE SET NULL,
    filename        TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    char_count      BIGINT NOT NULL DEFAULT 0,
    preview         TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_documents_user ON documents(user_id);
CREATE INDEX idx_documents_session ON documents(session_id);

COMMENT ON TABLE documents IS 'Uploaded documents, stored as text for RAG.';

-- ----------------------------------------------------------------------------
-- Table: document_chunks
-- ----------------------------------------------------------------------------
CREATE TABLE document_chunks (
    chunk_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index     BIGINT NOT NULL,
    text            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_document_chunk_idx ON document_chunks(doc_id, chunk_index);

COMMENT ON TABLE document_chunks IS
    'Text chunks of uploaded documents; each is embedded in the vector store as "doc:<chunk_id>".';

-- ----------------------------------------------------------------------------
-- Triggers
-- ----------------------------------------------------------------------------

-- Keep updated_at fresh on any UPDATE of a row.
CREATE OR REPLACE FUNCTION fn_set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_memory_atoms_updated
    BEFORE UPDATE ON memory_atoms
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_sessions_updated
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_user_settings_updated
    BEFORE UPDATE ON user_settings
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- ----------------------------------------------------------------------------
-- View: current (active) memory atoms
-- Convenience view mirroring the retrieval filter
-- (is_active = TRUE AND valid_until IS NULL).
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW active_memory_atoms AS
SELECT * FROM memory_atoms
WHERE is_active = TRUE AND valid_until IS NULL;

COMMIT;