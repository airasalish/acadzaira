# Acadza Report → Fix

Triage engine that turns student "Report error" comments on JEE/NEET questions into safe, surgical fixes, plus a faculty review console.

- Brief: [BRIEF.md](BRIEF.md) · Rules for AI agents: [AGENTS.md](AGENTS.md)
- Output: [results.json](results.json) · Prompts and decisions: [PROMPTS.md](PROMPTS.md) · Product: [PRODUCT.md](PRODUCT.md)

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

## Live console
https://acadza-review-console.vercel.app

The console is static: it loads the precomputed `results.json` (plus `data/` and a slim run record) and makes no LLM calls. Approve / Edit / Reject entries are stored in the reviewer's browser (localStorage); use **Export audit (JSON)** to keep them.

```bash
cd console && npm install && npm run build      # copies ../results.json + data into public/data
cd dist && vercel deploy --prod --project acadza-review-console
```
