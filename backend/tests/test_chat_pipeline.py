"""End-to-end chat pipeline test with a stubbed LLM.

Exercises: message storage -> extraction -> temporal versioning -> embedding ->
semantic retrieval -> SSE streaming -> assistant message, all through the real
FastAPI app and PostgreSQL.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import provider
from app.database import SessionLocal
from app.demo import demo_user_id
from app.models import ChatSession, FactVersion, MemoryAtom, Message, RetrievalLog
from app.vectorstore import NumpyVectorStore


class StubLLM:
    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        out = []
        for t in texts:
            h = hashlib.md5(t.encode()).digest()
            out.append([b / 255.0 for b in h])
        return out

    def complete_json(self, prompt):
        self.calls += 1
        if self.calls == 1:
            return [
                {"memory_type": "FACT", "category": "general", "subject": "user",
                 "attribute": "name", "value": "Bibek",
                 "content": "The user's name is Bibek.", "priority": "HIGH",
                 "confidence_score": 0.95},
                {"memory_type": "PREFERENCE", "category": "language", "subject": "user",
                 "attribute": "language", "value": "Python",
                 "content": "The user prefers Python.", "priority": "HIGH",
                 "confidence_score": 0.9},
            ]
        return [
            {"memory_type": "PREFERENCE", "category": "language", "subject": "user",
             "attribute": "language", "value": "Go",
             "content": "Actually the user now prefers Go.", "priority": "HIGH",
             "confidence_score": 0.9},
        ]

    def stream_chat(self, *, system, turns, new_user_text):
        def g():
            yield SimpleNamespace(text="Hello ")
            yield SimpleNamespace(text=f"{new_user_text[:5]}!")
        return g()


@pytest.fixture
def stubbed_app(tmp_path):
    stub = StubLLM()

    def fake_get_llm():
        return stub

    def fake_get_vector_store():
        return NumpyVectorStore(str(tmp_path / "vec"), stub)

    provider._llm = None
    provider._vector_store = None
    provider.get_llm = fake_get_llm
    provider.get_vector_store = fake_get_vector_store

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
            db.execute(delete(RetrievalLog))
            db.execute(delete(FactVersion))
            db.execute(delete(MemoryAtom).where(MemoryAtom.user_id == uid))
            db.execute(delete(Message))
            db.execute(delete(ChatSession))
            db.commit()
        finally:
            db.close()

    _clean()  # remove leftovers from a live server sharing the demo DB
    yield
    _clean()


def test_chat_streams_and_stores_memory(stubbed_app):
    app, _ = stubbed_app
    client = TestClient(app)

    r = client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek and I prefer Python.",
        "history": [],
    })
    assert r.status_code == 200
    body = r.text
    assert '"type": "session"' in body
    assert '"type": "delta"' in body
    assert '"type": "done"' in body

    # active atoms were stored
    atoms = client.get("/api/memory/atoms?filter=active").json()
    assert {a["attribute"] for a in atoms} == {"name", "language"}


def test_retrieval_returns_stored_atoms(stubbed_app):
    """A question must pull the stored fact into the assistant's context."""
    import json as _json

    app, _ = stubbed_app
    client = TestClient(app)

    client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek and I prefer Python.",
        "history": [],
    })

    second = client.post("/api/chat", json={
        "session_id": None,
        "text": "What language do I prefer?",
        "history": [],
    })
    done = {}
    for line in second.text.split("\n\n"):
        if '"type": "done"' in line:
            done = _json.loads(line[5:])
    assert done.get("memory_context_count", 0) > 0

    logs = client.get("/api/memory/retrieval-logs").json()
    assert any("language" in l["query_text"] and l["retrieved_memory_ids"]
               for l in logs)


def test_chat_versions_changed_fact(stubbed_app):
    app, _ = stubbed_app
    client = TestClient(app)

    first = client.post("/api/chat", json={
        "session_id": None,
        "text": "My name is Bibek and I prefer Python.",
        "history": [],
    })
    sid = None
    for line in first.text.split("\n\n"):
        if '"type": "session"' in line:
            import json as _json

            sid = _json.loads(line[5:])["session_id"]

    second = client.post("/api/chat", json={
        "session_id": sid,
        "text": "Actually I prefer Go now.",
        "history": [{"role": "user", "content": "My name is Bibek and I prefer Python."}],
    })
    assert '"type": "done"' in second.text

    # temporal versioning: language fact changed to Go, history logged
    versions = client.get("/api/memory/fact-versions").json()
    assert len(versions) == 1
    assert versions[0]["subject"] == "user"
    assert versions[0]["attribute"] == "language"

    lang = [
        a for a in client.get("/api/memory/atoms?filter=active").json()
        if a["attribute"] == "language"
    ]
    assert lang[0]["value"] == "Go"
