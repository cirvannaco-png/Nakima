import React, { useState } from "react";
import { Check, X, RotateCcw, ChevronDown, GitCommit, Bot, User, FileText } from "lucide-react";

// Diff-review prototype for Nakima — per-hunk review with model selection,
// scoped deliberately: this is NOT a code editor / IDE. It only handles
// reviewing, adjusting, and re-linking hunks that Nakima's orchestrator
// already proposed. Provenance is tagged the moment a decision is made
// here (see core/provenance.py), never inferred afterward.

const MODELS = [
  { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
  { id: "claude-opus-4-8", label: "Claude Opus 4.8" },
  { id: "gpt-4", label: "GPT-4" },
  { id: "deepseek", label: "DeepSeek" },
];

const initialHunks = [
  {
    id: "h1",
    file: "core/decision_router.py",
    issue: "#482",
    status: "pending", // pending | accepted | edited | rejected
    model: "claude-sonnet-4-6",
    before: `def route(signal):
    if signal.confidence < 0.5:
        return None
    return signal.action`,
    after: `def route(signal):
    if signal is None:
        raise ValueError("signal cannot be None")
    if signal.confidence < 0.5:
        return None
    return signal.action`,
  },
  {
    id: "h2",
    file: "security/nsil.py",
    issue: "#470",
    status: "pending",
    model: "claude-sonnet-4-6",
    before: `def scan_secrets(path):
    results = []
    for f in walk(path):
        results.append(check(f))
    return results`,
    after: `def scan_secrets(path):
    results = []
    for f in walk(path):
        if f.is_binary():
            continue
        results.append(check(f))
    return results`,
  },
  {
    id: "h3",
    file: "api/routes.py",
    issue: "#455",
    status: "human",
    model: null,
    before: `@app.get("/health")
def health():
    return {"status": "ok"}`,
    after: `@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}`,
  },
];

function DiffLine({ text, kind }) {
  const bg =
    kind === "add" ? "#0d2818" : kind === "del" ? "#2a1215" : "transparent";
  const color = kind === "add" ? "#7ee2a8" : kind === "del" ? "#ff9b9b" : "#c9d1d9";
  const marker = kind === "add" ? "+" : kind === "del" ? "-" : " ";
  return (
    <div style={{ display: "flex", background: bg, fontFamily: "ui-monospace, monospace", fontSize: 13 }}>
      <span style={{ width: 24, color: "#6e7681", userSelect: "none", flexShrink: 0 }}>{marker}</span>
      <span style={{ color, whiteSpace: "pre" }}>{text}</span>
    </div>
  );
}

function simpleDiff(before, after) {
  const b = before.split("\n");
  const a = after.split("\n");
  const lines = [];
  let i = 0, j = 0;
  while (i < b.length || j < a.length) {
    if (i < b.length && j < a.length && b[i] === a[j]) {
      lines.push({ text: b[i], kind: "ctx" });
      i++; j++;
    } else if (j < a.length && !b.includes(a[j])) {
      lines.push({ text: a[j], kind: "add" });
      j++;
    } else if (i < b.length) {
      lines.push({ text: b[i], kind: "del" });
      i++;
    } else {
      j++;
    }
  }
  return lines;
}

const statusStyles = {
  pending: { label: "Pending review", color: "#e3b341", bg: "#3a2f10" },
  accepted: { label: "Accepted verbatim", color: "#3fb950", bg: "#0d2818" },
  edited: { label: "Edited by human", color: "#58a6ff", bg: "#0d2740" },
  rejected: { label: "Rejected", color: "#f85149", bg: "#3a1215" },
  human: { label: "Human-written", color: "#a371f7", bg: "#251a3a" },
};

function HunkCard({ hunk, onAction, onModelChange }) {
  const [showModelPicker, setShowModelPicker] = useState(false);
  const diffLines = simpleDiff(hunk.before, hunk.after);
  const st = statusStyles[hunk.status];
  const isAI = hunk.status !== "human";

  return (
    <div style={{ border: "1px solid #30363d", borderRadius: 8, marginBottom: 16, overflow: "hidden", background: "#0d1117" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", background: "#161b22", borderBottom: "1px solid #30363d" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <FileText size={14} color="#8b949e" />
          <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 13, color: "#c9d1d9" }}>{hunk.file}</span>
          <span style={{ fontSize: 12, color: "#6e7681" }}>· issue {hunk.issue}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 11, padding: "3px 8px", borderRadius: 12, color: st.color, background: st.bg, display: "flex", alignItems: "center", gap: 4 }}>
            {isAI ? <Bot size={11} /> : <User size={11} />}
            {st.label}
          </span>
          {isAI && (
            <div style={{ position: "relative" }}>
              <button
                onClick={() => setShowModelPicker(!showModelPicker)}
                style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#8b949e", background: "#21262d", border: "1px solid #30363d", borderRadius: 6, padding: "4px 8px", cursor: "pointer" }}
              >
                {MODELS.find((m) => m.id === hunk.model)?.label || hunk.model}
                <ChevronDown size={12} />
              </button>
              {showModelPicker && (
                <div style={{ position: "absolute", right: 0, top: "110%", background: "#161b22", border: "1px solid #30363d", borderRadius: 6, zIndex: 10, minWidth: 180 }}>
                  {MODELS.map((m) => (
                    <div
                      key={m.id}
                      onClick={() => { onModelChange(hunk.id, m.id); setShowModelPicker(false); }}
                      style={{ padding: "8px 10px", fontSize: 12, color: "#c9d1d9", cursor: "pointer", background: m.id === hunk.model ? "#1f6feb22" : "transparent" }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "#1f2937")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = m.id === hunk.model ? "#1f6feb22" : "transparent")}
                    >
                      {m.label}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div style={{ padding: "8px 0" }}>
        {diffLines.map((l, idx) => (
          <DiffLine key={idx} text={l.text} kind={l.kind} />
        ))}
      </div>

      {isAI && hunk.status === "pending" && (
        <div style={{ display: "flex", gap: 8, padding: "10px 14px", borderTop: "1px solid #30363d", background: "#0d1117" }}>
          <button
            onClick={() => onAction(hunk.id, "accepted")}
            style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#3fb950", background: "#0d2818", border: "1px solid #23572f", borderRadius: 6, padding: "6px 12px", cursor: "pointer" }}
          >
            <Check size={13} /> Accept
          </button>
          <button
            onClick={() => onAction(hunk.id, "edited")}
            style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#58a6ff", background: "#0d2740", border: "1px solid #1f4e8a", borderRadius: 6, padding: "6px 12px", cursor: "pointer" }}
          >
            <RotateCcw size={13} /> Edit & accept
          </button>
          <button
            onClick={() => onAction(hunk.id, "rejected")}
            style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#f85149", background: "#3a1215", border: "1px solid #6e2329", borderRadius: 6, padding: "6px 12px", cursor: "pointer" }}
          >
            <X size={13} /> Reject, regenerate
          </button>
        </div>
      )}
    </div>
  );
}

// Set to your real API base once deployed, e.g. "/api" behind the same
// origin, or a full URL if the frontend and API are on separate hosts.
const API_BASE = null; // e.g. "/api" — null keeps this in local-demo mode

export default function DiffReviewPrototype() {
  const [hunks, setHunks] = useState(initialHunks);
  const [currentUser] = useState("kelson"); // replace with real auth/session user

  const handleAction = async (id, status) => {
    setHunks((prev) => prev.map((h) => (h.id === id ? { ...h, status } : h)));

    if (!API_BASE) return; // demo mode — local state only, matches api/diff_review_routes.py contract

    try {
      await fetch(`${API_BASE}/hunks/${id}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: status, human_actor: currentUser }),
      });
      // POST /hunks/{record_id}/action — see api/diff_review_routes.py
    } catch (err) {
      console.error("Failed to record review decision:", err);
    }
  };

  const handleModelChange = async (id, model) => {
    setHunks((prev) => prev.map((h) => (h.id === id ? { ...h, model, status: "pending" } : h)));

    if (!API_BASE) return; // demo mode

    try {
      const res = await fetch(`${API_BASE}/hunks/${id}/model`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: model, human_actor: currentUser }),
      });
      // POST /hunks/{record_id}/model — regenerates just this hunk,
      // does not re-run the Planner step. Response includes new_diff.
      const data = await res.json();
      if (data.new_diff) {
        setHunks((prev) => prev.map((h) => (h.id === id ? { ...h, after: data.new_diff } : h)));
      }
    } catch (err) {
      console.error("Failed to swap model:", err);
    }
  };

  const pendingCount = hunks.filter((h) => h.status === "pending").length;

  return (
    <div style={{ minHeight: "100vh", background: "#010409", padding: "32px 24px", fontFamily: "ui-sans-serif, system-ui" }}>
      <div style={{ maxWidth: 780, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <GitCommit size={20} color="#58a6ff" />
          <h1 style={{ fontSize: 18, color: "#e6edf3", margin: 0, fontWeight: 600 }}>Diff Review — Issue #482, #470, #455</h1>
        </div>
        <p style={{ color: "#8b949e", fontSize: 13, marginTop: 4, marginBottom: 24 }}>
          {pendingCount} hunk{pendingCount !== 1 ? "s" : ""} pending review · scoped to reviewing and adjusting proposed diffs, not free-form editing
        </p>

        {hunks.map((hunk) => (
          <HunkCard key={hunk.id} hunk={hunk} onAction={handleAction} onModelChange={handleModelChange} />
        ))}

        <div style={{ marginTop: 20, padding: 14, borderRadius: 8, background: "#161b22", border: "1px solid #30363d" }}>
          <p style={{ color: "#8b949e", fontSize: 12, margin: 0, lineHeight: 1.6 }}>
            Every accept / edit / reject / re-model action here writes a provenance
            record immediately — agent, model, issue, human actor, and whether AI
            output was accepted verbatim. That's the entire input to the
            contribution report. Nothing is inferred after the fact.
          </p>
        </div>
      </div>
    </div>
  );
}
