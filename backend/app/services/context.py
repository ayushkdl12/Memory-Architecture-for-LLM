"""Prompt building and context assembly.

Highest-priority atoms are placed at the START of the injected memory block
(the report notes models attend most to the beginning and end of context), and
the single most relevant atom is re-emphasized at the END.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import settings
from ..models import MemoryAtom

SYSTEM_PROMPT = """\
You are a helpful, memory-aware assistant. A block of the user's memories is
provided below. Use it to ground your answers:

- Facts/preferences/goals/events are CURRENT unless marked otherwise.
- "Unconfirmed" memories are tentative: treat them as guesses, not facts.
- If the memory block conflicts with something the user says now, trust the
  user's latest statement and say you are updating that memory.
- If a fact the user needs is NOT in the memory block, say you don't know and
  ask a short clarifying question instead of guessing or inventing values.
- Never claim to remember something that is not present in the memory block.
- Do NOT mention that you have "memory" or a "memory block" to the user.
"""


def build_system_prompt(custom_instructions: str | None = None) -> str:
    prompt = SYSTEM_PROMPT
    if custom_instructions and custom_instructions.strip():
        prompt += (
            "\n\n## User instructions (follow these whenever they apply)\n"
            f"{custom_instructions.strip()}"
        )
    return prompt


def build_memory_context(atoms: list[dict], max_atoms: int | None = None) -> str:
    """Format the top-ranked atoms (and document passages) into a structured,
    budget-limited block."""
    if not atoms:
        return ""
    max_atoms = max_atoms or settings.context_max_atoms
    budget = settings.context_char_budget

    lines = ["<memory context>"]
    used = 0
    for i, r in enumerate(atoms[:max_atoms]):
        if used >= budget:
            break
        if "atom" in r:
            a: MemoryAtom = r["atom"]
            label = a.memory_type.title()
            since = _date(a.valid_from)
            flag = "" if a.is_confirmed else " (unconfirmed)"
            line = (
                f"{i + 1}. [{label}|{a.priority}] {a.content}{flag} "
                f"(since {since}; {a.subject}/{a.attribute})"
            )
        else:
            doc = r["document"]
            chunk = r["chunk"]
            line = (
                f"{i + 1}. [Document '{doc.filename}' chunk {chunk.chunk_index + 1}] "
                f"{chunk.text}"
            )
        if len(line) > budget - used:
            line = line[: budget - used].rstrip() + "…"
        lines.append(line)
        used += len(line)

    # End-of-block emphasis: re-state the single most relevant item.
    top = atoms[0]
    if "atom" in top:
        top_txt = top["atom"].content
    else:
        top_txt = f"[{top['document'].filename}] {top['chunk'].text}"
    lines.append(f"<most relevant> {top_txt} </most relevant>")
    lines.append("</memory context>")
    return "\n".join(lines)


def _date(dt: datetime) -> str:
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%b %Y")
