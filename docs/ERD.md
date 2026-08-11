# ERD — Memory Architecture Database

Entity-relationship diagram for the `memory_db` PostgreSQL schema (12 tables).
DDL source: [`db/schema.sql`](../db/schema.sql).

```mermaid
erDiagram
    users ||--o{ chat_sessions : "owns"
    chat_sessions ||--o{ messages : "contains"
    users ||--o{ memory_atoms : "owns"
    chat_sessions ||--o{ memory_atoms : "sourced_from"
    messages ||--o{ memory_atoms : "produced"
    memory_atoms ||--o{ fact_versions : "superseded_by(old)"
    memory_atoms ||--o{ fact_versions : "resulted_in(new)"
    chat_sessions ||--o{ retrieval_logs : "logged_for"
    messages ||--o{ retrieval_logs : "queried_from"
    memory_atoms ||--o{ retention_logs : "decided_upon"
    users ||--o{ media : "uploaded"
    chat_sessions ||--o{ media : "belongs_to"
    messages ||--o{ media : "attached_to"
    memory_atoms ||--o{ media : "captioned_by"
    users ||--|| user_settings : "has"
    chat_sessions ||--o{ search_logs : "searched_for"
    messages ||--o{ search_logs : "triggered_by"
    users ||--o{ documents : "uploaded"
    chat_sessions ||--o{ documents : "uploaded_in"
    documents ||--o{ document_chunks : "split_into"

    users {
        uuid user_id PK
        text name
        timestamptz created_at
    }
    chat_sessions {
        uuid session_id PK
        uuid user_id FK
        text title
        timestamptz created_at
        timestamptz updated_at
    }
    messages {
        uuid message_id PK
        uuid session_id FK
        message_role role
        text content
        timestamptz created_at
    }
    memory_atoms {
        uuid memory_id PK
        uuid user_id FK
        uuid session_id FK
        uuid source_message_id FK
        memory_type type
        text category
        text subject
        text attribute
        text value
        text content
        priority_level priority
        float confidence_score
        bool is_confirmed
        bool is_pinned
        bool is_active
        retention_status retention_status
        int access_count
        timestamptz valid_from
        timestamptz valid_until
        timestamptz expires_at
        timestamptz created_at
        timestamptz updated_at
    }
    fact_versions {
        uuid version_id PK
        uuid user_id FK
        text subject
        text attribute
        uuid old_memory_id FK
        uuid new_memory_id FK
        timestamptz changed_at
        text change_reason
    }
    retrieval_logs {
        uuid retrieval_id PK
        uuid session_id FK
        uuid message_id FK
        text query_text
        jsonb retrieved_memory_ids
        text retrieval_reason
        timestamptz created_at
    }
    retention_logs {
        uuid retention_id PK
        uuid memory_id FK
        retention_action action
        text reason
        timestamptz created_at
    }
    media {
        uuid media_id PK
        uuid user_id FK
        uuid session_id FK
        uuid source_message_id FK
        uuid memory_id FK
        text filename
        text url
        text mime_type
        text description
        timestamptz created_at
    }
    user_settings {
        uuid user_id PK, FK
        text custom_instructions
        timestamptz updated_at
    }
    search_logs {
        uuid search_id PK
        uuid session_id FK
        uuid message_id FK
        text query_text
        text provider
        jsonb results
        timestamptz created_at
    }
    documents {
        uuid document_id PK
        uuid user_id FK
        uuid session_id FK
        text filename
        text mime_type
        int size_bytes
        text text_content
        timestamptz created_at
    }
    document_chunks {
        uuid chunk_id PK
        uuid document_id FK
        int chunk_index
        text content
        timestamptz created_at
    }
```

## Relationships

| From | To | Cardinality | FK / On delete |
|---|---|---|---|
| `users` | `chat_sessions` | 1 → N | `user_id` / CASCADE |
| `chat_sessions` | `messages` | 1 → N | `session_id` / CASCADE |
| `users` | `memory_atoms` | 1 → N | `user_id` / CASCADE |
| `chat_sessions` | `memory_atoms` | 1 → N (optional) | `session_id` / SET NULL |
| `messages` | `memory_atoms` | 1 → N (optional) | `source_message_id` / SET NULL |
| `memory_atoms` | `fact_versions` (old) | 1 → N | `old_memory_id` / SET NULL |
| `memory_atoms` | `fact_versions` (new) | 1 → N | `new_memory_id` / SET NULL |
| `chat_sessions` | `retrieval_logs` | 1 → N | `session_id` / CASCADE |
| `messages` | `retrieval_logs` | 1 → N (optional) | `message_id` / SET NULL |
| `memory_atoms` | `retention_logs` | 1 → N | `memory_id` / CASCADE |
| `users` | `media` | 1 → N | `user_id` / CASCADE |
| `chat_sessions` | `media` | 1 → N (optional) | `session_id` / SET NULL |
| `messages` | `media` | 1 → N (optional) | `source_message_id` / SET NULL |
| `memory_atoms` | `media` | 1 → N (optional) | `memory_id` / SET NULL |
| `users` | `user_settings` | 1 → 1 | `user_id` / CASCADE |
| `chat_sessions` | `search_logs` | 1 → N (optional) | `session_id` / CASCADE |
| `messages` | `search_logs` | 1 → N (optional) | `message_id` / SET NULL |
| `users` | `documents` | 1 → N | `user_id` / CASCADE |
| `chat_sessions` | `documents` | 1 → N (optional) | `session_id` / SET NULL |
| `documents` | `document_chunks` | 1 → N | `document_id` / CASCADE |

## Key notes

- `memory_atoms` is the hub: ownership (`users`), provenance (`chat_sessions`,
  `messages`), and references from both audit tables (`fact_versions`,
  `retention_logs`).
- `media` links each uploaded photo to the user, optional session/message, and
  the memory atom whose value is the vision caption (`user/photo` EVENT).
- `fact_versions` has two FKs to `memory_atoms` — a transition record from
  `old_memory_id` to `new_memory_id`.
- `is_pinned` on `memory_atoms` marks user-pinned facts; the retention sweep
  never archives pinned atoms.
- `expires_at` is the user-set expiry ("remember X until <date>" or picked in
  the calendar). Atoms past their expiry are auto-archived at the start of
  every chat turn and during the sweep — unless pinned. Distinct from
  `valid_until`, which records temporal-version closure.
- `documents` + `document_chunks` back document RAG; each chunk is embedded in
  the local vector store under the synthetic id `doc:<chunk_id>` with metadata
  `kind=document`, so document retrieval shares the same hybrid pipeline.
- `search_logs` stores the full JSONB result list of each web search for
  auditing/citation reconstruction.
- Partial unique index `uq_memory_active_subject_attribute` on
  `(user_id, subject, attribute) WHERE is_active AND memory_type IN
  ('FACT','PREFERENCE','GOAL')` enforces at most one active version per fact.
