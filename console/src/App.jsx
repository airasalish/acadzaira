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

const REPAIR_TITLE = {
  answer_key: "Answer key looks wrong", option_repair: "An option is missing or blank",
  identical_options: "Two options are identical", diagram: "Figure is missing",
  solution_missing: "Solution is missing or unusable", solution_fix: "Solution has a wrong step",
  stem_data: "A value is missing or wrong in the question", spelling: "Spelling mistake",
  notation: "Symbol or notation lost", markup_leak: "Raw code is showing as text",
  exam_reference: "Exam tag left in the question", noise: "Stray text in the question",
  answer_form: "Answer form not stated", type_mismatch: "Stored as the wrong question type",
  unsound: "No valid answer as written", wrong_question: "Question and solution do not match",
  wrong_chapter: "Filed under the wrong chapter", syllabus: "Out of syllabus",
};
const VERDICT_TITLE = {
  no_error: "No error found. The stored answer holds", display_issue: "Display problem. The content is fine",
  app_issue: "App problem, not this question", language_mode: "Language request",
  already_fixed: "Already fixed in the live record", not_actionable: "Nothing actionable found",
};
const headline = (row) => (row.verdict === "defect" ? REPAIR_TITLE[row.repair] || row.repair : VERDICT_TITLE[row.verdict] || row.verdict);
const NEXT = { faculty_review: "Needs your decision", auto_apply: "Safe fix, ready to apply", no_change: "No content change" };
const SHORT = { answer_key: "Answer key", option_repair: "Option", identical_options: "Options", diagram: "Figure",
  solution_missing: "Solution", solution_fix: "Solution", stem_data: "Missing data", spelling: "Spelling", notation: "Notation",
  markup_leak: "Markup", exam_reference: "Exam tag", noise: "Stray text", type_mismatch: "Type" };
const issueTag = (r) => (r.verdict === "defect" ? SHORT[r.repair] || "Defect" : VERDICT_LABEL[r.verdict] || r.verdict);
// Display only: split the engine's evidence into the finding and the routing / availability notes.
const splitEvidence = (text) => {
  let main = text || "", why = "", missing = "";
  let i = main.indexOf(" Sent to faculty: ");
  if (i >= 0) { why = main.slice(i + 18).replace(/\.$/, ""); main = main.slice(0, i); }
  i = main.indexOf(" Some checks failed to run (");
  if (i >= 0) { missing = main.slice(i + 28).replace(/\)\.?$/, ""); main = main.slice(0, i); }
  return { main: main.trim(), why, missing };
};
const stripSolves = (t) => t.replace(/\s*Blind solve A = [^.]*stored key = [^.]*\./, "").trim();
const EMPH = /(looks wrong|missing or blank|identical|is missing|missing or unusable|wrong step|missing or wrong|Spelling mistake|No error found|content is fine|not this question|Already fixed|Nothing actionable)/;
const emph = (t) => { const m = (t || "").match(EMPH); if (!m) return t; const i = m.index; return <>{t.slice(0, i)}<span className="em">{m[0]}</span>{t.slice(i + m[0].length)}</>; };
const plain = (h) => String(h ?? "").replace(/<[^>]*>/g, " ").replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

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

function Trust({ rec, q, n, comment }) {
  if (!rec) return null;
  const failed = rec.checks.filter((c) => !c.passed);
  const sa = rec.solves.solve_a, sb = rec.solves.solve_b;
  const okA = sa && !sa.error && sa.answer != null, okB = sb && !sb.error && sb.answer != null;
  const agree = okA && okB && same(sa.answer, sb.answer);
  const key = body(q).answer;
  const norm = (v) => [].concat(v).map(String);
  const keyOff = agree && !same(norm(sa.answer), norm(key));
  const solOk = agree && rec.solution_final != null && same(norm(rec.solution_final), norm(sa.answer));
  const steps = [
    { st: "info", t: `${n} student report${n > 1 ? "s" : ""}`, note: comment ? `“${comment}”` : "No comment text" },
    failed.length === 0
      ? { st: "ok", t: "Automatic checks on the question", v: `${rec.checks.length} passed` }
      : { st: "warn", t: "Automatic checks on the question", v: `${failed.length} flagged`, note: failed.map((c) => c.detail).join(" · ") },
    okA ? { st: "ok", t: "Independent solve 1", v: fmt(sa.answer), note: "Solved without seeing the key or the comments" }
        : { st: "off", t: "Independent solve 1", v: "—", note: "Not available for this question" },
    okB ? { st: "ok", t: "Independent solve 2", v: fmt(sb.answer), note: "Solved without seeing the key or the comments" }
        : { st: "off", t: "Independent solve 2", v: "—", note: "Not available for this question" },
    { st: solOk ? "ok" : "info", t: "Stored solution ends at", v: fmt(rec.solution_final), note: solOk ? "Agrees with both solves" : null },
    { st: keyOff ? "bad" : agree ? "ok" : "info", t: "Stored answer key", v: fmtKey(key), note: keyOff ? "Disagrees with both independent solves" : agree ? "Matches both solves" : null },
  ];
  return (
    <div className="trust">
      <ol className="tl">
        {steps.map((x, i) => (
          <li key={i} className={`tl-${x.st}`}>
            <span className="tl-dot" />
            <div className="tl-main"><span className="tl-t">{x.t}</span>{x.note && <span className="tl-n">{x.note}</span>}</div>
            {x.v != null && <span className="tl-v">{x.v}</span>}
          </li>
        ))}
      </ol>
      <div className={`agree ${agree ? "yes" : "no"}`}>
        {agree ? <>Two independent solves agree on <b>{fmt(sa.answer)}</b>{solOk ? <>, and so does the stored solution</> : null}</>
          : okA && okB ? <>The two independent solves disagree, so this needs a careful look</>
          : okA || okB ? <>Only one independent solve was available for this question</>
          : <>No independent solve was available for this question</>}
      </div>
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
  const [toast, setToast] = useState(null);
  const [view, setView] = useState("queue");
  const [filt, setFilt] = useState("todo");
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 1800); return () => clearTimeout(t); }, [toast]);
  const [theme, setTheme] = useState(() => load("acadza-theme", null));
  useEffect(() => {
    document.documentElement.dataset.theme = theme || "light";
  }, [theme]);
  const isDark = theme === "dark";
  const toggleTheme = () => { const t = isDark ? "light" : "dark"; setTheme(t); save("acadza-theme", t); };
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
    setToast({ id: Date.now(), action, reportId: row.reportId });
    setEditing(false);
    const i = model.order.indexOf(sel);
    const nextPending = model.order.slice(i + 1).find((id) => !status[id]);
    if (nextPending) setSel(nextPending);
  };

  useEffect(() => {
    const onKey = (e) => {
      if (!model || editing || !name || view !== "queue" || ["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
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

  const download = (obj, file) => {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = file; a.click();
  };
  // Latest decision per report; approved or edited rows that carry an edit become a change set.
  const changeSet = () => {
    const last = {};
    for (const a of audit) last[a.reportId] = a;
    const out = [];
    for (const a of Object.values(last)) {
      const r = model.rowBy[a.reportId];
      if (!r || !r.edit || a.action === "reject") continue;
      let replace = r.edit.replace;
      if (a.action === "edit") {
        if (Array.isArray(r.edit.replace)) { try { replace = JSON.parse(a.after); } catch { continue; } }
        else replace = a.after;
      }
      out.push({ questionId: r.questionId, reportId: r.reportId, repair: r.repair, field: r.edit.field, find: r.edit.find, replace, decidedBy: a.actor, decidedAt: a.at, action: a.action });
    }
    return out;
  };
  const lists = model ? {
    todo: model.urgent,
    key: model.urgent.filter((g) => g.top.repair === "answer_key"),
    calm: model.calm,
    all: [...model.urgent, ...model.calm],
  } : { todo: [], key: [], calm: [], all: [] };
  const FILTERS = [["todo", "To review"], ["key", "Answer key"], ["calm", "No change"], ["all", "All"]];
  const visible = lists[filt] || [];
  if (model && sel && filt !== "all" && !visible.some((g) => g.rows.some((r) => r.reportId === sel))) setTimeout(() => setFilt("all"), 0);
  const pickFilt = (k) => {
    setFilt(k);
    const l = lists[k] || [];
    if (l.length && !l.some((g) => g.rows.some((r) => r.reportId === sel))) { setSel(l[0].rows[0].reportId); setEditing(false); }
  };
  const pos = model ? model.order.indexOf(sel) + 1 : 0;
  const step = (d) => { const i = model.order.indexOf(sel); const n = model.order[Math.min(Math.max(i + d, 0), model.order.length - 1)]; setSel(n); setEditing(false); detailRef.current?.scrollTo({ top: 0 }); };

  const Group = ({ g }) => {
    const gq = model.qby[g.qid];
    const pending = g.rows.filter((r) => !status[r.reportId]).length;
    const tone = g.top.verdict === "defect" ? (g.top.repair === "answer_key" ? "high" : "mid") : g.top.route === "faculty_review" ? "mid" : "low";
    return (
      <div className={`group tone-${tone} ${g.rows.some((r) => r.reportId === sel) ? "open" : ""}`}>
        <div className="g-head">
          <span className="g-tag">{issueTag(g.top)}</span>
          <span className="g-meta" title={`${gq?.subject} · ${gq?.chapter}`}>{gq?.subject} · {gq?.chapter}</span>
          <span className="g-count" title="Reports on this question">{g.rows.length} report{g.rows.length > 1 ? "s" : ""}</span>
        </div>
        {g.rows.map((r) => (
          <button key={r.reportId} className={`item ${r.reportId === sel ? "active" : ""} ${status[r.reportId] ? "done" : ""}`}
            onClick={() => { setSel(r.reportId); setEditing(false); }}>
            <span className="i-id">{r.reportId}</span>
            <span className="i-c">{model.rby[r.reportId]?.comment || <em>(empty comment)</em>}</span>
            {status[r.reportId] && <span className={`i-st st-${status[r.reportId]}`}>{status[r.reportId] === "approve" ? "Approved" : status[r.reportId] === "reject" ? "Rejected" : "Edited"}</span>}
          </button>
        ))}
        {pending === 0 && <div className="g-done">All reviewed</div>}
      </div>
    );
  };

  return (
    <div className="app">
      {!name && <NamePrompt onSet={(n) => { setName(n); save(NAME_KEY, n); }} />}
      {toast && <div key={toast.id} className={`toast toast-${toast.action}`} role="status">{toast.action === "approve" ? "Approved" : toast.action === "reject" ? "Rejected" : "Edit saved"} · {toast.reportId} · logged to audit</div>}
      <header>
        <div className="brand"><span className="logo">A</span>Acadza<span>Question Review</span></div>
        <nav className="tabs">
          <button className={view === "queue" ? "on" : ""} onClick={() => setView("queue")}>Review queue <i>{data.results.length - done}</i></button>
          <button className={view === "audit" ? "on" : ""} onClick={() => setView("audit")}>Audit log <i>{audit.length}</i></button>
        </nav>
        <div className="progress"><div className="bar"><i style={{ width: `${(100 * done) / data.results.length}%` }} /></div><b>{done}</b> of {data.results.length} reports reviewed</div>
        <div className="who">{name && <><span className="avatar">{name.slice(0, 1).toUpperCase()}</span>{name}</>}</div>
        <button className="btn ghost" onClick={toggleTheme} title="Switch between light and dark">{isDark ? "☀ Light" : "☾ Dark"}</button>
        <button className="btn" onClick={exportAudit}>Export audit (JSON)</button>
      </header>

      {view === "audit" ? (
        <div className="auditview">
          <div className="av-head">
            <div>
              <h2>Audit log</h2>
              <p>Every Approve, Edit and Reject made in this browser. Decisions are stored locally; nothing is written to the question bank from this console.</p>
            </div>
            <div className="av-actions">
              <button className="btn" onClick={() => download(changeSet(), "acadza-approved-changes.json")} disabled={changeSet().length === 0}>Export approved changes ({changeSet().length})</button>
              <button className="btn primary" onClick={exportAudit} disabled={audit.length === 0}>Export audit (JSON)</button>
            </div>
          </div>
          {audit.length === 0 ? (
            <div className="empty">No decisions yet. Open the review queue and approve, edit or reject a report.</div>
          ) : (
            <div className="tablewrap">
              <table className="table">
                <thead><tr><th>When</th><th>Reviewer</th><th>Report</th><th>Decision</th><th>Finding</th><th>Change</th></tr></thead>
                <tbody>
                  {[...audit].reverse().map((a, i) => (
                    <tr key={i} onClick={() => { setSel(a.reportId); setView("queue"); }}>
                      <td className="num">{new Date(a.at).toLocaleString()}</td>
                      <td>{a.actor}</td>
                      <td><span className="rid">{a.reportId}</span></td>
                      <td><span className={`pill pill-${a.action}`}>{a.action === "approve" ? "Approved" : a.action === "reject" ? "Rejected" : "Edited"}</span></td>
                      <td>{VERDICT_LABEL[a.verdict] || a.verdict}{a.repair ? ` · ${SHORT[a.repair] || a.repair}` : ""}</td>
                      <td>{a.before != null || a.after != null ? <><code>{plain(fmtKey(a.before)) || "—"}</code> → <code>{plain(fmtKey(a.after)) || "—"}</code></> : <span className="dim">No content change</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : (
      <>
      <aside>
        <div className="p-head">
          <div className="p-title">Queue<span>{visible.length} question{visible.length === 1 ? "" : "s"} · most urgent first</span></div>
          <div className="seg" role="tablist">
            {FILTERS.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={filt === k} className={filt === k ? "on" : ""} onClick={() => pickFilt(k)}>{label}<i>{lists[k].length}</i></button>
            ))}
          </div>
        </div>
        <div className="p-body">
          {visible.map((g) => <Group key={g.qid} g={g} />)}
          {visible.length === 0 && <div className="empty">Nothing in this view.</div>}
        </div>
        <div className="hint"><span><kbd>J</kbd><kbd>K</kbd> move</span><span><kbd>A</kbd> approve</span><span><kbd>E</kbd> edit</span><span><kbd>R</kbd> reject</span></div>
      </aside>

      <main>
        {row && (() => {
          const ev = splitEvidence(row.evidence);
          const isKey = !!(row.edit && row.edit.field === "answer");
          const n = group?.rows.length || 1;
          const qtype = q?.questionType === "scq" ? "Single correct" : q?.questionType === "mcq" ? "Multiple correct" : "Numerical";
          const lede = isKey
            ? <>Students are currently marked against <b>{fmtKey(row.edit.find)}</b>. The evidence points to <b>{fmtKey(row.edit.replace)}</b>.</>
            : stripSolves(ev.main);
          const impact = row.verdict !== "defect" ? ["calm", "No content change"]
            : row.repair === "answer_key" ? ["high", "Affects marking"]
            : ["option_repair", "identical_options", "unsound", "stem_data", "type_mismatch", "diagram", "wrong_question"].includes(row.repair) ? ["mid", "Affects answering"]
            : ["low", "Wording or presentation"];
          const conf = Math.round(row.confidence * 100);
          return (
          <>
          <section className="review">
            <div className="toolbar">
              <span className="rid">{row.reportId}</span>
              <span className="crumbs">{q?.subject} <em>/</em> {q?.chapter} <em>/</em> {qtype}</span>
              <span className="pos">{pos} of {model.order.length}</span>
              <button className="btn icon" onClick={() => step(-1)} title="Previous report (K)" aria-label="Previous report">↑</button>
              <button className="btn icon" onClick={() => step(1)} title="Next report (J)" aria-label="Next report">↓</button>
            </div>

            <div className="scroll" ref={detailRef} key={row.reportId}>
              <div className="finding">
                <div className="f-kicker"><span className={`tag ${row.verdict === "defect" ? "tag-attn" : "tag-calm"}`}>{issueTag(row)}</span><span>Finding</span></div>
                <h1>{headline(row)}</h1>
                {lede && <p className="lede">{lede}</p>}
                <div className="signals">
                  <div className={`sig sig-${row.route}`}><small>Status</small><b>{NEXT[row.route]}</b></div>
                  <div className={`sig sig-impact-${impact[0]}`}><small>Impact</small><b>{impact[1]}</b></div>
                  <div className="sig sig-conf" title="The engine's own estimate from its rules. It is not measured accuracy."><small>Engine confidence</small><b>{conf}%<span className="meter"><i style={{ width: `${conf}%` }} /></span></b></div>
                  <div className="sig"><small>Reported by</small><b>{n} student{n > 1 ? "s" : ""}</b></div>
                </div>
              </div>

              <section className="sect">
                <header className="sect-h"><h3>Proposed correction</h3><span>{row.edit ? `Field: ${row.edit.field}` : "No edit"}</span></header>
                <div className="sect-b">
                  {isKey ? (<>
                    <div className="keychange">
                      <div className="kc old"><small>Before · stored key</small><b>{fmtKey(row.edit.find)}</b><em>marked against today</em></div>
                      <div className="kc-arrow" aria-hidden="true">→</div>
                      <div className="kc new"><small>After · proposed key</small><b>{fmtKey(row.edit.replace)}</b><em>supported by the evidence</em></div>
                    </div>
                    <p className="summary"><b>Change:</b> answer key <span className="s-old">{fmtKey(row.edit.find)}</span> → <span className="s-new">{fmtKey(row.edit.replace)}</span>. The question text, options and solution stay as they are.</p>
                  </>) : (<>
                    {row.edit && <p className="summary"><b>Change:</b> in the {row.edit.field}, <span className="s-old">{plain(row.edit.find) || "(markup only)"}</span> → <span className="s-new">{plain(row.edit.replace) || "(removed)"}</span>. Nothing else is touched.</p>}
                    <Diff row={row} q={q} />
                  </>)}
                </div>
              </section>

              <section className="sect">
                <header className="sect-h"><h3>Evidence</h3><span>What was checked, in order</span></header>
                <div className="sect-b"><Trust rec={rec} q={q} n={n} comment={model.rby[row.reportId]?.comment} /></div>
              </section>

              <section className="sect">
                <header className="sect-h"><h3>Question as students see it</h3><span>{qtype} · stored key {fmtKey(body(q).answer)}</span></header>
                <div className="sect-b question">
                  <Html className="qhtml" html={body(q).question} />
                  <details>
                    <summary>Stored solution</summary>
                    <Html className="qhtml" html={body(q).solution} />
                  </details>
                </div>
              </section>
            </div>

            <div className="actionbar">
              {editing
                ? <EditBox row={row} onSave={(v) => act("edit", v)} onCancel={() => setEditing(false)} />
                : (
                  <>
                    <div className="ab-info">{status[sel] ? <>Already <b>{status[sel] === "approve" ? "approved" : status[sel] === "reject" ? "rejected" : "edited"}</b>. You can act again.</> : isKey ? <>Approving records the key change <b>{fmtKey(row.edit.find)}</b> → <b>{fmtKey(row.edit.replace)}</b> in the audit log.</> : row.edit ? <>Approving records the change shown above in the audit log.</> : <>No content change is proposed for this report.</>}</div>
                    <button className="btn" onClick={() => act("reject")}>Reject <kbd>R</kbd></button>
                    <button className="btn" onClick={() => setEditing(true)}>Edit <kbd>E</kbd></button>
                    <button className="btn primary" onClick={() => act("approve")}>{row.edit ? "Approve change" : "Approve"} <kbd>A</kbd></button>
                  </>
                )}
            </div>
          </section>

          <section className="context">
            <div className="p-head"><div className="p-title">Context</div></div>
            <div className="p-body">
              <section className="panel">
                <h3>Details</h3>
                <dl className="props">
                  <dt>Verdict</dt><dd>{VERDICT_LABEL[row.verdict] || row.verdict}</dd>
                  <dt>Repair type</dt><dd>{row.repair ? (SHORT[row.repair] || row.repair) : "None"}</dd>
                  <dt>Route</dt><dd><Chip kind={row.route}>{NEXT[row.route]}</Chip></dd>
                  <dt>Subject</dt><dd>{q?.subject}</dd>
                  <dt>Chapter</dt><dd>{q?.chapter}</dd>
                  <dt>Type</dt><dd>{qtype}</dd>
                  <dt>Question ID</dt><dd><code>{row.questionId.slice(0, 8)}…</code></dd>
                </dl>
                <p className="fine">Engine confidence is the engine's own estimate, not measured accuracy.</p>
                {ev.why && <p className="fine">Nothing is applied automatically yet, so every change waits for a teacher.</p>}
                {ev.missing && <details className="fine"><summary>Some automatic steps were unavailable</summary><div>{ev.missing}</div></details>}
              </section>

              <section className="panel">
                <h3>Reply the student will see</h3>
                <div className="bubble">{row.student_reply}</div>
              </section>

              <section className="panel">
                <h3>Reports on this question <i>{n}</i></h3>
                {group?.rows.map((r) => {
                  const rep = model.rby[r.reportId];
                  return (
                    <button key={r.reportId} className={`rep ${r.reportId === sel ? "me" : ""}`} onClick={() => { setSel(r.reportId); setEditing(false); }}>
                      <span className="i-id">{r.reportId}</span>
                      <span className="rep-c">“{rep?.comment || "(empty)"}”</span>
                      <span className="rep-m"><i>{rep?.source}</i>{rep?.reportedAt?.slice(0, 10)}</span>
                    </button>
                  );
                })}
              </section>

              <section className="panel">
                <h3>Audit trail <i>{mine.length}</i></h3>
                {mine.length === 0 ? <p className="fine">No decision recorded for this report yet.</p> : (
                  <ul className="audit">
                    {mine.map((a, i) => (
                      <li key={i}><b>{a.action === "approve" ? "Approved" : a.action === "reject" ? "Rejected" : "Edited"}</b> by {a.actor}<span>{new Date(a.at).toLocaleString()}</span>
                        {a.after != null && <span><code>{plain(fmtKey(a.before)) || "—"}</code> → <code>{plain(fmtKey(a.after))}</code></span>}</li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </section>
          </>
          );
        })()}
      </main>
      </>
      )}
    </div>
  );
}
