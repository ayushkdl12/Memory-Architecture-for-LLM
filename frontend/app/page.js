"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import hljs from "highlight.js";
import "highlight.js/styles/github-dark.css";
import {
  listSessions,
  createSession,
  getSession,
  deleteSession,
  streamChat,
  uploadImage,
  uploadDocument,
  getSettings,
  updateSettings,
} from "./lib/api";

const SPEECH_SUPPORTED =
  typeof window !== "undefined" &&
  Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);

const PRESETS = [
  { name: "Concise", text: "Be concise. Prefer short answers over long ones." },
  { name: "Friendly", text: "Be warm, friendly and encouraging in your tone." },
  { name: "Academic", text: "Answer academically: precise, formal, and cite sources when possible." },
  { name: "Tutor", text: "Act as a patient tutor: explain step by step and check understanding." },
  { name: "Professional", text: "Use professional, business-appropriate language." },
];

const ARTIFACT_LANGS = new Set(["html", "svg", "python", "javascript", "js", "ts", "sql", "json", "bash", "css"]);

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-CA"); // YYYY-MM-DD in local tz
}

function speak(text) {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  window.speechSynthesis.speak(u);
}

function CodeBlock({ className, children, onArtifact }) {
  const match = /language-(\w+)/.exec(className || "");
  const lang = match ? match[1].toLowerCase() : "text";
  const code = String(children).replace(/\n$/, "");
  let highlighted = null;
  try {
    highlighted = hljs.highlight(code, { language: lang }).value;
  } catch {}
  return (
    <div className="code-block">
      <div className="code-head">
        <span className="code-lang">{lang}</span>
        <span className="code-actions">
          <button onClick={() => navigator.clipboard?.writeText(code)}>Copy</button>
          {ARTIFACT_LANGS.has(lang) && (
            <button onClick={() => onArtifact(code, lang)}>⧉ Open</button>
          )}
        </span>
      </div>
      <pre>
        {highlighted ? (
          <code dangerouslySetInnerHTML={{ __html: highlighted }} />
        ) : (
          <code>{code}</code>
        )}
      </pre>
    </div>
  );
}

function Markdown({ text, onArtifact }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            if (!className) return <code {...props}>{children}</code>;
            return <CodeBlock className={className} onArtifact={onArtifact}>{children}</CodeBlock>;
          },
          a({ href, children }) {
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function ArtifactPanel({ artifact, onClose }) {
  if (!artifact) return null;
  const { code, language } = artifact;
  let body;
  if (language === "html") {
    body = <iframe sandbox="" srcDoc={code} className="artifact-frame" title="artifact" />;
  } else if (language === "svg") {
    body = <div dangerouslySetInnerHTML={{ __html: code }} className="artifact-svg" />;
  } else {
    let highlighted = null;
    try {
      highlighted = hljs.highlight(code, { language }).value;
    } catch {}
    body = (
      <pre className="artifact-code">
        {highlighted ? (
          <code dangerouslySetInnerHTML={{ __html: highlighted }} />
        ) : (
          <code>{code}</code>
        )}
      </pre>
    );
  }
  return (
    <div className="artifact-overlay" onClick={onClose}>
      <div className="artifact-panel" onClick={(e) => e.stopPropagation()}>
        <div className="artifact-head">
          <span>⧉ {language}</span>
          <span className="code-actions">
            <button onClick={() => navigator.clipboard?.writeText(code)}>Copy</button>
            <button onClick={onClose}>✕</button>
          </span>
        </div>
        {body}
      </div>
    </div>
  );
}

function SettingsModal({ value, onClose, onSave }) {
  const [text, setText] = useState(value);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Custom instructions</h3>
          <p className="muted">
            Always-on instructions (ChatGPT/Claude style). Start with a preset:
          </p>
        </div>
        <div className="presets">
          {PRESETS.map((p) => (
            <button key={p.name} className="btn ghost" onClick={() => setText(p.text)}>
              {p.name}
            </button>
          ))}
        </div>
        <textarea
          className="settings-input"
          rows={6}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Always answer in bullet points. I am a backend engineer — use technical terms."
        />
        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" onClick={() => onSave(text)}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function Nav({ sessions, currentId, onSelect, onNew, onDelete }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="dot" /> Memory Agent
      </div>
      <button className="new-chat" onClick={onNew}>
        + New chat
      </button>
      <div className="nav">
        <Link href="/" className="active">
          Chat
        </Link>
        <Link href="/dashboard">Memory</Link>
      </div>
      <div className="sessions">
        {sessions.length === 0 && (
          <div className="muted" style={{ padding: 12, fontSize: 13 }}>
            No conversations yet.
          </div>
        )}
        {sessions.map((s) => (
          <div
            key={s.session_id}
            className={`session-item ${s.session_id === currentId ? "active" : ""}`}
            onClick={() => onSelect(s.session_id)}
            title={s.title}
          >
            {s.title}
            <button
              style={{
                float: "right",
                background: "none",
                border: "none",
                color: "var(--muted)",
                padding: 0,
                fontSize: 13,
              }}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(s.session_id);
              }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}

export default function ChatPage() {
  const pathname = usePathname();
  const [sessions, setSessions] = useState([]);
  const [currentId, setCurrentId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState(null);
  const [attachment, setAttachment] = useState(null); // {kind, url?, filename?, description?}
  const [uploading, setUploading] = useState(false);
  const [listening, setListening] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [artifact, setArtifact] = useState(null);
  const bottomRef = useRef(null);
  const historyRef = useRef([]);
  const fileRef = useRef(null);
  const docRef = useRef(null);
  const expiryRef = useRef(null);
  const recRef = useRef(null);
  const searchedRef = useRef(0);

  useEffect(() => {
    listSessions()
      .then((ss) => {
        setSessions(ss);
        if (ss.length) selectSession(ss[0].session_id);
      })
      .catch((e) => setError(e.message));
    getSettings().then((s) => setInstructions(s.custom_instructions)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    return () => recRef.current?.stop();
  }, []);

  const scrollBottom = () =>
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });

  async function selectSession(id) {
    setCurrentId(id);
    setAttachment(null);
    const data = await getSession(id);
    setMessages(data.messages);
    historyRef.current = data.messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));
    scrollBottom();
  }

  async function newChat() {
    const s = await createSession();
    setSessions((prev) => [s, ...prev]);
    setCurrentId(s.session_id);
    setMessages([]);
    historyRef.current = [];
    setAttachment(null);
    setError(null);
  }

  async function handleDelete(id) {
    await deleteSession(id);
    const rest = sessions.filter((s) => s.session_id !== id);
    setSessions(rest);
    if (currentId === id) {
      setCurrentId(null);
      setMessages([]);
      historyRef.current = [];
      if (rest.length) selectSession(rest[0].session_id);
    }
  }

  async function handleFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const res = await uploadImage(file, currentId);
      setAttachment({
        kind: "photo",
        url: res.url,
        description: res.description,
      });
    } catch (err) {
      setError(err.message);
    }
    setUploading(false);
  }

  async function handleDoc(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const res = await uploadDocument(file, currentId);
      setAttachment({ kind: "doc", filename: res.filename });
    } catch (err) {
      setError(err.message);
    }
    setUploading(false);
  }

  function toggleMic() {
    if (listening) {
      recRef.current?.stop();
      setListening(false);
      return;
    }
    if (!SPEECH_SUPPORTED) {
      setError("Voice input isn't supported in this browser (try Chrome or Edge).");
      return;
    }
    const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new Rec();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.onresult = (ev) => {
      let t = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++)
        t += ev.results[i][0].transcript;
      setInput((prev) => (prev ? prev + " " : "") + t);
    };
    rec.onend = () => setListening(false);
    rec.onerror = (ev) => {
      setListening(false);
      setError(`Microphone error: ${ev.error}`);
    };
    recRef.current = rec;
    setListening(true);
    rec.start();
  }

  async function send() {
    const raw = input.trim();
    if ((!raw && !attachment) || streaming) return;

    let text = raw;
    if (attachment) {
      if (attachment.kind === "photo") {
        const desc = `[Attached photo: ${attachment.description}]`;
        text = raw ? `${raw}\n\n${desc}` : desc;
      } else {
        const ref = `[Attached document: ${attachment.filename}]`;
        text = raw ? `${raw}\n\n${ref}` : ref;
      }
    }

    setInput("");
    setError(null);
    setStreaming(true);
    searchedRef.current = 0;

    const localHistory = historyRef.current;
    const userMsg = {
      role: "user",
      content: raw || (attachment ? `📎 Sent ${attachment.kind === "photo" ? "a photo" : attachment.filename}` : ""),
      image: attachment?.kind === "photo" ? attachment.url : null,
    };
    const asstMsg = { role: "assistant", content: "", chips: [], searched: 0 };
    setMessages((prev) => [...prev, userMsg, asstMsg]);
    const sentAttachment = attachment?.kind === "photo" ? attachment : null;
    setAttachment(null);
    scrollBottom();

    let sessionId = currentId;
    let reply = "";
    const sentExpiry = expiresAt;
    setExpiresAt("");

    try {
      await streamChat(
        {
          sessionId,
          text,
          history: localHistory,
          attachment: sentAttachment,
          expiresAt: sentExpiry || undefined,
        },
        (evt) => {
          if (evt.type === "session" && evt.session_id) {
            sessionId = evt.session_id;
            if (!currentId) {
              setCurrentId(evt.session_id);
              setSessions((prev) => [
                { session_id: evt.session_id, title: raw.slice(0, 40) || "Attachment chat" },
                ...prev,
              ]);
            }
          } else if (evt.type === "search") {
            searchedRef.current = evt.count || 0;
          } else if (evt.type === "delta") {
            reply += evt.delta;
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                ...asstMsg,
                content: reply,
                searched: searchedRef.current,
              };
              return next;
            });
            scrollBottom();
          } else if (evt.type === "done") {
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                ...asstMsg,
                content: reply,
                chips: evt.retrieved || [],
                searched: searchedRef.current,
              };
              return next;
            });
          } else if (evt.type === "error") {
            setError(evt.message);
          }
        }
      );
    } catch (e) {
      setError(e.message);
    }

    if (sessionId) historyRef.current = [...localHistory, userMsg, { role: "assistant", content: reply }];
    setStreaming(false);
    if (sessionId) listSessions().then(setSessions);
  }

  async function saveInstructions(text) {
    try {
      await updateSettings(text);
      setInstructions(text);
      setShowSettings(false);
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="app">
      <Nav
        sessions={sessions}
        currentId={currentId}
        onSelect={selectSession}
        onNew={newChat}
        onDelete={handleDelete}
      />
      <main className="main">
        <div className="chat-header">
          <span>Chat</span>
          <span className="header-actions">
            <button className="header-btn" title="Custom instructions" onClick={() => setShowSettings(true)}>
              ⚙️
            </button>
            <span className="hint">
              {currentId ? "Memory-aware session" : "Start a conversation"}
            </span>
          </span>
        </div>

        <div className="messages">
          {messages.length === 0 && (
            <div className="empty">
              <h2>Memory-aware assistant</h2>
              <p>
                Facts, preferences, goals and events are stored and versioned
                automatically. Attach a photo or document, talk with the mic, or
                search the web.
              </p>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg-row ${m.role}`}>
              <div className={`avatar ${m.role}`}>
                {m.role === "user" ? "U" : "AI"}
              </div>
              <div className="bubble">
                {m.image && (
                  <img
                    src={m.image}
                    alt="attached"
                    className="msg-image"
                    onClick={() => window.open(m.image, "_blank")}
                  />
                )}
                {m.searched > 0 && (
                  <div className="chips">
                    <span className="chip chip-search">🔎 searched the web ({m.searched} sources)</span>
                  </div>
                )}
                {m.chips?.length > 0 && (
                  <div className="chips">
                    {m.chips.map((c, ci) => (
                      <span key={ci} className={`chip ${c.kind === "document" ? "chip-doc" : "chip-memory"}`}>
                        {c.kind === "document"
                          ? `📄 ${c.filename}`
                          : `🧠 ${c.subject}/${c.attribute}`}
                        {c.expires_at ? ` · ⏳ until ${fmtDate(c.expires_at)}` : ""}
                      </span>
                    ))}
                  </div>
                )}
                <div className="msg-text">
                  {m.role === "assistant" && m.content ? (
                    <Markdown text={m.content} onArtifact={(code, lang) => setArtifact({ code, language: lang })} />
                  ) : (
                    (m.content || (streaming && "…"))
                  )}
                </div>
                {m.role === "assistant" && m.content && (
                  <button className="speak-btn" title="Read aloud" onClick={() => speak(m.content)}>
                    🔊
                  </button>
                )}
              </div>
            </div>
          ))}
          {error && <div style={{ color: "var(--danger)", textAlign: "center", padding: 8 }}>⚠ {error}</div>}
          <div ref={bottomRef} />
        </div>

        <div className="composer">
          {attachment && (
            <div className="attachment">
              {attachment.kind === "photo" ? (
                <img src={attachment.url} alt="attachment" />
              ) : (
                <div className="attachment-icon">📄</div>
              )}
              <div className="attachment-meta">
                <strong>
                  {attachment.kind === "photo" ? "Photo attached" : attachment.filename}
                </strong>
                {attachment.kind === "photo" && <span>{attachment.description}</span>}
              </div>
              <button
                className="icon-btn"
                onClick={() => setAttachment(null)}
                title="Remove"
              >
                ✕
              </button>
            </div>
          )}
          {expiresAt && (
            <div className="expiry-chip-row">
              <button className="chip chip-expiry" onClick={() => setExpiresAt("")} title="Remove expiry">
                ⏳ remembers until {expiresAt} ✕
              </button>
            </div>
          )}
          <div className="composer-row">
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              style={{ display: "none" }}
              onChange={handleFile}
            />
            <input
              ref={docRef}
              type="file"
              accept=".pdf,.txt,.md,.csv,.json,.py,.js,.sql"
              style={{ display: "none" }}
              onChange={handleDoc}
            />
            <input
              ref={expiryRef}
              type="date"
              style={{ display: "none" }}
              onChange={(e) => {
                setExpiresAt(e.target.value);
                e.target.value = "";
              }}
            />
            <button
              className="icon-btn"
              onClick={() => fileRef.current?.click()}
              title="Attach photo"
              disabled={streaming}
            >
              📷
            </button>
            <button
              className="icon-btn"
              onClick={() => docRef.current?.click()}
              title="Attach document (PDF/TXT/MD/CSV/JSON)"
              disabled={streaming}
            >
              📄
            </button>
            <button
              className={`icon-btn ${expiresAt ? "expiry-on" : ""}`}
              onClick={() => expiryRef.current?.showPicker?.() || expiryRef.current?.click()}
              title="Make this memory expire on a date (calendar)"
              disabled={streaming}
            >
              📅
            </button>
            <button
              className={`icon-btn ${listening ? "mic-live" : ""}`}
              onClick={toggleMic}
              title={listening ? "Stop voice input" : "Voice input"}
              disabled={streaming}
            >
              {listening ? "⏹" : "🎤"}
            </button>
            <textarea
              rows={1}
              value={input}
              placeholder={
                uploading
                  ? "Analyzing…"
                  : "Ask anything… attach a file, or use the mic"
              }
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <button onClick={send} disabled={streaming || (!input.trim() && !attachment)}>
              {streaming ? "…" : "Send"}
            </button>
          </div>
        </div>
      </main>

      {showSettings && (
        <SettingsModal
          value={instructions}
          onClose={() => setShowSettings(false)}
          onSave={saveInstructions}
        />
      )}
      {artifact && <ArtifactPanel artifact={artifact} onClose={() => setArtifact(null)} />}
    </div>
  );
}
