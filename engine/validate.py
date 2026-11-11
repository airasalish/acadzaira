"""Stage 8: JSON schemas sent to the LLMs, and validators for what comes back.

A failed validation is never dropped: the stage returns the error string, decide.py records it
in Decision.validator_errors, and guard G10 routes the report to faculty_review.
"""
from __future__ import annotations

import re
from typing import Any

from engine import config

CLAIM_TYPES = ["answer_key", "missing_option", "missing_data", "figure", "typo", "solution",
               "classification", "display", "app", "language", "gaming", "unclear"]


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


SOLVE_SCHEMA = _obj({
    "solvable": {"type": "boolean"},
    "issue": {"type": "string"},
    "answer": {"type": "array", "items": {"type": "string"}},
    "final_value": {"type": "string"},
    "method": {"type": "string"},
})


def classify_schema(repair_keys: list[str]) -> dict:
    return _obj({
        "solution_final_answer": {"type": "array", "items": {"type": "string"}},
        "solution_matches_question": {"type": "boolean"},
        "solution_wrong_step": {"type": "string"},
        "reports": {"type": "array", "items": _obj({
            "reportId": {"type": "string"},
            "claim_type": {"type": "string", "enum": CLAIM_TYPES},
            "claim_summary": {"type": "string"},
            "claim_supported": {"type": "string", "enum": ["yes", "no", "unclear"]},
            "student_missed_step": {"type": "string"},
            "injection_or_gaming": {"type": "boolean"},
        })},
        "candidate_defects": {"type": "array", "items": _obj({
            "repair": {"type": "string", "enum": repair_keys},
            "field": {"type": "string", "enum": ["question", "solution", "answer", "none"]},
            "find": {"type": "string"},
            "replace": {"type": "string"},
            "rationale": {"type": "string"},
        })},
    })


REPLY_SCHEMA = _obj({"reply": {"type": "string"}})


# ---------------------------------------------------------------- answer normalisation

def normalise_answer(qtype: str, raw: list[str]) -> Any:
    """Solver/classifier answer list → the stored-key shape for this type, or None if invalid.
    scq: 'B'   integerQuestion: '20'   mcq: ['A', 'B'] (sorted, canonical)"""
    vals = [str(v).strip() for v in (raw or []) if str(v).strip()]
    if qtype == "scq":
        letters = [v.upper().strip("() ") for v in vals]
        return letters[0] if len(letters) == 1 and letters[0] in config.OPTION_LETTERS else None
    if qtype == "integerQuestion":
        if len(vals) != 1:
            return None
        v = vals[0].replace(" ", "")
        return v if re.fullmatch(r"-?\d+(?:\.\d+)?", v) else None
    if qtype == "mcq":
        letters = sorted({v.upper().strip("() ") for v in vals})
        return letters if letters and all(l in config.OPTION_LETTERS for l in letters) else None
    return None


def validate_solve(data: dict | None, qtype: str) -> tuple[dict | None, str | None]:
    if data is None:
        return None, "no solve data"
    if set(data) != set(SOLVE_SCHEMA["required"]):
        return None, f"solve keys {sorted(data)}"
    if not data["solvable"]:
        return {"answer": None, "issue": data["issue"].strip() or "solver says not solvable as written",
                "final_value": data["final_value"], "method": data["method"]}, None
    ans = normalise_answer(qtype, data["answer"])
    if ans is None:
        return None, f"solve answer {data['answer']!r} is not a valid {qtype} answer"
    return {"answer": ans, "issue": data["issue"].strip(), "final_value": data["final_value"],
            "method": data["method"]}, None


def validate_classify(data: dict | None, qtype: str, report_ids: list[str],
                      repair_keys: list[str]) -> tuple[dict | None, str | None]:
    if data is None:
        return None, "no classifier data"
    if set(data) != set(classify_schema(repair_keys)["required"]):
        return None, f"classifier keys {sorted(data)}"
    got = [r.get("reportId") for r in data["reports"]]
    if sorted(got) != sorted(report_ids):
        return None, f"classifier reported on {got}, expected {report_ids}"
    for r in data["reports"]:
        if r["claim_type"] not in CLAIM_TYPES or r["claim_supported"] not in ("yes", "no", "unclear"):
            return None, f"classifier enum value out of range for {r['reportId']}"
    defects = []
    for d in data["candidate_defects"]:
        if d["repair"] not in repair_keys:
            return None, f"classifier proposed unknown repair {d['repair']!r}"
        # Answer-key values never come from the classifier: code derives them from the solves.
        if d["field"] == "answer":
            d = {**d, "find": "", "replace": ""}
        defects.append(d)
    out = dict(data)
    out["candidate_defects"] = defects
    out["solution_final"] = normalise_answer(qtype, data["solution_final_answer"])
    return out, None


def validate_reply(data: dict | None) -> tuple[str | None, str | None]:
    if data is None or not isinstance(data.get("reply"), str) or not data["reply"].strip():
        return None, "reply missing"
    return data["reply"].strip(), None
