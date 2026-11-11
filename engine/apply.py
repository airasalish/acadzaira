"""Apply an approved change set to the question data (the "Fix" half of Report -> Fix).

The console exports `acadza-approved-changes.json`: the edits a teacher approved or edited.
This tool applies them to a COPY of data/questions.json. It never edits the organiser data,
and it is not connected to any production system.

  python -m engine.apply path/to/acadza-approved-changes.json
      -> engine/out/questions.fixed.json   (patched copy)
      -> engine/out/apply_report.json      (what was applied or refused, and why)

Every change goes through the same checks as engine output (engine/edits.py + taxonomy):
field allowed for the repair type, auto:false repairs carry no edit, edit shape valid, `find`
matches the stored value exactly once, markup still valid afterwards. A change that fails any
check is refused and reported; nothing is applied silently.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from engine import config
from engine.edits import apply_edit, count_matches, get_field, markup_errors, shape_errors
from engine.load import load_all


def check_change(q: dict, change: dict, taxonomy: dict) -> list[str]:
    """Reasons this change must not be applied to question q (empty list = safe to apply)."""
    repair = change.get("repair")
    spec = taxonomy["repairs"].get(repair)
    if spec is None:
        return [f"unknown repair type {repair!r}"]
    edit = {"field": change.get("field"), "find": change.get("find"), "replace": change.get("replace")}
    if edit["field"] not in spec["fields"]:
        return [f"field {edit['field']!r} is outside {repair}.fields {spec['fields']}"]
    if repair == "type_mismatch":
        return ["type_mismatch carries no edit; it needs a manual change"]
    errs = shape_errors(edit, q["questionType"])
    if errs:
        return errs
    stored = get_field(q, edit["field"])
    n = count_matches(stored, edit["find"], edit["field"])
    if n != 1:
        return [f"find matches {n} times in the current record (needs exactly 1)"]
    if edit["field"] in ("question", "solution"):
        errs = markup_errors(stored, edit["find"], edit["replace"])
        if errs:
            return errs
    return []


def apply_changes(questions: dict, changes: list[dict], taxonomy: dict) -> tuple[dict, list[dict]]:
    """Return (patched copy of questions, report). One edit per question+field: reports on the
    same question usually carry the same edit, so an identical repeat is skipped, not an error."""
    patched = copy.deepcopy(questions)
    report, done = [], {}
    for ch in changes:
        qid = ch.get("questionId")
        entry = {"reportId": ch.get("reportId"), "questionId": qid, "repair": ch.get("repair"),
                 "field": ch.get("field"), "decidedBy": ch.get("decidedBy")}
        q = patched.get(qid)
        if q is None:
            report.append({**entry, "status": "refused", "reasons": ["unknown questionId"]})
            continue
        spec = taxonomy["repairs"].get(ch.get("repair"))
        if spec is None or ch.get("field") not in spec["fields"]:
            report.append({**entry, "status": "refused",
                           "reasons": [f"field {ch.get('field')!r} is not allowed for repair {ch.get('repair')!r}"]})
            continue
        key = (qid, ch.get("field"))
        if key in done:
            same = done[key] == ch.get("replace")
            report.append({**entry, "status": "already_applied" if same else "refused",
                           "reasons": [] if same else ["conflicts with an earlier change to the same field"]})
            continue
        reasons = check_change(q, ch, taxonomy)
        if reasons:
            report.append({**entry, "status": "refused", "reasons": reasons})
            continue
        edit = {"field": ch["field"], "find": ch["find"], "replace": ch["replace"]}
        patched[qid] = apply_edit(q, edit)
        done[key] = ch.get("replace")
        report.append({**entry, "status": "applied", "reasons": []})
    return patched, report


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    changes = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not isinstance(changes, list):
        print("change set must be a JSON array")
        return 2
    questions, _, taxonomy = load_all()
    patched, report = apply_changes(questions, changes, taxonomy)
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (config.OUT_DIR / "questions.fixed.json").write_text(
        json.dumps(list(patched.values()), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (config.OUT_DIR / "apply_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = {s: sum(r["status"] == s for r in report) for s in ("applied", "already_applied", "refused")}
    print(f"{len(changes)} changes: {counts} -> engine/out/questions.fixed.json")
    for r in report:
        if r["status"] == "refused":
            print(f"   refused {r['reportId']}: {'; '.join(r['reasons'])}")
    return 1 if counts["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
