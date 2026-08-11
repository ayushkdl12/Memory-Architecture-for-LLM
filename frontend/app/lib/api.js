// Client-side API helpers. All /api calls are proxied by Next.js rewrites to
// the FastAPI backend on :8000.

export async function api(path, options = {}) {
  const { json = true, ...rest } = options;
  const headers = json ? { "Content-Type": "application/json" } : {};
  const res = await fetch(`/api${path}`, { headers, ...rest });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export const listSessions = () => api("/sessions");
export const createSession = (title = "New chat") =>
  api("/sessions", { method: "POST", body: JSON.stringify({ title }) });
export const getSession = (id) => api(`/sessions/${id}`);
export const deleteSession = (id) =>
  api(`/sessions/${id}`, { method: "DELETE" });

export const getSummary = () => api("/memory/summary");
export const getAtoms = (filter = "active") =>
  api(`/memory/atoms?filter=${filter}`);
export const getFactVersions = () => api("/memory/fact-versions");
export const getRetrievalLogs = () => api("/memory/retrieval-logs?limit=50");
export const getRetentionLogs = () => api("/memory/retention-logs");
export const runSweep = (dryRun = false) =>
  api("/memory/retention/sweep", {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  });

// --- interactive memory management (dashboard) ------------------------------
export const createAtom = (atom) =>
  api("/memory/atoms", { method: "POST", body: JSON.stringify(atom) });
export const updateAtom = (id, patch) =>
  api(`/memory/atoms/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
export const deleteAtom = (id) =>
  api(`/memory/atoms/${id}`, { method: "DELETE" });
export const restoreAtom = (id) =>
  api(`/memory/atoms/${id}/restore`, { method: "POST" });

// --- photo / voice -----------------------------------------------------------
export const uploadImage = (file, sessionId = null) => {
  const fd = new FormData();
  fd.append("file", file);
  if (sessionId) fd.append("session_id", sessionId);
  return api("/media/upload", { method: "POST", body: fd, json: false });
};
export const listMedia = () => api("/media");

// --- documents (file upload & analysis) --------------------------------------
export const uploadDocument = (file, sessionId = null) => {
  const fd = new FormData();
  fd.append("file", file);
  if (sessionId) fd.append("session_id", sessionId);
  return api("/documents/upload", { method: "POST", body: fd, json: false });
};
export const listDocuments = () => api("/documents");
export const deleteDocument = (id) =>
  api(`/documents/${id}`, { method: "DELETE" });

// --- settings / custom instructions ------------------------------------------
export const getSettings = () => api("/settings");
export const updateSettings = (custom_instructions) =>
  api("/settings", {
    method: "PUT",
    body: JSON.stringify({ custom_instructions }),
  });

// Stream a chat completion. Calls onEvent for each SSE event.
export async function streamChat({ sessionId, text, history, attachment, expiresAt }, onEvent) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId || null,
      text,
      history: history || [],
      attachment: attachment || null,
      expires_at: expiresAt || null,
    }),
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch {}
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch {}
    }
  }
}
