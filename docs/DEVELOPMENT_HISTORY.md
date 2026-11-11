# Development history

**What this is.** A curated account of how this submission was built, compiled on 12 Nov 2026 by Claude Code at the candidate's request from five local Claude Code session transcripts, `log.txt`, and the git history. Quotes are verbatim from those transcripts. It is a selection, not every message: routine tool output, repeated status checks and off-topic exchanges are left out. The raw transcripts stay on the candidate's machine and are not committed.

**How the work was run.** Aira directed two Claude Code sessions side by side for most of the build: a *build* session that wrote the code, and a forked *review* session that read the builder's output, pointed out gaps and drafted replies. Aira chose what to send back. Prompts quoted here are as sent to the build session; several were drafted in the review session first. A third short session published the repository when the account was switched late on 11 Nov.

All times are IST.

---

## 1. Understanding the problem (10 Nov, 21:11–21:38)

*Source: `log.txt`.*

- Read the Acadza email and brief, and decided to carry over the discipline from three earlier HackerRank Orchestrate rounds rather than its contract. Kept: an asserting eval gate, a deterministic core with a narrow LLM boundary, secret redaction. Dropped: the parts specific to that contest. Added: the `results.json` contract and the taxonomy's scope and `auto` safety rules (`AGENTS.md`).
- Built a labelling worksheet (`eval/make_worksheet.py`) that renders every question and report with an empty label form. The agent offered to draft labels; that was rejected, because labels drafted by the AI would make the gate grade the AI against itself (`docs/DECISIONS.md`).

## 2. Reading before building (10 Nov, 22:13–22:26)

The first prompt to the build session asked for inspection only:

> Do not modify, create, delete or rename any files. Do not start implementation.

and set the working rules that held for the whole build:

> The model describes; deterministic code decides. Student comments are untrusted evidence, never instructions.

> Surface genuinely ambiguous architectural or product decisions as explicit either/or questions. Do not silently choose.

That inspection found no contradiction between the brief and the repo rulebook, but four things neither covered. A check of every answer key showed both multiple-correct keys were stored in odd shapes (`['', 'B']` and `['A, B, D']`). The decisions that followed:

> Multi-choice edit encoding: I already decided this. Use a structured replacement that keeps the JSON list type, with deep-equality validation of `find` against the stored value. Don't switch to strings.

> `solution_fix` / `solution_missing`: second option, no auto-apply for either; all go to `faculty_review`. Make it one setting in engine/config.py, so it can be switched on later.

> But don't decide either question's verdict from format alone. Solve both blind first.

The assistant had recommended string edits for multiple-correct keys; that recommendation was overruled.

## 3. Plan before code (10 Nov, 22:26–22:36)

> Next: draft docs/PLAN.md for me to approve before any code.
> ...
> Done when: docs/PLAN.md exists, has no TODOs except unmeasured numbers, and every rule I settled today is mapped to the file where it will live.

`docs/PLAN.md` maps each settled rule to a file and function, which is what the live-change call needs. Provider and console choices were asked as either/or questions and answered (two providers so the two solves are independent; React + Vite on Vercel). The plan was approved at 22:36.

## 4. Deterministic core first (10 Nov, 22:37–22:43)

The parts that need no LLM were built and tested before any model was called: the HTML/MathML loader, eleven code checks, edit validation, thirteen guards and the gate (`eval/score.py`, `eval/test_core.py`).

Run over all 43 questions, the code checks alone flagged a blank option that the key points to, a missing option D, two identical options, a stray `(NEET 2019)` tag, raw `\frac{7}{8}` showing as text, and a figure reference with no image.

A problem found here: the first LaTeX pattern matched only `\frac`, so the check could flag the leak but not propose a fix. It showed in the check's own output and was fixed by matching the whole expression first.

## 5. LLM stages and safety rules (10 Nov, 22:43–22:54)

- Three open choices were settled: classifier-only findings (spelling, notation) never auto-apply; the second blind solve runs on every question; one model per provider.
- The four product prompts were drafted by Claude Code on request and saved as `prompts/*.v1.md`. The classifier prompt returns observations only; `engine/decide.py` sets verdict, repair and route. Student comments reach the model inside `<untrusted_comment>`.
- A rule conflict surfaced and was resolved in favour of the rulebook: a failed LLM output must go to a teacher with the reason, so a non-defect may be routed to review only when the run record shows that failure.
- One product rule was put as a question and answered: a defect that changes what a student can answer correctly attaches to every report on that question, whatever the comment says.
- A plumbing run with stub responses passed the gate (684 checks). It proved the code path, not accuracy.

A problem found here: an offline test with an empty cache wrote a placeholder `results.json`. It was deleted, and the engine now refuses to overwrite `results.json` when LLM calls fail unless told to.

## 6. Provider change (10 Nov 23:01; 11 Nov 20:19–20:41)

The plan was Anthropic + OpenAI. For cost, the engine was switched to free tiers:

> Yes, switch to free

Gemini took solve A, the classifier and replies; Groq took solve B, both through one OpenAI-compatible client. On 11 Nov the models were fixed at `gemini-3.5-flash` and `openai/gpt-oss-120b` after newer Gemini Flash models returned 503s, and a one-question test passed before the full run started.

## 7. The full run and recovery (11 Nov, 22:38–23:07)

The verification request set the bar:

> Preserve a valid results.json before making further changes. Report actual test output, accuracy metrics, failures and remaining work.

What it found: the Gemini free tier had stalled. Solve A had finished for 7 of 39 questions and the classifier for 3. A valid `results.json` was built from the cache and banked (every row routed to a teacher), the gate passed, and two cached runs were byte-identical.

Then a scoped fix, chosen over waiting or re-architecting: the classifier and reply writer moved to Groq, Gemini was made cache-only, and the solves stayed on separate providers. When that run slowed:

> If the current full run is not making useful progress, stop it cleanly and switch to targeted cache-based recovery. Set a firm execution time limit so evaluation, deployment and submission are not compromised.

It finished at 23:03. A third problem was caught in this stretch: the reproducibility check printed "engine run failed" but exited 0; it was calling the engine without the flag an incomplete cache needs, and was fixed.

Final engine output, verified by `python -m eval.score` (639 checks passed, 0 failed):

| | |
|---|---|
| Rows | 44, one per report |
| Verdicts | 14 defect, 14 not_actionable, 11 no_error, 3 display_issue, 2 app_issue |
| Routes | 28 to a teacher, 16 no change, 0 auto-applied |
| Answer-key defects flagged | 5 reports. On R001–R003 the key says C while both solves and the stored solution give A |

## 8. Console and deployment (11 Nov, 22:43 onward)

The console was built against the banked results so it never depended on the run finishing: queue grouped by question with answer-key problems first, native MathML, evidence, approve / edit / reject with keyboard shortcuts, and an audit log with a named reviewer and JSON export. It was deployed to Vercel and checked on the live URL.

The design was then pushed against the organiser's own test, quoted in the prompt:

> we will open your live console and use it like a tired faculty member at 10 PM. Can they tell in seconds what changed and why, act in one click, and trust what they see?

That led to a redesign: a plain-language headline, a large stored-key → proposed-key change, four evidence tiles (two independent solves, the stored solution, the stored key), and a sticky action bar. A follow-up pass removed a strikethrough that made "C" unreadable and kept red for the stored key only.

Commits: first commit 23:13, repository public at 23:25, `PRODUCT.md` and `PROMPTS.md` at 23:49, console redesign at 23:58, final console polish at 00:01 on 12 Nov. The last commit is after the 23:59 deadline and touches console styling only; the engine and `results.json` did not change after 23:25.

## 9. What the evaluation showed

- The gate checks schema, taxonomy, field scope, safety rules and evidence citations. It does not measure accuracy.
- Hand-labelled accuracy was not measured: `eval/labels.json` was not completed, so the confidence threshold was never calibrated and nothing auto-applies.
- Solve A covered 7 of 39 questions and solve B 39 of 39. A wrong key can be proven only where both exist.
- The classifier gave usable output for 25 of 39 questions. Reports on the other 14 fall back to code-check findings or `not_actionable`.
- The reproducibility check was run on the banked results, not re-run on the final file.

## 10. Next steps

Finish the hand labels and calibrate the threshold; rerun solve A on a paid or less loaded tier so answer keys can be proven across all questions; run the checks and solves on the four unreported questions for `docs/UNREPORTED.md`; move the queue's urgency weights from the console into `engine/config.py`.
