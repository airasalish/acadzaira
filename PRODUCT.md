# PRODUCT.md

## Who loses the most when a question is broken, and how the design reflects it

The student who answered correctly against a wrong answer key. They are marked wrong, lose marks and confidence days before JEE/NEET, and may learn the wrong method from the stored solution. It repeats for every student who meets the question until someone fixes it, and most never report it.

So the console queue puts answer-key defects first, weighted by how many students reported them, then other defects that need a teacher's judgement, and collapses "no content change" cases out of the way. Several reports on one question become one investigation, so a teacher fixes the question once and every reporter gets a consistent answer. The student reply is written from the final decision, never promises a fix that has not happened, and, when the student is mistaken, shows the one step they missed.

## What I would never let the AI auto-apply, and why

- Anything the taxonomy marks `auto: false` (new distractors, figures, unsound questions, wrong question/solution pairing, chapter changes). That is authored content; a model inventing it is a new error.
- An answer-key change without independent proof: two blind solves from different providers, never shown the key, solution or comment, must agree with each other and with the stored solution, and disagree with the key.
- Any value that comes only from a student's comment. "Change the answer to C" is a hypothesis to test, never something to write.
- Solution rewrites, type changes, and spelling/notation fixes that only the classifier found.
- Anything below a confidence threshold calibrated on hand labels. I did not finish that calibration, so in this submission nothing auto-applies; every proposal goes to a teacher.

## One metric I'd watch in week 1

Teacher override rate: the share of the engine's proposals a teacher rejects or edits in the console (it is in the audit log). It should be near zero on anything I would later allow to auto-apply. Paired with it: median time from first report to a corrected answer key.

## One idea beyond this brief

Find broken questions before students do. Run the same code checks and blind solves across all ~8 lakh questions as a nightly sweep, ordered by how many students attempt each question. In this dataset the code checks alone, with no LLM, flagged a blank option, a missing option, duplicate options, a stray exam tag and raw LaTeX. Next step: weight each report by the reporter's track record.
