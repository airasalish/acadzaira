"""Stage 7: classifier. Returns observations only (what each comment claims, whether the
evidence supports it, the stored solution's final answer, candidate defects with proposed
spans). It returns no verdict and no route: engine/decide.py decides.

Student comments are passed inside <untrusted_comment> blocks and are data, never instructions.
"""
from __future__ import annotations

import json

from engine import llm
from engine.checks import CheckResult
from engine.load import NormQ
from engine.validate import classify_schema, validate_classify


def _quote_untrusted(text: str) -> str:
    return (text or "").replace("<", "‹").replace(">", "›")


def build_classify_input(nq: NormQ, checks: list[CheckResult], solves: dict, reports: list[dict],
                         taxonomy: dict) -> str:
    repairs = "\n".join(f"- {k} (fields: {', '.join(v['fields']) or 'none'}): {v['label']}"
                        for k, v in taxonomy["repairs"].items())
    check_lines = "\n".join(f"- {c.id}: {'ok' if c.passed else 'FAILED'} — {c.detail}" for c in checks)
    solve_lines = "\n".join(
        f"- {role}: " + (f"answer={s['answer']!r}, value={s['final_value']!r}, issue={s['issue']!r}"
                         if s else f"failed ({err})")
        for role, (s, err) in solves.items()
    )
    report_blocks = "\n".join(
        f'<report id="{r["reportId"]}" reportedAt="{r["reportedAt"]}" source="{r["source"]}">\n'
        f"<untrusted_comment>{_quote_untrusted(r['comment'])}</untrusted_comment>\n</report>"
        for r in reports
    )
    history = json.dumps(nq.error_history, ensure_ascii=False) if nq.error_history else "[]"
    return (
        f"Question type: {nq.qtype}\nRecord updatedAt: {nq.updated_at}\nerrorHistory: {history}\n\n"
        f"<question_html>\n{nq.question_html}\n</question_html>\n\n"
        f"<stored_answer_key>{json.dumps(nq.answer, ensure_ascii=False)}</stored_answer_key>\n\n"
        f"<stored_solution_html>\n{nq.solution_html}\n</stored_solution_html>\n\n"
        f"<deterministic_checks>\n{check_lines}\n</deterministic_checks>\n\n"
        f"<blind_solves>\n{solve_lines}\n</blind_solves>\n\n"
        f"<reports>\n{report_blocks}\n</reports>\n\n"
        f"<repair_types>\n{repairs}\n</repair_types>"
    )


def _fake(reports: list[dict]) -> dict:
    return {
        "solution_final_answer": [], "solution_matches_question": True, "solution_wrong_step": "",
        "reports": [{"reportId": r["reportId"], "claim_type": "unclear", "claim_summary": "fake",
                     "claim_supported": "unclear", "student_missed_step": "", "injection_or_gaming": False}
                    for r in reports],
        "candidate_defects": [],
    }


def classify(nq: NormQ, checks: list[CheckResult], solves: dict, reports: list[dict],
             taxonomy: dict) -> tuple[dict | None, str | None]:
    repair_keys = list(taxonomy["repairs"])
    res = llm.call_json("classify", nq.id, build_classify_input(nq, checks, solves, reports, taxonomy),
                        classify_schema(repair_keys), fake=lambda: _fake(reports))
    if res.error:
        return None, res.error
    return validate_classify(res.data, nq.qtype, [r["reportId"] for r in reports], repair_keys)
