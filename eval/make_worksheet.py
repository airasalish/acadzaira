"""Build eval/worksheet.html: a Phase 0 reading + hand-labelling aid.

Shows every reported question rendered (native MathML), its answer, solution,
raw HTML, errorHistory, and the reports on it, with a blank label form per report.
Questions nobody reported are listed after, for the bonus "unreported defects" pass.

It makes NO judgement: no verdicts are suggested, nothing is pre-filled.
Labels are typed by the user and exported to eval/labels.json from the page.

Run:  python eval/make_worksheet.py   (then open eval/worksheet.html)
"""
import html
import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = Path(__file__).resolve().parent / "worksheet.html"

questions = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
reports = json.loads((DATA / "reports.json").read_text(encoding="utf-8"))
taxonomy = json.loads((DATA / "taxonomy.json").read_text(encoding="utf-8"))

qby = {q["_id"]: q for q in questions}

# group reports by question, questions ordered by their earliest report
groups: "OrderedDict[str, list]" = OrderedDict()
for r in sorted(reports, key=lambda r: (r["reportedAt"], r["reportId"])):
    groups.setdefault(r["questionId"], []).append(r)

missing = [qid for qid in groups if qid not in qby]
unreported = [q for q in questions if q["_id"] not in groups]


def body(q):
    return q.get(q["questionType"]) or {}


def esc(s):
    return html.escape("" if s is None else str(s))


def q_block(q, idx, reps):
    b = body(q)
    ans = b.get("answer")
    eh = q.get("errorHistory") or []
    imgs = (b.get("quesImages") or []) + (b.get("solutionImages") or [])
    meta = (
        f"<b>{esc(q['questionType'])}</b> · {esc(q.get('subject'))} › {esc(q.get('chapter'))}"
        f" · concept: {esc(q.get('concept'))} · level: {esc(q.get('level'))}"
        f" · qid: {esc(q.get('qid'))} · error flag: {esc(q.get('error'))}"
        f" · updatedAt: <code>{esc(q.get('updatedAt'))}</code>"
    )
    rep_html = []
    for r in reps:
        after = q.get("updatedAt") and q["updatedAt"] > r["reportedAt"]
        fact = (
            '<span class="fact">record updatedAt is after this report</span>' if after else ""
        )
        rep_html.append(f"""
<div class="report" data-rid="{esc(r['reportId'])}" data-qid="{esc(q['_id'])}">
  <div class="rhead"><b>{esc(r['reportId'])}</b> · {esc(r['source'])} · {esc(r['studentId'])} ·
    reportedAt <code>{esc(r['reportedAt'])}</code> {fact}</div>
  <blockquote>{esc(r['comment']) or '<i>(empty)</i>'}</blockquote>
  <div class="form">
    <label>verdict <select name="verdict"></select></label>
    <label>repair <select name="repair"></select></label>
    <label>route <select name="route"></select></label>
    <label>edit field <select name="field"></select></label>
    <label class="wide">find <input name="find"></label>
    <label class="wide">replace <input name="replace"></label>
    <label class="wide">why (one line, your words) <input name="why"></label>
  </div>
</div>""")
    return f"""
<section class="q" id="q-{esc(q['_id'])}">
  <h2>#{idx} · <code>{esc(q['_id'])}</code> <span class="count">{len(reps)} report(s)</span></h2>
  <div class="meta">{meta}</div>
  <div class="cols">
    <div class="col">
      <h3>Question</h3><div class="render">{b.get('question') or '<i>(empty)</i>'}</div>
      <h3>Stored answer</h3><pre>{esc(json.dumps(ans, ensure_ascii=False))}</pre>
      <h3>Solution</h3><div class="render">{b.get('solution') or '<i>(empty)</i>'}</div>
      {'<h3>Images</h3><pre>' + esc(json.dumps(imgs, ensure_ascii=False, indent=1)) + '</pre>' if imgs else ''}
      {'<h3>errorHistory</h3><pre>' + esc(json.dumps(eh, ensure_ascii=False, indent=1)) + '</pre>' if eh else ''}
      <details><summary>raw question HTML</summary><pre class="raw">{esc(b.get('question'))}</pre></details>
      <details><summary>raw solution HTML</summary><pre class="raw">{esc(b.get('solution'))}</pre></details>
    </div>
    <div class="col reps">{''.join(rep_html)}</div>
  </div>
</section>"""


def unrep_block(q, idx):
    b = body(q)
    return f"""
<section class="q unrep" id="q-{esc(q['_id'])}">
  <h2>U{idx} · <code>{esc(q['_id'])}</code> <span class="count">not reported</span></h2>
  <div class="meta"><b>{esc(q['questionType'])}</b> · {esc(q.get('subject'))} › {esc(q.get('chapter'))} · updatedAt <code>{esc(q.get('updatedAt'))}</code></div>
  <h3>Question</h3><div class="render">{b.get('question') or '<i>(empty)</i>'}</div>
  <h3>Stored answer</h3><pre>{esc(json.dumps(b.get('answer'), ensure_ascii=False))}</pre>
  <h3>Solution</h3><div class="render">{b.get('solution') or '<i>(empty)</i>'}</div>
  {'<h3>errorHistory</h3><pre>' + esc(json.dumps(q.get('errorHistory'), ensure_ascii=False, indent=1)) + '</pre>' if q.get('errorHistory') else ''}
  <details><summary>raw question HTML</summary><pre class="raw">{esc(b.get('question'))}</pre></details>
  <label class="wide">defect notes (for docs/UNREPORTED.md) <input class="unote" data-qid="{esc(q['_id'])}"></label>
</section>"""


sections = [q_block(qby[qid], i + 1, reps) for i, (qid, reps) in enumerate(groups.items()) if qid in qby]
unrep = [unrep_block(q, i + 1) for i, q in enumerate(unreported)]

cfg = {
    "verdicts": list(taxonomy["verdicts"].keys()),
    "verdictHelp": taxonomy["verdicts"],
    "repairs": {k: {"fields": v["fields"], "auto": v["auto"], "label": v["label"]} for k, v in taxonomy["repairs"].items()},
    "routes": ["auto_apply", "faculty_review", "no_change"],
    "reportIds": [r["reportId"] for r in reports],
}

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phase 0 Worksheet</title>
<style>
:root{{--bg:#fafaf7;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e2e1db;--acc:#2a5bd7;--warn:#a15c00;--ok:#1d7a3a}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16171a;--fg:#e8e8e3;--mut:#9a9a94;--card:#1f2024;--line:#33343a;--acc:#7aa2ff;--warn:#f0b35a;--ok:#6fd38f}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
header{{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}}
header b{{font-size:16px}} button{{font:inherit;padding:5px 10px;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:6px;cursor:pointer}}
#progress{{color:var(--mut)}} main{{max-width:1300px;margin:0 auto;padding:16px}}
.q{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:0 0 18px}}
.q h2{{margin:0 0 4px;font-size:16px}} .count{{color:var(--mut);font-weight:400;font-size:13px}}
.meta{{color:var(--mut);font-size:13px;margin-bottom:8px}} h3{{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);margin:12px 0 4px}}
.cols{{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:18px}} @media (max-width:900px){{.cols{{grid-template-columns:1fr}}}}
.render{{overflow-x:auto;font-size:16px}} .render *{{color:inherit!important;background:none!important}} .render h3{{all:revert;font-size:16px;font-weight:400;margin:4px 0}}
math{{font-size:1.1em}} pre{{white-space:pre-wrap;word-break:break-word;background:var(--bg);padding:6px 8px;border-radius:6px;margin:0;font-size:13px}}
.raw{{max-height:300px;overflow:auto}} details{{margin-top:6px}} summary{{cursor:pointer;color:var(--acc);font-size:13px}}
.report{{border:1px solid var(--line);border-radius:8px;padding:10px;margin-bottom:10px}} .report.done{{border-color:var(--ok)}}
.rhead{{font-size:13px;color:var(--mut)}} blockquote{{margin:6px 0;padding:6px 10px;border-left:3px solid var(--acc);background:var(--bg);font-size:15px}}
.fact{{color:var(--warn);font-weight:600}} .form{{display:flex;flex-wrap:wrap;gap:6px 10px;font-size:13px}}
label{{display:flex;flex-direction:column;gap:2px}} label.wide{{flex:1 1 100%}} select,input{{font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--fg);width:100%}}
.hint{{font-size:12px;color:var(--mut)}} .unrep{{opacity:.95}}
</style></head><body>
<header><b>Phase 0 — read &amp; hand-label</b>
<span id="progress"></span>
<button id="export">Export labels.json</button>
<label style="flex-direction:row;align-items:center;gap:6px"><span>Import</span><input type="file" id="import" accept=".json" style="width:auto"></label>
<a href="#unreported">Jump to unreported questions ({len(unreported)})</a>
</header>
<main>
<p class="hint">Generated by <code>eval/make_worksheet.py</code> from <code>data/</code>. Nothing is pre-filled or suggested; the only computed hint is a plain date comparison (record <code>updatedAt</code> vs <code>reportedAt</code>). Answers autosave in this browser; Export writes <code>labels.json</code> — save it to <code>eval/labels.json</code>.
{len(groups)} reported questions, {len(reports)} reports{', missing question ids: ' + ', '.join(missing) if missing else ''}.</p>
{''.join(sections)}
<h2 id="unreported">Questions with no report ({len(unreported)}) — bonus pass</h2>
{''.join(unrep)}
</main>
<script>
const CFG = {json.dumps(cfg, ensure_ascii=False)};
const KEY = 'acadza-phase0-labels-v1';
let state = {{labels:{{}}, unreported:{{}}}};
try {{ const s = localStorage.getItem(KEY); if (s) state = Object.assign(state, JSON.parse(s)); }} catch(e) {{}}
function save(){{ try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch(e) {{}} progress(); }}
function opts(sel, list, blank){{ sel.innerHTML = (blank!==undefined?`<option value="">${{blank}}</option>`:'') + list.map(v=>`<option value="${{v}}">${{v}}</option>`).join(''); }}
function fillFields(card){{
  const rep = card.querySelector('[name=repair]').value, f = card.querySelector('[name=field]');
  const cur = f.value; const list = rep && CFG.repairs[rep] ? CFG.repairs[rep].fields : [];
  opts(f, list, '(no edit)'); if (list.includes(cur)) f.value = cur;
}}
function readCard(card){{
  const g = n => card.querySelector(`[name=${{n}}]`).value;
  const field = g('field');
  return {{reportId:card.dataset.rid, questionId:card.dataset.qid, verdict:g('verdict')||null,
    repair:g('verdict')==='defect' ? (g('repair')||null) : null, route:g('route')||null,
    edit: field ? {{field, find:g('find'), replace:g('replace')}} : null, why:g('why')}};
}}
function progress(){{
  const n = CFG.reportIds.filter(id => state.labels[id] && state.labels[id].verdict && state.labels[id].route).length;
  document.getElementById('progress').textContent = `${{n}} / ${{CFG.reportIds.length}} labelled`;
  document.querySelectorAll('.report').forEach(c => {{ const l = state.labels[c.dataset.rid]; c.classList.toggle('done', !!(l && l.verdict && l.route)); }});
}}
function load(card){{
  const l = state.labels[card.dataset.rid]; if (!l) return;
  const s = (n,v) => {{ card.querySelector(`[name=${{n}}]`).value = v ?? ''; }};
  s('verdict', l.verdict); s('repair', l.repair); s('route', l.route); fillFields(card);
  s('field', l.edit && l.edit.field); s('find', l.edit && l.edit.find); s('replace', l.edit && l.edit.replace); s('why', l.why);
}}
document.querySelectorAll('.report').forEach(card => {{
  opts(card.querySelector('[name=verdict]'), CFG.verdicts, '—');
  opts(card.querySelector('[name=repair]'), Object.keys(CFG.repairs), '—');
  opts(card.querySelector('[name=route]'), CFG.routes, '—');
  [...card.querySelector('[name=repair]').options].forEach(o => {{ const r = CFG.repairs[o.value]; if (r) o.title = (r.auto?'auto':'NOT auto') + ' · fields: ' + (r.fields.join(', ')||'none') + ' · ' + r.label; }});
  [...card.querySelector('[name=verdict]').options].forEach(o => {{ if (CFG.verdictHelp[o.value]) o.title = CFG.verdictHelp[o.value]; }});
  fillFields(card); load(card);
  card.addEventListener('input', e => {{ if (e.target.name === 'repair') fillFields(card); state.labels[card.dataset.rid] = readCard(card); save(); }});
  card.addEventListener('change', e => {{ if (e.target.name === 'repair') fillFields(card); state.labels[card.dataset.rid] = readCard(card); save(); }});
}});
document.querySelectorAll('.unote').forEach(i => {{ i.value = state.unreported[i.dataset.qid] || ''; i.addEventListener('input', () => {{ state.unreported[i.dataset.qid] = i.value; save(); }}); }});
document.getElementById('export').onclick = () => {{
  const out = {{labels: CFG.reportIds.map(id => state.labels[id] || {{reportId:id, verdict:null, repair:null, route:null, edit:null, why:''}}),
    unreported: Object.entries(state.unreported).filter(([k,v]) => v.trim()).map(([questionId, note]) => ({{questionId, note}}))}};
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {{type:'application/json'}}));
  a.download = 'labels.json'; a.click();
}};
document.getElementById('import').onchange = async e => {{
  const f = e.target.files[0]; if (!f) return; const d = JSON.parse(await f.text());
  (d.labels||[]).forEach(l => state.labels[l.reportId] = l); (d.unreported||[]).forEach(u => state.unreported[u.questionId] = u.note);
  save(); location.reload();
}};
progress();
</script></body></html>"""

OUT.write_text(page, encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}: {len(groups)} reported questions, {len(reports)} reports, {len(unreported)} unreported, missing={missing}")
