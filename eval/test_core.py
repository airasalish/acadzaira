"""Unit tests for the deterministic core (parser, edits, guards, reply check).

Run: python -m eval.test_core      (plain asserts, no test framework needed)

Synthetic decisions only: no verdict here is a claim about any real report.
"""
from __future__ import annotations

import sys

from engine import config
from engine.checks import run_question_checks
from engine.decision import Decision
from engine.edits import count_matches, markup_errors, shape_errors
from engine.guards import apply_guards, reply_errors, value_in_text
from engine.load import load_all, normalise_question, split_options

QBY, REPORTS, TAX = load_all()


def nq(qid):
    return normalise_question(QBY[qid])


def guarded(d, q, threshold=0.9):
    old = config.AUTO_APPLY_MIN_CONFIDENCE
    config.AUTO_APPLY_MIN_CONFIDENCE = threshold
    try:
        checks = run_question_checks(q)
        return apply_guards(d, q, TAX, checks, {c.id for c in checks} | {"solve_a", "solve_b"})
    finally:
        config.AUTO_APPLY_MIN_CONFIDENCE = old


def test_parser():
    stem, opts = split_options("Assertion (A): x. Reason (R): y. (A) Both (B) Only A (C) Only R (D) None")
    assert stem.startswith("Assertion (A)") and opts["A"] == "Both" and opts["D"] == "None"
    _, opts = split_options("Q (A) 1 (B) 2 (C) (D) 4")
    assert opts["C"] == ""
    _, opts = split_options("Q (A) 1 (B) 2 (C) 3")
    assert "D" not in opts


def test_matching():
    assert count_matches("20", "2", "answer") == 0
    assert count_matches("B", "B", "answer") == 1
    assert count_matches(["", "B"], ["", "B"], "answer") == 1
    assert count_matches(["", "B"], ["B"], "answer") == 0
    assert count_matches("aXa aXa", "aXa", "question") == 2
    assert shape_errors({"field": "answer", "find": "['', 'B']", "replace": "['B']"}, "mcq")
    assert shape_errors({"field": "answer", "find": ["", "B"], "replace": ["A, B"]}, "mcq")
    assert not shape_errors({"field": "answer", "find": ["", "B"], "replace": ["A", "B"]}, "mcq")


def test_markup():
    html = '<h3><span style="x">a \\frac{7}{8} b</h3>'
    ok = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><mn>7</mn><mn>8</mn></mfrac></math>'
    assert not markup_errors(html, "\\frac{7}{8}", ok)
    assert markup_errors(html, 'style="x">a', "a")              # starts inside a tag
    assert markup_errors(html, "\\frac{7}{8}", "<math><mfrac><mn>7</mn></math>")  # bad MathML


def test_value_in_text():
    assert value_in_text("<math><mn>4</mn></math>", "so mu = 4 here")
    assert not value_in_text("4", "a force of 40 N")
    assert value_in_text("9 × 10", "9×10−2")


def test_guards():
    # auto:false repair can never auto-apply
    q = nq("6956d79788d7701e5617bc29")
    d = guarded(Decision("X1", q.id, "defect", "identical_options", None, "auto_apply", 0.99), q)
    assert d.route == "faculty_review"

    # deterministic exam tag edit survives every guard when confidence clears the threshold
    q = nq("617fa18efd53ff1629ed890f")
    edit = {"field": "question", "find": "(NEET 2019) ", "replace": ""}
    d = guarded(Decision("X2", q.id, "defect", "exam_reference", edit, "auto_apply", 0.95,
                         cited_checks=["exam_reference"]), q)
    assert d.route == "auto_apply" and d.edit == edit, d.guard_log
    # ...and is downgraded below the threshold, and at the shipped default (nothing auto yet)
    assert guarded(Decision("X3", q.id, "defect", "exam_reference", edit, "auto_apply", 0.5), q).route == "faculty_review"
    assert guarded(Decision("X3", q.id, "defect", "exam_reference", edit, "auto_apply", 0.99), q,
                   threshold=config.AUTO_APPLY_MIN_CONFIDENCE).route == "faculty_review"

    # scope: an exam_reference edit may not touch the answer
    bad = {"field": "answer", "find": "D", "replace": "A"}
    d = guarded(Decision("X4", q.id, "defect", "exam_reference", bad, "auto_apply", 0.99), q)
    assert d.edit is None and d.route == "faculty_review"

    # answer_key needs both solves + solution to agree against the key
    proof = {"solve_a": "A", "solve_b": "A", "solution_final": "A", "stored_key": q.answer}
    akey = {"field": "answer", "find": q.answer, "replace": "A"}
    d = guarded(Decision("X5", q.id, "defect", "answer_key", akey, "auto_apply", 0.99, proof=proof), q)
    assert d.route == "auto_apply", d.guard_log
    d = guarded(Decision("X6", q.id, "defect", "answer_key", akey, "auto_apply", 0.99,
                         proof={**proof, "solve_b": "B"}), q)
    assert d.route == "faculty_review"
    # comment-sourced value never becomes an edit
    d = guarded(Decision("X7", q.id, "defect", "answer_key", akey, "auto_apply", 0.99, proof=proof,
                         flags=["value_from_comment_only"]), q)
    assert d.edit is None and d.route == "faculty_review"

    # type_mismatch: edit null, faculty
    q = nq("68f21caf941cda588bc04365")
    d = guarded(Decision("X8", q.id, "defect", "type_mismatch",
                         {"field": "answer", "find": ["", "B"], "replace": ["B"]}, "auto_apply", 0.99), q)
    assert d.edit is None and d.route == "faculty_review"

    # solution repairs never auto while the switch is off
    d = guarded(Decision("X9", q.id, "defect", "solution_fix",
                         {"field": "solution", "find": "x", "replace": "y"}, "auto_apply", 0.99), q)
    assert d.route == "faculty_review"

    # evidence citing a check that never ran
    d = guarded(Decision("X10", q.id, "defect", "spelling", None, "faculty_review", 0.99,
                         cited_checks=["made_up_check"]), q)
    assert any("G12" in l for l in d.guard_log)


def test_replies():
    assert reply_errors("Thanks! A teacher is checking this now.", "faculty_review") == []
    assert reply_errors("Thanks, we fixed it.", "faculty_review")
    assert not reply_errors("You're right, it's fixed now. Thanks!", "auto_apply")
    assert reply_errors("One. Two. Three. Four.", "no_change")
    assert not reply_errors("mu = 0.4 is close. Check step 2. Thanks!", "no_change")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print("ok  ", t.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL", t.__name__, e)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
