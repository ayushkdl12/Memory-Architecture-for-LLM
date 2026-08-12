"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import KnowledgeGraphView from "./KnowledgeGraphView";
import {
  getSummary,
  getAtoms,
  getFactVersions,
  getRetrievalLogs,
  getRetentionLogs,
  runSweep,
  createAtom,
  updateAtom,
  deleteAtom,
  restoreAtom,
} from "../lib/api";

const TABS = [
  { key: "active", label: "Active Atoms" },
  { key: "pinned", label: "Pinned" },
  { key: "archived", label: "Archived" },
  { key: "all", label: "All Atoms" },
  { key: "versions", label: "Fact History" },
  { key: "retrieval", label: "Retrieval Logs" },
  { key: "retention", label: "Retention Logs" },
  { key: "graph", label: "Knowledge Graph" },
];

const TYPES = ["FACT", "PREFERENCE", "GOAL", "RULE", "EVENT"];
const PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

function fmt(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  return d.toLocaleString();
}

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-CA"); // YYYY-MM-DD in local tz
}

const EMPTY_ATOM = {
  memory_type: "FACT",
  category: "general",
  subject: "",
  attribute: "",
  value: "",
  content: "",
  priority: "MEDIUM",
  confidence_score: 0.5,
  expires_at: null,
};

function AtomEditor({ atom, isNew, onClose, onSaved, onDeleted }) {
  const [form, setForm] = useState(
    atom
      ? {
          memory_type: atom.memory_type,
          category: atom.category,
          subject: atom.subject,
          attribute: atom.attribute,
          value: atom.value,
          content: atom.content,
          priority: atom.priority,
          confidence_score: atom.confidence_score,
          expires_at: atom.expires_at || "",
        }
      : { ...EMPTY_ATOM }
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const set = (k) => (e) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function save() {
    setSaving(true);
    setErr("");
    const data = { ...form, expires_at: form.expires_at || null };
    try {
      if (isNew) {
        await createAtom(data);
      } else {
        const patch = {};
        for (const k of Object.keys(data)) {
          if (data[k] !== atom[k]) patch[k] = data[k];
        }
        await updateAtom(atom.memory_id, patch);
      }
      onSaved();
    } catch (e) {
      setErr(e.message);
    }
    setSaving(false);
  }

  async function del() {
    if (!window.confirm("Delete this memory atom permanently?")) return;
    setSaving(true);
    setErr("");
    try {
      await deleteAtom(atom.memory_id);
      onDeleted();
    } catch (e) {
      setErr(e.message);
    }
    setSaving(false);
  }

  async function restore() {
    setSaving(true);
    setErr("");
    try {
      await restoreAtom(atom.memory_id);
      onSaved();
    } catch (e) {
      setErr(e.message);
    }
    setSaving(false);
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{isNew ? "Add memory atom" : "Edit memory atom"}</h3>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>

        <div className="form-grid">
          <label>Type
            <select value={form.memory_type} onChange={set("memory_type")}>
              {TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </label>
          <label>Priority
            <select value={form.priority} onChange={set("priority")}>
              {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
            </select>
          </label>
          <label>Category
            <input value={form.category} onChange={set("category")} />
          </label>
          <label>Confidence (0–1)
            <input
              type="number" min="0" max="1" step="0.05"
              value={form.confidence_score}
              onChange={set("confidence_score")}
            />
          </label>
          <label>Subject
            <input value={form.subject} onChange={set("subject")} placeholder="user" />
          </label>
          <label>Attribute
            <input value={form.attribute} onChange={set("attribute")} placeholder="language" />
          </label>
          <label className="full">Value
            <input value={form.value} onChange={set("value")} placeholder="Go" />
          </label>
          <label className="full">Expires on (optional — leave empty for indefinite)
            <input
              type="date"
              value={form.expires_at ? fmtDate(form.expires_at) : ""}
              onChange={(e) => {
                const v = e.target.value;
                setForm((f) => ({ ...f, expires_at: v ? `${v}T23:59:59Z` : null }));
              }}
            />
          </label>
          <label className="full">Content
            <textarea
              rows={3}
              value={form.content}
              onChange={set("content")}
              placeholder="One natural-language sentence."
            />
          </label>
        </div>

        {err && <div style={{ color: "var(--danger)", margin: "8px 0" }}>⚠ {err}</div>}

        <div className="modal-actions">
          {!isNew && atom && !atom.is_active && (
            <button className="btn ghost" onClick={restore} disabled={saving}>
              Restore
            </button>
          )}
          {!isNew && atom && (
            <button className="btn danger" onClick={del} disabled={saving}>
              Delete
            </button>
          )}
          <div style={{ flex: 1 }} />
          <button className="btn ghost" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : isNew ? "Create" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AtomTable({ atoms, onEdit, onTogglePin }) {
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            <th>Type</th>
            <th>Priority</th>
            <th>Subject / Attribute</th>
            <th>Value</th>
            <th>Status</th>
            <th>Valid from → until</th>
            <th>Expires</th>
            <th>Conf.</th>
            <th>Access</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {atoms.map((a) => (
            <tr key={a.memory_id} onClick={() => onEdit(a)} className="clickable">
              <td>
                {a.is_pinned && <span className="chip pin" title="Pinned">📌</span>}
                <span className={`chip ${a.memory_type}`}>{a.memory_type}</span>
              </td>
              <td>{a.priority}</td>
              <td>{a.subject} / {a.attribute}</td>
              <td>{a.value}</td>
              <td>
                <span className={`chip ${a.retention_status}`}>
                  {a.is_active ? "ACTIVE" : a.retention_status}
                </span>
                {a.is_active && !a.is_confirmed && (
                  <span className="chip unconfirmed" title="Low-confidence memory">unconfirmed</span>
                )}
              </td>
              <td className="muted">
                {fmt(a.valid_from)} → {a.valid_until ? fmt(a.valid_until) : <span style={{ color: "var(--accent-2)" }}>now</span>}
              </td>
              <td>
                {a.expires_at ? (
                  <span className="chip chip-expiry" title="Auto-archived after this date">
                    ⏳ {fmtDate(a.expires_at)}
                  </span>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>{a.confidence_score?.toFixed(2)}</td>
              <td>{a.access_count ?? 0}</td>
              <td>
                <button
                  className="icon-btn"
                  title={a.is_pinned ? "Unpin atom" : "Pin atom"}
                  onClick={(e) => {
                    e.stopPropagation();
                    onTogglePin(a);
                  }}
                >
                  {a.is_pinned ? "📌" : "📍"}
                </button>
                <button
                  className="icon-btn"
                  title="Edit atom"
                  onClick={(e) => {
                    e.stopPropagation();
                    onEdit(a);
                  }}
                >
                  ✎
                </button>
              </td>
            </tr>
          ))}
          {atoms.length === 0 && (
            <tr>
              <td colSpan={10} className="muted">No atoms to display.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function DashboardPage() {
  const [tab, setTab] = useState("active");
  const [summary, setSummary] = useState(null);
  const [atoms, setAtoms] = useState([]);
  const [versions, setVersions] = useState([]);
  const [retrieval, setRetrieval] = useState([]);
  const [retention, setRetention] = useState([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [sweepMsg, setSweepMsg] = useState("");
  const [sweeping, setSweeping] = useState(false);
  const [editing, setEditing] = useState(null); // atom | {_new: true}

  async function load() {
    setSummary(await getSummary());
    setVersions(await getFactVersions());
    setRetrieval(await getRetrievalLogs());
    setRetention(await getRetentionLogs());
  }

  async function loadAtoms() {
    const filter = tab === "archived" || tab === "all" || tab === "pinned" ? tab : "active";
    setAtoms(await getAtoms(filter));
  }

  useEffect(() => {
    load().catch(console.error);
  }, []);

  useEffect(() => {
    loadAtoms().catch(console.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, typeFilter]);

  async function onSweep(dry) {
    setSweeping(true);
    setSweepMsg("");
    try {
      const res = await runSweep(dry);
      setSweepMsg(
        dry
          ? `Dry run: ${res.archived.length} atoms would be archived.`
          : `Sweep complete: ${res.archived.length} atoms archived, ${res.logged.length} decisions logged.`
      );
      await load();
      await loadAtoms();
    } catch (e) {
      setSweepMsg(`Sweep error: ${e.message}`);
    }
    setSweeping(false);
  }

  async function afterEdit() {
    setEditing(null);
    await load();
    await loadAtoms();
  }

  const editingAtom = editing && !editing._new ? editing : null;
  const isNew = editing && editing._new;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><span className="dot" /> Memory Agent</div>
        <div className="nav" style={{ marginBottom: 12 }}>
          <Link href="/">Chat</Link>
          <Link href="/dashboard" className="active">Memory</Link>
        </div>
        <div style={{ padding: "0 12px", flex: 1 }}>
          <p className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
            Developer dashboard: inspect, add, edit, delete or restore memory
            atoms, plus temporal versions, retrieval events and retention decisions.
          </p>
        </div>
      </aside>

      <main className="dashboard">
        <h2 style={{ marginTop: 0 }}>Memory Dashboard</h2>

        <div className="cards">
          {summary && (
            <>
              <div className="card"><div className="num">{summary.active_atoms}</div><div className="lbl">Active atoms</div></div>
              <div className="card"><div className="num">{summary.archived_atoms}</div><div className="lbl">Archived</div></div>
              <div className="card"><div className="num">{summary.total_atoms}</div><div className="lbl">Total atoms</div></div>
              <div className="card"><div className="num">{summary.total_sessions}</div><div className="lbl">Sessions</div></div>
              <div className="card"><div className="num">{summary.retrieval_count}</div><div className="lbl">Retrievals</div></div>
              <div className="card"><div className="num">{summary.retention_count}</div><div className="lbl">Retention decisions</div></div>
              <div className="card"><div className="num">{summary.expiring_soon ?? 0}</div><div className="lbl">Expiring ≤ 7 days</div></div>
            </>
          )}
        </div>

        <div className="tabs">
          {TABS.map((t) => (
            <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>

        {(tab === "active" || tab === "all" || tab === "archived" || tab === "pinned") && (
          <>
            <div className="toolbar">
              <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="">All types</option>
                {TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <button className="btn primary" onClick={() => setEditing({ _new: true })}>
                + Add fact
              </button>
              <div style={{ flex: 1 }} />
              <button onClick={() => onSweep(false)} disabled={sweeping}>
                Run retention sweep
              </button>
              <button onClick={() => onSweep(true)} disabled={sweeping}>
                Dry-run sweep
              </button>
            </div>
            {sweepMsg && <div className="muted" style={{ marginBottom: 10 }}>{sweepMsg}</div>}
            <AtomTable
              atoms={atoms.filter((a) => !typeFilter || a.memory_type === typeFilter)}
              onEdit={setEditing}
              onTogglePin={async (a) => {
                await updateAtom(a.memory_id, { is_pinned: !a.is_pinned });
                await loadAtoms();
              }}
            />
          </>
        )}

        {tab === "versions" && (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Changed at</th><th>Subject / Attribute</th>
                  <th>Old memory</th><th>New memory</th><th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.version_id}>
                    <td>{fmt(v.changed_at)}</td>
                    <td>{v.subject} / {v.attribute}</td>
                    <td className="muted">{v.old_memory_id ? v.old_memory_id.slice(0, 8) : "—"}</td>
                    <td className="muted">{v.new_memory_id ? v.new_memory_id.slice(0, 8) : "—"}</td>
                    <td>{v.change_reason || "—"}</td>
                  </tr>
                ))}
                {versions.length === 0 && (
                  <tr><td colSpan={5} className="muted">No fact version changes yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {tab === "retrieval" && (
          <div className="scroll">
            <table>
              <thead>
                <tr><th>Time</th><th>Query</th><th>Retrieved atoms</th></tr>
              </thead>
              <tbody>
                {retrieval.map((r) => (
                  <tr key={r.retrieval_id}>
                    <td>{fmt(r.created_at)}</td>
                    <td>{r.query_text}</td>
                    <td className="muted">{(r.retrieved_memory_ids || []).length} atom(s)</td>
                  </tr>
                ))}
                {retrieval.length === 0 && (
                  <tr><td colSpan={3} className="muted">No retrieval events yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {tab === "retention" && (
          <div className="scroll">
            <table>
              <thead>
                <tr><th>Time</th><th>Atom</th><th>Action</th><th>Score</th><th>Reason</th></tr>
              </thead>
              <tbody>
                {retention.map((r) => (
                  <tr key={r.retention_id}>
                    <td>{fmt(r.created_at)}</td>
                    <td className="muted">{r.memory_id.slice(0, 8)}</td>
                    <td><span className={`chip ${r.action}`}>{r.action}</span></td>
                    <td className="muted">{r.score != null ? r.score.toFixed(3) : "—"}</td>
                    <td>{r.reason || "—"}</td>
                  </tr>
                ))}
                {retention.length === 0 && (
                  <tr><td colSpan={5} className="muted">No retention decisions yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {tab === "graph" && <KnowledgeGraphView />}
      </main>

      {(isNew || editingAtom) && (
        <AtomEditor
          atom={editingAtom}
          isNew={isNew}
          onClose={() => setEditing(null)}
          onSaved={afterEdit}
          onDeleted={afterEdit}
        />
      )}
    </div>
  );
}
