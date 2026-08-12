#!/usr/bin/env python
"""Compile db/schema.sql directly into an interactive ER diagram.

Output: docs/erd_from_sql.html — a vis-network graph with:
  - hand-placed layout (no overlap): identity -> conversation -> memory hub ->
    audit -> feature columns
  - color-grouped table cards (Core / Memory hub / Audit / Feature)
  - PK + FK columns only by default, double-click or button to expand
  - edges: solid = ON DELETE CASCADE, dashed = ON DELETE SET NULL, labeled N:1
  - legend + zoom/navigation

Usage:
    ./.venv/bin/python scripts/gen_erd_from_sql.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(ROOT, "db", "schema.sql")
OUT_PATH = os.path.join(ROOT, "docs", "erd_from_sql.html")

GROUPS = {
    "core": {"label": "Core / Identity", "color": "#3b82f6", "fill": "#1d2b53"},
    "conversation": {"label": "Conversation", "color": "#22c55e", "fill": "#123524"},
    "hub": {"label": "Memory hub", "color": "#6366f1", "fill": "#232050"},
    "audit": {"label": "Audit", "color": "#64748b", "fill": "#1e293b"},
    "feature": {"label": "Feature", "color": "#a855f7", "fill": "#2f1b4e"},
}

TABLE_GROUPS = {
    "users": "core",
    "chat_sessions": "conversation",
    "messages": "conversation",
    "memory_atoms": "hub",
    "fact_versions": "audit",
    "retrieval_logs": "audit",
    "retention_logs": "audit",
    "search_logs": "audit",
    "media": "feature",
    "user_settings": "feature",
    "documents": "feature",
    "document_chunks": "feature",
}

# deterministic hand-placed layout: [x, y]
POSITIONS = {
    "users": [0, 0],
    "chat_sessions": [330, -170],
    "messages": [330, 170],
    "memory_atoms": [660, 0],
    "fact_versions": [1010, -330],
    "retrieval_logs": [1010, -110],
    "retention_logs": [1010, 110],
    "search_logs": [1010, 330],
    "media": [1330, -290],
    "documents": [1330, -70],
    "document_chunks": [1330, 150],
    "user_settings": [1330, 380],
}


def parse_schema() -> dict:
    sql = open(SCHEMA).read()
    tables = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\);", sql, re.S):
        name, body = m.group(1), m.group(2)
        cols, fks = [], []
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
            is_pk = "PRIMARY KEY" in rest
            fkm = re.search(r"REFERENCES (\w+)\((\w+)\)\s*(ON DELETE (\w+))?", rest)
            fk = None
            if fkm:
                fk = {
                    "to": fkm.group(1),
                    "col": fkm.group(2),
                    "on_delete": (fkm.group(4) or "NO ACTION").upper(),
                }
            cols.append({"n": col, "t": typ, "pk": is_pk, "fk": fk})
            if fk:
                fks.append(col)
        tables[name] = {
            "group": TABLE_GROUPS.get(name, "core"),
            "cols": cols,
            "fks": fks,
        }
    return tables


def build_html(tables: dict) -> str:
    data = {"tables": tables, "positions": POSITIONS}
    return PAGE.replace("__DATA__", json.dumps(data))


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ERD — from db/schema.sql</title>
<style>
  body { margin: 0; background: #0f1220; color: #e5e7eb;
         font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }
  header { padding: 16px 24px; border-bottom: 1px solid #273047;
           display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 18px; }
  header .sub { color: #9ca3af; font-size: 12px; }
  #toolbar { display: flex; gap: 8px; margin-left: auto; }
  button { background: #1e2440; color: #dbeafe; border: 1px solid #34406b;
           border-radius: 8px; padding: 6px 12px; font-size: 12px; cursor: pointer; }
  button:hover { background: #2a3358; }
  #erd { height: calc(100vh - 170px); }
  #legend { padding: 10px 24px; display: flex; gap: 20px; flex-wrap: wrap;
            align-items: center; font-size: 12px; color: #9ca3af;
            border-top: 1px solid #273047; }
  #legend .g { display: inline-flex; align-items: center; gap: 7px; }
  .chip { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
  .ln { width: 22px; height: 3px; display: inline-block; }
  #err { display: none; background: #fde8e8; color: #7f1d1d; padding: 10px 16px;
         font: 12px/1.5 ui-monospace, monospace; white-space: pre-wrap; }
</style>
<script src="https://unpkg.com/vis-network@9.1.2/standalone/umd/vis-network.min.js"></script>
</head>
<body>
<div id="err"></div>
<header>
  <h1>memory_db — ER Diagram</h1>
  <span class="sub">compiled from <code>db/schema.sql</code> · solid = ON DELETE CASCADE · dashed = ON DELETE SET NULL · double-click a table to expand columns</span>
  <div id="toolbar">
    <button onclick="expandAll()">Show all columns</button>
    <button onclick="collapseAll()">Compact</button>
    <button onclick="network.fit()">Fit view</button>
  </div>
</header>
<div id="erd"></div>
<div id="legend">
  <span class="g"><span class="chip" style="background:#3b82f6"></span>Core / Identity</span>
  <span class="g"><span class="chip" style="background:#22c55e"></span>Conversation</span>
  <span class="g"><span class="chip" style="background:#6366f1"></span>Memory hub</span>
  <span class="g"><span class="chip" style="background:#64748b"></span>Audit</span>
  <span class="g"><span class="chip" style="background:#a855f7"></span>Feature</span>
  <span class="g"><span style="background:#fbbf24;border-radius:50%">🔑</span> primary key</span>
  <span class="g"><span class="ln" style="background:#64748b"></span> FK → N:1 (solid=CASCADE, dashed=SET NULL)</span>
</div>
<script>
const D = __DATA__;
const GROUPS = {
  core:       { color: "#3b82f6", fill: "#16244a" },
  conversation:{ color: "#22c55e", fill: "#10271c" },
  hub:        { color: "#6366f1", fill: "#1c1b4a" },
  audit:      { color: "#64748b", fill: "#151d2b" },
  feature:    { color: "#a855f7", fill: "#241540" }
};
const expanded = {};

function cardLabel(name, t, full) {
  const g = GROUPS[t.group];
  const pk = t.cols.filter(c => c.pk);
  const fk = t.cols.filter(c => c.fk);
  const rest = t.cols.filter(c => !c.pk && !c.fk);
  const lines = [name];
  if (full) {
    for (const c of t.cols)
      lines.push((c.pk ? "🔑 " : (c.fk ? "· " : "  ")) + c.n);
  } else {
    pk.forEach(c => lines.push("🔑 " + c.n));
    if (fk.length) lines.push("· " + fk.map(c => c.n).join(", "));
    if (rest.length) lines.push("… " + rest.length + " more");
  }
  return lines.join("\\n");
}

const nodes = [];
const edges = [];
const byName = {};
for (const [name, t] of Object.entries(D.tables)) {
  const g = GROUPS[t.group];
  byName[name] = { t, g, full: false };
  nodes.push({
    id: name, label: cardLabel(name, t, false), shape: "box",
    color: { background: g.fill, border: g.color, highlight: { background: g.fill, border: "#ffffff" } },
    font: { color: "#f1f5f9", face: "ui-monospace, Menlo, monospace", size: 12, multi: false },
    borderRadius: 10, borderWidth: 2, widthConstraint: { minimum: 150, maximum: 240 },
    x: D.positions[name][0], y: D.positions[name][1], fixed: { x: true, y: true },
    mass: 4, title: name.toUpperCase() + "\\n" + t.cols.map(c => c.n + " " + c.t + (c.fk ? " → " + c.fk.to + " (" + c.fk.on_delete + ")" : "")).join("\\n")
  });
}
for (const [child, t] of Object.entries(D.tables)) {
  for (const c of t.cols) {
    if (!c.fk) continue;
    const g = GROUPS[byName[c.fk.to].g.color];
    edges.push({
      from: child, to: c.fk.to,
      color: { color: byName[c.fk.to].g.color, opacity: 0.9 },
      width: 1.8, dashes: c.fk.on_delete === "SET NULL" ? [5, 4] : false,
      arrows: { to: { enabled: true, scaleFactor: 0.8 } },
      label: "N:1", font: { size: 10, color: "#cbd5e1", background: "#0f1220" },
      title: child + "." + c.n + " → " + c.fk.to + "." + c.fk.col + "  [" + c.fk.on_delete + "]",
      smooth: { enabled: true, type: "curvedCW", roundness: 0.12 }
    });
  }
}

const container = document.getElementById("erd");
const network = new vis.Network(container, { nodes, edges }, {
  physics: false,
  interaction: { hover: true, tooltipDelay: 120, navigationButtons: true, keyboard: true },
  nodes: { shadow: { enabled: true, color: "rgba(0,0,0,0.4)" } },
  edges: { selectionWidth: 2.5 }
});
network.on("doubleClick", p => {
  if (p.nodes.length !== 1) return;
  const name = p.nodes[0];
  byName[name].full = !byName[name].full;
  network.update([{ id: name, label: cardLabel(name, byName[name].t, byName[name].full) }]);
});
function expandAll() {
  for (const name of Object.keys(byName)) byName[name].full = true;
  network.update(Object.entries(byName).map(([name, o]) => ({ id: name, label: cardLabel(name, o.t, true) })));
}
function collapseAll() {
  for (const name of Object.keys(byName)) byName[name].full = false;
  network.update(Object.entries(byName).map(([name, o]) => ({ id: name, label: cardLabel(name, o.t, false) })));
}
window.onerror = (msg, src, line) => {
  const el = document.getElementById("err");
  el.style.display = "block";
  el.textContent = "Browser error: " + msg + " (" + (src || "") + ":" + line + ")";
};
</script>
</body>
</html>
"""


def main() -> int:
    tables = parse_schema()
    doc = build_html(tables)
    with open(OUT_PATH, "w") as f:
        f.write(doc)
    print(f"wrote {OUT_PATH} ({len(tables)} tables, "
          f"{sum(1 for t in tables.values() for c in t['cols'] if c['fk'])} FKs)")
    subprocess.run(["open", OUT_PATH], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())