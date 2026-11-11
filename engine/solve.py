"""Stages 5–6: blind solves. The solver sees the question and its options only: never the stored
key, never the stored solution, never a student comment."""
from __future__ import annotations

from engine import llm
from engine.load import NormQ
from engine.validate import SOLVE_SCHEMA, validate_solve

TYPE_RULE = {
    "scq": "Single-correct MCQ: exactly one option is correct. Answer with one option letter.",
    "mcq": "Multiple-correct MCQ: one or more options are correct. Answer with every correct option letter.",
    "integerQuestion": "Numerical answer: answer with one number in the units/form the question asks for.",
}


def build_solve_input(nq: NormQ) -> str:
    opts = "\n".join(f"({l}) {t if t.strip() else '[BLANK]'}" for l, t in nq.options.items()) or "(no options)"
    return (
        f"Question type: {nq.qtype}. {TYPE_RULE.get(nq.qtype, '')}\n\n"
        f"<question_html>\n{nq.question_html}\n</question_html>\n\n"
        f"<question_text>\n{nq.stem_text}\n</question_text>\n\n"
        f"<options>\n{opts}\n</options>\n"
        f"Images attached to the question: {len(nq.ques_images)}"
    )


def _fake(nq: NormQ) -> dict:
    ans = {"scq": ["A"], "mcq": ["A", "B"], "integerQuestion": ["0"]}.get(nq.qtype, [])
    return {"solvable": True, "issue": "", "answer": ans, "final_value": ans[0] if ans else "", "method": "fake"}


def solve_blind(nq: NormQ, role: str) -> tuple[dict | None, str | None]:
    """→ (solve, error). solve = {answer (stored-key shape or None), issue, final_value, method}."""
    res = llm.call_json(role, nq.id, build_solve_input(nq), SOLVE_SCHEMA, fake=lambda: _fake(nq))
    if res.error:
        return None, res.error
    return validate_solve(res.data, nq.qtype)
