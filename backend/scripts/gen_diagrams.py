#!/usr/bin/env python
"""Generate docs/diagrams.html: interactive Knowledge Graph + ER Diagram.

Knowledge graph (vis-network):
  - live atoms (colored by memory type), sessions, messages, documents/chunks
  - provenance edges (source message -> atom), fact-version transitions
    (old -> new), retrieval edges, session clustering (clusterByConnection)
ER diagram: same vis-network widget as gen_erd_from_sql.py, from db/schema.sql.

Usage:
    ./.venv/bin/python scripts/gen_diagrams.py
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

import psycopg2  # noqa: E402
from app.database import engine  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_PATH = os.path.join(ROOT, "db", "schema.sql")
OUT_PATH = os.path.join(ROOT, "docs", "diagrams.html")

TYPE_COLORS = {
    "FACT": "#4f8ef7",
    "PREFERENCE": "#22c55e",
    "GOAL": "#f59e0b",
    "RULE": "#8b5cf6",
    "EVENT": "#ec4899",
}

ERD_GROUPS = {
    "core": {"color": "#3b82f6", "fill": "#16244a"},
    "conversation": {"color": "#22c55e", "fill": "#10271c"},
    "hub": {"color": "#6366f1", "fill": "#1c1b4a"},
    "audit": {"color": "#64748b", "fill": "#151d2b"},
    "feature": {"color": "#a855f7", "fill": "#241540"},
}
ERD_TABLE_GROUPS = {
    "users": "core", "chat_sessions": "conversation", "messages": "conversation",
    "memory_atoms": "hub", "fact_versions": "audit", "retrieval_logs": "audit",
    "retention_logs": "audit", "search_logs": "audit", "media": "feature",
    "user_settings": "feature", "documents": "feature", "document_chunks": "feature",
}
ERD_POSITIONS = {
    "users": [0, 0], "chat_sessions": [330, -170], "messages": [330, 170],
    "memory_atoms": [660, 0], "fact_versions": [1010, -330],
    "retrieval_logs": [1010, -110], "retention_logs": [1010, 110],
    "search_logs": [1010, 330], "media": [1330, -290], "documents": [1330, -70],
    "document_chunks": [1330, 150], "user_settings": [1330, 380],
}


def fetch_knowledge_graph() -> dict:
    with engine.connect() as conn:
        atoms = conn.execute(text("""
            SELECT memory_id::text, memory_type, subject, attribute, value,
                   content, priority, is_active, is_pinned, expires_at,
                   source_message_id::text, session_id::text, created_at
            FROM memory_atoms ORDER BY created_at
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
                   change_reason, changed_at FROM fact_versions
        """)).mappings().all()
        retrievals = conn.execute(text("""
            SELECT retrieval_id::text, query_text, retrieved_memory_ids,
                   message_id::text FROM retrieval_logs
        """)).mappings().all()
        docs = conn.execute(text("""
            SELECT doc_id::text, filename, session_id::text FROM documents
        """)).mappings().all()
        chunks = conn.execute(text("""
            SELECT chunk_id::text, doc_id::text, left(text, 90) AS preview
            FROM document_chunks ORDER BY chunk_index
        """)).mappings().all()

    now = datetime.now(timezone.utc)
    return {
        "generated": now.isoformat(timespec="seconds"),
        "atoms": [
            {
                "id": a["memory_id"], "type": a["memory_type"],
                "subject": a["subject"], "attribute": a["attribute"],
                "value": a["value"], "content": a["content"],
                "priority": a["priority"], "is_active": a["is_active"],
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
            {"id": r["retrieval_id"], "query": r["query_text"],
             "atom_ids": r["retrieved_memory_ids"], "message_id": r["message_id"]}
            for r in retrievals
        ],
        "documents": [dict(d) for d in docs],
        "chunks": [dict(c) for c in chunks],
    }


def parse_schema() -> dict:
    sql = open(SCHEMA_PATH).read()
    tables = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\);", sql, re.S):
        name, body = m.group(1), m.group(2)
        cols = []
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("--") or line.startswith(
                ("CONSTRAINT", "CHECK", "FOREIGN")
            ):
                continue
            cm = re.match(r"(\w+)\s+([\w]+(?:\s+PRECISION)?)\s*(.*)", line)
            if not cm:
                continue
            col, typ, rest = cm.group(1), cm.group(2), cm.group(3)
            fkm = re.search(r"REFERENCES (\w+)\((\w+)\)\s*(ON DELETE (\w+))?", rest)
            cols.append({
                "n": col, "t": typ, "pk": "PRIMARY KEY" in rest,
                "fk": {"to": fkm.group(1), "col": fkm.group(2),
                       "on_delete": (fkm.group(4) or "NO ACTION").upper()}
                if fkm else None,
            })
        tables[name] = {
            "group": ERD_TABLE_GROUPS.get(name, "core"),
            "cols": cols,
        }
    return tables


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Memory DB — Knowledge Graph & ER Diagram</title>
<style>
  body {{ margin: 0; background: #0f1220; color: #e5e7eb;
         font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }}
  header {{ padding: 14px 24px; border-bottom: 1px solid #273047; }}
  header h1 {{ margin: 0; font-size: 18px; }}
  header p {{ margin: 4px 0 0; color: #9ca3af; font-size: 12px; }}
  .tabs {{ display: flex; gap: 6px; padding: 10px 24px 0; }}
  .tab {{ background: #1e2440; color: #94a3b8; border: 1px solid #34406b;
          border-radius: 10px 10px 0 0; padding: 8px 18px; font-size: 13px;
          cursor: pointer; }}
  .tab.active {{ background: #161a2e; color: #fff; border-bottom-color: #161a2e; }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}
  #kg {{ height: 620px; }}
  #erd {{
    height: 620px; }}
  .legend {{ padding: 10px 24px; display: flex; gap: 18px; flex-wrap: wrap;
             align-items: center; font-size: 12px; color: #9ca3af;
             border-top: 1px solid #273047; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
  .sw { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
  .ln {{ width: 22px; height: 3px; display: inline-block; }}
  button {{ background: #1e2440; color: #dbeafe; border: 1px solid #34406b;
           border-radius: 8px; padding: 5px 12px; font-size: 12px; cursor: pointer; }}
  button:hover {{ background: #2a3358; }}
  #kgbar {{ display: flex; gap: 8px; align-items: center; padding: 8px 24px; }}
  #err {{ display: none; background: #fde8e8; color: #7f1d1d; padding: 10px 16px;
          font: 12px/1.5 ui-monospace, monospace; white-space: pre-wrap; }}
</style>
<script src="https://unpkg.com/vis-network@9.1.2/standalone/umd/vis-network.min.js"></script>
</head>
<body>
<div id="err"></div>
<header>
  <h1>memory_db — Knowledge Graph &amp; ER Diagram</h1>
  <p>Generated __GENERATED__ · graph from live database · ERD compiled from <code>db/schema.sql</code></p>
</header>
<div class="tabs">
  <div class="tab active" data-tab="kg" onclick="switchTab('kg')">Knowledge Graph (__N_ATOMS__ atoms)</div>
  <div class="tab" data-tab="erd" onclick="switchTab('erd')">ER Diagram (12 tables)</div>
</div>

<div class="panel active" id="pane-kg">
  <div id="kgbar">
    <button onclick="network.fit()">Fit view</button>
    <button onclick="network.clusterByConnection(0.5)">Cluster by session</button>
    <button onclick="network.openCluster(0)">Expand all</button>
  </div>
  <div id="kg"></div>
  <div class="legend">
    <span><span class="swatch" style="background:#4f8ef7"></span>FACT</span>
    <span><span class="swatch" style="background:#22c55e"></span>PREFERENCE</span>
    <span><span class="swatch" style="background:#f59e0b"></span>GOAL</span>
    <span><span class="swatch" style="background:#8b5cf6"></span>RULE</span>
    <span><span class="swatch" style="background:#ec4899"></span>EVENT</span>
    <span><span class="swatch" style="background:#a855f7"></span>document chunk</span>
    <span><span class="sw" style="background:#374151"></span>session</span>
    <span><span class="sw" style="background:#2b3148"></span>message</span>
    <span><span class="ln" style="background:#f43f5e"></span>fact version (old → new)</span>
    <span><span class="ln" style="background:#fbbf24"></span>retrieved</span>
    <span><span class="ln" style="background:#ffffff;opacity:.3"></span>provenance</span>
    <span><span style="width:14px;height:3px;background:#fbbf24;display:inline-block;vertical-align:middle"></span>gold ring = pinned</span>
    <span><span style="width:14px;height:3px;background:#f43f5e;display:inline-block;vertical-align:middle"></span>red ring = expired</span>
  </div>
</div>

<div class="panel" id="pane-erd">
  <div id="erdbar" style="padding:8px 24px;display:flex;gap:8px">
    <button onclick="erdExpandAll()">Show all columns</button>
    <button onclick="erdCollapseAll()">Compact</button>
    <button onclick="erdNetwork.fit()">Fit view</button>
  </div>
  <div id="erd"></div>
  <div class="legend">
    <span><span class="sw" style="background:#3b82f6"></span>Core</span>
    <span><span class="sw" style="background:#22c55e"></span>Conversation</span>
    <span><span class="sw" style="background:#6366f1"></span>Memory hub</span>
    <span><span class="sw" style="background:#64748b"></span>Audit</span>
    <span><span class="sw" style="background:#a855f7"></span>Feature</span>
    <span><span class="sw" style="background:#fbbf24"></span>🔑 PK</span>
    <span><span class="ln" style="background:#64748b"></span> N:1 · solid=CASCADE · dashed=SET NULL</span>
  </div>
</div>

<script>
const json = __KG_JSON__;
const erdData = __ERD_JSON__;
const TYPE_COLORS = __TYPE_COLORS__;

// ============ Knowledge Graph ============
const nodes = [];
const edges = [];
const msgById = {{}};

for (const s of json.sessions) {{
  nodes.push({{
    id: s.session_id, label: s.title, shape: "box", level: 0,
    color: {{ background: "#374151", border: "#4b5563", highlight: {{ border: "#fff" }} }},
    font: {{ color: "#d1d5db", size: 13, bold: true }},
    borderRadius: 8, borderWidth: 1.5, mass: 8,
    title: "session\\n" + s.session_id
  }});
}}
for (const m of json.messages) {{
  msgById[m.message_id] = m;
  nodes.push({{
    id: m.message_id, label: (m.role === "user" ? "🧑 " : "🤖 ") + m.preview,
    shape: "box", level: 1,
    color: {{ background: "#2b3148", border: "#4b5563" }},
    font: {{ color: "#9ca3af", size: 10 }}, borderRadius: 6, mass: 3,
    title: (m.role === "user" ? "user" : "assistant") + " message\\n" + m.preview
  }});
  edges.push({{ from: m.session_id, to: m.message_id, color: {{ color: "#4b5563" }}, width: 1, physics: false }});
}}
for (const a of json.atoms) {{
  const color = a.is_active
    ? {{ background: TYPE_COLORS[a.type] || "#64748b", border: "#0f1220" }}
    : {{ background: "#3f3f46", border: "#71717a" }};
  nodes.push({{
    id: a.id,
    label: a.subject + " → " + a.attribute,
    shape: "dot", size: a.is_pinned ? 24 : 18, mass: 1.5,
    color: color,
    font: {{ color: a.is_active ? "#f3f4f6" : "#a1a1aa", size: 11,
             background: "rgba(15,18,32,.85)", strokeWidth: 0 }},
    title: "[" + a.type + " · " + a.priority + "] " + a.content + "\\n──\\ncreated " + a.created_at.slice(0, 10)
      + (a.expires_at ? "\\nexpires " + a.expires_at.slice(0, 10) : "")
      + (a.is_pinned ? "\\n📌 pinned" : "") + (a.expired ? "\\n⌛ EXPIRED" : "")
  }});
  const src = a.source_message_id || a.session_id;
  if (src && (msgById[src] || json.sessions.some(s => s.session_id === src)))
    edges.push({{
      from: src, to: a.id, color: {{ color: "#ffffff", opacity: 0.25 }},
      dashes: [3, 3], width: 1, physics: false
    }});
}}
for (const d of json.documents) {{
  nodes.push({{
    id: d.doc_id, label: "📄 " + d.filename, shape: "box",
    color: {{ background: "#241540", border: "#a855f7" }},
    font: {{ color: "#e9d5ff", size: 11 }}, borderRadius: 6, mass: 5,
    title: "document\\n" + d.filename
  }});
  if (d.session_id)
    edges.push({{ from: d.session_id, to: d.doc_id, color: {{ color: "#4b5563" }}, width: 1, physics: false }});
}}
for (const c of json.chunks) {{
  nodes.push({{
    id: c.chunk_id, label: c.preview, shape: "box",
    color: {{ background: "#241540", border: "#c084fc" }},
    font: {{ color: "#c4b5fd", size: 9 }}, borderRadius: 4, mass: 2,
    title: "chunk of " + c.doc_id.slice(0, 8) + "\\n" + c.preview
  }});
  edges.push({{ from: c.doc_id, to: c.chunk_id, color: {{ color: "#a855f7", opacity: 0.5 }}, width: 1.2, physics: false }});
}}
for (const v of json.versions) {{
  edges.push({{
    from: v.old_memory_id, to: v.new_memory_id, color: {{ color: "#f43f5e" }}, width: 2.5,
    arrows: "to", label: v.change_reason || "updated", physics: false,
    font: {{ color: "#f43f5e", size: 10, background: "#161a2e" }}
  }});
}}
for (const r of json.retrievals) {{
  if (!msgById[r.message_id]) continue;
  for (const aid of r.atom_ids) {{
    edges.push({{
      from: r.message_id, to: aid, color: {{ color: "#fbbf24", opacity: 0.55 }},
      width: 1.5, dashes: [4, 4], physics: false, title: "retrieved for: " + r.query
    }});
  }}
}}

const kgContainer = document.getElementById("kg");
const network = new vis.Network(kgContainer, {{ nodes, edges }}, {{
  nodes: {{ borderWidth: 2, shadow: {{ enabled: true, color: "rgba(0,0,0,0.35)" }} }},
  edges: {{ smooth: {{ type: "dynamic" }}, selectionWidth: 2 }},
  physics: {{
    solver: "barnesHut",
    barnesHut: {{ gravitationalConstant: -4500, centralGravity: 0.08, springLength: 150,
                  springConstant: 0.05, damping: 0.1, avoidOverlap: 0.4 }},
    stabilization: {{ iterations: 400, fit: true }}
  }},
  interaction: {{ hover: true, tooltipDelay: 120, navigationButtons: true, keyboard: true }}
}});

// ============ ER Diagram ============
const GROUPS = {{
  core: {{ color: "#3b82f6", fill: "#16244a" }}, conversation: {{ color: "#22c55e", fill: "#10271c" }},
  hub: {{ color: "#6366f1", fill: "#1c1b4a" }}, audit: {{ color: "#64748b", fill: "#151d2b" }},
  feature: {{ color: "#a855f7", fill: "#241540" }}
}};
const erdExpanded = {{}};
function erdCard(name, t, full) {{
  const pk = t.cols.filter(c => c.pk), fk = t.cols.filter(c => c.fk),
        rest = t.cols.filter(c => !c.pk && !c.fk);
  const lines = [name];
  if (full) {{
    for (const c of t.cols) lines.push((c.pk ? "🔑 " : (c.fk ? "· " : "  ")) + c.n);
  }} else {{
    pk.forEach(c => lines.push("🔑 " + c.n));
    if (fk.length) lines.push("· " + fk.map(c => c.n).join(", "));
    if (rest.length) lines.push("… " + rest.length + " more");
  }}
  return lines.join("\\n");
}}
const erdNodes = [];
const erdEdges = [];
const erdMeta = {{}};
for (const [name, t] of Object.entries(erdData.tables)) {{
  const g = GROUPS[t.group];
  erdMeta[name] = {{ t, full: false }};
  erdNodes.push({{
    id: "t:" + name, label: erdCard(name, t, false), shape: "box",
    color: {{ background: g.fill, border: g.color, highlight: {{ border: "#fff" }} }},
    font: {{ color: "#f1f5f9", face: "ui-monospace, Menlo, monospace", size: 12 }},
    borderRadius: 10, borderWidth: 2, widthConstraint: {{ minimum: 150, maximum: 240 }},
    x: erdData.positions[name][0], y: erdData.positions[name][1],
    fixed: {{ x: true, y: true }}, mass: 4,
    title: name.toUpperCase() + "\\n" + t.cols.map(c => c.n + " " + c.t + (c.fk ? " → " + c.fk.to + " (" + c.fk.on_delete + ")" : "")).join("\\n")
  }});
}}
for (const [child, t] of Object.entries(erdData.tables)) {{
  for (const c of t.cols) {{
    if (!c.fk) continue;
    erdEdges.push({{
      from: "t:" + child, to: "t:" + c.fk.to,
      color: {{ color: GROUPS[erdData.tables[c.fk.to].group].color, opacity: 0.9 }},
      width: 1.8, dashes: c.fk.on_delete === "SET NULL" ? [5, 4] : false,
      arrows: {{ to: {{ enabled: true, scaleFactor: 0.8 }} }},
      label: "N:1", font: {{ size: 10, color: "#cbd5e1", background: "#0f1220" }},
      title: child + "." + c.n + " → " + c.fk.to + "." + c.fk.col + "  [" + c.fk.on_delete + "]",
      smooth: {{ enabled: true, type: "curvedCW", roundness: 0.12 }}
    }});
  }}
}}
const erdContainer = document.getElementById("erd");
const erdNetwork = new vis.Network(erdContainer, {{ nodes: erdNodes, edges: erdEdges }}, {{
  physics: false,
  interaction: {{ hover: true, tooltipDelay: 120, navigationButtons: true, keyboard: true }}
}});
erdNetwork.on("doubleClick", p => {{
  if (p.nodes.length !== 1) return;
  const id = p.nodes[0];
  const name = id.slice(2);
  erdMeta[name].full = !erdMeta[name].full;
  erdNetwork.update([{{ id, label: erdCard(name, erdMeta[name].t, erdMeta[name].full) }}]);
}});
function erdExpandAll() {{
  for (const name of Object.keys(erdMeta)) erdMeta[name].full = true;
  erdNetwork.update(Object.entries(erdMeta).map(([name, o]) => ({{ id: "t:" + name, label: erdCard(name, o.t, true) }})));
}}
function erdCollapseAll() {{
  for (const name of Object.keys(erdMeta)) erdMeta[name].full = false;
  erdNetwork.update(Object.entries(erdMeta).map(([name, o]) => ({{ id: "t:" + name, label: erdCard(name, o.t, false) }})));
}}
function switchTab(name) {{
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === "pane-" + name));
  const net = name === "kg" ? network : erdNetwork;
  net.redraw();
  net.fit({ animation: false });
}}
window.onerror = (msg, src, line) => {{
  const el = document.getElementById("err");
  el.style.display = "block";
  el.textContent = "Browser error: " + msg + " (" + (src || "") + ":" + line + ")";
}};
</script>
</body>
</html>
"""


def build_html(kg: dict, erd: dict) -> str:
    out = _TEMPLATE
    out = out.replace("{{", "{").replace("}}", "}")
    out = out.replace("__GENERATED__", html.escape(kg["generated"]))
    out = out.replace("__N_ATOMS__", str(len(kg["atoms"])))
    out = out.replace("__KG_JSON__", json.dumps(kg))
    out = out.replace("__ERD_JSON__", json.dumps(erd))
    out = out.replace("__TYPE_COLORS__", json.dumps(TYPE_COLORS))
    return out


def main() -> int:
    kg = fetch_knowledge_graph()
    erd = {"tables": parse_schema(), "positions": ERD_POSITIONS}
    doc = build_html(kg, erd)
    with open(OUT_PATH, "w") as f:
        f.write(doc)
    print(f"wrote {OUT_PATH} ({kg['generated']}, {len(kg['atoms'])} atoms, "
          f"{len(kg['documents'])} docs)")
    subprocess.run(["open", OUT_PATH], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())