import React, { useEffect, useMemo, useRef, useState } from "react";

// ---------------------------------------------------------------- data + urgency
// Urgency (PRODUCT.md): a wrong answer key silently marks correct students wrong, so confirmed
// answer-key defects come first, weighted by how many students reported them; then other
// defects that need a human; then platform/no-change cases (collapsed).
const TIER = (r) =>
  r.verdict === "defect" && r.repair === "answer_key" ? 100
  : r.verdict === "defect" && r.route === "faculty_review" ? 60
  : r.verdict === "defect" ? 50
  : r.route === "faculty_review" ? 30
  : 0;

const WHY = (top, n) => {
  const who = `${n} student${n > 1 ? "s" : ""} reported`;
  if (top.verdict === "defect" && top.repair === "answer_key") return `Answer key may be wrong · ${who}`;
  if (top.verdict === "defect" && top.route === "faculty_review") return `Defect needs your judgement · ${who}`;
  if (top.verdict === "defect") return `Safe fix ready to apply · ${who}`;
  if (top.route === "faculty_review") return `Checks could not finish · ${who}`;
  return `No content change · ${who}`;
};

const VERDICT_LABEL = {
  defect: "Defect", no_error: "No error", display_issue: "Display issue", app_issue: "App issue",
  language_mode: "Language", already_fixed: "Already fixed", not_actionable: "Not actionable",
};
const ROUTE_LABEL = { auto_apply: "Auto-apply", faculty_review: "Needs review", no_change: "No change" };

function useData() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    const get = (f) => fetch(`/data/${f}`).then((r) => { if (!r.ok) throw new Error(f); return r.json(); });
    Promise.all(["results.json", "questions.json", "reports.json", "taxonomy.json", "run_record.json"].map(get))
      .then(([results, questions, reports, taxonomy, record]) => setD({ results, questions, reports, taxonomy, record }))
      .catch((e) => setErr(String(e)));
  }, []);
  return [d, err];
}

// ---------------------------------------------------------------- audit (this browser only)
const AUDIT_KEY = "acadza-audit-v1";
const NAME_KEY = "acadza-reviewer";
const load = (k, fb) => { try { return JSON.parse(localStorage.getItem(k)) ?? fb; } catch { return fb; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage blocked */ } };

// ---------------------------------------------------------------- helpers
const body = (q) => (q ? q[q.questionType] || {} : {});
const fmt = (v) => (v == null ? "—" : Array.isArray(v) ? (v.length ? v.join(", ") : "[]") : String(v));
const fmtKey = (v) => (Array.isArray(v) ? JSON.stringify(v) : fmt(v));

function markEdit(html, find, replace, side) {
  const i = html.indexOf(find);
  if (i < 0) return html;
  const piece = side === "before" ? `<del class="d-del">${find || "&nbsp;"}</del>` : `<ins class="d-ins">${replace || "∅"}</ins>`;
  return html.slice(0, i) + piece + html.slice(i + find.length);
}

// ---------------------------------------------------------------- components
function Html({ html, className }) {
  return <div className={className} dangerouslySetInnerHTML={{ __html: html || "" }} />;
}

function Chip({ kind, children }) {
  return <span className={`chip chip-${kind}`}>{children}</span>;
}

function Diff({ row, q }) {
  const e = row.edit;
  if (!e) {
    return (
      <div className="diff empty">
        No content edit proposed{row.verdict === "defect" ? " — the fix needs a teacher to author it." : "."}
      </div>
    );
  }
  if (e.field === "answer") {
    return (
      <div className="diff key">
        <span className="lbl">Answer key</span>
        <span className="old">{fmtKey(e.find)}</span>
        <span className="arrow">→</span>
        <span className="new">{fmtKey(e.replace)}</span>
      </div>
    );
  }
  const stored = body(q)[e.field] || "";
  return (
    <div className="diff text">
      <div className="side">
        <div className="side-h before">Before · {e.field}</div>
        <Html className="qhtml" html={markEdit(stored, e.find, e.replace, "before")} />
      </div>
      <div className="side">
        <div className="side-h after">After · {e.field}</div>
        <Html className="qhtml" html={markEdit(stored, e.find, e.replace, "after")} />
      </div>
    </div>
  );
}

function Trust({ rec, q }) {
  if (!rec) return null;
  const failed = rec.checks.filter((c) => !c.passed);
  const sa = rec.solves.solve_a, sb = rec.solves.solve_b;
  const s = (x) => (!x ? "—" : x.error ? "failed" : fmt(x.answer));
  return (
    <div className="trust">
      <div className="trust-row">
        <span className={sa && !sa.error ? "ok" : "bad"}>{sa && !sa.error ? "✔" : "✘"} Solve A = {s(sa)}</span>
        <span className={sb && !sb.error ? "ok" : "bad"}>{sb && !sb.error ? "✔" : "✘"} Solve B = {s(sb)}</span>
        <span className="neutral">Solution ends at {fmt(rec.solution_final)}</span>
        <span className="neutral">Key = {fmtKey(body(q).answer)}</span>
      </div>
      <div className="trust-row small">
        {failed.length === 0
          ? <span className="ok">✔ {rec.checks.length} code checks passed</span>
          : failed.map((c, i) => <span key={i} className="bad">✘ {c.id}: {c.detail}</span>)}
      </div>
      {(rec.validator_errors.length > 0 || rec.guard_log.length > 0) && (
        <details className="guards">
          <summary>Why it came to you ({rec.guard_log.length + rec.validator_errors.length})</summary>
          <ul>{[...rec.validator_errors, ...rec.guard_log].map((l, i) => <li key={i}>{l}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

function NamePrompt({ onSet }) {
  const [v, setV] = useState("");
  return (
    <div className="overlay">
      <form className="modal" onSubmit={(e) => { e.preventDefault(); if (v.trim()) onSet(v.trim()); }}>
        <h2>Who is reviewing?</h2>
        <p>Your name goes on every audit entry. It stays in this browser.</p>
        <input autoFocus value={v} onChange={(e) => setV(e.target.value)} placeholder="e.g. Dr. Mehta" />
        <button className="btn primary" type="submit">Start reviewing</button>
      </form>
    </div>
  );
}

function EditBox({ row, onSave, onCancel }) {
  const isAnswer = row.edit?.field === "answer";
  const init = row.edit ? (isAnswer ? fmtKey(row.edit.replace) : row.edit.replace) : "";
  const [v, setV] = useState(init);
  return (
    <div className="editbox">
      <label>{row.edit ? `Edit the proposed ${row.edit.field} change` : "Describe the fix you want made"}</label>
      <textarea autoFocus rows={isAnswer ? 1 : 4} value={v} onChange={(e) => setV(e.target.value)} />
      <div className="row">
        <button className="btn primary" onClick={() => onSave(v)}>Save edit</button>
        <button className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- app
export default function App() {
  const [data, err] = useData();
  const [audit, setAudit] = useState(() => load(AUDIT_KEY, []));
  const [name, setName] = useState(() => load(NAME_KEY, ""));
  const [sel, setSel] = useState(null);
  const [editing, setEditing] = useState(false);
  const [showDone, setShowDone] = useState(false);
  const detailRef = useRef(null);

  const model = useMemo(() => {
    if (!data) return null;
    const qby = Object.fromEntries(data.questions.map((q) => [q._id, q]));
    const rby = Object.fromEntries(data.reports.map((r) => [r.reportId, r]));
    const groups = {};
    for (const row of data.results) (groups[row.questionId] ||= []).push(row);
    const list = Object.entries(groups).map(([qid, rows]) => {
      const top = [...rows].sort((a, b) => TIER(b) - TIER(a))[0];
      return { qid, rows, top, score: TIER(top) * 10 + rows.length, why: WHY(top, rows.length) };
    });
    list.sort((a, b) => b.score - a.score || a.qid.localeCompare(b.qid));
    const urgent = list.filter((g) => TIER(g.top) > 0);
    const calm = list.filter((g) => TIER(g.top) === 0);
    const order = [...urgent, ...calm].flatMap((g) => g.rows.map((r) => r.reportId));
    return { qby, rby, urgent, calm, order, rowBy: Object.fromEntries(data.results.map((r) => [r.reportId, r])) };
  }, [data]);

  const status = useMemo(() => {
    const s = {};
    for (const a of audit) s[a.reportId] = a.action;
    return s;
  }, [audit]);

  useEffect(() => { if (model && !sel) setSel(model.order[0]); }, [model, sel]);

  const act = (action, after) => {
    const row = model.rowBy[sel];
    const entry = {
      actor: name, at: new Date().toISOString(), reportId: row.reportId, questionId: row.questionId,
      action, verdict: row.verdict, repair: row.repair, route: row.route,
      before: row.edit ? row.edit.find : null,
      after: after !== undefined ? after : action === "approve" && row.edit ? row.edit.replace : null,
    };
    const next = [...audit, entry];
    setAudit(next); save(AUDIT_KEY, next);
    setEditing(false);
    const i = model.order.indexOf(sel);
    const nextPending = model.order.slice(i + 1).find((id) => !status[id]);
    if (nextPending) setSel(nextPending);
  };

  useEffect(() => {
    const onKey = (e) => {
      if (!model || editing || !name || ["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
      const i = model.order.indexOf(sel);
      const k = e.key.toLowerCase();
      if (k === "j") setSel(model.order[Math.min(i + 1, model.order.length - 1)]);
      else if (k === "k") setSel(model.order[Math.max(i - 1, 0)]);
      else if (k === "a") act("approve");
      else if (k === "r") act("reject");
      else if (k === "e") { e.preventDefault(); setEditing(true); }
      else return;
      detailRef.current?.scrollTo({ top: 0 });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (err) return <div className="center">Could not load data: {err}</div>;
  if (!model) return <div className="center">Loading…</div>;

  const row = model.rowBy[sel];
  const q = row && model.qby[row.questionId];
  const rec = row && data.record[row.reportId];
  const group = row && [...model.urgent, ...model.calm].find((g) => g.qid === row.questionId);
  const done = Object.keys(status).length;
  const mine = audit.filter((a) => a.reportId === sel);

  const exportAudit = () => {
    const blob = new Blob([JSON.stringify(audit, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "acadza-audit.json"; a.click();
  };

  const Group = ({ g }) => (
    <div className="group">
      <div className="g-why">{g.why}</div>
      {g.rows.map((r) => (
        <button key={r.reportId} className={`item ${r.reportId === sel ? "active" : ""} ${status[r.reportId] ? "done" : ""}`}
          onClick={() => { setSel(r.reportId); setEditing(false); }}>
          <span className="i-id">{r.reportId}</span>
          <span className="i-c">{model.rby[r.reportId]?.comment || <em>(empty comment)</em>}</span>
          <span className={`dot dot-${r.verdict === "defect" ? r.route : "calm"}`} />
          {status[r.reportId] && <span className={`i-st st-${status[r.reportId]}`}>{status[r.reportId]}</span>}
        </button>
      ))}
    </div>
  );

  return (
    <div className="app">
      {!name && <NamePrompt onSet={(n) => { setName(n); save(NAME_KEY, n); }} />}
      <header>
        <div className="brand">Report → Fix <span>review console</span></div>
        <div className="progress"><b>{done}</b> / {data.results.length} reviewed</div>
        <div className="keys"><kbd>J</kbd><kbd>K</kbd> move · <kbd>A</kbd> approve · <kbd>E</kbd> edit · <kbd>R</kbd> reject</div>
        <div className="who">{name && <>Reviewing as <b>{name}</b></>}</div>
        <button className="btn" onClick={exportAudit}>Export audit (JSON)</button>
      </header>

      <aside>
        <div className="sec-h">Needs attention · {model.urgent.length} questions</div>
        {model.urgent.map((g) => <Group key={g.qid} g={g} />)}
        <button className="sec-h toggle" onClick={() => setShowDone(!showDone)}>
          {showDone ? "▾" : "▸"} No content change · {model.calm.length} questions
        </button>
        {showDone && model.calm.map((g) => <Group key={g.qid} g={g} />)}
      </aside>

      <main ref={detailRef}>
        {row && (
          <>
            <section className="card head">
              <div className="chips">
                <Chip kind={row.verdict === "defect" ? "defect" : "calm"}>{VERDICT_LABEL[row.verdict] || row.verdict}</Chip>
                {row.repair && <Chip kind="repair">{data.taxonomy.repairs[row.repair]?.label || row.repair}</Chip>}
                <Chip kind={row.route}>{ROUTE_LABEL[row.route]}</Chip>
                <span className="conf" title="Engine confidence">{Math.round(row.confidence * 100)}% confident</span>
                <span className="rid">{row.reportId} · {q?.subject} › {q?.chapter} · {q?.questionType}</span>
              </div>
              <p className="evidence">{row.evidence}</p>
              <Trust rec={rec} q={q} />
            </section>

            <section className="card">
              <h3>Proposed change</h3>
              <Diff row={row} q={q} />
              {editing
                ? <EditBox row={row} onSave={(v) => act("edit", v)} onCancel={() => setEditing(false)} />
                : (
                  <div className="actions">
                    <button className="btn primary" onClick={() => act("approve")}>Approve <kbd>A</kbd></button>
                    <button className="btn" onClick={() => setEditing(true)}>Edit <kbd>E</kbd></button>
                    <button className="btn danger" onClick={() => act("reject")}>Reject <kbd>R</kbd></button>
                  </div>
                )}
              {mine.length > 0 && (
                <ul className="audit">
                  {mine.map((a, i) => (
                    <li key={i}><b>{a.action}</b> by {a.actor} · {new Date(a.at).toLocaleString()}
                      {a.after != null && <> · after: <code>{fmtKey(a.after)}</code></>}</li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card">
              <h3>Reply the student will see</h3>
              <div className="bubble">{row.student_reply}</div>
            </section>

            <section className="card">
              <h3>Question</h3>
              <Html className="qhtml" html={body(q).question} />
              <details>
                <summary>Stored solution · key {fmtKey(body(q).answer)}</summary>
                <Html className="qhtml" html={body(q).solution} />
              </details>
            </section>

            <section className="card">
              <h3>Reports on this question ({group?.rows.length})</h3>
              {group?.rows.map((r) => {
                const rep = model.rby[r.reportId];
                return (
                  <div key={r.reportId} className={`rep ${r.reportId === sel ? "me" : ""}`}>
                    <span className="i-id">{r.reportId}</span>
                    <span className="rep-c">“{rep?.comment || "(empty)"}”</span>
                    <span className="rep-m">{rep?.source} · {rep?.reportedAt?.slice(0, 10)}</span>
                  </div>
                );
              })}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
