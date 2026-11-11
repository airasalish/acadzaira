"""Stage 4: deterministic checks (no LLM). Every result goes into the run record, and evidence
strings may only cite check ids that ran for that report (guard 12).

`passed=True` means the check found nothing wrong. A failed check is evidence, not a verdict:
engine/decide.py combines checks with the blind solves and the classifier's observations.

Where a check can name an exact, surgical fix (an exam tag, a stray label, a simple LaTeX
leak), it attaches a suggested `find`/`replace` on the raw stored field. The suggestion is
still validated by engine/edits.py and engine/guards.py before it can reach results.json.

Run `python -m engine.checks` to print every failed check over all 43 questions.
"""
from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass
from typing import Any

from engine import config
from engine.load import NormQ, compact, load_all, mathml_to_text, normalise_question, text_without_math


@dataclass
class CheckResult:
    id: str
    passed: bool
    detail: str = ""
    field: str | None = None      # stored field the finding is in (question / solution / answer)
    find: Any = None              # suggested surgical edit, if the check can name one exactly
    replace: Any = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------- helpers

def parse_mcq_letters(value: Any) -> list[str]:
    """Option letters a stored mcq key refers to, however it is formatted
    (`['A','B']`, `['A, B, D']`, `['', 'B']`). Used for comparison only, never written."""
    items = value if isinstance(value, list) else [value]
    letters: list[str] = []
    for item in items:
        for tok in re.split(r"[\s,;/]+", str(item or "")):
            tok = tok.strip().upper()
            if tok in config.OPTION_LETTERS and tok not in letters:
                letters.append(tok)
    return letters


def is_canonical_mcq(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(v, str) and v in config.OPTION_LETTERS for v in value)
        and len(set(value)) == len(value)
    )


def _locate(raw: str, snippet: str) -> str | None:
    """Return a find-string for `snippet` in the raw field if it occurs exactly once
    (preferring to also swallow one adjacent space so the removal leaves no double space)."""
    for cand in (snippet + " ", " " + snippet, snippet):
        if raw.count(cand) == 1:
            return cand
    return None


_FRAC = re.compile(r"\\d?frac\s*\{\s*([0-9A-Za-z]+)\s*\}\s*\{\s*([0-9A-Za-z]+)\s*\}")


def _tok(x: str) -> str:
    return f"<mn>{x}</mn>" if x.isdigit() else f"<mi>{x}</mi>"


def latex_to_mathml(snippet: str) -> str | None:
    """Deterministic conversion for the one LaTeX shape we can convert safely: a single
    \\frac{a}{b} with plain number/identifier arguments. Anything else → None (no suggestion)."""
    m = _FRAC.fullmatch(snippet.strip())
    if not m:
        return None
    a, b = m.groups()
    return (
        '<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">'
        f"<mfrac>{_tok(a)}{_tok(b)}</mfrac></math>"
    )


# ---------------------------------------------------------------- question-level checks

def check_options_present(nq: NormQ) -> CheckResult | None:
    if nq.qtype not in ("scq", "mcq"):
        return None
    missing = [l for l in config.OPTION_LETTERS if l not in nq.options]
    blank = [l for l, t in nq.options.items() if not t.strip()]
    if not missing and not blank:
        return CheckResult("options_present", True, "options A–D present and non-empty")
    parts = []
    if missing:
        parts.append("missing option(s) " + ", ".join(missing))
    if blank:
        parts.append("blank option(s) " + ", ".join(blank))
    return CheckResult("options_present", False, "; ".join(parts), field="question")


def check_options_unique(nq: NormQ) -> CheckResult | None:
    if nq.qtype not in ("scq", "mcq"):
        return None
    seen: dict[str, str] = {}
    dups = []
    for letter, text in nq.options.items():
        key = compact(text)
        if not key:
            continue
        if key in seen:
            dups.append(f"{seen[key]} = {letter} ('{text}')")
        else:
            seen[key] = letter
    if dups:
        return CheckResult("options_unique", False, "identical options: " + "; ".join(dups), field="question")
    return CheckResult("options_unique", True, "no two options identical")


def _pattern_check(nq: NormQ, check_id: str, patterns: list[str], text_fn, flags=re.I) -> list[CheckResult]:
    out = []
    found_any = False
    for fld, raw in (("question", nq.question_html), ("solution", nq.solution_html)):
        text = text_fn(raw)
        taken: list[tuple[int, int]] = []   # spans already reported by an earlier, more specific pattern
        for pat in patterns:
            for m in re.finditer(pat, text, flags | re.M):
                if any(m.start() < e and s < m.end() for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                found_any = True
                snippet = m.group(0).strip()
                find = _locate(raw, snippet)
                replace = None
                if find is not None:
                    if check_id == "markup_leak":
                        conv = latex_to_mathml(snippet)
                        replace = None if conv is None else find.replace(snippet, conv)
                        if replace is None:
                            find = None
                    else:
                        replace = ""
                detail = f"'{snippet}' in {fld}"
                if find is None:
                    detail += " (no unique surgical edit derivable in code)"
                out.append(CheckResult(check_id, False, detail, field=fld, find=find, replace=replace))
    if not found_any:
        out.append(CheckResult(check_id, True, f"no {check_id.replace('_', ' ')} found in question or solution"))
    return out


def check_exam_reference(nq: NormQ) -> list[CheckResult]:
    return _pattern_check(nq, "exam_reference", config.EXAM_TAG_PATTERNS, mathml_to_text)


def check_noise(nq: NormQ) -> list[CheckResult]:
    return _pattern_check(nq, "noise", config.NOISE_PATTERNS, mathml_to_text)


def check_markup_leak(nq: NormQ) -> list[CheckResult]:
    # LaTeX is case-sensitive (\Delta vs \delta), so no IGNORECASE here.
    return _pattern_check(nq, "markup_leak", config.MARKUP_LEAK_PATTERNS, text_without_math, flags=0)


def check_answer_shape(nq: NormQ) -> CheckResult:
    a = nq.answer
    if nq.qtype == "scq":
        ok = isinstance(a, str) and a in config.OPTION_LETTERS
        return CheckResult("answer_shape", ok, f"scq key {a!r}" + ("" if ok else " is not one option letter"), field="answer")
    if nq.qtype == "integerQuestion":
        ok = isinstance(a, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", a.strip() or "x") is not None
        return CheckResult("answer_shape", ok, f"integer key {a!r}" + ("" if ok else " is not numeric"), field="answer")
    if nq.qtype == "mcq":
        if is_canonical_mcq(a):
            return CheckResult("answer_shape", True, f"mcq key {a!r} is a list of single letters", field="answer")
        return CheckResult(
            "mcq_key_noncanonical", False,
            f"mcq key {a!r} is not a list of single option letters (reads as {parse_mcq_letters(a)})",
            field="answer",
        )
    return CheckResult("answer_shape", False, f"unknown questionType {nq.qtype!r}", field="answer")


def check_key_option_present(nq: NormQ) -> CheckResult | None:
    """The keyed option(s) must exist and be non-blank."""
    if nq.qtype not in ("scq", "mcq"):
        return None
    letters = [nq.answer] if nq.qtype == "scq" else parse_mcq_letters(nq.answer)
    bad = [l for l in letters if not (nq.options.get(l) or "").strip()]
    if bad:
        return CheckResult("key_option_present", False, f"key points at missing/blank option(s) {', '.join(bad)}", field="answer")
    return CheckResult("key_option_present", True, f"keyed option(s) {', '.join(letters) or '-'} present")


def check_type_consistency(nq: NormQ) -> CheckResult | None:
    """Number of keyed options vs the stored type. Evidence for a type_mismatch investigation only."""
    if nq.qtype == "mcq":
        n = len(parse_mcq_letters(nq.answer))
        if n <= 1:
            return CheckResult("type_consistency", False, f"stored as mcq but key marks {n} option(s)", field="answer")
        return CheckResult("type_consistency", True, f"mcq key marks {n} options")
    if nq.qtype == "scq":
        n = len(parse_mcq_letters(nq.answer))
        if n != 1:
            return CheckResult("type_consistency", False, f"stored as scq but key marks {n} option(s)", field="answer")
        return CheckResult("type_consistency", True, "scq key marks 1 option")
    return None


def check_figure_reference(nq: NormQ) -> CheckResult:
    mentions = re.search(config.FIGURE_WORDS, nq.question_text, re.I)
    if mentions and not nq.ques_images:
        return CheckResult("figure_reference", False, f"question mentions '{mentions.group(0)}' but has no image", field="question")
    return CheckResult("figure_reference", True, "no figure referenced without an image")


def check_solution_present(nq: NormQ) -> CheckResult:
    n = len(nq.solution_text)
    if n < 15 and not nq.solution_images:
        return CheckResult("solution_present", False, f"solution has {n} characters of text and no image", field="solution")
    return CheckResult("solution_present", True, f"solution present ({n} characters)")


def run_question_checks(nq: NormQ) -> list[CheckResult]:
    results: list[CheckResult] = []
    for fn in (check_options_present, check_options_unique, check_answer_shape, check_key_option_present,
               check_type_consistency, check_figure_reference, check_solution_present):
        r = fn(nq)
        if r is not None:
            results.append(r)
    for fn in (check_exam_reference, check_noise, check_markup_leak):
        results.extend(fn(nq))
    return results


# ---------------------------------------------------------------- report-level checks

def check_changed_after_report(nq: NormQ, report: dict) -> CheckResult:
    """The live record changed after the student reported. Signal for already_fixed only:
    decide.py must also find the reported problem absent before using that verdict."""
    rep_at = report.get("reportedAt") or ""
    later = [h for h in nq.error_history if (h.get("at") or "") > rep_at]
    upd = nq.updated_at > rep_at
    if later:
        notes = "; ".join(f"{h.get('type')} at {h.get('at')}: {h.get('note')}" for h in later)
        return CheckResult("changed_after_report", False, f"errorHistory after report ({rep_at}): {notes}")
    if upd:
        return CheckResult("changed_after_report", False, f"record updatedAt {nq.updated_at} is after reportedAt {rep_at}")
    return CheckResult("changed_after_report", True, f"no change to the record after reportedAt {rep_at}")


def run_report_checks(nq: NormQ, report: dict) -> list[CheckResult]:
    return [check_changed_after_report(nq, report)]


# ---------------------------------------------------------------- CLI

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    qby, reports, _ = load_all()
    reported = {r["questionId"] for r in reports}
    for qid, q in qby.items():
        nq = normalise_question(q)
        fails = [r for r in run_question_checks(nq) if not r.passed]
        fails += [c for r in reports if r["questionId"] == qid for c in run_report_checks(nq, r) if not c.passed]
        if fails:
            tag = "" if qid in reported else "  [UNREPORTED]"
            print(f"{qid} {nq.qtype}{tag}")
            for f in fails:
                edit = f"  edit: {f.find!r} -> {f.replace!r}" if f.find is not None else ""
                print(f"   ✘ {f.id}: {f.detail}{edit}")


if __name__ == "__main__":
    main()
