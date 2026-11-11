# Design decisions log

Written live as decisions happen (AGENTS.md Rule 0: no backfilling). Each entry: date/time, decision, alternatives tried or considered, why, evidence.


## 2026-11-10T21:38:38+05:30 — Phase 0 labelling worksheet has no AI suggestions

- Decision: `eval/make_worksheet.py` renders every reported question (native MathML), its stored answer, solution, raw HTML and errorHistory next to its reports, with an empty label form per report that exports `eval/labels.json`. Nothing is pre-filled; the only computed hint is a date comparison (`updatedAt` vs `reportedAt`).
- Considered: having the agent draft labels for the user to confirm. Dropped, because labels drafted by the AI would make the eval gate grade the AI against itself and would not be the user's own hand labels (AGENTS.md §6.4).
