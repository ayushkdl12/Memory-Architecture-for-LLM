#!/usr/bin/env python
"""Generate docs/diagrams.html: ERD (mermaid) + live knowledge graph (vis-network).

- Extracts the mermaid erDiagram block from docs/ERD.md
- Queries the live DB for memory atoms, provenance, fact versions, retrieval events
- Emits a single self-contained HTML file with both diagrams

Usage:
    ./.venv/bin/python scripts/gen_diagrams.py
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ERD_PATH = os.path.join(ROOT, "docs", "ERD.md")
OUT_PATH = os.path.join(ROOT, "docs", "diagrams.html")

TYPE_COLORS = {
    "FACT": "#4f8ef7",
    "PREFERENCE": "#22c55e",
    "GOAL": "#f59e0b",
    "RULE": "#8b5cf6",
    "EVENT": "#ec4899",
}


def extract_erd() -> str:
    md = open(ERD_PATH).read()
    m = re.search(r"```mermaid\n(.*?)```", md, re.S)
    if not m:
        sys.exit("no mermaid block found in ERD.md")
    return m.group(1)


def fetch_knowledge_graph() -> dict:
    with engine.connect() as conn:
        atoms = conn.execute(text("""
            SELECT memory_id::text, memory_type, subject, attribute, value,
                   content, priority, is_active, is_pinned, expires_at,
                   source_message_id::text, session_id::text, created_at
            FROM memory_atoms
            ORDER BY created_at
        """)).mappings().all()
        messages = conn.execute(text("""
            SELECT message_id::text, session_id::text, role,
                   left(content, 80) AS preview
            FROM messages ORDER BY created_at
        """)).mappings().all()
        sessions = conn.execute(text("""
            SELECT session_id::text, title FROM chat_sessions ORDER BY created_at
        """)).mappings().all()
        versions = conn.execute(text("""
            SELECT version_id::text, old_memory_id::text, new_memory_id::text,
                   change_reason, changed_at
            FROM fact_versions
        """)).mappings().all()
        retrievals = conn.execute(text("""
            SELECT retrieval_id::text, query_text, retrieved_memory_ids,
                   message_id::text
            FROM retrieval_logs
        """)).mappings().all()

    now = datetime.now(timezone.utc)
    return {
        "generated": now.isoformat(timespec="seconds"),
        "atoms": [
            {
                "id": a["memory_id"],
                "type": a["memory_type"],
                "subject": a["subject"],
                "attribute": a["attribute"],
                "value": a["value"],
                "content": a["content"],
                "priority": a["priority"],
                "is_active": a["is_active"],
                "is_pinned": a["is_pinned"],
                "expired": a["expires_at"] is not None and a["expires_at"] < now,
                "expires_at": a["expires_at"].isoformat() if a["expires_at"] else None,
                "source_message_id": a["source_message_id"],
                "session_id": a["session_id"],
                "created_at": a["created_at"].isoformat(),
            }
            for a in atoms
        ],
        "messages": [dict(m) for m in messages],
        "sessions": [dict(s) for s in sessions],
        "versions": [
            {**dict(v), "changed_at": v["changed_at"].isoformat()} for v in versions
        ],
        "retrievals": [
            {
                "id": r["retrieval_id"],
                "query": r["query_text"],
                "atom_ids": r["retrieved_memory_ids"],
                "message_id": r["message_id"],
            }
            for r in retrievals
        ],
    }


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Memory DB — ERD & Knowledge Graph</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
         background: #0f1220; color: #e5e7eb; margin: 0; }}
  header {{ padding: 18px 28px; border-bottom: 1px solid #273047; }}
  h1 {{ margin: 0; font-size: 20px; }}
  header p {{ margin: 6px 0 0; color: #9ca3af; font-size: 13px; }}
  .panel {{ background: #161a2e; margin: 24px 28px; border: 1px solid #273047;
            border-radius: 12px; overflow: hidden; }}
  .panel h2 {{ margin: 0; padding: 12px 18px; font-size: 15px;
               background: #1b2040; border-bottom: 1px solid #273047; }}
  .panel h2 small {{ color: #9ca3af; font-weight: 400; }}
  #erd {{ background: #ffffff; padding: 18px; }}
  #kg {{ height: 620px; }}
  .legend {{ padding: 10px 18px; display: flex; gap: 16px; flex-wrap: wrap;
             font-size: 12px; color: #9ca3af; border-top: 1px solid #273047; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script src="https://unpkg.com/vis-network@9.1.2/standalone/umd/vis-network.min.js"></script>
</head>
<body>
<header>
  <h1>memory_db — ER Diagram &amp; Knowledge Graph</h1>
  <p>Generated __GENERATED__ · schema from <code>db/schema.sql</code> · graph data from live database</p>
</header>

<div class="panel">
  <h2>Entity-Relationship Diagram <small>12 tables · mermaid erDiagram</small></h2>
  <div id="erd"><pre class="mermaid">__ERD__
</pre></div>
  <div class="legend">
    <span><span class="swatch" style="background:#4f8ef7"></span>FACT</span>
    <span><span class="swatch" style="background:#22c55e"></span>PREFERENCE</span>
    <span><span class="swatch" style="background:#f59e0b"></span>GOAL</span>
    <span><span class="swatch" style="background:#8b5cf6"></span>RULE</span>
    <span><span class="swatch" style="background:#ec4899"></span>EVENT</span>
    <span><span class="swatch" style="background:#9ca3af; border-radius:2px"></span>message</span>
    <span><span class="swatch" style="background:#374151; border-radius:2px"></span>session</span>
    <span><span style="width:14px;height:3px;background:#f43f5e;display:inline-block;vertical-align:middle"></span>fact version (old → new)</span>
    <span><span style="width:14px;height:3px;background:#fbbf24;display:inline-block;vertical-align:middle"></span>retrieved</span>
    <span><span style="width:14px;height:3px;background:#fff;display:inline-block;vertical-align:middle;opacity:.3"></span>provenance</span>
  </div>
</div>

<div class="panel">
  <h2>Knowledge Graph <small>memory atoms · provenance · versioning · retrieval (__N_ATOMS__ atoms)</small></h2>
  <div id="kg"></div>
</div>

<script>
const mermaid = window.mermaid;
mermaid.initialize({ startOnLoad: true, theme: "default", er: { useMaxWidth: true, fontSize: 13 } });

const json = __KG_JSON__;
const TYPE_COLORS = __TYPE_COLORS__;

const nodes = [];
const edges = [];
const byId = {};

for (const s of json.sessions) {
  nodes.push({
    id: s.session_id, label: s.title, shape: "box",
    color: { background: "#374151", border: "#4b5563" }, font: { color: "#d1d5db" },
    title: "session"
  });
}
const msgById = {};
for (const m of json.messages) {
  msgById[m.message_id] = m;
  nodes.push({
    id: m.message_id, label: (m.role === "user" ? "🧑 " : "🤖 ") + m.preview,
    shape: "box", color: { background: "#2b3148", border: "#4b5563" },
    font: { color: "#9ca3af", size: 11 }, title: m.role
  });
  edges.push({ from: m.session_id, to: m.message_id, color: { color: "#374151" }, width: 1 });
}
for (const a of json.atoms) {
  const infer = (a.value && !a.content.includes(a.value)) ? a.value : a.content;
  nodes.push({
    id: a.id,
    label: a.subject + " → " + a.attribute + "\\n" + infer.slice(0, 42),
    shape: "dot", size: a.is_pinned ? 22 : 18,
    color: a.is_active
      ? { background: TYPE_COLORS[a.type] || "#64748b", border: a.is_pinned ? "#fbbf24" : "#0f1220" }
      : { background: "#3f3f46", border: "#71717a", opacity: 0.6 },
    font: { color: a.is_active ? "#f3f4f6" : "#a1a1aa", size: 12, background: "rgba(15,18,32,.85)" },
    title: "[" + a.type + " · " + a.priority + "] " + a.content + "\\n──\\ncreated " + a.created_at.slice(0, 10)
      + (a.expires_at ? "\\nexpires " + a.expires_at.slice(0, 10) : "")
      + (a.is_pinned ? "\\n📌 pinned" : "") + (a.expired ? "\\n⌛ EXPIRED" : "")
  });
  byId[a.id] = a;
  const src = a.source_message_id || a.session_id;
  if (src)
    edges.push({ from: src, to: a.id, color: { color: "#ffffff", opacity: 0.25 }, dashes: [3, 3], width: 1 });
}
for (const v of json.versions) {
  edges.push({
    from: v.old_memory_id, to: v.new_memory_id, color: { color: "#f43f5e" }, width: 2.5,
    arrows: "to", label: v.change_reason || "updated",
    font: { color: "#f43f5e", size: 10, background: "#161a2e" }
  });
}
for (const r of json.retrievals) {
  for (const aid of r.atom_ids) {
    edges.push({
      from: r.message_id || r.id, to: aid, color: { color: "#fbbf24", opacity: 0.55 },
      width: 1.5, dashes: [4, 4], title: "retrieved for: " + r.query
    });
  }
}

const container = document.getElementById("kg");
const network = new vis.Network(container, { nodes, edges }, {
  nodes: { borderWidth: 2, shadow: { enabled: true, color: "rgba(0,0,0,0.35)" } },
  edges: { smooth: { type: "cubicBezier" }, selectionWidth: 2 },
  physics: { solver: "forceAtlas2Based", forceAtlas2Based: {
    gravitationalConstant: -60, centralGravity: 0.01, springLength: 140, springConstant: 0.08 },
    stabilization: { iterations: 300 } },
  interaction: { hover: true, tooltipDelay: 120, navigationButtons: true, keyboard: true }
});
</script>
</body>
</html>
"""


def build_html(erd: str, kg: dict) -> str:
    out = _TEMPLATE
    out = out.replace("__GENERATED__", html.escape(kg["generated"]))
    out = out.replace("__ERD__", erd)
    out = out.replace("__N_ATOMS__", str(len(kg["atoms"])))
    out = out.replace("__KG_JSON__", json.dumps(kg))
    out = out.replace("__TYPE_COLORS__", json.dumps(TYPE_COLORS))
    return out


def main() -> int:
    erd = extract_erd()
    kg = fetch_knowledge_graph()
    html_doc = build_html(erd, kg)
    with open(OUT_PATH, "w") as f:
        f.write(html_doc)
    print(f"wrote {OUT_PATH} ({kg['generated']}, {len(kg['atoms'])} atoms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())