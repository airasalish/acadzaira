# Acadza Report → Fix

Triage engine that turns student "Report error" comments on JEE/NEET questions into safe, surgical fixes, plus a faculty review console.

- Brief: [BRIEF.md](BRIEF.md) · Rules for AI agents: [AGENTS.md](AGENTS.md)
- Output: [results.json](results.json) · Prompts and decisions: [PROMPTS.md](PROMPTS.md) · Product: [PRODUCT.md](PRODUCT.md) · Build session transcript: [SESSION_TRANSCRIPT.md](SESSION_TRANSCRIPT.md)

## Layout
| Path | What |
|---|---|
| `data/` | Organiser data (read-only) |
| `engine/` | Triage pipeline |
| `prompts/` | Every in-product prompt, versioned |
| `eval/` | Hand labels, scoring gate, usage/cost log |
| `console/` | Faculty review web app |
| `docs/` | Decisions, AI-wrong moments, unreported defects, checklist |

## Run
```bash
pip install -r requirements.txt          # keys in .env: GEMINI_API_KEY, GROQ_API_KEY (see .env.example)
python -m engine.run                     # live: cached LLM calls reused, misses call Gemini / Groq
python -m engine.run --offline --allow-errors   # rebuild results.json from engine/.cache only
python -m eval.score                     # gate: schema, taxonomy, scope, safety, evidence; exits 1 on failure
python -m eval.score --repro             # two cached runs must be byte-identical
python -m eval.test_core                 # unit tests for parser, edits, guards, replies
```
If an LLM call fails, `engine.run` keeps the banked `results.json` and writes `engine/out/results.partial.json`; rows whose LLM steps failed are routed to `faculty_review` with the reason, never dropped.

## Results and coverage
`results.json` in this repository is the completed run of 12 Nov 2026 (after the deadline). The run submitted on 11 Nov is commit `7ccd01c`; free-tier quotas had left it with solve A on 7 of 39 questions and the classifier on 25 of 39.

| | Submitted (11 Nov) | Current |
|---|---|---|
| Solve A | 7 of 39 | 38 of 39 |
| Solve B | 39 of 39 | 39 of 39 |
| Classifier | 25 of 39 | 37 of 39 |

Solve A uses Gemini where a cached answer exists (9 questions) and a second Groq model, `qwen/qwen3.8-27b`, elsewhere (29). On those 29 both solves run on Groq with two different models, which is weaker independence than two providers. Nothing auto-applies, and accuracy against hand labels has not been measured. Details: [docs/DEVELOPMENT_HISTORY.md](docs/DEVELOPMENT_HISTORY.md).

## Applying approved changes
Approving in the console records a decision in that browser only; nothing is written to any question bank. To turn decisions into fixed data, use **Audit log → Export approved changes** in the console, then:

```bash
python -m engine.apply acadza-approved-changes.json   # writes engine/out/questions.fixed.json + apply_report.json
```
Each change is re-checked before it is applied (allowed field for the repair type, `find` matches exactly once, markup still valid). A change that fails is refused and listed in the report. `data/questions.json` is never modified.

## Live console
https://acadza-review-console.vercel.app

The console is static: it loads the precomputed `results.json` (plus `data/` and a slim run record) and makes no LLM calls. Approve / Edit / Reject entries are stored in the reviewer's browser (localStorage); use **Export audit (JSON)** to keep them.

```bash
cd console && npm install && npm run build      # copies ../results.json + data into public/data
cd dist && vercel deploy --prod --project acadza-review-console
```
