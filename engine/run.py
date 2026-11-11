"""Engine entry point: data → results.json (+ engine/out/run_record.json).

  python -m engine.run              live: cached responses reused, misses call the APIs
  python -m engine.run --offline    cache only; a miss becomes a validator error → faculty_review
  python -m engine.run --fake       stub LLM responses, writes engine/out/*.fake.json (plumbing test only)
  python -m engine.run --only QID   investigate one question (output files are not written)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from engine import config, llm
from engine.checks import run_question_checks, run_report_checks
from engine.classify import classify
from engine.decide import decide, investigate
from engine.guards import apply_guards
from engine.load import load_all, normalise_question
from engine.replies import write_reply
from engine.solve import solve_blind


def group_reports(reports: list[dict]) -> "OrderedDict[str, list[dict]]":
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for r in sorted(reports, key=lambda r: r["reportId"]):
        groups.setdefault(r["questionId"], []).append(r)
    return groups


def solve_roles() -> list[str]:
    # SOLVE_B_SCOPE "all": both solves on every reported question.
    return ["solve_a", "solve_b"] if config.SOLVE_B_SCOPE == "all" else ["solve_a"]


def run_question(q: dict, reps: list[dict], taxonomy: dict) -> list[tuple[dict, dict]]:
    nq = normalise_question(q)
    qchecks = run_question_checks(nq)
    solves = {role: solve_blind(nq, role) for role in solve_roles()}
    obs, obs_err = classify(nq, qchecks, solves, reps, taxonomy)
    inv = investigate(nq, qchecks, solves, obs, obs_err)
    out = []
    for rep in reps:
        rchecks = run_report_checks(nq, rep)
        ran = inv.ran_ids() | {c.id for c in rchecks}
        d = decide(inv, rep, rchecks, taxonomy)
        d = apply_guards(d, nq, taxonomy, qchecks, ran)
        reply, reply_problem = write_reply(d, rep)
        d.student_reply = reply
        if reply_problem:
            d.guard_log.append(f"G13 reply: {reply_problem}")
        g9 = [i for i, l in enumerate(d.guard_log) if l.startswith("G9 confidence: auto_apply")]
        later = g9 and any(not l.startswith("G13") for l in d.guard_log[g9[0] + 1:])
        record = {
            "reportId": rep["reportId"], "questionId": nq.id,
            "ran_ids": sorted(ran), "cited_checks": d.cited_checks, "proof": d.proof,
            "checks": [c.to_dict() for c in qchecks + rchecks],
            "solves": {r: (s if s else {"error": e}) for r, (s, e) in solves.items()},
            "classifier": obs if obs else {"error": obs_err},
            "flags": d.flags, "validator_errors": d.validator_errors, "guard_log": d.guard_log,
            "confidence": d.confidence,
            "route_before_confidence_guard": "auto_apply" if g9 and not later else d.route,
        }
        out.append((d.to_row(config.CONFIDENCE_DECIMALS), record))
    return out


def dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--fake", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--allow-errors", action="store_true",
                    help="write results.json even if some LLM calls failed (those rows go to faculty)")
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")   # API keys; .env is git-ignored
    llm.set_mode("fake" if a.fake else "offline" if a.offline else "live")

    qby, reports, taxonomy = load_all()
    groups = group_reports(reports)
    if a.only:
        groups = OrderedDict((k, v) for k, v in groups.items() if k == a.only)
    missing = [qid for qid in groups if qid not in qby]
    if missing:
        print("reports point at unknown questions:", missing)
        return 1

    with ThreadPoolExecutor(max_workers=1 if a.fake else config.MAX_WORKERS) as pool:
        futures = {qid: pool.submit(run_question, qby[qid], reps, taxonomy) for qid, reps in groups.items()}
        pairs = [p for qid in groups for p in futures[qid].result()]

    rows = sorted((r for r, _ in pairs), key=lambda r: r["reportId"])
    record = sorted((rec for _, rec in pairs), key=lambda r: r["reportId"])
    if a.only:
        print(dump(rows))
        return 0
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    errored = [rec["reportId"] for rec in record
               if any(not e.startswith("classifier supports") for e in rec["validator_errors"])]
    if a.fake:
        (config.OUT_DIR / "results.fake.json").write_text(dump(rows), encoding="utf-8")
        (config.OUT_DIR / "run_record.fake.json").write_text(dump(record), encoding="utf-8")
    elif errored and not a.allow_errors:
        # Keep the banked results.json intact: a run with failed LLM calls is written aside.
        (config.OUT_DIR / "results.partial.json").write_text(dump(rows), encoding="utf-8")
        (config.OUT_DIR / "run_record.partial.json").write_text(dump(record), encoding="utf-8")
        print(f"{len(errored)} reports had LLM errors (e.g. {errored[:3]}); results.json left untouched, "
              "output in engine/out/results.partial.json. Use --allow-errors to bank it anyway.")
        return 2
    else:
        config.RESULTS_PATH.write_text(dump(rows), encoding="utf-8")
        config.RUN_RECORD_PATH.write_text(dump(record), encoding="utf-8")
    from collections import Counter
    print(f"{len(rows)} rows · verdicts {dict(Counter(r['verdict'] for r in rows))} · "
          f"routes {dict(Counter(r['route'] for r in rows))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
