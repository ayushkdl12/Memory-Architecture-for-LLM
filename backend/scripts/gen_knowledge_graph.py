#!/usr/bin/env python
"""Generate the Knowledge Graph Explorer data from db/seed_data.json.

Produces:
  knowledge-graph/js/data.js     (window.GRAPH_DATA — works from file://)
  knowledge-graph/data/graph.json  (same elements, pure JSON)

Mapping:
  - every memory_atom is a (subject, attribute, value) triple
  - subject "user"          -> Person node (Aarav Thapa)
  - attributes (employer, city, language_preference, diet, seat_preference,
    trip_to_pokhara, attended_event) -> typed entity nodes + relationship edges
  - fact_versions           -> REPLACED edge (old <- new)
  - documents + chunks      -> Document node, MENTIONS edges to technologies

Usage:
    ./.venv/bin/python scripts/gen_knowledge_graph.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED = os.path.join(ROOT, "db", "seed_data.json")
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
}


class Builder:
    def __init__(self, seed: dict):
        self.seed = seed
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


def build(seed: dict) -> list[dict]:
    b = Builder(seed)
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


def main() -> int:
    seed = json.load(open(SEED))
    elements = build(seed)
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "types": TYPE_COLORS,
        "elements": elements,
    }
    os.makedirs(os.path.dirname(DATA_JS), exist_ok=True)
    os.makedirs(os.path.dirname(GRAPH_JSON), exist_ok=True)
    with open(DATA_JS, "w") as f:
        f.write("/* generated from db/seed_data.json — do not edit */\n"
                "window.GRAPH_DATA = " + json.dumps(payload) + ";\n")
    with open(GRAPH_JSON, "w") as f:
        json.dump(payload, f, indent=2)
    n_nodes = sum(1 for e in elements if "source" not in e["data"])
    n_edges = len(elements) - n_nodes
    print(f"wrote {DATA_JS} and {GRAPH_JSON} — {n_nodes} nodes, {n_edges} edges")
    subprocess.run(["open", INDEX], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())