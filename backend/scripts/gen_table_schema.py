#!/usr/bin/env python
"""Generate docs/table_schema.html — a simple, table-style view of the SQL schema.

Each PostgreSQL table from db/schema.sql becomes an HTML <table> card, grouped
by concern (Core / Conversation / Memory hub / Audit / Feature), with
PK/FK/ON DELETE badges and a live search filter.

Usage:
    ./.venv/bin/python scripts/gen_table_schema.py
"""
from __future__ import annotations

import html
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(ROOT, "db", "schema.sql")
OUT_PATH = os.path.join(ROOT, "docs", "table_schema.html")

SECTIONS = [
    ("Core & Identity", ["users"], "#3b82f6"),
    ("Conversation", ["chat_sessions", "messages"], "#22c55e"),
    ("Memory hub", ["memory_atoms"], "#6366f1"),
    ("Audit & Logs", ["fact_versions", "retrieval_logs", "retention_logs",
                      "search_logs"], "#64748b"),
    ("Feature", ["media", "user_settings", "documents", "document_chunks"],
     "#a855f7"),
]

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>memory_db — SQL Schema Tables</title>
<style>
  :root { --bg: #f6f7fb; --card: #ffffff; --line: #e2e8f0; --text: #0f172a;
          --muted: #64748b; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
         padding: 24px 28px 60px; }
  header { display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
           margin-bottom: 6px; }
  h1 { font-size: 22px; margin: 0; }
  .sub { color: var(--muted); font-size: 13px; margin: 4px 0 18px; }
  #search { width: 320px; max-width: 100%; padding: 10px 14px; border-radius: 10px;
            border: 1px solid #cbd5e1; background: #fff; font-size: 14px;
            outline: none; margin-left: auto; }
  #search:focus { border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,.15); }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px;
            color: var(--muted); margin-bottom: 22px; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  section { margin-top: 26px; }
  .section-head { font-size: 15px; font-weight: 700; letter-spacing: .02em;
                  margin-bottom: 12px; display: flex; align-items: center; gap: 10px; }
  .section-head::before { content: ""; width: 14px; height: 14px; border-radius: 4px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
          gap: 16px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 14px;
          overflow: hidden; box-shadow: 0 1px 3px rgba(15,23,42,.06);
          break-inside: avoid; }
  .card-head { padding: 12px 16px; color: #fff; font-weight: 700; font-size: 15px;
               display: flex; align-items: center; gap: 10px; }
  .card-head code { font-size: 14px; background: rgba(255,255,255,.18);
                    border-radius: 6px; padding: 2px 8px; }
  .card-head .n { margin-left: auto; font-size: 11px; font-weight: 500; opacity: .85; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 600; font-size: 11px;
       text-transform: uppercase; letter-spacing: .04em; padding: 8px 16px;
       border-bottom: 1px solid var(--line); background: #fafbfe; }
  td { padding: 8px 16px; border-bottom: 1px solid #eef2f7; vertical-align: top;
       font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  tr:last-child td { border-bottom: none; }
  .pk { display: inline-flex; align-items: center; gap: 5px; background: #fef3c7;
        color: #92400e; border: 1px solid #fde68a; border-radius: 6px;
        padding: 1px 7px; font-size: 11px; font-family: inherit; }
  .fk { display: inline-block; background: #dcfce7; color: #166534;
        border: 1px solid #bbf7d0; border-radius: 6px; padding: 1px 7px;
        font-size: 11px; font-family: inherit; white-space: nowrap; }
  .fk b { font-weight: 700; }
  .dash { color: #94a3b8; }
  footer { margin-top: 34px; color: var(--muted); font-size: 12px; }
  .hidden { display: none !important; }
  @media print { body { padding: 10px; } .card { break-inside: avoid; }
                 #search { display: none; } }
</style>
</head>
<body>
<header>
  <h1>memory_db — SQL Schema</h1>
  <input id="search" type="search" placeholder="Filter tables or columns…">
</header>
<div class="legend">
  <span><span class="pk" style="border:none">PK</span> primary key</span>
  <span><span class="fk" style="border:none">FK</span> foreign key → table(column) · on-delete action</span>
  <span>compiled from <code>db/schema.sql</code></span>
</div>
__SECTIONS__
<footer>Generated from <code>db/schema.sql</code> — 12 tables. Re-run
<b>scripts/gen_table_schema.py</b> after any schema change.</footer>
<script>
(function () {
  const input = document.getElementById("search");
  input.addEventListener("input", function () {
    const q = this.value.toLowerCase().trim();
    document.querySelectorAll(".card").forEach(card => {
      const hay = card.textContent.toLowerCase();
      card.classList.toggle("hidden", q !== "" && !hay.includes(q));
    });
  });
})();
</script>
</body>
</html>
"""


def parse_schema() -> dict[str, dict]:
    sql = open(SCHEMA).read()
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
                "name": col,
                "type": typ,
                "pk": "PRIMARY KEY" in rest,
                "fk_to": fkm.group(1) if fkm else None,
                "fk_col": fkm.group(2) if fkm else None,
                "on_delete": (fkm.group(4) or "NO ACTION").upper() if fkm else None,
            })
        tables[name] = cols
    return tables


def card(name: str, cols: list[dict], color: str) -> str:
    rows = []
    for c in cols:
        cell = f'<td>{html.escape(c["name"])}</td>'
        if c["pk"]:
            key = '<span class="pk">PK</span>'
        elif c["fk_to"]:
            key = (f'<span class="fk"><b>FK</b> → {c["fk_to"]}({c["fk_col"]})'
                   f' <span class="dash">· {c["on_delete"]}</span></span>')
        else:
            key = '<span class="dash">—</span>'
        rows.append(
            f'<tr><td>{html.escape(c["name"])}</td>'
            f'<td>{html.escape(c["type"])}</td><td>{key}</td></tr>'
        )
    return f"""<article class="card">
  <div class="card-head" style="background:{color}">
    <code>{name}</code><span class="n">{len(cols)} columns</span>
  </div>
  <table>
    <thead><tr><th>Column</th><th>Type</th><th>Key</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</article>"""


def main() -> int:
    tables = parse_schema()
    sections = []
    for title, names, color in SECTIONS:
        cards = "".join(card(n, tables[n], color) for n in names)
        rgb = color.lstrip("#")
        sections.append(
            f'<section><div class="section-head" '
            f'style="color:{color}">{title}</div>'
            f'<div class="grid" data-section="{title}">{cards}</div></section>'
        )
    doc = PAGE.replace("__SECTIONS__", "\n".join(sections))
    with open(OUT_PATH, "w") as f:
        f.write(doc)
    total_cols = sum(len(c) for c in tables.values())
    print(f"wrote {OUT_PATH} ({len(tables)} tables, {total_cols} columns)")
    subprocess.run(["open", OUT_PATH], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())