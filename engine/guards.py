"""Stage 11: safety guards (AGENTS §7, docs/PLAN.md §4.2). Pure code.

Guards are downgrade-only. The two things a guard may do:
  * move route auto_apply -> faculty_review
  * drop an unsafe edit (edit -> null), which also forces faculty_review for a defect
They never upgrade a route, never change the verdict or repair, and never turn a defect
into no_change. Every action is logged in decision.guard_log, and the first downgrade
reason is appended to the evidence so a faculty member sees why it came to them.

Allowed fields and auto flags are read from data/taxonomy.json at call time, never copied.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from engine import config
from engine.checks import CheckResult, parse_mcq_letters
from engine.decision import Decision
from engine.edits import count_matches, get_field, markup_errors, shape_errors
from engine.load import NormQ, compact, mathml_to_text


class _Ctx:
    def __init__(self, d: Decision):
        self.d = d

    def downgrade(self, guard: str, reason: str) -> None:
        if self.d.route == "auto_apply":
            self.d.route = config.DOWNGRADE_TO
            self.d.guard_log.append(f"{guard}: auto_apply -> faculty_review ({reason})")
        else:
            self.d.guard_log.append(f"{guard}: {reason}")

    def drop_edit(self, guard: str, reason: str) -> None:
        if self.d.edit is not None:
            self.d.edit = None
            self.d.guard_log.append(f"{guard}: edit dropped ({reason})")
        if self.d.verdict == "defect" and self.d.route == "auto_apply":
            self.downgrade(guard, reason)


# ---------------------------------------------------------------- value helpers

def value_in_text(value: str, text: str) -> bool:
    """Does `value` (HTML/MathML allowed) occur in `text` once both are reduced to compact
    plain text? Numbers must not match inside longer numbers ('4' is not in '40')."""
    v = compact(mathml_to_text(value))
    t = compact(text)
    if not v:
        return False
    pat = re.escape(v)
    if v[0].isdigit() or v[0] == ".":
        pat = r"(?<![0-9.])" + pat
    if v[-1].isdigit():
        pat = pat + r"(?![0-9])"
    return re.search(pat, t) is not None


def _norm_answer(qtype: str, a: Any) -> Any:
    if a is None:
        return None
    if qtype == "mcq":
        return tuple(sorted(parse_mcq_letters(a))) or None
    if qtype == "integerQuestion":
        try:
            return float(str(a).strip())
        except ValueError:
            return None
    s = str(a).strip().upper()
    return s if s in config.OPTION_LETTERS else None


def answer_key_proof(qtype: str, proof: dict, edit: dict | None) -> dict[str, bool]:
    """Recompute the four answer_key conditions from raw values (never trust precomputed flags)."""
    a = _norm_answer(qtype, proof.get("solve_a"))
    b = _norm_answer(qtype, proof.get("solve_b"))
    sol = _norm_answer(qtype, proof.get("solution_final"))
    key = _norm_answer(qtype, proof.get("stored_key"))
    rep = _norm_answer(qtype, edit.get("replace")) if edit else None
    agree = a is not None and a == b
    return {
        "solves_agree": agree,
        "solves_match_solution": agree and sol is not None and a == sol,
        "solves_disagree_with_key": agree and a != key,
        "replace_equals_solves": agree and rep is not None and rep == a,
    }


# ---------------------------------------------------------------- the guards, in order

def apply_guards(decision: Decision, nq: NormQ, taxonomy: dict, checks: list[CheckResult],
                 ran_ids: set[str]) -> Decision:
    d = copy.deepcopy(decision)
    g = _Ctx(d)
    repairs = taxonomy["repairs"]
    rep = d.repair
    spec = repairs.get(rep) if rep else None

    if d.verdict != "defect":
        # Non-defects carry no edit and no route other than no_change; decide.py owns that.
        # A guard can only drop the edit here.
        if d.edit is not None:
            g.drop_edit("G0 non-defect", "non-defect verdict carries no edit")
        return d

    if spec is None:
        g.drop_edit("G0 taxonomy", f"repair {rep!r} not in taxonomy")
        g.downgrade("G0 taxonomy", f"repair {rep!r} not in taxonomy")
        return d

    # G1 scope: edit field must be one the repair may touch
    if d.edit is not None:
        allowed = spec["fields"]
        if not allowed or d.edit.get("field") not in allowed:
            g.drop_edit("G1 scope", f"field {d.edit.get('field')!r} not in {rep}.fields {allowed}")

    # G2 auto:false never auto-applies
    if not spec["auto"]:
        g.downgrade("G2 auto:false", f"{rep} needs faculty approval (taxonomy auto:false)")

    # G3 solution repairs switch
    if rep in config.SOLUTION_REPAIRS and not config.SOLUTION_REPAIRS_AUTO:
        g.downgrade("G3 solution repair", f"{rep} always goes to faculty (SOLUTION_REPAIRS_AUTO off)")

    # G4 value must be stated in the stored solution
    if rep in config.VALUE_FROM_SOLUTION_REPAIRS:
        if d.edit is None or not value_in_text(str(d.edit.get("replace", "")), nq.solution_text):
            g.downgrade("G4 value from solution", "replacement value not found in the stored solution")

    # G4b proof policy for the remaining auto:true repairs
    policy = config.AUTO_POLICY.get(rep)
    if policy == "faculty":
        g.downgrade("G4b policy", f"{rep} evidence would be the classifier alone")
    elif policy == "deterministic_check":
        cid = config.REPAIR_PROVING_CHECK.get(rep)
        proven = d.edit is not None and any(
            c.id == cid and not c.passed and c.field == d.edit.get("field") and c.find == d.edit.get("find")
            for c in checks
        )
        if not proven:
            g.downgrade("G4b policy", f"no deterministic {cid} check produced this exact edit")

    # G5 answer_key proof
    if rep == "answer_key":
        res = answer_key_proof(nq.qtype, d.proof, d.edit)
        missing = [k for k in config.ANSWER_KEY_PROOF if not res.get(k)]
        if missing:
            g.downgrade("G5 answer_key proof", "unmet: " + ", ".join(missing))

    # G6 type_mismatch
    if rep == "type_mismatch":
        if d.edit is not config.TYPE_MISMATCH_EDIT:
            g.drop_edit("G6 type_mismatch", "type_mismatch carries no edit")
        g.downgrade("G6 type_mismatch", "type change needs faculty")

    # G7 shape + match exactly once
    if d.edit is not None:
        errs = shape_errors(d.edit, nq.qtype)
        if errs:
            g.drop_edit("G7 shape", "; ".join(errs))
    if d.edit is not None:
        n = count_matches(get_field(nq.raw, d.edit["field"]), d.edit["find"], d.edit["field"])
        if n != 1:
            g.drop_edit("G7 match", f"find matches {n} times (needs exactly 1)")

    # G8 markup survives the edit
    if d.edit is not None and d.edit["field"] in ("question", "solution"):
        errs = markup_errors(get_field(nq.raw, d.edit["field"]), d.edit["find"], d.edit["replace"])
        if errs:
            g.drop_edit("G8 markup", "; ".join(errs))

    # A defect with no edit left cannot auto-apply.
    if d.edit is None and d.route == "auto_apply":
        g.downgrade("G7 no edit", "no valid edit to apply")

    # G9 calibrated confidence
    if d.confidence < config.AUTO_APPLY_MIN_CONFIDENCE:
        g.downgrade("G9 confidence", f"{d.confidence:.2f} < threshold {config.AUTO_APPLY_MIN_CONFIDENCE}")

    # G10 validator failures are routed, never dropped
    if d.validator_errors:
        g.downgrade("G10 validator", "; ".join(d.validator_errors))

    # G11 the comment is never an instruction
    if {"injection_or_gaming", "value_from_comment_only"} & set(d.flags):
        g.drop_edit("G11 comment-as-instruction", "edit value traces only to the student comment")

    # G12 evidence cites only checks that ran
    uncited = [c for c in d.cited_checks if c not in ran_ids]
    if uncited:
        g.downgrade("G12 evidence", "evidence names checks that did not run: " + ", ".join(uncited))

    _note_first_downgrade(d)
    return d


def _note_first_downgrade(d: Decision) -> None:
    first = next((l for l in d.guard_log if "auto_apply -> faculty_review" in l), None)
    if first:
        reason = first.split("(", 1)[-1].rstrip(")")
        d.evidence = (d.evidence.rstrip() + f" Sent to faculty: {reason}.").strip()


# ---------------------------------------------------------------- G13 reply check (used by replies.py)

_SENT = re.compile(r"[.!?]+(?:\s+|$)")


def reply_errors(reply: str, route: str) -> list[str]:
    errs = []
    text = (reply or "").strip()
    n = len([s for s in _SENT.split(text) if s.strip()])
    if not text:
        errs.append("empty reply")
    elif n > config.REPLY_MAX_SENTENCES:
        errs.append(f"{n} sentences (max {config.REPLY_MAX_SENTENCES})")
    if route != "auto_apply":
        for p in config.BANNED_REPLY_PHRASES_NON_AUTO:
            if re.search(r"\b" + re.escape(p) + r"\b", text, re.I):
                errs.append(f"promises a fix ('{p}') on route {route}")
    return errs
