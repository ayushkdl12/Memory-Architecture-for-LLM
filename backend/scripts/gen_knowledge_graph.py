#!/usr/bin/env python
"""Generate the Knowledge Graph Explorer data from db/seed_data.json and/or the
LoCoMo-MC10 raw conversation dataset.

Produces:
  knowledge-graph/js/data.js  (window.GRAPH_DATASETS + window.GRAPH_DATA — works from file://)
  knowledge-graph/data/graph.json  (dump of the same, all datasets)

Datasets:
  demo   — Aarav Thapa profile graph from db/seed_data.json
           (memory atoms -> typed entities, fact_versions -> REPLACED,
            documents+chunks -> MENTIONS)
  locomo — LoCoMo-MC10 raw v1 conversation graph from data/locomo10.json
           (conversation -> sessions -> speakers/messages, session summaries
            as Memory nodes, event_summary events, observation facts folded
            into session descriptions, QA questions typed by category)

Mapping (LoCoMo categories -> question types, per the LoCoMo paper):
  1 -> single_hop, 2 -> temporal_reasoning, 3 -> open_domain,
  4 -> multi_hop, 5 -> adversarial

Usage:
    ./.venv/bin/python scripts/gen_knowledge_graph.py                 # both datasets
    ./.venv/bin/python scripts/gen_knowledge_graph.py --source demo    # demo only
    ./.venv/bin/python scripts/gen_knowledge_graph.py --source locomo  # locomo only
    ./.venv/bin/python scripts/gen_knowledge_graph.py --conv conv-26 --max-questions 15
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED = os.path.join(ROOT, "db", "seed_data.json")
LOCOMO_RAW = os.path.join(ROOT, "data", "locomo10.json")       # 2.7 MB raw v1 (gitignored)
LOCOMO_SAMPLE = os.path.join(ROOT, "data", "locomo_sample.json")  # extracted cache (committed)
DATA_JS = os.path.join(ROOT, "knowledge-graph", "js", "data.js")
GRAPH_JSON = os.path.join(ROOT, "knowledge-graph", "data", "graph.json")
INDEX = os.path.join(ROOT, "knowledge-graph", "index.html")

TYPE_COLORS = {
    "Person": "#38bdf8",
    "Project": "#a78bfa",
    "Technology": "#22c55e",
    "Organization": "#f59e0b",
    "Location": "#ef4444",
    "Event": "#ec4899",
    "Document": "#64748b",
    "Preference": "#f472b6",
    "Conversation": "#a3e635",
    "Session": "#94a3b8",
    "Memory": "#22d3ee",
    "Message": "#64748b",
    "single_hop": "#facc15",
    "temporal_reasoning": "#fb923c",
    "open_domain": "#2dd4bf",
    "multi_hop": "#e879f9",
    "adversarial": "#f87171",
}

CATEGORY_TO_TYPE = {
    1: "single_hop",
    2: "temporal_reasoning",
    3: "open_domain",
    4: "multi_hop",
    5: "adversarial",
}


class Builder:
    def __init__(self):
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self._ids: set[str] = set()
        self._e = 0

    def node(self, id: str, label: str, type_: str, description: str,
             status: str | None = None) -> str:
        if id not in self._ids:
            self._ids.add(id)
            d = {"id": id, "label": label, "type": type_,
                 "description": description}
            if status:
                d["status"] = status
            self.nodes.append({"data": d})
        return id

    def edge(self, source: str, target: str, label: str,
             dash: bool = False, version: bool = False) -> str:
        self._e += 1
        eid = f"e{self._e}"
        d = {"id": eid, "source": source, "target": target, "label": label}
        if dash:
            d["style"] = "archived"
        if version:
            d["style"] = "version"
        self.edges.append({"data": d})
        return eid

    def elements(self) -> list[dict]:
        return self.nodes + self.edges


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ============================================================================
# demo dataset (from db/seed_data.json)
# ============================================================================
def build_demo(seed: dict) -> list[dict]:
    b = Builder()
    user = seed["user"]["name"]  # "Aarav Thapa"
    first = user.split()[0]
    person = b.node("person-user", user, "Person",
                    f"{first} — backend engineer. Memory profile subject.",
                    status="ACTIVE")

    tech_nodes: dict[str, str] = {}

    def tech(name: str, desc: str) -> str:
        nid = f"tech-{slug(name)}"
        tech_nodes[name.lower()] = b.node(nid, name, "Technology", desc)
        return nid

    def org(name: str, desc: str, status: str) -> str:
        return b.node(f"org-{slug(name)}", name, "Organization", desc, status=status)

    def loc(name: str, desc: str) -> str:
        return b.node(f"loc-{slug(name)}", name, "Location", desc)

    kathmandu = loc("Kathmandu", "Capital of Nepal. Home city.")
    pokhara = loc("Pokhara", "Lakeside city; trip destination and summit venue.")

    # ---- memory atoms -> nodes/edges --------------------------------------
    for atom in seed["memory_atoms"]:
        attr = atom["attribute"]
        value = atom["value"]
        content = atom["content"]
        active = atom["is_active"]
        status = "ACTIVE" if active else "ARCHIVED"

        if attr == "employer":
            nid = org(value,
                      content + ("" if active else f" (superseded {atom['valid_until'][:10]})"),
                      status)
            b.edge(person, nid, "WORKS_AT", dash=not active)
        elif attr == "job_title":
            pass  # folded into the Person description
        elif attr == "city":
            b.edge(person, kathmandu, "BASED_IN")
        elif attr == "language_preference":
            # value like "Python over Java"
            langs = [l.strip() for l in value.split("over") if l.strip()]
            python = tech("Python", "Preferred programming language.")
            b.edge(person, python, "PREFERS")
            if len(langs) > 1:
                java = tech(langs[1], "Previously preferred; now displaced by Python.")
                b.edge(person, java, "AVOIDS", dash=True)
        elif attr == "diet":
            nid = b.node("pref-vegetarian", value.title(), "Preference",
                         content + " (pinned)", status=status)
            b.edge(person, nid, "PREFERS")
        elif attr == "seat_preference":
            nid = b.node("pref-window-seat", "No window seats", "Preference",
                         content + " (standing rule, pinned, CRITICAL)", status=status)
            b.edge(person, nid, "RULE")
        elif attr == "trip_to_pokhara":
            nid = b.node("proj-pokhara-trip", "Trip to Pokhara", "Project",
                         "Goal: " + content + f" (expires {atom['expires_at'][:10]}).",
                         status=status)
            b.edge(person, nid, "PLANNING", dash=not active)
            b.edge(nid, pokhara, "DESTINATION")
        elif attr == "attended_event":
            name = value.split(",")[0].strip()
            nid = b.node("evt-" + slug(name), name, "Event",
                         f"Attended July 2026 in Pokhara. Memory unconfirmed.", status=status)
            b.edge(person, nid, "ATTENDED")
            b.edge(nid, pokhara, "HELD_IN")

    # ---- fact_versions: new -> old REPLACED edge --------------------------
    ids = {a["memory_id"]: a for a in seed["memory_atoms"]}
    for v in seed["fact_versions"]:
        old, new = ids.get(v["old_memory_id"]), ids.get(v["new_memory_id"])
        if old and new:
            old_id = f"org-{slug(old['value'])}"
            new_id = f"org-{slug(new['value'])}"
            b.edge(new_id, old_id, "REPLACED", version=True)

    # ---- documents + chunks -> MENTIONS ------------------------------------
    for doc in seed["documents"]:
        nid = b.node("doc-" + slug(doc["filename"]), doc["filename"], "Document",
                     f"Uploaded {doc['created_at'][:10]}: {doc['preview'][:90]}…",
                     status="ACTIVE")
        b.edge(person, nid, "UPLOADED")
    chunk_text = " ".join(c["text"] for c in seed["document_chunks"]).lower()
    for kw, desc in (
        ("python", "4 years of experience (resume)."),
        ("postgresql", "4 years of experience (resume)."),
        ("distributed systems", "Systems experience (resume)."),
    ):
        if kw in chunk_text:
            nid = tech(kw.title(), desc)
            b.edge("doc-" + slug(seed["documents"][0]["filename"]), nid, "MENTIONS")

    return b.elements()


# ============================================================================
# locomo dataset (from data/locomo10.json — LoCoMo-MC10 raw v1)
# ============================================================================
def extract_locomo_sample(*, conv: str) -> dict:
    """Extract one conversation from the raw dataset into the small cache file."""
    raw = json.load(open(LOCOMO_RAW))
    record = next(r for r in raw if r["sample_id"] == conv)
    conv_data = record["conversation"]  # speaker_a/b, session_N, session_N_date_time
    summary = record["session_summary"]
    events = record["event_summary"]
    observations = record["observation"]

    sessions = []
    i = 1
    while f"session_{i}" in conv_data:
        sid = f"session_{i}"
        ses = {
            "id": sid,
            "datetime": conv_data.get(f"{sid}_date_time", ""),
            "summary": summary.get(f"{sid}_summary", ""),
            "events": events.get(f"events_{sid}", {}),
            "turns": conv_data[sid],
        }
        obs = observations.get(f"{sid}_observation", {})
        ses["observations"] = {k: [it[0] for it in v] for k, v in obs.items()}
        sessions.append(ses)
        i += 1

    sample = {
        "dataset": "LoCoMo-MC10 raw v1",
        "sample_id": conv,
        "speaker_a": conv_data["speaker_a"],
        "speaker_b": conv_data["speaker_b"],
        "sessions": sessions,
        "questions": [
            {
                "id": f"Q{idx}",
                "category": q["category"],
                "question": q["question"],
                "answer": str(q.get("answer", "")),
                "evidence": q.get("evidence", []),
            }
            for idx, q in enumerate(record["qa"], start=1)
        ],
    }
    os.makedirs(os.path.dirname(LOCOMO_SAMPLE), exist_ok=True)
    with open(LOCOMO_SAMPLE, "w") as f:
        json.dump(sample, f, indent=1)
    print(f"wrote {LOCOMO_SAMPLE} — {len(sample['sessions'])} sessions, "
          f"{len(sample['questions'])} questions")
    return sample


def load_locomo_sample(*, conv: str) -> dict:
    if not os.path.exists(LOCOMO_RAW):
        raise SystemExit(
            f"{LOCOMO_RAW} not found — download it first:\n"
            "  curl -L 'https://huggingface.co/datasets/Percena/locomo-mc10/"
            "resolve/main/raw/locomo10.json' -o data/locomo10.json")
    if not os.path.exists(LOCOMO_SAMPLE):
        return extract_locomo_sample(conv=conv)
    sample = json.load(open(LOCOMO_SAMPLE))
    if sample["sample_id"] != conv:
        return extract_locomo_sample(conv=conv)
    return sample


def balance_questions(questions: list[dict], max_total: int) -> list[dict]:
    """Evenly sample questions across the 5 categories, at least 1 each."""
    if len(questions) <= max_total:
        return questions
    by_cat: dict[int, list[dict]] = {}
    for q in questions:
        by_cat.setdefault(q["category"], []).append(q)
    cats = sorted(by_cat)
    per = max(1, max_total // len(cats))
    picked: list[dict] = []
    for c in cats:
        pool = by_cat[c]
        step = max(1, len(pool) // per)
        picked.extend(pool[::step][:per])
    return picked[:max_total]


def session_key_from_evidence(evidence: str, sessions: list[dict]) -> str | None:
    m = re.match(r"D(\d+)", evidence)
    if not m:
        return None
    n = int(m.group(1))
    if 1 <= n <= len(sessions):
        return f"session_{n}"
    return None


def build_locomo(sample: dict, *, max_questions: int) -> list[dict]:
    b = Builder()
    conv_id = sample["sample_id"]
    sp_a, sp_b = sample["speaker_a"], sample["speaker_b"]
    sessions = sample["sessions"]

    conv = b.node("conv-" + conv_id, conv_id, "Conversation",
                  f"{sp_a} & {sp_b} · {len(sessions)} sessions over "
                  f"{sessions[0]['datetime']} → {sessions[-1]['datetime']} · "
                  f"{len(sample['questions'])} questions")
    pa = b.node("person-" + slug(sp_a), sp_a, "Person",
                f"Conversation participant A.")
    pb = b.node("person-" + slug(sp_b), sp_b, "Person",
                f"Conversation participant B.")
    b.edge(conv, pa, "FEATURES")
    b.edge(conv, pb, "FEATURES")

    for i, ses in enumerate(sessions, start=1):
        sid = ses["id"]
        n_turns = len(ses["turns"])
        obs_parts = []
        for k, facts in ses.get("observations", {}).items():
            for fact in facts[:2]:
                obs_parts.append(f"[{k}] {fact}")
        obs_txt = ("\n".join(obs_parts) or "no observation facts") + f"\n({n_turns} turns)"

        sess = b.node("s-" + sid, f"S{i}", "Session",
                      f"{ses['datetime']} · {n_turns} turns\n" + clip(ses["summary"], 220)
                      + "\nObservations:\n" + clip(obs_txt, 200))
        b.edge(conv, sess, "CONTAINS")
        b.edge(pa, sess, "PARTICIPATED")
        b.edge(pb, sess, "PARTICIPATED")

        mem = b.node("m-" + sid, f"memory S{i}", "Memory",
                     clip(ses["summary"], 400) or "No summary in dataset.")
        b.edge(sess, mem, "PRODUCED")

        # events per speaker
        for speaker in (sp_a, sp_b):
            for j, ev in enumerate(ses["events"].get(speaker, [])):
                eid = b.node(f"evt-{slug(sid)}-{j}", clip(ev, 46), "Event",
                             clip(ev, 400) + f"\n({ses['datetime']})")
                b.edge(eid, "person-" + slug(speaker), "PERFORMED_BY")
                b.edge(eid, sess, "OCCURRED_IN")

        # first + last turns as Message nodes
        turns = ses["turns"]
        picks = turns[:1] + turns[-1:] if len(turns) > 2 else turns
        for t in picks:
            sp = t.get("speaker", "?")
            mid = f"{sid}-t{slug(t.get('dia_id', ''))}"
            b.node(mid, f"{sp}: {clip(t.get('text', ''), 40)}", "Message",
                   f"{t.get('dia_id', '')} · {clip(t.get('text', ''), 400)}")
            b.edge("person-" + slug(sp), mid, "SAID")
            b.edge(sess, mid, "IN_SESSION")

    # questions -> typed nodes + evidence edges
    for q in balance_questions(sample["questions"], max_questions):
        qtype = CATEGORY_TO_TYPE.get(q["category"], "single_hop")
        desc = f"Q: {q['question']}\nAnswer: {q['answer']}"
        if q["evidence"]:
            desc += f"\nEvidence: {', '.join(q['evidence'])}"
        qid = b.node("q-" + slug(q["id"]), f"{q['id']} · {qtype}", qtype, desc)
        b.edge(conv, qid, "PART_OF")
        ev = next((e for e in q["evidence"] if e), "")
        sref = session_key_from_evidence(ev, sessions)
        if sref:
            b.edge(qid, "s-" + sref, "BASED_ON")

    return b.elements()


# ============================================================================
# output
# ============================================================================
def write_datasets(datasets: dict[str, list[dict]]) -> None:
    payloads = {}
    for name, elements in datasets.items():
        payloads[name] = {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "types": TYPE_COLORS,
            "elements": elements,
        }

    lines = ["/* generated by gen_knowledge_graph.py — do not edit */",
             "window.KG_TYPES = " + json.dumps(TYPE_COLORS) + ";",
             "window.GRAPH_DATASETS = " + json.dumps(payloads) + ";",
             "window.GRAPH_DATA = window.GRAPH_DATASETS" +
             ("['" + next(iter(payloads)) + "']" if len(payloads) == 1
              else "['demo']") + ";  // default dataset",
             ]
    os.makedirs(os.path.dirname(DATA_JS), exist_ok=True)
    with open(DATA_JS, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.makedirs(os.path.dirname(GRAPH_JSON), exist_ok=True)
    with open(GRAPH_JSON, "w") as f:
        json.dump(payloads, f, indent=2)

    for name, elements in payloads.items():
        n_nodes = sum(1 for e in elements["elements"] if "source" not in e["data"])
        n_edges = len(elements["elements"]) - n_nodes
        print(f"  {name}: {n_nodes} nodes, {n_edges} edges")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["demo", "locomo", "both"], default="both")
    ap.add_argument("--conv", default="conv-26")
    ap.add_argument("--max-questions", type=int, default=15)
    args = ap.parse_args()

    datasets: dict[str, list[dict]] = {}
    if args.source in ("demo", "both"):
        seed = json.load(open(SEED))
        datasets["demo"] = build_demo(seed)
    if args.source in ("locomo", "both"):
        sample = load_locomo_sample(conv=args.conv)
        datasets["locomo"] = build_locomo(sample, max_questions=args.max_questions)

    print("writing knowledge-graph/js/data.js + data/graph.json")
    write_datasets(datasets)
    print(f"datasets: {', '.join(datasets)}")
    subprocess.run(["open", INDEX], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())