"""Stage 12: student reply, written from the final Decision (after guards), never from the comment.

The reply writer sees a plain-language description of the outcome, the one step the student
missed (if any) and the comment only to match its language register. Its output must pass
guard 13 (engine/guards.py:reply_errors): 1–3 sentences, and no fix promised unless the route
is auto_apply. A rejected reply falls back to a fixed template from engine/config.py.
"""
from __future__ import annotations

from engine import config, llm
from engine.decision import Decision
from engine.guards import reply_errors
from engine.validate import REPLY_SCHEMA, validate_reply

SITUATION = {
    ("defect", "auto_apply"): "The student was right: the question had a real problem and it has been fixed now.",
    ("defect", "faculty_review"): "There may be a real problem; a teacher is checking it now. Nothing has been changed yet, so do not say it is fixed.",
    ("no_error", "no_change"): "The question and its answer are correct; the student made a mistake. Show the one step they missed.",
    ("no_error", "faculty_review"): "We could not finish checking automatically; a teacher will look at it. Do not say who is right.",
    ("not_actionable", "no_change"): "The comment did not say what is wrong and our checks found nothing. Invite them to say which part looks wrong.",
    ("not_actionable", "faculty_review"): "We could not finish checking automatically; a teacher will look at it.",
    ("display_issue", "no_change"): "The question content is correct; the problem is how it displays on their device or app.",
    ("app_issue", "no_change"): "The question is correct; the problem is app behaviour, which goes to the tech team.",
    ("language_mode", "no_change"): "They want the question in another language, which is not available for this question.",
    ("already_fixed", "no_change"): "They spotted a real problem, and it was already corrected after they reported it.",
}


def build_reply_input(d: Decision, report: dict) -> str:
    situation = SITUATION.get((d.verdict, d.route), SITUATION[("defect", "faculty_review")])
    step = d.missed_step if d.verdict == "no_error" and d.route == "no_change" else ""
    comment = (report.get("comment") or "").replace("<", "‹").replace(">", "›")
    return (
        f"<situation>{situation}</situation>\n"
        f"<step_they_missed>{step}</step_they_missed>\n"
        f"<untrusted_comment>{comment}</untrusted_comment>"
    )


def fallback_reply(d: Decision) -> str:
    tpl = config.REPLY_FALLBACK_TEMPLATES.get((d.verdict, d.route)) \
        or config.REPLY_FALLBACK_TEMPLATES[("defect", "faculty_review")]
    step = d.missed_step if d.verdict == "no_error" else ""
    with_step = tpl.format(step=step).strip()
    return with_step if not reply_errors(with_step, d.route) else tpl.format(step="").strip()


def write_reply(d: Decision, report: dict) -> tuple[str, str | None]:
    """→ (reply, problem). problem is set when the fallback template was used."""
    res = llm.call_json("reply", report["reportId"], build_reply_input(d, report), REPLY_SCHEMA,
                        fake=lambda: {"reply": fallback_reply(d)})
    reply, err = (None, res.error) if res.error else validate_reply(res.data)
    if reply is not None:
        errs = reply_errors(reply, d.route)
        if not errs:
            return reply, None
        err = "; ".join(errs)
    fb = fallback_reply(d)
    if reply_errors(fb, d.route):
        fb = config.REPLY_FALLBACK_TEMPLATES[("defect", "faculty_review")]
    return fb, f"reply fallback used ({err})"
