"""Memory extraction: turn conversation logs into structured memory atoms.

The extraction LLM is prompted to return a JSON array of atoms. Trivial
messages (greetings, filler) must produce NO atoms.

Local 3B models (see note on 8GB laptops) tend to emit a single JSON object
rather than a full array, and may under-report every fact in one pass. So the
extractor:
  1. tolerates `dict` OR `list` (wraps singleton into a list),
  2. runs up to N passes, feeding already-extracted atoms back to the model so
     each pass attempts to recover remaining facts,
  3. deduplicates by (memory_type, subject, attribute, value).
"""
from __future__ import annotations

import calendar
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .llm import LLMService

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {"FACT", "PREFERENCE", "GOAL", "RULE", "EVENT"}
ALLOWED_PRIORITY = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}

MAX_PASSES = 3

# Canonicalize attribute synonyms so the same fact always maps to the same
# (subject, attribute) key — required for reliable temporal versioning.
ATTRIBUTE_SYNONYMS = {
    "project deadline": "deadline",
    "project_deadline": "deadline",
    "due date": "deadline",
    "due_date": "deadline",
    "deadline date": "deadline",
    "deadline_date": "deadline",
    "preferred theme": "theme",
    "preferred_theme": "theme",
    "preferred language": "language",
    "preferred_language": "language",
    "programming language": "language",
    "programming_language": "language",
    "coding language": "language",
    "coding_language": "language",
    "favorite food": "food",
    "preferred food": "food",
    "preferred_food": "food",
    "preferred name": "name",
    "preferred_name": "name",
    "email address": "email",
    "email_address": "email",
    "phone number": "phone",
    "phone_number": "phone",
    "home town": "location",
    "home_town": "location",
    "job title": "role",
    "job_title": "role",
    "company name": "company",
    "company_name": "company",
    "work location": "workplace",
    "work_location": "workplace",
    "programming skill": "skill",
    "birthday": "event",
}

EXTRACTION_PROMPT = """\
You are a memory-extraction engine for a personal assistant. Extract durable,
useful facts about the user into memory atoms.

Your entire response must be exactly ONE JSON array, with no text before or
after it. Each element uses exactly this shape:
{{
  "memory_type": "FACT" or "PREFERENCE" or "GOAL" or "RULE" or "EVENT",
  "category": "one short word",
  "subject": "the entity this fact is about",
  "attribute": "short, stable property name",
  "value": "the actual value",
  "content": "one natural-language sentence",
  "priority": "HIGH" or "MEDIUM" or "LOW",
  "confidence_score": 0.5,
  "expires_at": "optional ISO-8601 timestamp (e.g. 2026-06-30T23:59:59) ONLY if the user stated an expiry, deadline or 'until'/'for N days' for this fact; otherwise OMIT"
}}

Example (memory_type is FACT or PREFERENCE or GOAL or RULE or EVENT):
[
  {{"memory_type": "FACT", "category": "project", "subject": "project",
    "attribute": "deadline", "value": "June 1st",
    "content": "The project deadline is June 1st.",
    "priority": "HIGH", "confidence_score": 0.9}}
]

Rules:
- subject is the ENTITY the fact is about: use "user" for the person
  themselves, "project" for the user's project. Be CONSISTENT across messages.
- attribute MUST be exactly one of: "name", "age", "language", "theme",
  "deadline", "location", "goal", "food", "workplace", "company", "role",
  "manager", "team", "skill", "email", "phone", "event", "address". Pick the
  closest one; never invent other attribute names.
- memory_type: FACT=stable fact, PREFERENCE=a user preference, GOAL=an
  objective, RULE=a hard constraint, EVENT=a specific one-time event.
- One element per fact. NEVER merge two facts into one object.
- Do NOT emit an atom for greetings, filler, or single-word acknowledgements.
  Output [] for those.
- When the user corrects an earlier fact, output the NEW value as a normal atom.
- Output the facts present in the message that are NOT already listed in
  "Already extracted" below.

Already extracted: {already}
User message: {message}
Output:
"""


def _normalize_type(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    u = v.strip().upper()
    if u in ALLOWED_TYPES:
        return u
    return None


def _prio(v: Any) -> str | None:
    if isinstance(v, str) and v.strip().upper() in ALLOWED_PRIORITY:
        return v.strip().upper()
    return None


def _confidence(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, f))


def _canon_subject(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _canon_attribute(s: str) -> str:
    s = s.replace("_", " ")
    s = re.sub(r"\(.*?\)", "", s)  # drop parentheticals
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.removeprefix("preferred ")
    s = ATTRIBUTE_SYNONYMS.get(s, s)
    return s


def _normalize_atom(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    mtype = _normalize_type(raw.get("memory_type"))
    if mtype is None:
        return None
    category = str(raw.get("category") or "").strip() or "general"
    subject = _canon_subject(str(raw.get("subject") or ""))
    attribute = _canon_attribute(str(raw.get("attribute") or ""))
    value = str(raw.get("value") or "").strip()
    content = str(raw.get("content") or "").strip()
    if not (subject and attribute and value and content):
        return None
    return {
        "memory_type": mtype,
        "category": category,
        "subject": subject,
        "attribute": attribute,
        "value": value,
        "content": content,
        "priority": _prio(raw.get("priority")) or "MEDIUM",
        "confidence_score": _confidence(raw.get("confidence_score")) or 0.5,
        "expires_at": _expiry(raw.get("expires_at")),
    }


def _expiry(v: Any):
    """Accept an ISO-8601/date string for expires_at; return a tz-aware UTC
    datetime (end-of-day for bare dates) or None."""
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


_MONTH_NAMES = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {
    m.lower(): i for i, m in enumerate(calendar.month_abbr) if m
}

_MEMORY_VERB = re.compile(
    r"\b(remember|keep|store|save|note|memorize|recall|don'?t forget)\b",
    re.IGNORECASE,
)

_EXPIRY_PATTERNS = [
    # "until 2026-06-30" / "till June 30, 2026" / "through 2026-06-30"
    re.compile(
        r"\b(?:until|till|through|thru)\s+"
        r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
        re.IGNORECASE,
    ),
    # "remember X for 2 weeks" / "keep this for 3 days"
    re.compile(
        r"\b(?:for|in|after|within|for the next)\s+"
        r"(\d+)\s+(day|days|week|weeks|month|months|year|years)\b",
        re.IGNORECASE,
    ),
]

_NAKED_DATE = re.compile(
    r"\b(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?)\b",
    re.IGNORECASE,
)


def parse_expiry(text: str) -> datetime | None:
    """Deterministic fallback: pull an expiry out of plain language.

    - "until/till/through <date>" is unambiguous and always honored.
    - Relative ("for N days") and bare dates are only honored when the user
      phrased it as a memory request (remember/keep/store/note…).
    Returns a tz-aware UTC datetime or None.
    """
    now = datetime.now(timezone.utc)
    low = text.lower()

    for m in _EXPIRY_PATTERNS[0].finditer(low):
        dt = _parse_date_token(m.group(1))
        if dt:
            return dt

    if _MEMORY_VERB.search(low):
        for m in _EXPIRY_PATTERNS[1].finditer(low):
            n = int(m.group(1))
            unit = m.group(2)
            if unit.startswith("day"):
                return (now + timedelta(days=n)).replace(hour=23, minute=59, second=59)
            if unit.startswith("week"):
                return (now + timedelta(weeks=n)).replace(hour=23, minute=59, second=59)
            if unit.startswith("month"):
                return _add_months(now, n).replace(hour=23, minute=59, second=59)
            if unit.startswith("year"):
                return (now + timedelta(days=365 * n)).replace(
                    hour=23, minute=59, second=59
                )

        m = _NAKED_DATE.search(low)
        if m:
            dt = _parse_date_token(m.group(1))
            if dt and dt > now:
                return dt

    return None


def _parse_date_token(token: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    token = token.strip()
    for src_fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(token, src_fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    m = re.match(
        r"(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?)\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?",
        token,
        re.IGNORECASE,
    )
    if m:
        month = _MONTH_NAMES[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        try:
            return datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
        except ValueError:
            return None

    # bare "2026-06-30" handled above; bare numeric month/day handled by
    # month-name parse; anything else is unsupported.
    return None


def _add_months(dt: datetime, months: int) -> datetime:
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day, tzinfo=dt.tzinfo)


def _dedup_key(atom: dict) -> tuple:
    return (
        atom["memory_type"],
        atom["subject"].lower(),
        atom["attribute"].lower(),
        atom["value"].lower(),
    )


_QUESTION_RE = re.compile(
    r"^(what|when|where|which|who|whose|whom|how|why|do|does|did|is|are|was|"
    r"were|can|could|will|would|should|shall|may|might|have|has|had|"
    r"tell me|show me|remind me)\b",
    re.IGNORECASE,
)


def is_question(message: str) -> bool:
    """A cheap, deterministic guard: questions never create memory atoms."""
    text = message.strip().lower()
    if text.endswith("?"):
        return True
    return bool(_QUESTION_RE.match(text))


class MemoryExtractor:
    def __init__(self, llm: LLMService, max_passes: int = MAX_PASSES):
        self.llm = llm
        self.max_passes = max_passes

    def _parse_list(self, data: Any) -> list[dict]:
        """Normalize the model output into a clean list of atoms."""
        if isinstance(data, dict):
            # tolerate {"atoms": [...]} and common model variants
            inner = None
            for key in ("atoms", "output", "memories", "user_message",
                        "User message", "facts", "extracted"):
                if isinstance(data.get(key), list):
                    inner = data[key]
                    break
            if inner is not None:
                data = inner
            else:
                data = [data]  # singleton object -> wrap
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for d in data:
            a = _normalize_atom(d)
            if a:
                out.append(a)
        return out

    def extract(
        self,
        message: str,
        turn_context: str,
        expires_at: datetime | None = None,
    ) -> list[dict]:
        if is_question(message):
            return []

        collected: list[dict] = []
        seen_keys: set[tuple] = set()

        for i in range(self.max_passes):
            already = collected if collected else "none yet"
            prompt = EXTRACTION_PROMPT.format(
                already=str(already), message=message
            )
            try:
                data = self.llm.complete_json(prompt)
            except Exception as exc:  # extraction must never break chat
                logger.warning("Extraction pass %d failed: %s", i + 1, exc)
                break

            new_atoms = self._parse_list(data)
            added = False
            for a in new_atoms:
                key = _dedup_key(a)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                collected.append(a)
                added = True

            if not added:
                break  # no new facts recovered -> stop

        # --- expiry precedence -------------------------------------------------
        # 1. explicit expiry from the request (calendar picker) wins,
        # 2. else the LLM's own expires_at, 3. else deterministic text parse.
        if not collected:
            return collected
        if expires_at is not None:
            for a in collected:
                a["expires_at"] = expires_at
        else:
            parsed = parse_expiry(message)
            for a in collected:
                if a.get("expires_at") is None and parsed is not None:
                    a["expires_at"] = parsed

        return collected