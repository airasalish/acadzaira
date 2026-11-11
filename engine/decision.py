"""The single Decision object per report. verdict, repair, edit, route, confidence, evidence
and the student reply all come from this one object (AGENTS §7: no field drift)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RESULT_KEYS = ("reportId", "questionId", "verdict", "repair", "edit", "route",
               "confidence", "evidence", "student_reply")


@dataclass
class Decision:
    report_id: str
    question_id: str
    verdict: str
    repair: str | None = None
    edit: dict | None = None
    route: str = "no_change"
    confidence: float = 0.0
    evidence: str = ""
    student_reply: str = ""
    # Provenance — kept in engine/out/run_record.json, never in results.json.
    cited_checks: list[str] = field(default_factory=list)   # check ids / solve roles the evidence names
    proof: dict[str, Any] = field(default_factory=dict)     # solve_a, solve_b, solution_final, stored_key
    flags: list[str] = field(default_factory=list)          # e.g. injection_or_gaming, value_from_comment_only
    validator_errors: list[str] = field(default_factory=list)
    guard_log: list[str] = field(default_factory=list)
    missed_step: str = ""                                   # classifier's "one step the student missed"

    def to_row(self, decimals: int = 2) -> dict:
        return {
            "reportId": self.report_id,
            "questionId": self.question_id,
            "verdict": self.verdict,
            "repair": self.repair,
            "edit": self.edit,
            "route": self.route,
            "confidence": round(float(self.confidence), decimals),
            "evidence": self.evidence,
            "student_reply": self.student_reply,
        }
