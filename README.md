# Memory Agent — Universal Memory Architecture for LLM Agents

A full working implementation of the architecture proposed in
*"A Memory Architecture for LLM with Temporal Fact Tracking and Selective
Retention"*. It provides:

1. **A database design** — 12-table PostgreSQL schema for structured, versioned
   memory atoms (see [`docs/DATABASE_DESIGN.md`](docs/DATABASE_DESIGN.md)).
2. **A ChatGPT-style agent** — a Next.js chat UI backed by FastAPI, where the
   assistant *remembers facts across sessions*, versioned over time. The LLM
   runs fully **local via Ollama** by default (no API key); Gemini is an
   opt-in provider.
3. **ChatGPT/Claude/Grok-class features** — web search with citations, document
   upload + RAG, custom instructions, memory transparency (chips) + pinning,
   and markdown rendering with code-block artifacts.

```
Next.js UI (chat + memory dashboard)
        │  REST / SSE
   FastAPI backend  ─ services ──  MemoryExtractor · TemporalManager
        │                │        RetentionManager · RetrievalEngine · LLMService
        │                │        WebSearchService · DocumentService
  PostgreSQL (12 tables)  Numpy vector store (embeddings)
```

## Architecture pipeline (one chat turn)
`store message → LLM extraction (JSON atoms, iterative multi-pass) →
temporal versioning → retention check → embed active atoms → semantic
retrieval → active filter → priority ranking → memory context → LLM response
(streamed) → audit logs`

---

## Repository layout

```
backend/            FastAPI service
  app/
    main.py         app + route mounting
    config.py       settings (.env)
    database.py     SQLAlchemy engine
    models.py       ORM models (mirror db/schema.sql)
    provider.py     LLM + vector store singletons
    vectorstore.py  swappable vector store (Numpy / ChromaDB)
  routers/        chat (SSE), sessions, memory (dashboard), media, documents, settings
  services/       extractor · temporal · retention · retrieval · context · llm
                  websearch · documents
  tests/            pytest (temporal, retention, extraction)
frontend/           Next.js (chat UI + developer dashboard)
db/schema.sql       complete PostgreSQL DDL (the database design deliverable)
docs/               DATABASE_DESIGN.md (ER diagram, table specs, rationale)
```

---

## Prerequisites
- Python 3.12+ & PostgreSQL 17 (returns `brew install postgresql@17`)
- **Ollama** for the default local LLM: `brew install ollama && brew services
  start ollama`
- (Optional, opt-in) A **Gemini API key** from https://aistudio.google.com/apikey

---

## Setup

### 1. Database
```bash
brew install postgresql@17
brew services start postgresql@17

/opt/homebrew/opt/postgresql@17/bin/psql -d postgres <<'SQL'
CREATE ROLE memory WITH LOGIN PASSWORD 'memory_pass';
CREATE DATABASE memory_db OWNER memory;
SQL

# load the schema (12 tables, enums, indexes, triggers, view)
/opt/homebrew/opt/postgresql@17/bin/psql \
  "postgresql://memory:memory_pass@localhost:5432/memory_db" \
  -f db/schema.sql
```
> The backend also auto-creates the schema via `Base.metadata.create_all()`, so
> applying `db/schema.sql` manually is optional.

### 2. Backend
```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env
./.venv/bin/uvicorn app.main:app --reload --port 8000
```
API docs: http://localhost:8000/docs

### 2b. Pull the local models (Ollama, default provider)
```bash
ollama pull llama3.2:3b     # chat model (works well on 8 GB RAM)
ollama pull all-minilm      # embeddings (45 MB)
```

### 2c. Choose the LLM provider
`backend/.env` controls the provider via `LLM_PROVIDER`:

| Provider  | `LLM_PROVIDER=` | Requirements                               |
|-----------|-----------------|--------------------------------------------|
| **Ollama** (default) | `ollama` | local, no key; uses `OLLAMA_CHAT_MODEL` + `OLLAMA_EMBED_MODEL` |
| **Gemini** (opt-in)   | `gemini` | `GEMINI_API_KEY` in `backend/.env` |

> On 8 GB RAM use 3–4B models (e.g. `llama3.2:3b`); larger models may swap.
> `GET /api/health` reports the active `llm_provider` and `model`.

### 2d. Photos (optional)
Photo understanding uses a vision model via `VISION_PROVIDER`:

| Vision provider | `VISION_PROVIDER=` | Requirements                                   |
|-----------------|--------------------|------------------------------------------------|
| **Gemini** (default) | `gemini` | `GEMINI_API_KEY` in `backend/.env`; chat can stay local |
| **Ollama** (local)    | `ollama` | `OLLAMA_VISION_MODEL=qwen2.5vl:3b` + `ollama pull qwen2.5vl:3b` |

Uploaded images are saved to `backend/uploads/`, captioned by the vision
model, and the caption is stored as a memorable `EVENT user/photo` atom
(then embedded/retrievable like any other memory). Chat can keep running on
local Ollama while only vision uses Gemini.

### 2e. Web search (optional)
`backend/.env` controls web search via `SEARCH_PROVIDER`:

| Provider       | `SEARCH_PROVIDER=` | Requirements                      |
|----------------|--------------------|-----------------------------------|
| **DuckDuckGo** (default) | `duckduckgo` | none (free HTML endpoint) |
| **Tavily**     | `tavily` | `TAVILY_API_KEY` (free tier) |

The agent searches when the user asks a knowledge/current-events question
(e.g. "what is…", "latest 2026…"), cites numbered sources in the reply, and
logs every search in the `search_logs` table.

### 3. Frontend
```bash
cd frontend
npm install
npm run dev                    # http://localhost:3000
```
Open http://localhost:3000 → chat. Open http://localhost:3000/dashboard to
inspect active atoms, fact-history (temporal versions), retrieval & retention
logs, and run a retention sweep.

---

## Try the memory + versioning
1. In chat: *"My name is Bibek and I prefer Python."*
2. Start a **new chat** and ask *"What language do I prefer?"* → it remembers
   from the stored memory atoms.
3. Say *"Actually, I prefer Go now."*
4. Ask again or open the **Memory → Fact History** tab → you'll see the old
   value closed and the new value made active (temporal versioning with no bad
   old data leaking into answers).

## Photos & voice
- **Photos**: click 📷 in the composer, pick an image, and it is uploaded to
  `POST /api/media/upload`, captioned by the vision model, and stored as an
  `EVENT user/photo` memory atom. Ask follow-up questions like *"what was in
  the photo I showed you?"* — retrieval finds it across sessions. The caption
  is also injected into the current reply.
- **Voice**: click 🎤 to dictate (Web Speech API, browser speech-to-text; works
  in Chrome/Edge). Assistant replies can be read aloud with the 🔊 button on a
  message (Web Speech synthesis). Both are client-side, so nothing to install.

## Tier-1 features
- **Web search with citations**: click 🔎-capable questions trigger a live
  DuckDuckGo/Tavily search; results are injected as a numbered block the model
  must cite inline (`[1]`, `[2]…`). A "searched the web (n sources)" chip
  appears on the reply, and every search is audited in `search_logs`.
- **Documents (RAG)**: click 📄 in the composer to upload `.pdf`, `.txt`,
  `.md`, `.csv`, `.json`, `.py`, `.js`, `.sql` files. Text is extracted and
  chunked (800 chars / 80 overlap); each chunk is embedded into the same vector
  store under synthetic ids (`doc:<chunk_id>`) and retrieved on demand — no
  whole-file prompt injection. Documents are listed/managed via
  `/api/documents` and appear as 📄 chips on replies that used them.
- **Custom instructions**: the ⚙️ button opens settings with presets
  (Concise / Friendly / Academic / Tutor / Professional) or a free-text
  instructions box, stored per-user in `user_settings` and injected into every
  system prompt.
- **Memory transparency + pinning**: each reply shows 🧠 chips of which memory
  atoms (and 📄 documents) informed it. In the dashboard, the 📌/📍 buttons pin
  or unpin atoms; pinned atoms are never touched by the retention sweep, and a
  **Pinned** tab lists them.
- **Markdown + artifacts**: replies render GitHub-flavored markdown with
  syntax-highlighted code blocks. Each code block has copy and ⧉ Open buttons;
  HTML/SVG blocks open in a sandboxed in-app preview panel (artifacts-lite),
  other languages show a highlighted code panel.

## Tests
```bash
cd backend
./.venv/bin/python -m pytest -q
```

## Notes
- **Local model extraction quality**: small 3–4B models (the default) are
  lossy and pick inconsistent fact keys. The extractor mitigates this with
  (a) up to `MAX_PASSES=3` iterative passes that feed back already-extracted
  atoms, (b) a constrained attribute vocabulary in the prompt, and (c)
  app-side canonicalization of `subject`/`attribute` synonyms. For the best
  extraction quality, switch `LLM_PROVIDER=gemini`.
- **Confidence gating**: atoms are flagged `is_confirmed = FALSE` when the
  extraction confidence is below `CONFIDENCE_AUTO_COMMIT` (default `0.6`);
  they are still stored and retrievable but marked "unconfirmed" in the
  dashboard and as tentative in the prompt. Re-stating the same fact
  (`REINFORCE`) raises its confidence (+0.1, cap 1.0) and confirms it.
- **Retrieval**: candidates below `RETRIEVAL_MIN_SCORE` (cosine, default
  `0.12` for `all-minilm`; the model's scores run low, e.g. the top hit for
  "What is my name?" is ~0.33) are dropped to save context; results are ranked
  by priority, then recency, then similarity. The memory block injected into
  the prompt is date-annotated, budget-limited (`CONTEXT_CHAR_BUDGET`), and
  re-emphasizes the single most relevant atom at the end.
- **Seeding a profile via `.docx`**: `backend/scripts/make_profile_docx.py`
  generates `docs/user_profile.docx` (one fact per bullet line, grouped into
  Personal / Work / Technical skills / Preferences / Goals / Projects &
  deadlines / Upcoming events). `backend/scripts/ingest_docx.py` reads it back:
  each line is parsed deterministically (fast and reliable even on small local
  models), with unmatched lines optionally sent to the LLM extractor via
  `--llm-fallback`. Atoms are POSTed to the running backend
  (`POST /api/memory/atoms`), so they get the same temporal versioning,
  confidence gating, and embedding as chat-derived memory. Run it from
  `backend/` with the server up:
  ```
  ./.venv/bin/python scripts/ingest_docx.py        # real run (--dry-run to preview)
  ```
- **Retention**: the numeric retention score is stored on every
  `retention_logs` row and shown in the dashboard, so the sweep threshold can
  be tuned from real data.
- Embeddings use `all-minilm` via Ollama (default) with a local NumPy vector
  store (a dependency-free stand-in for FAISS). Switch to ChromaDB by setting
  `VECTOR_STORE_PROVIDER=chroma` and installing `chromadb`.
- The data model and temporal/retention rules are designed to be decoupled so
  any component (LLM, vector store, RDBMS) can be swapped without touching the
  others, as required by the proposal.