# PLAN — Report → Fix (Phase 1, draft for approval)

Status: **approved by the candidate, 10 Nov 2026.** §7 items A–D are still open choices.
Sources: `BRIEF.md` (wins on conflict), `AGENTS.md` §6–7, decisions settled on 10 Nov 2026 (the candidate records them in `docs/DECISIONS.md`).
Numbers that can't be measured yet are marked **TODO**.

Fixed choices:
- Engine: Python 3. Pure code except the 4 LLM roles in §5.
- LLM providers (free tiers, switched 10 Nov): **Gemini** (solve A, classifier, reply writer) and **Groq** (solve B only), both through their OpenAI-compatible endpoints with the `openai` SDK.
- Console: **React + Vite**, deployed on **Vercel**, static (reads precomputed files; no LLM calls at runtime).
- Hand labels `eval/labels.json` are written by the candidate. `engine/` never imports or reads them. This plan sets no verdict for any report.

---

## 1. Pipeline stages → file / function

Run: `python -m engine.run` → `results.json` (+ `console/public/data/queue.json`, `engine/out/run_record.json`).

| # | Stage | File | Function(s) | LLM? |
|---|---|---|---|---|
| 1 | Load data, taxonomy, config | `engine/load.py` | `load_all()` | no |
| 2 | Normalise each question: per-type body, stem HTML, options parsed out of question HTML, solution, answer; plain-text view with MathML stripped | `engine/load.py` | `normalise_question(q) -> NormQ`, `mathml_to_text(html)` | no |
| 3 | Group reports by `questionId`; one investigation per question | `engine/run.py` | `group_reports(reports)` | no |
| 4 | Deterministic checks (list in §4.1) | `engine/checks.py` | `run_checks(nq, reports) -> list[CheckResult]` | no |
| 5 | Blind solve A: stem + options only (no key, no solution, no comment) | `engine/solve.py` | `solve_blind(nq, role="solve_a")` | Gemini |
| 6 | Blind solve B: different prompt, different provider | `engine/solve.py` | `solve_blind(nq, role="solve_b")` | Groq |
| 7 | Classifier: question + check results + solves + stored key/solution + comments (quoted as untrusted) → **observations only**, JSON | `engine/classify.py` | `classify(nq, checks, solves, reports) -> Observations` | Gemini |
| 8 | Validate LLM JSON against schema; failure → observation `validator_failed(reason)` (never dropped) | `engine/validate.py` | `validate_observations()`, `validate_solve()` | no |
| 9 | Decide: observations + checks + solves → one **Decision** object per report (verdict, repair, edit, route, confidence, evidence, check ids). Rules read from config/taxonomy | `engine/decide.py` | `decide(nq, report, checks, solves, obs) -> Decision` | no |
| 10 | Build and test edits: count `find` occurrences, deep-equality for lists, apply, re-parse MathML | `engine/edits.py` | `build_edit()`, `count_matches()`, `apply_edit()`, `markup_ok()` | no |
| 11 | Guards: can only **downgrade** route (auto_apply → faculty_review → never upward); each downgrade appends its reason to evidence | `engine/guards.py` | `apply_guards(decision, nq) -> Decision` | no |
| 12 | Reply writer: from the final Decision (not the comment); output validated; fallback template on failure | `engine/replies.py` | `write_reply(decision, report)`, `validate_reply()` | Gemini |
| 13 | Assemble rows, sort by `reportId`, schema-check, write deterministic JSON | `engine/run.py` | `build_rows()`, `write_results()` | no |
| 14 | Urgency ordering for the console (weights from config) | `engine/queue.py` | `build_queue(decisions) -> queue.json` | no |
| 15 | Bonus sweep: checks + both solves on the 4 unreported questions → candidates for `docs/UNREPORTED.md` (never into `results.json`) | `engine/sweep.py` | `sweep_unreported()` → `eval/unreported_candidates.json` | Gemini + Groq |

Shared helpers:
- LLM client + cache + usage log: `engine/llm.py` (`call(role, subject_id, prompt_name, variables)`).
- Prompt loader: `engine/prompts.py`, which reads `prompts/<name>.v<N>.md` and uses the version set in config.

---

## 2. `results.json` schema

A JSON array of exactly 44 objects, one per `reportId` in `data/reports.json`, sorted by `reportId`. Each object has exactly these keys:

```json
{
  "reportId": "R000",
  "questionId": "24-hex",
  "verdict": "<key of taxonomy.verdicts>",
  "repair": "<key of taxonomy.repairs> | null",
  "edit": "<Edit> | null",
  "route": "auto_apply | faculty_review | no_change",
  "confidence": 0.00,
  "evidence": "1–2 sentences citing checks that ran",
  "student_reply": "1–3 sentences"
}
```

Invariants:
- `repair` is non-null **iff** `verdict == "defect"`.
- `verdict != "defect"` ⇒ `edit == null` and `route == "no_change"`, except `faculty_review` when an LLM output failed validation (AGENTS §7 fallback; the run record must show the validator error).
- `confidence` is a float in [0, 1], rounded to 2 dp, computed by `decide.py` (not stated by an LLM).

### Edit variants

`field` names a key inside the question's type body (`q[q.questionType][field]`).

| Case | Shape | Match rule |
|---|---|---|
| Text fields (`question`, `solution`) | `{"field":"question","find":"<str>","replace":"<str>"}` | `find` occurs exactly once in the stored string |
| `scq` / `integerQuestion` answer | `{"field":"answer","find":"B","replace":"D"}` (strings, as in BRIEF.md) | `find` equals the stored string exactly |
| `mcq` answer (**structured**) | `{"field":"answer","find":["","B"],"replace":["A","B"]}` (JSON lists, not strings) | `find` deep-equals the stored list (same length, same elements, same order); `replace` is a list of single uppercase letters |
| Repair with `fields: []` (all `auto:false` ones) and `type_mismatch` | `null` | — |

- **Canonical `mcq` key:** a list whose elements are each a single option letter `A`–`D`, no empties, no duplicates, no comma-joined strings.
- A non-canonical key is recorded as check `mcq_key_noncanonical`. It is evidence, not a verdict: the verdict waits for the blind solves.

---

## 3. Settings: `engine/config.py` vs `data/taxonomy.json`

**`data/taxonomy.json`** (organiser file, read-only, never edited by code) is the single source for:
- the verdict keys;
- the repair keys;
- each repair's allowed `fields`;
- each repair's `auto` flag.

If the requirement changes live, the candidate edits this file and reruns. Guards read `fields` / `auto` from here, never from a copy.

**`engine/config.py`** holds every other rule:

| Setting | Purpose | Value |
|---|---|---|
| `AUTO_APPLY_MIN_CONFIDENCE` | Below this → `faculty_review` | **TODO** (calibrated on the candidate's labels by running `eval/score.py --sweep`, then typed in by hand) |
| `SOLUTION_REPAIRS_AUTO = False` | Master switch: `solution_fix` and `solution_missing` always `faculty_review` | `False` (settled) |
| `SOLUTION_REPAIRS = ("solution_fix","solution_missing")` | Repairs governed by the switch above | settled |
| `VALUE_FROM_SOLUTION_REPAIRS = ("option_repair","stem_data")` | auto_apply only when code finds the replacement value in the stored solution (MathML-stripped text) | settled |
| `TYPE_MISMATCH_ROUTE = "faculty_review"`, edit `null` | type_mismatch handling | settled |
| `ANSWER_KEY_PROOF` | Required conditions for answer_key auto_apply (§4.2) | settled per AGENTS §7 |
| `AUTO_POLICY` | Per-repair proof rule for the other `auto:true` repairs | settled (§7 A): noise / exam_reference / markup_leak auto only when a code check found them; spelling / notation / answer_form → faculty |
| `CONFIDENCE_RULES` | Table: evidence pattern → base confidence + penalties (e.g. solves disagree, validator failed) | values **TODO** (set during Phase 3–4) |
| `URGENCY_WEIGHTS` | Per-verdict/repair weight × reporter count, used by `queue.py` | values: open item D |
| `PROVIDERS` / `PROVIDER_ENDPOINTS` / `MODEL_A` / `MODEL_B` | Provider, endpoint and model ID per role | Gemini (A, classify, reply), Groq (B); model IDs set by the candidate after checking each account (None = provider not called) |
| `TEMPERATURE` / `REASONING_EFFORT` | `0`; effort per role, sent only if set and dropped if the model rejects it (determinism guarantee is still the cache) | solve_a/solve_b `high`, classify `medium`, reply none |
| `MAX_WORKERS` / `MAX_RETRIES` | Free-tier rate limits: 2 questions in parallel, SDK backoff on 429 | 2 / 6 |
| `PROMPT_VERSIONS` | `{"solve_a":"v1","solve_b":"v1","classify":"v1","reply":"v1"}` | — |
| `SOLVE_B_SCOPE` | `"all"` or `"key_disagreement"` | settled (§7 B): `"all"` |
| `REPLY_FALLBACK_TEMPLATES` | Per-verdict/route template used when the reply validator rejects the LLM reply | drafted in Phase 2 |
| `BANNED_REPLY_PHRASES_NON_AUTO` | e.g. "fixed", "corrected", "updated": forbidden when route ≠ auto_apply | — |
| `EXAM_TAG_PATTERNS`, `NOISE_PATTERNS`, `MARKUP_LEAK_PATTERNS` | Regexes for the deterministic checks | — |

---

## 4. Safety guards and checks

### 4.1 Deterministic checks (`engine/checks.py`, all questions)

Each check returns `CheckResult{id, passed, detail}`, and all of them go to `engine/out/run_record.json`.

- `options_present`: options A–D are found in the question HTML and none is blank or cut off.
- `options_unique`: no two options are identical after MathML-stripped text normalisation.
- `markup_leak`: raw LaTeX (`\frac`, `$…$`) or escaped HTML visible as text.
- `exam_reference`: tags such as `(JEE Main 2019)`.
- `noise`: question numbers, "Space for rough work", source labels.
- `answer_shape`: the answer type matches `questionType`.
  - `scq`: one letter.
  - `integerQuestion`: a numeric string.
  - `mcq`: canonical list.
  - Failing `mcq` → `mcq_key_noncanonical`.
- `type_consistency`: the number of correct options implied by the key vs the type. For example, an `mcq` key with one real letter feeds the type_mismatch investigation. It is evidence only.
- `already_fixed`: `updatedAt` or an `errorHistory[].at` later than `reportedAt`, **and** the reported problem is absent from the live record.
- `images`: `quesImages` / `solutionImages` are empty while the text refers to a figure.

### 4.2 Guards (`engine/guards.py`, applied in this order, downgrade-only)

1. **Scope:** `edit.field ∈ taxonomy.repairs[repair].fields`. A repair with `fields: []` must have `edit == null`. Violation → drop the edit, `faculty_review`.
2. **auto:false:** if `taxonomy.repairs[repair].auto == false`, the route can't be `auto_apply`.
3. **Solution repairs:** `repair ∈ SOLUTION_REPAIRS` and `SOLUTION_REPAIRS_AUTO == False` → `faculty_review`. A solution copied from another question → `solution_fix`, `faculty_review`, `edit: null` (it needs a rewrite).
4. **Value from solution:** for `option_repair` / `stem_data`, the `replace` value (MathML-stripped) must occur in the stored solution's MathML-stripped text. Otherwise → `faculty_review`.
5. **answer_key proof:** all three must hold, otherwise → `faculty_review`:
   - solve A == solve B;
   - they agree with the stored solution's final answer (as reported by the classifier observation and cross-checked against the solution text);
   - they disagree with the stored key.

   `replace` must equal the solves' agreed answer, never a value that appears only in the comment.
6. **type_mismatch:** always `faculty_review`, `edit: null`.
7. **Match:** string `find` occurs exactly once; `mcq` list `find` deep-equals the stored value. 0 or 2+ matches → drop the edit, `faculty_review`.
8. **Markup:** after `apply_edit`, the field must still parse (HTML + MathML well-formed). Failure → `faculty_review`.
9. **Confidence:** `confidence < AUTO_APPLY_MIN_CONFIDENCE` → `faculty_review`.
10. **Validator failure:** any LLM output rejected by `validate.py` → `faculty_review` with the reason in evidence. Never silently dropped, never disabled.
11. **Comment-as-instruction:** a classifier flag `injection_or_gaming`, or an edit value that traces only to the comment, → no edit. The verdict comes from the checks (`no_error` / `not_actionable`).
12. **Evidence citation:** evidence may name only check ids or solves that are present in that report's run record.
13. **Reply:** 1–3 sentences; when route ≠ `auto_apply`, no phrase from `BANNED_REPLY_PHRASES_NON_AUTO`. Failure → fallback template.

Consistency: verdict, repair, edit, evidence and reply all derive from one `Decision` object, and nothing is generated independently. Reports on the same question share one investigation: their verdict and repair are the same unless the evidence differs.

### 4.3 `eval/score.py` (a gate: exits non-zero on failure)

**Hard asserts on `results.json` alone (no labels needed):**
- 44 rows; `reportId`s equal the set in `data/reports.json`; no duplicates; `questionId` matches the report.
- Exact key set; `verdict`/`repair` are taxonomy keys; `route` is in the enum; `confidence` is in [0, 1].
- `repair` null iff not a defect; a non-defect has route `no_change` and `edit` null.
- Zero scope violations.
- Zero `auto_apply` on `auto:false` repairs, on `solution_fix` / `solution_missing` (while the switch is off), or on `type_mismatch`.
- Every edit: `find` matches exactly once (string) or deep-equals (list); the field still parses after the edit; an `mcq` `replace` is canonical.
- Every `auto_apply` `answer_key` row has the solves-agree + solution-agrees + key-disagrees record in the run record.
- Every evidence string cites only checks present in the run record.
- Every reply is 1–3 sentences, with no fix promise on non-auto routes.
- No question without a report appears in `results.json`.
- `engine/` source contains no reference to `labels.json` (grep).
- Determinism (`--repro`): run the engine twice from the cache; the two `results.json` files are byte-identical.

**Accuracy gate vs `eval/labels.json` (candidate's file, read only by `score.py`):**
- Prints verdict / repair / route accuracy and a per-report mismatch list.
- Fails if any metric drops below `eval/baseline.json`, the last banked run. Baseline values: **TODO** (first run).
- `--sweep`: prints route accuracy and safety violations for candidate thresholds. The candidate picks `AUTO_APPLY_MIN_CONFIDENCE` from it.

---

## 5. LLM roles, cache, call estimate

| Role | Provider | Sees | Never sees | Returns (JSON, validated) | Prompt file |
|---|---|---|---|---|---|
| `solve_a` | Gemini | stem + options (MathML) | key, solution, comments | `{answer, value, method_summary}` | `prompts/solve_a.v1.md` |
| `solve_b` | Groq | stem + options (different prompt) | key, solution, comments | same shape | `prompts/solve_b.v1.md` |
| `classify` | Gemini | question, stored key + solution, check results, both solves, comments inside an `<untrusted_comment>` block | — | observations only: what the comment claims, whether the evidence supports it, the solution's final answer, candidate defects with proposed `find`/`replace` spans, `injection_or_gaming`, language/display/app signals. **No verdict, no route.** | `prompts/classify.v1.md` |
| `reply` | Gemini | final Decision (verdict, route, the one step the student missed, if any), the comment's language register | internal labels are not to be shown to the student | `{reply}` | `prompts/reply.v1.md` |

- Prompt files are saved by the candidate (AGENTS §4.7). A changed prompt is a new version file, never edited in place.
- **Cache:** one file, `engine/.cache/llm_cache.json`.
  - Key: `"<subject_id>|<role>"`, where subject_id is the `questionId` for solves/classify, the `reportId` for replies, and the `questionId` for sweep solves.
  - Each entry stores the prompt version, model ID, request hash and response. A stored entry with a different prompt version or model is treated as a miss and recomputed.
- **Usage log:** `engine/llm.py` appends one line per real (uncached) call to `eval/usage.jsonl` with `{ts, role, subject_id, model, input_tokens, output_tokens, cost_usd}`.
- **Calls per full uncached run (estimate):**
  - 39 reported questions × 3 (solve A, solve B, classify) = 117
  - 44 replies
  - 4 unreported questions × 2 solves (bonus sweep) = 8
  - **Total ≈ 169** (`SOLVE_B_SCOPE="all"`): 124 Gemini, 45 Groq. Cost on free tiers: $0 (usage still logged).
  - Cached rerun: 0 calls.
- Tokens and cost per run: **TODO** (measured from `eval/usage.jsonl` after the first run).

---

## 6. Console (React + Vite, Vercel)

- **Data:**
  - A prebuild script `console/scripts/copy-data.mjs` copies `results.json`, `data/*.json` and `queue.json` into `console/public/data/`.
  - No backend, no LLM calls. README says the console shows precomputed results.
- **Queue:**
  - Grouped by question, ordered by `queue.json` (urgency from `URGENCY_WEIGHTS`), with a one-line "why first" on each group.
  - `no_change` cases sit in a collapsed section.
- **Card:**
  - Header: verdict chip + confidence.
  - One-line evidence.
  - Checks that ran (✔/✘).
  - Before/after diff of the edited field. Text: inline red/green with MathML rendered. `mcq`: old list vs new list.
  - The rendered question (native MathML).
  - The reporters' comments.
  - A reply preview.
- **Actions:** Approve / Edit / Reject, with keys `A` / `E` / `R` and `J` / `K` for next / previous.
- **Audit:**
  - Entry: `{actor, at, reportId, action, before, after}`, stored in `localStorage`.
  - Actor is a "your name" prompt, stored in the browser.
  - An "Export audit (JSON)" button.
  - README says the history lives only in that browser.

---

## 7. Choices

Settled 10 Nov 2026:
- **A.** `noise`, `exam_reference`, `markup_leak` auto-apply only when a deterministic check found the problem; `spelling`, `notation`, `answer_form` always → `faculty_review`.
- **B.** `SOLVE_B_SCOPE = "all"`: solve B runs on every reported question.
- **C.** Originally Anthropic (`claude-opus-5-5`) + OpenAI; switched 10 Nov to free providers: Gemini for solve A / classify / reply, Groq for solve B. Model IDs set by the candidate.

Still open:
- **D. `URGENCY_WEIGHTS`:**
  - Default order: confirmed `answer_key` × reporters → other auto-fixable defects → needs-judgement defects → no-change.
  - Exact weights to be set by the candidate in `PRODUCT.md` terms.

---

## 8. Settled rules → where they live

| Rule (settled 10 Nov 2026) | File : function / setting |
|---|---|
| scq / integer answer edits are plain string find/replace | `engine/edits.py:build_edit`; asserted in `eval/score.py` |
| mcq edits are structured lists; `find` deep-equals the stored value | `engine/edits.py:build_edit`, `count_matches`; `engine/guards.py` guard 7; `eval/score.py` |
| Canonical mcq key = list of single letters; non-canonical is evidence, not a verdict | `engine/checks.py:answer_shape` → `mcq_key_noncanonical`; `engine/decide.py` (verdict waits for solves) |
| `['', 'B']`-style key also investigated as possible type_mismatch | `engine/checks.py:type_consistency`; `engine/decide.py` |
| Unreported questions never in `results.json`; go to `docs/UNREPORTED.md` | `engine/sweep.py`; `engine/run.py:build_rows` (reports only); `eval/score.py` |
| `solution_fix` / `solution_missing` never auto-apply; one switch | `engine/config.py:SOLUTION_REPAIRS_AUTO`; `engine/guards.py` guard 3 |
| Solution from another question → `solution_fix`, faculty, edit null | `engine/decide.py`; `engine/guards.py` guard 3 |
| `option_repair` / `stem_data` auto only if value found in MathML-stripped solution | `engine/config.py:VALUE_FROM_SOLUTION_REPAIRS`; `engine/load.py:mathml_to_text`; `engine/guards.py` guard 4 |
| type_mismatch: defect / type_mismatch / `faculty_review` / edit null | `engine/config.py:TYPE_MISMATCH_ROUTE`; `engine/guards.py` guard 6 |
| Audit in localStorage, name prompt, export button, README note | `console/src/audit.ts`, `console/src/NamePrompt.tsx`, `console/src/ExportAudit.tsx`; `README.md` |
| Two free providers: Gemini (A, classify, reply), Groq (B) | `engine/config.py:PROVIDERS`; `engine/llm.py` |
| spelling / notation / answer_form never auto; noise / exam_reference / markup_leak auto only with a code check | `engine/config.py:AUTO_POLICY`, `REPAIR_PROVING_CHECK`; `engine/guards.py` guard 4b |
| Solve B on all reported questions | `engine/config.py:SOLVE_B_SCOPE`; `engine/run.py` |
| Model IDs chosen by the candidate per account | `engine/config.py:MODEL_A` (Gemini), `MODEL_B` (Groq); `engine/llm.py` |
| A major defect (changes what a student can answer correctly) attaches to every report on the question; minor defects only to reports that claim them | `engine/config.py:MAJOR_REPAIRS`, `CLAIM_TO_REPAIRS`, `REPAIR_PRIORITY`; `engine/decide.py:decide` |
| Non-defect may be `faculty_review` only as the validator fallback | `engine/decide.py:decide`; `eval/score.py` |
| Console: React + Vite on Vercel | `console/` |
| Engine never reads `eval/labels.json` | `eval/score.py` grep assert |
| No verdict preset for any report (incl. R020 / R021) | `engine/decide.py` uses observations only; no per-report constants (grep assert for `R0` literals in `engine/`) |
