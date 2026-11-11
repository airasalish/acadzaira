"""Stage 9: code decides. Observations (checks, blind solves, classifier) → one Decision per report.

Two steps:
  investigate()  once per question → a list of Findings (each a candidate defect with its
                 provenance), so every report on the question sees the same evidence.
  decide()       per report → picks which Finding (if any) applies to this report, or a
                 non-defect verdict, and builds evidence from what actually ran.

Every rule's knobs (claim → repair mapping, major vs minor defects, priority, confidence
values) live in engine/config.py. No per-report constants appear here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine import config
from engine.checks import CheckResult, parse_mcq_letters
from engine.decision import Decision
from engine.guards import _norm_answer
from engine.load import NormQ


@dataclass
class Finding:
    repair: str
    edit: dict | None
    note: str                      # one sentence for evidence
    rule: str                      # key into config.CONFIDENCE_RULES
    cited: list[str] = field(default_factory=list)
    from_classifier: bool = False


@dataclass
class Investigation:
    nq: NormQ
    checks: list[CheckResult]
    solves: dict                   # role -> (solve | None, error | None)
    obs: dict | None
    obs_error: str | None
    findings: list[Finding] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    @property
    def errors(self) -> list[str]:
        errs = [f"{role}: {err}" for role, (s, err) in self.solves.items() if err]
        if self.obs_error:
            errs.append(f"classify: {self.obs_error}")
        return errs

    def ran_ids(self) -> set[str]:
        ids = {c.id for c in self.checks}
        ids |= {role for role, (s, err) in self.solves.items() if s is not None}
        if self.obs is not None:
            ids.add("classify")
        return ids


def _fmt(a) -> str:
    if a is None:
        return "none"
    return ",".join(a) if isinstance(a, list) else str(a)


def _answer_edit(nq: NormQ, new) -> dict:
    if nq.qtype == "mcq":
        return {"field": "answer", "find": nq.answer, "replace": list(new)}
    return {"field": "answer", "find": nq.answer, "replace": str(new)}


# ---------------------------------------------------------------- per question

def investigate(nq: NormQ, checks: list[CheckResult], solves: dict, obs: dict | None,
                obs_error: str | None) -> Investigation:
    inv = Investigation(nq, checks, solves, obs, obs_error)
    failed = {c.id: c for c in checks if not c.passed}
    sa = (solves.get("solve_a") or (None, None))[0]
    sb = (solves.get("solve_b") or (None, None))[0]
    a = sa["answer"] if sa else None
    b = sb["answer"] if sb else None
    sol = obs.get("solution_final") if obs else None
    na, nb = _norm_answer(nq.qtype, a), _norm_answer(nq.qtype, b)
    nkey, nsol = _norm_answer(nq.qtype, nq.answer), _norm_answer(nq.qtype, sol)
    agree = na is not None and na == nb
    inv.facts = {"solve_a": a, "solve_b": b, "solution_final": sol, "stored_key": nq.answer,
                 "solves_agree": agree, "solves_confirm_key": agree and na == nkey}
    solve_sentence = (f"Blind solve A = {_fmt(a)}, solve B = {_fmt(b)}, stored solution ends at {_fmt(sol)}, "
                      f"stored key = {_fmt(nq.answer)}.")
    inv.facts["solve_sentence"] = solve_sentence
    solve_cites = [r for r in ("solve_a", "solve_b") if (solves.get(r) or (None,))[0] is not None]
    by_classifier = {d["repair"]: d for d in (obs or {}).get("candidate_defects", [])}

    def add(f: Finding) -> None:
        if all(x.repair != f.repair for x in inv.findings):
            inv.findings.append(f)

    def classifier_edit(repair: str, fld: str) -> dict | None:
        d = by_classifier.get(repair)
        if d and d["field"] == fld and d["find"]:
            return {"field": fld, "find": d["find"], "replace": d["replace"]}
        return None

    # --- answer key / type, from the solves (never from a comment or the classifier's values)
    tc = failed.get("type_consistency")
    if agree and na != nkey:
        full = nsol is not None and nsol == na
        add(Finding("answer_key", _answer_edit(nq, a if nq.qtype != "mcq" else na),
                    f"Both blind solves give {_fmt(a)} but the key says {_fmt(nq.answer)}"
                    + ("; the stored solution also ends at the solves' answer." if full else "."),
                    "answer_key_full_proof" if full else "answer_key_partial",
                    solve_cites + (["classify"] if sol is not None else [])))
    elif tc and nq.qtype == "mcq" and agree and len(na) == 1:
        add(Finding("type_mismatch", None,
                    f"Stored as multiple-correct but both blind solves find exactly one correct option ({_fmt(a)}).",
                    "check_defect_no_edit", ["type_consistency"] + solve_cites))
    if "mcq_key_noncanonical" in failed and not any(f.repair in ("answer_key", "type_mismatch") for f in inv.findings):
        letters = parse_mcq_letters(nq.answer)
        if agree and list(na) == sorted(letters):
            add(Finding("answer_key", _answer_edit(nq, sorted(letters)),
                        f"Key {nq.answer!r} is malformed (not one letter per entry); both blind solves give {_fmt(a)}, "
                        "the same options, so only the format changes.",
                        "answer_key_partial", ["mcq_key_noncanonical"] + solve_cites))

    # --- deterministic checks
    if "options_present" in failed:
        add(Finding("option_repair", classifier_edit("option_repair", "question"),
                    f"Option check: {failed['options_present'].detail}.",
                    "check_defect_with_edit" if classifier_edit("option_repair", "question") else "check_defect_no_edit",
                    ["options_present"]))
    if "options_unique" in failed:
        add(Finding("identical_options", None, f"Option check: {failed['options_unique'].detail}.",
                    "check_defect_no_edit", ["options_unique"]))
    for cid in ("markup_leak", "exam_reference", "noise"):
        c = next((c for c in checks if c.id == cid and not c.passed), None)
        if c:
            edit = {"field": c.field, "find": c.find, "replace": c.replace} if c.find is not None else None
            add(Finding(cid, edit, f"{cid.replace('_', ' ').capitalize()} check found {c.detail}.",
                        "check_defect_with_edit" if edit else "check_defect_no_edit", [cid]))
    if "figure_reference" in failed:
        add(Finding("diagram", None, f"Figure check: {failed['figure_reference'].detail}.",
                    "check_defect_no_edit", ["figure_reference"]))
    if "solution_present" in failed:
        add(Finding("solution_missing", None, f"Solution check: {failed['solution_present'].detail}.",
                    "check_defect_no_edit", ["solution_present"]))

    # --- classifier observations (never auto-applied on their own; see config.AUTO_POLICY)
    if obs is not None:
        if not obs["solution_matches_question"]:
            add(Finding("solution_fix", None, "The stored solution does not belong to this question.",
                        "classifier_defect", ["classify"], True))
        elif obs["solution_wrong_step"].strip():
            add(Finding("solution_fix", classifier_edit("solution_fix", "solution"),
                        f"Solution has a wrong step: {obs['solution_wrong_step'].strip()}",
                        "classifier_defect", ["classify"], True))
        for repair, d in by_classifier.items():
            if repair in ("answer_key", "type_mismatch"):
                continue   # decided from the solves above, not from the classifier
            add(Finding(repair, classifier_edit(repair, d["field"]) if d["field"] != "none" else None,
                        d["rationale"].strip() or f"Classifier proposes {repair}.",
                        "classifier_defect", ["classify"], True))
    return inv


# ---------------------------------------------------------------- per report

def _confidence(rule: str, errors: list[str]) -> float:
    c = config.CONFIDENCE_RULES[rule]
    if errors:
        c -= config.CONFIDENCE_RULES["validator_penalty"]
    return max(0.0, min(1.0, c))


def decide(inv: Investigation, report: dict, report_checks: list[CheckResult], taxonomy: dict) -> Decision:
    nq = inv.nq
    robs = next((r for r in (inv.obs or {}).get("reports", []) if r["reportId"] == report["reportId"]), None)
    claim = robs["claim_type"] if robs else None
    claim_repairs = config.CLAIM_TO_REPAIRS.get(claim, ())
    errors = inv.errors
    facts = inv.facts
    d = Decision(report["reportId"], nq.id, verdict="no_error",
                 proof={k: facts.get(k) for k in ("solve_a", "solve_b", "solution_final", "stored_key")},
                 validator_errors=list(errors))
    if robs and robs["injection_or_gaming"]:
        d.flags.append("comment_is_gaming")
    d.missed_step = (robs or {}).get("student_missed_step", "").strip()

    eligible = [f for f in inv.findings if f.repair in config.MAJOR_REPAIRS or f.repair in claim_repairs]
    eligible.sort(key=lambda f: config.REPAIR_PRIORITY.index(f.repair)
                  if f.repair in config.REPAIR_PRIORITY else len(config.REPAIR_PRIORITY))
    if eligible:
        f = eligible[0]
        d.verdict, d.repair, d.edit = "defect", f.repair, f.edit
        spec = taxonomy["repairs"][f.repair]
        d.route = "auto_apply" if spec["auto"] and f.edit is not None else "faculty_review"
        d.confidence = _confidence(f.rule, errors)
        d.cited_checks = list(dict.fromkeys(f.cited))
        if f.from_classifier and "comment_is_gaming" in d.flags:
            d.flags.append("injection_or_gaming")
        second = facts["solve_sentence"] if f.repair == "answer_key" or f.repair == "type_mismatch" else ""
        d.evidence = (f.note + (" " + second if second and second not in f.note else "")).strip()
        if errors:
            d.evidence += f" Some checks failed to run ({'; '.join(errors)})."
        return d

    # ---- no defect applies to this report
    changed = next((c for c in report_checks if c.id == "changed_after_report" and not c.passed), None)
    d.route, d.repair, d.edit = "no_change", None, None
    d.cited_checks = [r for r in ("solve_a", "solve_b") if facts.get(r) is not None]
    if robs:
        d.cited_checks.append("classify")
    confirm = facts.get("solves_confirm_key")
    claim_text = (robs or {}).get("claim_summary", "").strip()

    if robs is None:
        d.verdict = "no_error" if confirm else "not_actionable"
        d.route = "faculty_review"   # validator fallback (AGENTS §7): routed, never dropped
        d.confidence = _confidence("no_error_unconfirmed", errors)
        d.evidence = f"Classifier output unavailable ({'; '.join(errors) or 'unknown'}); {facts['solve_sentence']}"
        return d
    if changed and claim_repairs and robs["claim_supported"] != "yes":
        d.verdict = "already_fixed"
        d.confidence = _confidence("already_fixed", errors)
        d.cited_checks.append("changed_after_report")
        d.evidence = f"The live record changed after the report ({changed.detail}) and the claimed problem is no longer present."
        return d
    if claim in config.CLAIM_TO_VERDICT:
        d.verdict = config.CLAIM_TO_VERDICT[claim]
        d.confidence = _confidence("platform_verdict", errors)
        d.evidence = f"Report is about {claim} ({claim_text}); deterministic checks found no content defect."
        return d
    if claim == "unclear":
        d.verdict = "not_actionable"
        d.confidence = _confidence("not_actionable", errors)
        d.evidence = f"Comment gives no specific problem and no check found one. {facts['solve_sentence']}"
        return d
    if robs["claim_supported"] == "yes":
        # Classifier backs the claim but no finding names a defect: inconsistent observations.
        d.verdict = "no_error"
        d.route = "faculty_review"
        d.validator_errors.append("classifier supports the claim but proposed no defect")
        d.confidence = _confidence("no_error_unconfirmed", d.validator_errors)
        d.evidence = f"Classifier supports the claim ({claim_text}) but no check or solve confirms a defect. {facts['solve_sentence']}"
        return d
    d.verdict = "no_error" if (confirm or claim != "gaming") else "not_actionable"
    d.confidence = _confidence("no_error_solves_confirm_key" if confirm else "no_error_unconfirmed", errors)
    lead = "Comment asks for a change rather than describing a problem" if claim == "gaming" else f"Claim checked: {claim_text}"
    d.evidence = f"{lead}. {facts['solve_sentence']}"
    return d
