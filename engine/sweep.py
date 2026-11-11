"""Stage 15 (bonus): checks + both blind solves on questions nobody reported.

Output goes to eval/unreported_candidates.json for review, never into results.json.
Findings worth listing are then written up in docs/UNREPORTED.md after a human check.

  python -m engine.sweep [--offline | --fake]
"""
from __future__ import annotations

import argparse
import json
import sys

from engine import config, llm
from engine.checks import run_question_checks
from engine.guards import _norm_answer
from engine.load import load_all, normalise_question
from engine.run import solve_roles
from engine.solve import solve_blind

OUT = config.ROOT / "eval" / "unreported_candidates.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
    llm.set_mode("fake" if a.fake else "offline" if a.offline else "live")
    qby, reports, _ = load_all()
    reported = {r["questionId"] for r in reports}
    out = []
    for qid, q in qby.items():
        if qid in reported:
            continue
        nq = normalise_question(q)
        checks = run_question_checks(nq)
        solves = {role: solve_blind(nq, role) for role in solve_roles()}
        answers = [_norm_answer(nq.qtype, s["answer"]) for s, _ in solves.values() if s]
        key = _norm_answer(nq.qtype, nq.answer)
        out.append({
            "questionId": qid, "questionType": nq.qtype,
            "failed_checks": [c.to_dict() for c in checks if not c.passed],
            "solves": {r: (s if s else {"error": e}) for r, (s, e) in solves.items()},
            "solves_agree_against_key": len(answers) == 2 and answers[0] == answers[1] and answers[0] != key,
        })
    target = OUT.with_name("unreported_candidates.fake.json") if a.fake else OUT
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=list) + "\n", encoding="utf-8")
    print(f"{len(out)} unreported questions swept → {target.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
