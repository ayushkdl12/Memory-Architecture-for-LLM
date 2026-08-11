#!/usr/bin/env python
"""Compile db/schema.sql directly into a mermaid ER diagram (docs/erd_from_sql.html).

Parses CREATE TABLE blocks: columns, PRIMARY KEY, REFERENCES (...), ON DELETE.
Opens the rendered HTML in the default browser.
"""
from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(ROOT, "db", "schema.sql")

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ERD — from db/schema.sql</title>
<style>
  body {{ margin: 0; background: #fff; font-family: ui-sans-serif, system-ui, sans-serif; }}
  #erd {{ max-width: 100%; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
</head><body><pre class="mermaid">__ERD__
</pre></body></html>"""


def parse() -> tuple[list[str], list[str], list[tuple[str, str, str]]]:
    tables: list[str] = []
    entities: list[str] = []
    rels: list[tuple[str, str, str]] = []
    sql = open(SCHEMA).read()
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\);", sql, re.S):
        name, body = m.group(1), m.group(2)
        cols: list[str] = []
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("--") or line.startswith(("CONSTRAINT", "CHECK", "FOREIGN")):
                continue
            cm = re.match(r"(\w+)\s+([\w]+(?:\s*(?:\(\d+\)|(?:\[\]))?)?)\s*(.*)", line)
            if not cm:
                continue
            col, typ = cm.group(1), cm.group(2)
            rest = cm.group(3)
            pk = "PROPERTY, PK" if "PRIMARY KEY" in rest else "PROPERTY"
            cols.append(f"        {typ} {col} {pk}")
            fkm = re.search(r"REFERENCES (\w+)\((\w+)\)", rest)
            if fkm:
                rels.append((name, fkm.group(1), fkm.group(2)))
        tables.append(f"    {name} {{")
        tables.extend(cols)
        tables.append("    }")
        entities.append(name)
    return entities, tables, rels


def main() -> int:
    entities, tables, rels = parse()
    lines = ["erDiagram"]
    for src, dst, col in rels:
        lines.append(f"    {dst} ||--o{{ {src} : \"{col}\"")
    lines.extend(tables)
    erd = "\n".join(lines)

    html_doc = PAGE.replace("__ERD__", html.escape(erd))
    out = os.path.join(ROOT, "docs", "erd_from_sql.html")
    with open(out, "w") as f:
        f.write(html_doc)
    subprocess.run(["open", out], check=False)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())