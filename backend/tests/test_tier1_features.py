"""Tier-1 feature tests: custom instructions, web search, document RAG, pinning,
and the retrieval-transparency payload of the SSE done event.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import provider
from app.database import SessionLocal
from app.demo import demo_user_id
from app.models import (
    ChatSession,
    Document,
    FactVersion,
    MemoryAtom,
    Message,
    RetrievalLog,
    SearchLog,
)
from app.services.websearch import SearchResult, should_search
from app.vectorstore import NumpyVectorStore


def _utc_date(iso: str) -> str:
    from datetime import datetime, timezone

    return datetime.fromisoformat(iso).astimezone(timezone.utc).date().isoformat()


class StubLLM:
    def __init__(self):
        self.calls = 0
        self.system_prompts: list[str] = []

    def embed(self, texts):
        out = []
        for t in texts:
            h = hashlib.md5(t.encode()).digest()
            out.append([b / 255.0 for b in h])
        return out

    def complete_json(self, prompt):
        """Message-driven extraction: emit a known atom for each mentioned fact."""
        self.calls += 1
        atoms = []
        if "Bibek" in prompt:
            atoms.append(
                {"memory_type": "FACT", "category": "general", "subject": "user",
                 "attribute": "name", "value": "Bibek",
                 "content": "The user's name is Bibek.", "priority": "HIGH",
                 "confidence_score": 0.95}
            )
        if "colour" in prompt:
            atoms.append(
                {"memory_type": "PREFERENCE", "category": "style", "subject": "user",
                 "attribute": "colour", "value": "blue",
                 "content": "The user's favourite colour is blue.", "priority": "MEDIUM",
                 "confidence_score": 0.8}
            )
        return atoms

    def stream_chat(self, *, system, turns, new_user_text):
        self.system_prompts.append(system)

        def g():
            yield SimpleNamespace(text="Acknowledged. ")
            yield SimpleNamespace(text="Done.")
        return g()


class StubSearchService:
    def __init__(self, results: list[SearchResult]):
        self._results = results

    def search(self, query):
        return self._results

    def format_context(self, results):
        from app.services.websearch import SearchService

        return SearchService().format_context(results)


def _done_events(text: str) -> list[dict]:
    return [
        json.loads(line[5:])
        for line in text.split("\n\n")
        if line.startswith("data:") and '"type": "done"' in line
    ]


@pytest.fixture
def stubbed_app(tmp_path):
    stub = StubLLM()
    search = StubSearchService(
        [SearchResult("PostgreSQL 18 released", "https://example.com/pg18",
                      "PostgreSQL 18 ships with new partitioning features.")]
    )

    def fake_get_llm():
        return stub

    def fake_get_vector_store():
        return NumpyVectorStore(str(tmp_path / "vec"), stub)

    def fake_get_search_service():
        return search

    provider._llm = None
    provider._vector_store = None
    provider.get_llm = fake_get_llm
    provider.get_vector_store = fake_get_vector_store
    provider.get_search_service = fake_get_search_service

    from app.main import app

    yield app, stub

    provider._llm = None
    provider._vector_store = None
    import importlib

    importlib.reload(provider)


@pytest.fixture(autouse=True)
def cleanup_demo_data():
    def _clean():
        db = SessionLocal()
        try:
            uid = demo_user_id()
            db.execute(delete(SearchLog))
            db.execute(delete(Document))
            db.execute(delete(RetrievalLog))
            db.execute(delete(FactVersion))
            db.execute(delete(MemoryAtom).where(MemoryAtom.user_id == uid))
            db.execute(delete(Message))
            db.execute(delete(ChatSession))
            db.commit()
        finally:
            db.close()

    _clean()
    yield
    _clean()


# --- search trigger heuristic -------------------------------------------------

def test_should_search_informational():
    assert should_search("What is the latest version of PostgreSQL in 2026?")
    assert should_search("How to set up docker compose")
    assert should_search("PostgreSQL 18 vs 17 differences")


def test_should_search_skips_personal():
    assert not should_search("What is my name?")
    assert not should_search("What do I prefer for coffee?")
    assert not should_search("What was in the photo I showed you?")


# --- expiry (user-set memory lifetime) ----------------------------------------

def test_parse_expiry():
    from app.services.extractor import parse_expiry

    future = parse_expiry("Remember the wifi password until 2026-09-01")
    assert future is not None and future.date().isoformat() == "2026-09-01"

    rel = parse_expiry("You should remember the office PIN for 2 weeks")
    assert rel is not None

    assert parse_expiry("My name is Bibek") is None
    assert parse_expiry("The meeting is on October 5") is None
    assert parse_expiry("What is the weather today?") is None


def test_chat_request_expires_at_stores_on_atoms(stubbed_app):
    app, _ = stubbed_app
    client = TestClient(app)

    r = client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek.",
        "history": [],
        "expires_at": "2026-09-01T23:59:59Z",
    })
    assert r.status_code == 200
    assert '"type": "done"' in r.text

    atoms = client.get("/api/memory/atoms?filter=active").json()
    assert len(atoms) == 1
    assert atoms[0]["expires_at"] is not None
    assert _utc_date(atoms[0]["expires_at"]) == "2026-09-01"

    # the expiry surfaces in the transparency chips of a follow-up turn
    second = client.post("/api/chat", json={
        "session_id": None,
        "text": "What is my name?",
        "history": [],
    })
    done = _done_events(second.text)
    assert any(
        item.get("expires_at") and _utc_date(item["expires_at"]) == "2026-09-01"
        for item in done[0]["retrieved"]
    )


def test_done_event_reports_expiry_from_text(stubbed_app):
    app, stub = stubbed_app
    client = TestClient(app)

    client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek.",
        "history": [],
    })
    # plain restatement, no expiry anywhere -> atoms stay permanent
    second = client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek, remember it until 2026-09-01.",
        "history": [],
    })
    assert '"type": "done"' in second.text

    atoms = client.get("/api/memory/atoms?filter=active").json()
    name = [a for a in atoms if a["attribute"] == "name"]
    assert name and name[0]["expires_at"] is not None
    assert _utc_date(name[0]["expires_at"]) == "2026-09-01"


def test_expired_atoms_archived_and_pinned_exempt(db, stubbed_app):
    from datetime import datetime, timedelta, timezone

    from app.database import SessionLocal
    from app.models import RetentionLog
    from app.services.retention import expire_due_atoms

    app, _ = stubbed_app
    client = TestClient(app)

    client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek.",
        "history": [],
        "expires_at": "2026-01-01T00:00:00Z",  # already in the past
    })
    atoms = client.get("/api/memory/atoms?filter=active").json()
    assert len(atoms) == 1
    past = atoms[0]
    assert past["is_active"] is True  # still stored; expiry takes effect on next turn/sweep

    # a chat turn triggers expiry -> atom archived and dropped from retrieval
    client.post("/api/chat", json={
        "session_id": None,
        "text": "What is my name?",
        "history": [],
    })
    assert client.get("/api/memory/atoms?filter=active").json() == []

    db = SessionLocal()
    try:
        logs = db.scalars(select(RetentionLog)).all()
        assert any(l.action == "ARCHIVE" and "expired" in (l.reason or "")
                   for l in logs)
    finally:
        db.close()

    # a pinned expired atom survives expiry
    client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek.",
        "history": [],
        "expires_at": "2026-01-01T00:00:00Z",
    })
    atoms = client.get("/api/memory/atoms?filter=active").json()
    client.patch(f"/api/memory/atoms/{atoms[0]['memory_id']}",
                 json={"is_pinned": True})
    client.post("/api/chat", json={
        "session_id": None,
        "text": "What is my name?",
        "history": [],
    })
    pinned = client.get("/api/memory/atoms?filter=active").json()
    assert [a["attribute"] for a in pinned] == ["name"]


def test_sweep_archives_expired_and_logs(db, stubbed_app):
    from datetime import datetime, timedelta, timezone

    from app.models import RetentionLog

    app, _ = stubbed_app
    client = TestClient(app)

    client.post("/api/chat", json={
        "session_id": None,
        "text": "My favourite colour is blue.",
        "history": [],
        "expires_at": "2030-01-01T00:00:00Z",  # far future
    })
    # an atom with an already-passed expiry, created outside a chat turn
    client.post("/api/memory/atoms", json={
        "memory_type": "FACT", "category": "general", "subject": "user",
        "attribute": "name", "value": "Bibek",
        "content": "The user's name is Bibek.", "priority": "HIGH",
        "confidence_score": 0.95, "expires_at": "2026-01-01T00:00:00Z",
    })
    atoms = client.get("/api/memory/atoms?filter=active").json()
    assert len(atoms) == 2

    r = client.post("/api/memory/retention/sweep", json={"dry_run": False})
    assert r.status_code == 200
    archived = {a["attribute"] for a in r.json()["archived"]}
    assert archived == {"name"}

    active = client.get("/api/memory/atoms?filter=active").json()
    assert [a["attribute"] for a in active] == ["colour"]

    db = SessionLocal()
    try:
        logs = db.scalars(select(RetentionLog)).all()
        assert any("expired" in (l.reason or "") for l in logs)
    finally:
        db.close()


# --- custom instructions ------------------------------------------------------

def test_settings_roundtrip_and_prompt_injection(stubbed_app):
    app, stub = stubbed_app
    client = TestClient(app)

    r = client.put("/api/settings",
                   json={"custom_instructions": "Always answer in pirate speak."})
    assert r.status_code == 200
    assert r.json()["custom_instructions"] == "Always answer in pirate speak."
    assert client.get("/api/settings").json()["custom_instructions"] == (
        "Always answer in pirate speak."
    )

    client.post("/api/chat", json={
        "session_id": None,
        "text": "What is my name?",
        "history": [],
    })
    assert stub.system_prompts, "stub must have received a system prompt"
    assert "## User instructions" in stub.system_prompts[0]
    assert "pirate speak" in stub.system_prompts[0]


# --- web search ---------------------------------------------------------------

def test_search_event_and_log(stubbed_app):
    app, _ = stubbed_app
    client = TestClient(app)

    r = client.post("/api/chat", json={
        "session_id": None,
        "text": "What is the latest version of PostgreSQL in 2026?",
        "history": [],
    })
    assert r.status_code == 200
    assert '"type": "search"' in r.text
    assert '"count": 1' in r.text

    db = SessionLocal()
    try:
        rows = db.scalars(select(SearchLog)).all()
        assert len(rows) == 1
        assert rows[0].results[0]["url"] == "https://example.com/pg18"
    finally:
        db.close()


def test_no_search_for_personal_query(stubbed_app):
    app, _ = stubbed_app
    client = TestClient(app)

    r = client.post("/api/chat", json={
        "session_id": None,
        "text": "What is my name?",
        "history": [],
    })
    assert '"type": "search"' not in r.text

    db = SessionLocal()
    try:
        assert db.scalars(select(SearchLog)).all() == []
    finally:
        db.close()


# --- document RAG -------------------------------------------------------------

def test_document_upload_and_retrieval(stubbed_app):
    app, _ = stubbed_app
    client = TestClient(app)

    content = (
        "Company facts. The refund policy allows 30 days for full refunds. "
        "The office address is 123 Market Street, San Francisco."
    ).encode()
    r = client.post(
        "/api/documents/upload",
        files={"file": ("company_facts.txt", content, "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "company_facts.txt"
    assert body["chunk_count"] >= 1

    docs = client.get("/api/documents").json()
    assert any(d["filename"] == "company_facts.txt" for d in docs)

    chat = client.post("/api/chat", json={
        "session_id": None,
        "text": "What is the refund policy per the company document?",
        "history": [],
    })
    done = _done_events(chat.text)
    assert done, "done event must carry the retrieved list"
    kinds = {(item["kind"], item.get("filename")) for item in done[0]["retrieved"]}
    assert ("document", "company_facts.txt") in kinds


def test_document_rejects_unsupported_type(stubbed_app):
    app, _ = stubbed_app
    client = TestClient(app)
    r = client.post(
        "/api/documents/upload",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 400


# --- pinning + transparency ---------------------------------------------------

def test_pin_filter(stubbed_app):
    app, _ = stubbed_app
    client = TestClient(app)

    client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek.",
        "history": [],
    })

    atoms = client.get("/api/memory/atoms?filter=active").json()
    assert len(atoms) == 1
    assert client.get("/api/memory/atoms?filter=pinned").json() == []

    r = client.patch(f"/api/memory/atoms/{atoms[0]['memory_id']}",
                     json={"is_pinned": True})
    assert r.status_code == 200
    assert r.json()["is_pinned"] is True

    pinned = client.get("/api/memory/atoms?filter=pinned").json()
    assert [a["memory_id"] for a in pinned] == [atoms[0]["memory_id"]]

    client.patch(f"/api/memory/atoms/{atoms[0]['memory_id']}",
                 json={"is_pinned": False})
    assert client.get("/api/memory/atoms?filter=pinned").json() == []


def test_done_event_reports_retrieved_memory(stubbed_app):
    app, _ = stubbed_app
    client = TestClient(app)

    client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek.",
        "history": [],
    })
    second = client.post("/api/chat", json={
        "session_id": None,
        "text": "What is my name?",
        "history": [],
    })
    done = _done_events(second.text)
    assert done and done[0]["memory_context_count"] > 0
    assert any(
        item["kind"] == "memory" and item["attribute"] == "name"
        for item in done[0]["retrieved"]
    )
