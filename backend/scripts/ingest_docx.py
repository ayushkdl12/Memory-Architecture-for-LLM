"""Ingest a .docx user profile into the AI's memory.

The profile doc (docs/user_profile.docx) is written as one fact per bullet line,
so this ingester first tries fast, deterministic pattern rules (reliable even on
small local models). Lines that match no rule are optionally handed to the LLM
extractor (--llm-fallback), otherwise skipped.

Extracted atoms are POSTed to the running backend (`POST /api/memory/atoms`),
which applies the same TemporalManager versioning, confidence gating, and
vector-store embedding the chat pipeline uses.

Prereq: the backend must be running on :8000.
Run from backend/:  ./.venv/bin/python scripts/ingest_docx.py [--docx PATH] [--api URL] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from docx import Document

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.provider import get_llm  # noqa: E402
from app.services.extractor import MemoryExtractor  # noqa: E402

DEFAULT_DOCX = BACKEND_DIR.parent / "docs" / "user_profile.docx"
DEFAULT_API = "http://localhost:8000/api/memory/atoms"


# (memory_type, category, subject, attribute, value, priority) — value may be a
# callable extracting from match groups; content = the original sentence.
def _fact(category, attribute, value, priority="HIGH"):
    return ("FACT", category, attribute, value, priority)


def _rule(mtype, category, subject, attribute, value, priority):
    return (mtype, category, subject, attribute, value, priority)


def parse_atom(line: str) -> dict | None:
    """Deterministic parse of one profile bullet line -> atom dict (or None)."""
    s = line.strip().rstrip(".")
    low = s.lower()

    def atom(mtype, category, attribute, value, priority="MEDIUM", subject="user"):
        return {
            "memory_type": mtype,
            "category": category,
            "subject": subject,
            "attribute": attribute,
            "value": value,
            "content": line.strip(),
            "priority": priority,
            "confidence_score": 0.95,
        }

    m = re.match(r"My name is (.+)$", s, re.I)
    if m:
        return atom("FACT", "personal", "name", m.group(1).strip(), "HIGH")

    m = re.match(r"I prefer to be called (.+)$", s, re.I)
    if m:
        return atom("FACT", "personal", "name", m.group(1).strip(), "HIGH")

    m = re.match(r"I am (\d+) years old$", s, re.I)
    if m:
        return atom("FACT", "personal", "age", m.group(1), "MEDIUM")

    m = re.match(r"I live in (.+)$", s, re.I)
    if m:
        return atom("FACT", "personal", "location", m.group(1).strip(), "MEDIUM")

    m = re.match(r"My email address is (.+)$", s, re.I)
    if m:
        return atom("FACT", "personal", "email", m.group(1).strip(), "MEDIUM")

    m = re.match(r"My phone number is (.+)$", s, re.I)
    if m:
        return atom("FACT", "personal", "phone", m.group(1).strip(), "MEDIUM")

    m = re.match(r"I work as (?:a|an) (.+)$", s, re.I)
    if m:
        return atom("FACT", "work", "role", m.group(1).strip(), "HIGH")

    m = re.match(r"I work at (.+)$", s, re.I)
    if m:
        return atom("FACT", "work", "company", m.group(1).strip(), "HIGH")

    m = re.match(r"I have been (?:a|an) (.+?) for (\d+) years$", s, re.I)
    if m:
        return atom("FACT", "work", "experience", f"{m.group(2)} years as {m.group(1)}", "HIGH")

    m = re.match(r"My team works on (.+)$", s, re.I)
    if m:
        return atom("FACT", "work", "team", m.group(1).strip(), "MEDIUM")

    m = re.match(r"My manager is (.+)$", s, re.I)
    if m:
        return atom("FACT", "work", "manager", m.group(1).strip(), "MEDIUM")

    m = re.match(r"I am fluent in (.+)$", s, re.I)
    if m:
        return atom("FACT", "skill", "skill", m.group(1).strip(), "HIGH")

    m = re.match(r"I know (.+)$", s, re.I)
    if m:
        return atom("FACT", "skill", "skill", m.group(1).strip(), "MEDIUM")

    m = re.match(r"I work with (.+) every day$", s, re.I)
    if m:
        return atom("FACT", "skill", "skill", m.group(1).strip(), "MEDIUM")

    m = re.match(r"I use (.+) for local development$", s, re.I)
    if m:
        return atom("FACT", "skill", "skill", m.group(1).strip(), "MEDIUM")

    m = re.match(r"I am learning (.+)$", s, re.I)
    if m:
        return atom("GOAL", "learning", "skill", m.group(1).strip(), "MEDIUM")

    # Preferences: known phrases map to typed attributes, others -> generic.
    known_pref = {
        "dark mode in all my tools": ("theme", "dark mode"),
        "coding with a keyboard over a mouse": ("preference", "keyboard over mouse"),
        "black coffee": ("food", "black coffee"),
    }
    m = re.match(r"I prefer (.+)$", s, re.I)
    if m:
        pref = m.group(1).strip()
        attr, value = known_pref.get(low[len("I prefer "):].rstrip("."), ("preference", pref))
        return atom("PREFERENCE", "preference", attr, value, "MEDIUM")

    if "morning person" in low:
        return atom("PREFERENCE", "preference", "preference", "morning person", "MEDIUM")

    if "asynchronous communication" in low:
        return atom("PREFERENCE", "preference", "preference", "asynchronous communication", "MEDIUM")

    if "electronic music" in low:
        return atom("PREFERENCE", "preference", "preference", "electronic music", "MEDIUM")

    m = re.match(r"My goal is to (.+)$", s, re.I)
    if m:
        return atom("GOAL", "goal", "goal", "to " + m.group(1).strip(), "HIGH")

    m = re.match(r"The project deadline for (.+?) is (.+)$", s, re.I)
    if m:
        return atom("FACT", "project", "deadline", m.group(2).strip(), "CRITICAL",
                    subject=m.group(1).strip())

    m = re.match(r"My (.+?) is scheduled for (.+)$", s, re.I)
    if m:
        return atom("EVENT", "event", "event", f"{m.group(1)} on {m.group(2)}", "MEDIUM")

    m = re.match(r"I will attend (.+?) on (.+)$", s, re.I)
    if m:
        return atom("EVENT", "event", "event", f"{m.group(1)} on {m.group(2)}", "MEDIUM")

    m = re.match(r"My birthday is on (.+)$", s, re.I)
    if m:
        return atom("EVENT", "event", "event", f"birthday on {m.group(1)}", "MEDIUM")

    if "team standup" in low:
        return atom("RULE", "work", "rule", "team standup every weekday at 10am", "MEDIUM")

    return None


def read_bullets(path: Path) -> list[str]:
    doc = Document(path)
    return [p.text.strip() for p in doc.paragraphs if p.style.name == "List Bullet" and p.text.strip()]


def post_atom(atom: dict, api_url: str) -> dict:
    req = urllib.request.Request(
        api_url,
        data=json.dumps(atom).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docx", type=Path, default=DEFAULT_DOCX)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--llm-fallback", action="store_true",
                        help="send unmatched lines to the LLM extractor (slow)")
    args = parser.parse_args()

    if not args.docx.exists():
        print(f"docx not found: {args.docx}")
        sys.exit(1)

    bullets = read_bullets(args.docx)
    print(f"{len(bullets)} profile lines found in {args.docx.name}")

    parsed = 0
    unmatched: list[str] = []
    atoms: list[dict] = []
    for line in bullets:
        a = parse_atom(line)
        if a:
            atoms.append(a)
            parsed += 1
        else:
            unmatched.append(line)

    if args.llm_fallback and unmatched:
        ex = MemoryExtractor(get_llm())
        for line in unmatched:
            for a in ex.extract(line, turn_context="profile docx fallback"):
                atoms.append(a)
        print(f"LLM fallback extracted extra atoms for {len(unmatched)} unmatched lines")

    print(f"parsed {parsed} lines deterministically; unmatched: {len(unmatched)}")
    for line in unmatched:
        print(f"  ! unmatched: {line}")

    stored = 0
    for a in atoms:
        if args.dry_run:
            print(f"[dry-run] [{a['memory_type']}|{a['priority']}] "
                  f"{a['subject']}/{a['attribute']} = {a['value']}")
            stored += 1
        else:
            try:
                out = post_atom(a, args.api)
                stored += 1
                print(f"[stored] {out['subject']}/{out['attribute']} = {out['value']} "
                      f"(confirmed={out['is_confirmed']})")
            except Exception as exc:
                print(f"[failed] {a['subject']}/{a['attribute']} = {a['value']}: {exc}")

    print(f"\nTotal atoms stored: {stored}")


if __name__ == "__main__":
    main()
