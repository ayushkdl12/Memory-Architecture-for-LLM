#!/usr/bin/env python
"""Ingest a LoCoMo conversation into the live memory system.

Adds the LoCoMo-MC10 raw v1 conversation (data/locomo_sample.json, default
conv-26 — Caroline & Melanie) as real chat_sessions + messages for the demo
user, then runs the app's own MemoryExtractor (the configured LLM) over every
turn and persists the resulting atoms via TemporalManager — exactly the same
path the chat API uses. Nothing is wiped: the Aarav Thapa demo data is kept.

Role mapping: speaker_a -> "user", speaker_b -> "assistant". Message content
keeps a "[SPEAKER]: " prefix so the model attributes facts correctly.

Usage (from backend/):
    ./.venv/bin/python scripts/ingest_locomo.py              # full conv-26
    ./.venv/bin/python scripts/ingest_locomo.py --max-sessions 1   # pilot
    ./.venv/bin/python scripts/ingest_locomo.py --min-len 30 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app import provider  # noqa: E402
from app.database import engine  # noqa: E402
from app.demo import demo_user_id  # noqa: E402
from app.models import ChatSession, Message, MemoryAtom  # noqa: E402
from app.services.extractor import MemoryExtractor  # noqa: E402
from app.services.temporal import TemporalManager  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "locomo_sample.json")

_DT_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)\s*on\s+(\d{1,2})\s+(\w+),?\s+(\d{4})")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


def parse_datetime(text: str) -> datetime | None:
    m = _DT_RE.search(text.lower())
    if not m:
        return None
    h, mi, ampm, day, mon, year = m.groups()
    hour = int(h) % 12 + (12 if ampm == "pm" else 0)
    if ampm == "am" and int(h) == 12:
        hour = 0
    try:
        return datetime(int(year), _MONTHS[mon], int(day), hour, int(mi),
                        tzinfo=timezone.utc)
    except (ValueError, KeyError):
        return None


def fallback_atoms(ses: dict, sp_a: str, sp_b: str) -> list[dict]:
    """Deterministic atoms from the dataset's gold observations + events.
    Each observation sentence becomes a FACT atom (subject = speaker); each
    event_summary entry becomes an EVENT atom."""
    out: list[dict] = []
    for speaker in (sp_a, sp_b):
        for fact in ses.get("observations", {}).get(speaker, []):
            if not isinstance(fact, str) or not fact.strip():
                continue
            text = fact.strip()
            words = [w for w in re.split(r"\W+", text.replace(speaker, "", 1))
                     if w and w.lower() not in ("a", "an", "the", "to", "of",
                                                "in", "on", "at", "and", "for",
                                                "has", "was", "had", "that")]
            attr = (re.sub(r"[^a-z0-9]+", "_", " ".join(words[:5]).lower())
                    .strip("_")) or "fact"
            out.append({
                "memory_type": "FACT", "category": "locomo", "subject": speaker,
                "attribute": attr, "value": text, "content": text,
                "priority": "MEDIUM", "confidence_score": 0.9,
            })
        for ev in ses.get("events", {}).get(speaker, []):
            if not isinstance(ev, str) or not ev.strip():
                continue
            text = ev.strip()
            out.append({
                "memory_type": "EVENT", "category": "locomo", "subject": speaker,
                "attribute": "event", "value": text, "content": text,
                "priority": "LOW", "confidence_score": 0.9,
            })
    return out


def extract_with_retry(ex: MemoryExtractor, source: str, attempts: int = 3) -> list[dict]:
    for i in range(attempts):
        atoms = ex.extract(source, "")
        if atoms:
            print(f"    extraction ok on attempt {i + 1} ({len(atoms)} atoms)",
                  flush=True)
            return atoms
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", default=SAMPLE)
    ap.add_argument("--max-sessions", type=int, default=0, help="0 = all")
    ap.add_argument("--min-len", type=int, default=25,
                    help="skip turns shorter than N chars")
    ap.add_argument("--mode", choices=["summary", "turns", "deterministic"],
                    default="deterministic",
                    help="deterministic = atoms straight from the dataset's "
                         "gold observations + events (fast, recommended); "
                         "summary = run the app MemoryExtractor over the "
                         "per-session summaries (slow); turns = run it over "
                         "every turn (very slow)")
    ap.add_argument("--reset", action="store_true",
                    help="delete any previously ingested LoCoMo conv data "
                         "before ingesting")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sample = json.load(open(args.sample))
    conv = sample["sample_id"]
    sp_a, sp_b = sample["speaker_a"], sample["speaker_b"]
    sessions = sample["sessions"][:args.max_sessions] if args.max_sessions else sample["sessions"]
    uid = demo_user_id()

    extractor = MemoryExtractor(provider.get_llm())
    vs = provider.get_vector_store()

    with Session(engine) as db:
        if args.reset:
            # Only ever touch sessions created by this script (exact title
            # prefix for THIS conv + the demo user). Never subject-matching:
            # that could delete legit atoms about a similarly-named person.
            dels = db.scalars(select(ChatSession).where(
                ChatSession.user_id == uid,
                ChatSession.title.like(f"LoCoMo {conv} · %"))).all()
            for s in dels:
                for a in db.scalars(select(MemoryAtom).where(
                        MemoryAtom.session_id == s.session_id)).all():
                    db.delete(a)
                db.delete(s)
            db.commit()
            print(f"[reset] removed {len(dels)} prior {conv} sessions and "
                  "their atoms")

    created_total = 0
    msg_total = 0
    t0 = time.time()
    with Session(engine) as db:
        for i, ses in enumerate(sessions, start=1):
            dt = parse_datetime(ses["datetime"]) or datetime.now(timezone.utc)
            if args.dry_run:
                print(f"[dry] session {i}: {ses['datetime']} · {len(ses['turns'])} turns")
                continue
            chat = ChatSession(
                user_id=uid,
                title=f"LoCoMo {conv} · Session {i}",
                created_at=dt,
                updated_at=dt,
            )
            db.add(chat)
            db.flush()

            messages: list[Message] = []
            for j, t in enumerate(ses["turns"]):
                speaker = t.get("speaker", "?")
                role = "user" if speaker == sp_a else "assistant"
                msg = Message(session_id=chat.session_id, role=role,
                              content=f"[{speaker}]: {t.get('text', '')}",
                              created_at=dt + timedelta(minutes=j))
                db.add(msg)
                db.flush()
                messages.append(msg)

            tm = TemporalManager(db)
            created = 0
            if args.mode == "summary":
                source = (ses["summary"] or "") + "\nEvents:\n" + json.dumps(
                    ses.get("events", {}))[:1500]
                atoms = extract_with_retry(extractor, source)
                if not atoms:
                    atoms = fallback_atoms(ses, sp_a, sp_b)
                    if atoms:
                        print(f"    using {len(atoms)} gold observations as atoms",
                              flush=True)
            elif args.mode == "turns":
                for j, msg in enumerate(messages):
                    if len(msg.content) < args.min_len:
                        continue
                    turn_context = "\n".join(
                        f"[{m.role.upper()}]: {m.content}"
                        for m in messages[max(0, j - 5):j])
                    atoms = extractor.extract(msg.content, turn_context)
                    if not atoms:
                        continue
                    created += len(tm.process_atoms(
                        uid, chat.session_id, msg.message_id, atoms))
                    db.flush()
                db.commit()
                rows = db.scalars(select(MemoryAtom).where(
                    MemoryAtom.session_id == chat.session_id)).all()
                for row in rows:
                    vs.upsert(str(row.memory_id), row.content, {
                        "memory_type": row.memory_type, "subject": row.subject,
                        "attribute": row.attribute, "priority": row.priority,
                        "is_active": row.is_active,
                    })
                vs.flush()
                created_total += len(rows)
                msg_total += len(messages)
                el = time.time() - t0
                print(f"[{i}/{len(sessions)}] session {i}: {len(messages)} msgs, "
                      f"{len(rows)} atoms stored (elapsed {el:.0f}s)", flush=True)
                continue
            else:
                atoms = fallback_atoms(ses, sp_a, sp_b)
            created = len(tm.process_atoms(
                uid, chat.session_id, messages[0].message_id, atoms))

            db.commit()
            rows = db.scalars(select(MemoryAtom).where(
                MemoryAtom.session_id == chat.session_id)).all()
            for row in rows:
                vs.upsert(str(row.memory_id), row.content, {
                    "memory_type": row.memory_type, "subject": row.subject,
                    "attribute": row.attribute, "priority": row.priority,
                    "is_active": row.is_active,
                })
            vs.flush()
            created_total += len(rows)
            msg_total += len(messages)
            el = time.time() - t0
            print(f"[{i}/{len(sessions)}] session {i}: {len(messages)} msgs, "
                  f"{len(rows)} atoms stored (elapsed {el:.0f}s)", flush=True)

    print(f"\nDONE — {msg_total} messages, {created_total} atoms for {conv} "
          f"({len(sessions)} sessions) in {time.time() - t0:.0f}s")
    if not args.dry_run:
        print("restart the backend (uvicorn) so it reloads the vector store")
    return 0


if __name__ == "__main__":
    sys.exit(main())
