#!/usr/bin/env python
"""Load db/seed.sql into the live memory_db, replacing the current demo profile.

Steps:
1. pg_dump a data-only backup to /tmp/memory_db_backup_<timestamp>.sql
2. TRUNCATE every table (clean slate; this is a demo database)
3. execute db/seed.sql verbatim
4. rebuild the local vector store (cleared files, then embed every active
   atom and document chunk)
5. print a summary of what was loaded

Run from backend/ with the server stopped OR while the server is running
(the server re-reads data per request; the vector store is rebuilt here so
the running process should be restarted afterwards to pick up the new files).

Usage:
    ./.venv/bin/python scripts/load_seed.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app import provider  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import engine as db_engine  # noqa: E402
from app.demo import demo_user_id  # noqa: E402

SEED_PATH = (
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "..", "db", "seed.sql")
)
TABLES = (
    "users", "chat_sessions", "messages", "memory_atoms", "fact_versions",
    "retrieval_logs", "retention_logs", "media", "user_settings",
    "search_logs", "documents", "document_chunks",
)


def _libpq_url() -> str:
    return settings.database_url.replace("postgresql+psycopg2://", "postgresql://")


def backup():
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = f"/tmp/memory_db_backup_{ts}.sql"
    subprocess.run(
        ["pg_dump", "--data-only", "--column-inserts", _libpq_url(), "-f", dest],
        check=True,
        capture_output=True,
    )
    print(f"[1/4] backup written to {dest}")
    return dest


def wipe():
    with db_engine.connect() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(TABLES) + " CASCADE;"))
        conn.commit()
    print("[2/4] truncated all tables")


def load_seed():
    """Execute db/seed.sql verbatim (it wraps itself in BEGIN/COMMIT)."""
    import psycopg2

    with open(os.path.normpath(SEED_PATH)) as f:
        sql = f.read()
    conn = psycopg2.connect(_libpq_url())
    try:
        conn.autocommit = True  # lets the file's own BEGIN/COMMIT control the txn
        with conn.cursor() as cur:
            cur.execute(sql)
    finally:
        conn.close()
    print("[3/4] executed db/seed.sql")


def rebuild_vector_store():
    vs_dir = settings.vector_store_dir
    if os.path.isdir(vs_dir):
        shutil.rmtree(vs_dir)
    store = provider.get_vector_store()

    with db_engine.connect() as conn:
        atoms = conn.execute(
            text(
                "SELECT memory_id::text, content, memory_type, subject, "
                "attribute, priority, is_active FROM memory_atoms "
                "WHERE user_id = :uid"
            ),
            {"uid": str(demo_user_id())},
        ).mappings().all()
        chunks = conn.execute(
            text("SELECT chunk_id::text, text FROM document_chunks")
        ).mappings().all()

    for row in atoms:
        store.upsert(
            row["memory_id"],
            row["content"],
            {
                "memory_type": row["memory_type"],
                "subject": row["subject"],
                "attribute": row["attribute"],
                "priority": row["priority"],
                "is_active": row["is_active"],
            },
        )
    for row in chunks:
        store.upsert(
            f"doc:{row['chunk_id']}",
            row["text"],
            {"kind": "document", "is_active": True},
        )
    print(f"[4/4] vector store rebuilt: {len(atoms)} atoms, {len(chunks)} chunks")


def report():
    checks = {
        "users": "SELECT count(*) FROM users",
        "sessions": "SELECT count(*) FROM chat_sessions",
        "messages": "SELECT count(*) FROM messages",
        "atoms (total)": "SELECT count(*) FROM memory_atoms",
        "atoms (active)": "SELECT count(*) FROM memory_atoms WHERE is_active",
        "fact_versions": "SELECT count(*) FROM fact_versions",
        "retention_logs": "SELECT count(*) FROM retention_logs",
        "retrieval_logs": "SELECT count(*) FROM retrieval_logs",
        "documents": "SELECT count(*) FROM documents",
        "doc chunks": "SELECT count(*) FROM document_chunks",
    }
    with db_engine.connect() as conn:
        for label, q in checks.items():
            n = conn.execute(text(q)).scalar()
            print(f"  {label:16s} {n}")


if __name__ == "__main__":
    if not os.path.exists(os.path.normpath(SEED_PATH)):
        sys.exit("seed.sql not found — run from the repo root or memory-agent/db")
    backup()
    wipe()
    load_seed()
    rebuild_vector_store()
    report()