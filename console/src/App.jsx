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

function Trust({ rec, q, hideKey }) {
  if (!rec) return null;
  const failed = rec.checks.filter((c) => !c.passed);
  const sa = rec.solves.solve_a, sb = rec.solves.solve_b;
  const okA = sa && !sa.error && sa.answer != null, okB = sb && !sb.error && sb.answer != null;
  const agree = okA && okB && same(sa.answer, sb.answer);
  const key = body(q).answer;
  const keyOff = agree && !same([].concat(sa.answer).map(String), [].concat(key).map(String));
  const Tile = ({ label, value, tone, note }) => (
    <div className={`tile tile-${tone}`}>
      <div className="tile-l">{label}</div>
      <div className="tile-v">{value}</div>
      {note && <div className="tile-n">{note}</div>}
    </div>
  );
  return (
    <div className="trust">
      <div className={`tiles ${hideKey ? "three" : ""}`}>
        <Tile label="Independent solve 1" value={okA ? fmt(sa.answer) : "—"} tone={okA ? "good" : "muted"} note={okA ? "did not see the key" : "not available"} />
        <Tile label="Independent solve 2" value={okB ? fmt(sb.answer) : "—"} tone={okB ? "good" : "muted"} note={okB ? "did not see the key" : "not available"} />
        <Tile label="Stored solution ends at" value={fmt(rec.solution_final)} tone="plain" />
        {!hideKey && <Tile label="Stored answer key" value={fmtKey(key)} tone={keyOff ? "bad" : "plain"} note={keyOff ? "disagrees with both solves" : agree ? "matches both solves" : null} />}
      </div>
      <div className="checks">
        {failed.length === 0
          ? <span className="ok">✔ {rec.checks.length} automatic checks on the question passed</span>
          : failed.map((c, i) => <span key={i} className="bad">✘ {c.detail}</span>)}
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
      <header>
        <div className="brand"><span className="logo">A</span>Acadza <span>Question Review</span></div>
        <div className="progress"><div className="bar"><i style={{ width: `${(100 * done) / data.results.length}%` }} /></div><b>{done}</b> of {data.results.length} reports reviewed</div>
        <div className="keys"><kbd>J</kbd><kbd>K</kbd> move · <kbd>A</kbd> approve · <kbd>E</kbd> edit · <kbd>R</kbd> reject</div>
        <div className="who">{name && <>Reviewing as <b>{name}</b></>}</div>
        <button className="btn" onClick={exportAudit}>Export audit (JSON)</button>
      </header>

      <aside>
        <div className="sec-h">Needs your decision <span>{model.urgent.length} questions · most urgent first</span></div>
        {model.urgent.map((g) => <Group key={g.qid} g={g} />)}
        <button className="sec-h toggle" onClick={() => setShowDone(!showDone)}>
          {showDone ? "▾" : "▸"} No content change <span>{model.calm.length} questions</span>
        </button>
        {showDone && model.calm.map((g) => <Group key={g.qid} g={g} />)}
      </aside>

      <main ref={detailRef}>
        {row && (
          <>
            <section className={`card hero hero-${row.verdict === "defect" ? "defect" : "calm"}`}>
              <div className="hero-top">
                <span className="rid">{row.reportId}</span>
                <span className="crumbs">{q?.subject} · {q?.chapter} · {q?.questionType === "scq" ? "Single correct" : q?.questionType === "mcq" ? "Multiple correct" : "Numerical"}</span>
                <Chip kind={row.route}>{NEXT[row.route]}</Chip>
              </div>
              <h1>{headline(row)}</h1>
              {row.edit && row.edit.field === "answer" && (
                <div className="keychange">
                  <div className="kc old"><small>Stored key · current</small><b>{fmtKey(row.edit.find)}</b><em>what students are marked against today</em></div>
                  <div className="kc-arrow">→</div>
                  <div className="kc new"><small>Proposed key</small><b>{fmtKey(row.edit.replace)}</b><em>what the evidence below supports</em></div>
                </div>
              )}
              {(() => { const ev = splitEvidence(row.evidence); return (
                <>
                  {!(row.edit && row.edit.field === "answer") && stripSolves(ev.main) && <p className="evidence">{stripSolves(ev.main)}</p>}
                  <Trust rec={rec} q={q} hideKey={!!(row.edit && row.edit.field === "answer")} />
                  <div className="notes">
                    <span className="conf">Engine confidence {Math.round(row.confidence * 100)}%</span>
                    {ev.why && <span>Nothing is applied automatically yet, so this waits for you</span>}
                    {ev.missing && <details><summary>Some automatic steps were unavailable for this question</summary><div>{ev.missing}</div></details>}
                  </div>
                </>
              ); })()}
            </section>

            {!(row.edit && row.edit.field === "answer") && (
              <section className="card">
                <h3>Proposed change</h3>
                <Diff row={row} q={q} />
              </section>
            )}

            <section className="card question">
              <h3>Question as students see it</h3>
              <Html className="qhtml" html={body(q).question} />
              <details>
                <summary>Stored solution · key {fmtKey(body(q).answer)}</summary>
                <Html className="qhtml" html={body(q).solution} />
              </details>
            </section>

            <section className="card">
              <h3>Reply the student will see</h3>
              <div className="bubble">{row.student_reply}</div>
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
            {mine.length > 0 && (
              <section className="card">
                <h3>Audit trail for this report</h3>
                <ul className="audit">
                  {mine.map((a, i) => (
                    <li key={i}><b>{a.action === "approve" ? "Approved" : a.action === "reject" ? "Rejected" : "Edited"}</b> by {a.actor} · {new Date(a.at).toLocaleString()}
                      {a.after != null && <> · change: <code>{fmtKey(a.before)}</code> → <code>{fmtKey(a.after)}</code></>}</li>
                  ))}
                </ul>
              </section>
            )}
            <div className="actionbar">
              {editing
                ? <EditBox row={row} onSave={(v) => act("edit", v)} onCancel={() => setEditing(false)} />
                : (
                  <>
                    <div className="ab-info">{status[sel] ? <>Already <b>{status[sel] === "approve" ? "approved" : status[sel] === "reject" ? "rejected" : "edited"}</b>. You can act again.</> : <><b>{group?.rows.length} student{group?.rows.length > 1 ? "s" : ""}</b> reported this question{row.edit ? ". Approving accepts the change shown above." : "."}</>}</div>
                    <button className="btn danger" onClick={() => act("reject")}>Reject <kbd>R</kbd></button>
                    <button className="btn" onClick={() => setEditing(true)}>Edit <kbd>E</kbd></button>
                    <button className="btn primary" onClick={() => act("approve")}>{row.edit ? "Approve change" : "Approve"} <kbd>A</kbd></button>
                  </>
                )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
