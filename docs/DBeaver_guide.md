# DBeaver Guide — memory_db ER Diagram & Data Browsing

This guide shows how to connect DBeaver Community to the `memory_db` PostgreSQL
database and view the **Entity-Relationship diagram** of the 12-table schema.

## 1. Connect to the database

1. Open **DBeaver**.
2. Open the connection wizard: **Ctrl+Shift+O** (or `Database ▸ New Database Connection`).
3. Select **PostgreSQL** → **Next**.
4. Enter these values:

   | Field    | Value          |
   |----------|----------------|
   | Host     | `localhost`    |
   | Port     | `5432`         |
   | Database | `memory_db`    |
   | Username | `memory`       |
   | Password | `memory_pass`  |

5. Toggle **"Save password locally"** (optional).
6. Click **Test Connection** — it should report "Connected".
7. Click **Finish**.

## 2. Open the ER Diagram

1. In the **Database Navigator** panel (left side), expand
   `memory_db > PostgreSQL > memory_db`.
2. **Right-click** the `memory_db` database → **Open ER Diagram** (or press
   **Ctrl+Shift+4** with the database selected).
3. A new tab opens showing all 12 tables connected by foreign keys.

## 3. Read the diagram

- **Boxes** = tables; yellow key = primary key; green links = foreign keys.
- **Double-click** a table to expand/contract its column attributes.
- Use the **Auto Layout** action in the ERD toolbar to arrange tables neatly.
- Hover a link to see the exact FK column pair.

## 4. Export the diagram (for the project proposal)

- In the ERD tab toolbar, use the **Export** / camera icon (*File ▸ Export ▸ Image*)
  to save as **PNG, SVG, or JPG**.
- Select a subset of tables first if you only want part of the diagram.

## 5. Browse live data

- In the Navigator, expand `memory_db ▸ public ▸ Tables`.
- Right-click a table (e.g. `memory_atoms`) → **View Data** to browse the current
  rows (seed demo profile: 9 atoms, 3 chat sessions, 1 uploaded document).

## 6. Where the schema comes from

- DDL source: [`db/schema.sql`](../db/schema.sql)
- Docs variant: [`ERD.md`](ERD.md) (mermaid)
- HTML renderer (auto-generated from SQL): `docs/erd_from_sql.html`