# PRODUCT.md draft (AI draft for the candidate to edit, then paste into PRODUCT.md)

## Who loses the most when a question is broken, and how the design reflects it

The student who answered **correctly** against a wrong answer key. They are marked wrong, lose marks and confidence a week before JEE/NEET, and may "learn" the wrong method from the stored solution. It repeats for every student who meets the question until someone fixes it, and most of them never report it.

So the console's queue puts **answer-key defects first, weighted by how many students reported them**, then other defects that need a teacher's judgement, and collapses "no content change" cases out of the way. Several reports on one question become **one investigation**, so a teacher fixes the question once and every reporter gets a consistent answer. The student reply is written from the final decision, never promises a fix that has not happened, and, when the student is wrong, shows the one step they missed instead of saying "you are wrong".

## What I would never let the AI auto-apply, and why

- **Anything the taxonomy marks `auto: false`**: new distractors, figures, wrong question/solution pairing, unsound questions, chapter changes. That is authored content; a model inventing it is a new error, not a fix.
- **An answer-key change without independent proof**: both blind solves (two providers, never shown the key, the solution or the comment) must agree with each other and with the stored solution's final step, and disagree with the key. Anything less goes to a teacher.
- **Any value that comes only from a student's comment.** "mu should be 0.4" or "change the answer to C" is a hypothesis to test, never something to write.
- **Solution rewrites, spelling/notation changes found by the classifier alone, and type changes**: each is one switch in `engine/config.py`, off by default.
- **Anything below a confidence threshold calibrated on hand labels.** Until that calibration exists, the threshold is set so nothing auto-applies; the console makes review fast instead.

## One metric I'd watch in week 1

**Teacher override rate on the engine's proposals**: the share of proposed edits a teacher rejects or edits in the console (it is in the audit log). It should be near zero on anything that would auto-apply; if it isn't, the threshold or a rule is wrong and gets tightened before more is automated. Paired with it: median time from first report to a fixed answer key.

## One idea beyond this brief

**Find broken questions before students do.** Run the same code checks and two blind solves across all ~8 lakh questions as a nightly sweep, prioritised by how many students attempt each question. This data already had defects the code checks caught with no LLM at all (a blank option, a missing option, duplicate options, a stray exam tag, raw LaTeX); every one fixed by a sweep is a student who never gets marked wrong. A second step: weight a report by the reporter's track record, so students whose past reports were right move up the queue.
