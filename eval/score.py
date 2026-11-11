"""Evaluation gate (docs/PLAN.md §4.3). Exits non-zero on any failure.

  python -m eval.score              hard asserts on results.json (+ accuracy gate if eval/labels.json exists)
  python -m eval.score --bank       ...and, if everything passes, save the accuracy numbers as eval/baseline.json
  python -m eval.score --sweep      print route accuracy / safety for candidate AUTO_APPLY_MIN_CONFIDENCE values
  python -m eval.score --repro      run the engine twice from cache and require byte-identical results.json

Hard asserts need no labels. The accuracy gate reads eval/labels.json, the candidate's own hand
labels; only this file reads it, and the gate asserts that engine/ never references it.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from engine import config
from engine.checks import is_canonical_mcq
from engine.decision import RESULT_KEYS
from engine.edits import count_matches, get_field, markup_errors, shape_errors
from engine.guards import answer_key_proof, reply_errors
from engine.load import load_all

ROOT = config.ROOT
LABELS = ROOT / "eval" / "labels.json"
BASELINE = ROOT / "eval" / "baseline.json"


class Gate:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passed = 0

    def check(self, ok: bool, msg: str) -> bool:
        if ok:
            self.passed += 1
        else:
            self.failures.append(msg)
        return ok


def hard_asserts(g: Gate) -> list[dict] | None:
    qby, reports, taxonomy = load_all()
    if not g.check(config.RESULTS_PATH.exists(), "results.json missing"):
        return None
    rows = json.loads(config.RESULTS_PATH.read_text(encoding="utf-8"))
    g.check(isinstance(rows, list), "results.json is not a JSON array")
    rep_by_id = {r["reportId"]: r for r in reports}
    ids = [r.get("reportId") for r in rows]
    g.check(len(rows) == len(reports), f"{len(rows)} rows, expected {len(reports)}")
    g.check(len(set(ids)) == len(ids), "duplicate reportIds")
    g.check(set(ids) == set(rep_by_id), f"reportIds differ from data/reports.json: "
            f"missing {sorted(set(rep_by_id) - set(ids))}, extra {sorted(set(ids) - set(rep_by_id))}")
    reported_qids = {r["questionId"] for r in reports}

    record = {}
    if config.RUN_RECORD_PATH.exists():
        record = {e["reportId"]: e for e in json.loads(config.RUN_RECORD_PATH.read_text(encoding="utf-8"))}
    g.check(bool(record), "engine/out/run_record.json missing or empty (evidence/proof checks need it)")

    verdicts, repairs = taxonomy["verdicts"], taxonomy["repairs"]
    for row in rows:
        rid = row.get("reportId", "?")
        p = f"{rid}:"
        if not g.check(set(row) == set(RESULT_KEYS), f"{p} keys {sorted(row)} != {sorted(RESULT_KEYS)}"):
            continue
        rep = rep_by_id.get(rid)
        if rep:
            g.check(row["questionId"] == rep["questionId"], f"{p} questionId does not match the report")
        g.check(row["questionId"] in reported_qids, f"{p} question has no report")
        q = qby.get(row["questionId"])
        if not g.check(q is not None, f"{p} unknown questionId"):
            continue
        v, r, e, route, conf = row["verdict"], row["repair"], row["edit"], row["route"], row["confidence"]
        g.check(v in verdicts, f"{p} verdict {v!r} not in taxonomy")
        g.check(route in config.ROUTES, f"{p} route {route!r} not allowed")
        g.check(isinstance(conf, (int, float)) and 0 <= conf <= 1, f"{p} confidence {conf!r} not in [0,1]")
        if v == "defect":
            g.check(r in repairs, f"{p} defect with repair {r!r} not in taxonomy")
            g.check(route != "no_change", f"{p} defect routed no_change")
        else:
            g.check(r is None, f"{p} non-defect has repair {r!r}")
            g.check(e is None, f"{p} non-defect has an edit")
            # faculty_review is allowed for a non-defect only as the validator fallback (AGENTS §7)
            g.check(route in ("no_change", "faculty_review"), f"{p} non-defect routed {route}")
            rec_ = record.get(rid)
            if route == "faculty_review" and rec_ is not None:
                g.check(bool(rec_.get("validator_errors")), f"{p} non-defect sent to faculty without a validator error")
        spec = repairs.get(r) if r else None
        if spec:
            if route == "auto_apply":
                g.check(spec["auto"], f"{p} auto_apply on auto:false repair {r}")
                g.check(not (r in config.SOLUTION_REPAIRS and not config.SOLUTION_REPAIRS_AUTO),
                        f"{p} auto_apply on {r} while SOLUTION_REPAIRS_AUTO is off")
                g.check(r != "type_mismatch", f"{p} auto_apply on type_mismatch")
                g.check(e is not None, f"{p} auto_apply without an edit")
                g.check(conf >= config.AUTO_APPLY_MIN_CONFIDENCE, f"{p} auto_apply below confidence threshold")
            if e is not None:
                g.check(e.get("field") in spec["fields"], f"{p} scope violation: {e.get('field')!r} not in {r}.fields")
            if r == "type_mismatch":
                g.check(e is None, f"{p} type_mismatch must have edit null")
        if e is not None:
            errs = shape_errors(e, q["questionType"])
            if g.check(not errs, f"{p} edit shape: {errs}"):
                stored = get_field(q, e["field"])
                g.check(count_matches(stored, e["find"], e["field"]) == 1, f"{p} find does not match exactly once")
                if e["field"] in ("question", "solution") and isinstance(stored, str):
                    m = markup_errors(stored, e["find"], e["replace"])
                    g.check(not m, f"{p} edit breaks markup: {m}")
                if q["questionType"] == "mcq" and e["field"] == "answer":
                    g.check(is_canonical_mcq(e["replace"]), f"{p} mcq replace not canonical")
        g.check(isinstance(row["evidence"], str) and row["evidence"].strip(), f"{p} empty evidence")
        rerrs = reply_errors(row["student_reply"], route)
        g.check(not rerrs, f"{p} reply: {rerrs}")

        rec = record.get(rid)
        if rec is not None:
            uncited = [c for c in rec.get("cited_checks", []) if c not in set(rec.get("ran_ids", []))]
            g.check(not uncited, f"{p} evidence cites checks that did not run: {uncited}")
            if r == "answer_key" and route == "auto_apply":
                proof = answer_key_proof(q["questionType"], rec.get("proof", {}), e)
                missing = [k for k in config.ANSWER_KEY_PROOF if not proof.get(k)]
                g.check(not missing, f"{p} answer_key auto_apply without proof: {missing}")

    # Engine never reads hand labels, never hardcodes report ids.
    for path in (ROOT / "engine").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        g.check("labels.json" not in src and "eval/labels" not in src, f"{path.name} references labels.json")
        g.check(re.search(r"['\"]R\d{3}['\"]", src) is None, f"{path.name} contains a hardcoded report id")
    return rows


def accuracy_gate(g: Gate, rows: list[dict], bank: bool) -> None:
    if not LABELS.exists():
        print("accuracy gate: eval/labels.json not present yet; skipped")
        return
    data = json.loads(LABELS.read_text(encoding="utf-8"))
    labels = {l["reportId"]: l for l in data.get("labels", []) if l.get("verdict")}
    by_id = {r["reportId"]: r for r in rows}
    metrics, misses = {}, []
    for key in ("verdict", "repair", "route"):
        hits = [rid for rid, l in labels.items() if rid in by_id and by_id[rid][key] == l.get(key)]
        metrics[key] = round(len(hits) / len(labels), 4) if labels else 0.0
        misses += [f"{rid} {key}: engine {by_id[rid][key]!r} vs label {labels[rid].get(key)!r}"
                   for rid in labels if rid in by_id and by_id[rid][key] != labels[rid].get(key)]
    print(f"accuracy vs {len(labels)} labels: " + ", ".join(f"{k} {v:.1%}" for k, v in metrics.items()))
    for m in misses:
        print("   miss", m)
    if BASELINE.exists():
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        for k, v in metrics.items():
            g.check(v >= base.get(k, 0), f"{k} accuracy {v:.1%} dropped below banked {base.get(k, 0):.1%}")
    if bank and not g.failures:
        BASELINE.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        print("banked eval/baseline.json")


def sweep() -> int:
    """Uses run_record's route before the confidence guard, so thresholds can be compared
    without rerunning the engine."""
    if not (LABELS.exists() and config.RUN_RECORD_PATH.exists()):
        print("sweep needs eval/labels.json and engine/out/run_record.json")
        return 1
    labels = {l["reportId"]: l for l in json.loads(LABELS.read_text(encoding="utf-8")).get("labels", []) if l.get("route")}
    record = json.loads(config.RUN_RECORD_PATH.read_text(encoding="utf-8"))
    for t in [x / 100 for x in range(50, 101, 5)]:
        hit = harmful = 0
        for e in record:
            pre, conf = e.get("route_before_confidence_guard"), e.get("confidence", 0)
            route = "faculty_review" if pre == "auto_apply" and conf < t else pre
            lab = labels.get(e["reportId"])
            if lab:
                hit += route == lab["route"]
                harmful += route == "auto_apply" and lab["route"] != "auto_apply"
        print(f"threshold {t:.2f}: route acc {hit}/{len(labels)}, auto_apply where label is not: {harmful}")
    return 0


def repro() -> int:
    outs = []
    for _ in range(2):
        r = subprocess.run([sys.executable, "-m", "engine.run", "--offline", "--allow-errors"], cwd=ROOT,
                           capture_output=True)
        if r.returncode != 0:
            print("engine run failed")
            return 1
        outs.append(config.RESULTS_PATH.read_bytes())
    same = outs[0] == outs[1]
    print("repro:", "byte-identical" if same else "DIFFERENT")
    return 0 if same else 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--repro", action="store_true")
    ap.add_argument("--fake", action="store_true", help="gate engine/out/*.fake.json (plumbing test, no labels)")
    a = ap.parse_args()
    if a.fake:
        config.RESULTS_PATH = config.OUT_DIR / "results.fake.json"
        config.RUN_RECORD_PATH = config.OUT_DIR / "run_record.fake.json"
    if a.sweep:
        return sweep()
    if a.repro:
        return repro()
    g = Gate()
    rows = hard_asserts(g)
    if rows is not None and not a.fake:
        accuracy_gate(g, rows, a.bank)
    print(f"{g.passed} checks passed, {len(g.failures)} failed")
    for f in g.failures:
        print("   FAIL", f)
    return 1 if g.failures else 0


if __name__ == "__main__":
    sys.exit(main())
