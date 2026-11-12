"""Every engine rule that is not in data/taxonomy.json lives here.

taxonomy.json (organiser file, never edited by code) is the only source for verdict keys,
repair keys, each repair's allowed `fields` and its `auto` flag. Everything else — thresholds,
proof policies, switches, patterns, models — is a named setting below, so a requirement
changed live is a one-line edit here (docs/PLAN.md §3).

Values marked PENDING are open choices in docs/PLAN.md §7; values marked TODO are numbers
that can only be measured after the engine has run.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "engine" / "out"
CACHE_PATH = ROOT / "engine" / ".cache" / "llm_cache.json"
USAGE_LOG = ROOT / "eval" / "usage.jsonl"
RESULTS_PATH = ROOT / "results.json"
RUN_RECORD_PATH = OUT_DIR / "run_record.json"
PROMPTS_DIR = ROOT / "prompts"

ROUTES = ("auto_apply", "faculty_review", "no_change")
# Guards make exactly one kind of route change: auto_apply -> faculty_review (plus dropping an edit).
# They never upgrade a route and never turn a defect into no_change.
DOWNGRADE_TO = "faculty_review"

# ---------------------------------------------------------------- confidence
# TODO: calibrated on the candidate's labels with `python -m eval.score --sweep`, typed in by hand.
# Until then nothing may auto-apply: a threshold above 1 makes guard 9 downgrade every auto_apply.
AUTO_APPLY_MIN_CONFIDENCE = 1.01
CONFIDENCE_DECIMALS = 2

# ---------------------------------------------------------------- auto-apply policy (settled 10 Nov)
# Solution repairs never auto-apply while this switch is off (guard 3).
SOLUTION_REPAIRS_AUTO = False
SOLUTION_REPAIRS = ("solution_fix", "solution_missing")

# auto_apply only when code finds the replacement value in the stored solution's
# MathML-stripped text (guard 4).
VALUE_FROM_SOLUTION_REPAIRS = ("option_repair", "stem_data")

# type_mismatch: verdict defect, repair type_mismatch, edit null, always faculty (guard 6).
TYPE_MISMATCH_ROUTE = "faculty_review"
TYPE_MISMATCH_EDIT = None

# answer_key auto_apply needs every one of these (guard 5, AGENTS §7).
ANSWER_KEY_PROOF = (
    "solves_agree",              # solve A answer == solve B answer
    "solves_match_solution",     # agreed answer == stored solution's final answer
    "solves_disagree_with_key",  # agreed answer != stored key
    "replace_equals_solves",     # edit.replace == agreed answer (never a comment-only value)
)

# Proof policy for the remaining auto:true repairs (guard 4b).
#   "deterministic_check": auto only if a code check in engine/checks.py found the problem
#   "faculty":             never auto (evidence would be the classifier alone)
# Settled 10 Nov (docs/PLAN.md §7 A): classifier-only evidence never auto-applies.
AUTO_POLICY = {
    "noise": "deterministic_check",
    "exam_reference": "deterministic_check",
    "markup_leak": "deterministic_check",
    "spelling": "faculty",
    "notation": "faculty",
    "answer_form": "faculty",
}
# Which deterministic check id proves which repair, for the "deterministic_check" policy.
REPAIR_PROVING_CHECK = {
    "noise": "noise",
    "exam_reference": "exam_reference",
    "markup_leak": "markup_leak",
}

# ---------------------------------------------------------------- multiple-choice key format (settled)
OPTION_LETTERS = ("A", "B", "C", "D")
# Canonical mcq key: a list of single option letters, no empties, no duplicates.

# ---------------------------------------------------------------- deterministic check patterns
EXAM_TAG_PATTERNS = [
    r"\(\s*(?:JEE|NEET|AIPMT|AIIMS|IIT|JIPMER|BITSAT|CBSE|KCET|MHT[- ]?CET|EAMCET|WBJEE)[^()]{0,40}?(?:19|20)\d{2}[^()]{0,20}\)",
    r"\[\s*(?:JEE|NEET|AIPMT|AIIMS|IIT)[^\[\]]{0,40}?(?:19|20)\d{2}[^\[\]]{0,20}\]",
]
NOISE_PATTERNS = [
    r"space\s+for\s+rough\s+work",
    r"^\s*Q\.?\s*\d{1,3}\s*[.):]",          # leading question number
    r"^\s*\d{1,3}\s*[.)]\s+(?=[A-Z])",       # leading "12. " numbering
    r"\b(?:source|ref(?:erence)?)\s*:\s*\S+",
]
MARKUP_LEAK_PATTERNS = [
    r"\\d?frac\s*\{[^{}]*\}\s*\{[^{}]*\}",     # whole \frac{a}{b} first, so the fix can convert it
    r"\\(?:frac|dfrac|sqrt|times|cdot|alpha|beta|gamma|theta|lambda|mu|pi|omega|Delta|delta|vec|hat|left|right|text|mathrm|circ|pm|le|ge|neq|infty)\b",
    r"\$[^$\n]{1,80}\$",
    r"&lt;/?[a-zA-Z][^&]{0,40}&gt;",
    r"&amp;(?:nbsp|lt|gt|amp);",
    r"</?(?:span|div|sup|sub|br|p)\b[^>]*>",   # applied to text, i.e. tags shown as text
]
# Words that, in a stem without images, suggest a figure the student cannot see.
FIGURE_WORDS = r"\b(?:figure|fig\.|diagram|shown\s+(?:in|below|above)|as\s+shown)\b"

# ---------------------------------------------------------------- replies
REPLY_MAX_SENTENCES = 3
BANNED_REPLY_PHRASES_NON_AUTO = (
    "fixed", "corrected", "updated", "has been changed", "we changed", "we've changed",
)

# ---------------------------------------------------------------- LLM (free providers, switched 10 Nov)
# Gemini: solve A, classifier, reply writer. Groq: solve B only (a different provider, so the
# two blind solves stay independent). Both are called through their OpenAI-compatible
# endpoints with the `openai` SDK; keys come from .env.
PROVIDERS = {
    "solve_a": "gemini",
    "solve_b": "groq",
    "classify": "groq",   # moved 11 Nov: Gemini free tier overloaded (503); solves stay split
    "reply": "groq",
}
# Providers used from cache only: a cache miss becomes a routed error instead of a live call.
# Gemini is here because its free tier stalled the 11 Nov run; cached solve A results still count.
CACHE_ONLY_PROVIDERS = {"gemini"}
# 12 Nov: Gemini's free daily quota is used up, so solve A falls back to a second Groq model of a
# different family from solve B's. Cached Gemini solves are kept. Trade-off, decided by the
# candidate: on fallback questions both solves run on one provider (two different models), which
# is weaker independence than the Gemini + Groq split. The run record names the model per solve.
# The classifier and reply writer fall back to the same second model when the main Groq model's
# free daily token allowance (200,000 tokens) is used up. They only describe and phrase; code decides.
ROLE_FALLBACK = {"solve_a": ("groq", "qwen/qwen3.8-27b"),
                 "classify": ("groq", "qwen/qwen3.8-27b"),
                 "reply": ("groq", "qwen/qwen3.8-27b")}
# Free-tier pacing (Groq allows 8,000 tokens a minute per model): wait out rate limits, and leave
# a gap after every live call.
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT = 30.0     # seconds, when the provider gives no retry-after
CALL_SPACING = 4.0         # seconds after each successful live call
CALL_TIMEOUT = 90.0        # seconds; a hung request is dropped and retried
PROVIDER_ENDPOINTS = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "key_env": "GEMINI_API_KEY"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY"},
}
# Model ids are set by the candidate after checking each account's model list.
# None makes engine/llm.py refuse to call that provider (the report is routed to faculty).
MODEL_A = "gemini-3.5-flash"  # Gemini model id (11 Nov: 3.7/3.8-flash returned 503 high demand; 2.5-flash closed to new users)
MODEL_B = "openai/gpt-oss-120b"  # Groq model id (strict json_schema verified 11 Nov)
TEMPERATURE = 0               # determinism; cached replays are the byte-for-byte guarantee
# Optional reasoning effort per role ("low" | "medium" | "high" | None). Sent only when set;
# if the model rejects it, llm.py retries without it.
REASONING_EFFORT = {"solve_a": "high", "solve_b": "high", "classify": "medium", "reply": None}
PROMPT_VERSIONS = {"solve_a": "v1", "solve_b": "v1", "classify": "v1", "reply": "v1"}
SOLVE_B_SCOPE = "all"         # every reported question gets two independent solves

MAX_WORKERS = 1               # one question at a time: free tiers are limited per minute
MAX_RETRIES = 6               # SDK backoff on 429 / 5xx (honours retry-after)
MAX_TOKENS = {"solve_a": 8192, "solve_b": 8192, "classify": 8192, "reply": 1024}
FREE_TIER = True              # usage log records cost_usd 0.0 while on free tiers
PRICES: dict[str, tuple[float, float]] = {}   # USD per 1M tokens (in, out) if a paid tier is used

# ---------------------------------------------------------------- decide.py rules
# What a student's claim (classifier claim_type) can be "about", in repair terms.
CLAIM_TO_REPAIRS = {
    "answer_key": ("answer_key", "type_mismatch", "unsound"),
    "missing_option": ("option_repair", "identical_options", "unsound"),
    "missing_data": ("stem_data", "diagram"),
    "figure": ("diagram",),
    "typo": ("spelling", "notation", "noise", "exam_reference", "markup_leak", "answer_form"),
    "solution": ("solution_fix", "solution_missing", "wrong_question"),
    "classification": ("wrong_chapter", "syllabus"),
    # A "looks wrong on screen" report whose cause is stored in the content (a raw LaTeX leak, an
    # exam tag, stray text) is a content defect, not a display issue, when a check finds it.
    "display": ("markup_leak", "exam_reference", "noise"),
}
# When the classifier says a report's claim holds but the claim type maps to no defect that was
# found, the report takes the question's top finding (by REPAIR_PRIORITY) instead of being left
# as an inconsistent no_error. Set False to restore the strict claim → repair mapping.
SUPPORTED_CLAIM_TAKES_ANY_FINDING = True
CLAIM_TO_VERDICT = {"display": "display_issue", "app": "app_issue", "language": "language_mode"}

# Defects that change what a student can answer correctly. Such a defect is attached to every
# report on the question, whatever the comment says. Other ("minor") defects attach only to a
# report whose claim is about them. Settled 10 Nov: major defects attach to every report.
MAJOR_REPAIRS = ("answer_key", "option_repair", "identical_options", "unsound", "stem_data",
                 "type_mismatch", "wrong_question", "diagram", "solution_missing")
# When several defects are found on one question, the report gets the first in this order.
REPAIR_PRIORITY = ("answer_key", "unsound", "type_mismatch", "option_repair", "identical_options",
                   "stem_data", "diagram", "wrong_question", "solution_missing", "solution_fix",
                   "markup_leak", "notation", "answer_form", "exam_reference", "noise", "spelling",
                   "wrong_chapter", "syllabus")

# Provisional confidence values (TODO: tune in Phase 3–4 against the candidate's labels).
CONFIDENCE_RULES = {
    "answer_key_full_proof": 0.95,
    "answer_key_partial": 0.60,
    "check_defect_with_edit": 0.95,
    "check_defect_no_edit": 0.85,
    "classifier_defect": 0.60,
    "solves_find_no_option": 0.75,
    "solution_contradicts_key": 0.80,  # both solves = key, stored solution ends elsewhere (→ solution_fix)     # both blind solves: no option is correct (→ unsound)
    "no_error_solves_confirm_key": 0.90,
    "no_error_unconfirmed": 0.55,
    "platform_verdict": 0.80,          # display_issue / app_issue / language_mode
    "already_fixed": 0.85,
    "not_actionable": 0.70,
    "validator_penalty": 0.30,
}

# Used when the LLM reply fails validation (guard 13). {step} is the classifier's
# "one step the student missed", empty when unknown.
REPLY_FALLBACK_TEMPLATES = {
    ("defect", "auto_apply"): "Thank you, you were right. We've fixed this question, so please try it again.",
    ("defect", "faculty_review"): "Thank you for flagging this. A teacher is checking this question now, and we'll update it if needed.",
    ("no_error", "no_change"): "Thanks for checking this carefully. We re-solved it and the given answer holds. {step}",
    ("display_issue", "no_change"): "Thanks for telling us. The question itself is correct; this looks like a display problem on your device, so please refresh or update the app.",
    ("app_issue", "no_change"): "Thanks for telling us. The question is correct; this looks like an app problem, and we've passed it to our tech team.",
    ("language_mode", "no_change"): "Thanks for asking. This question is only available in its current language right now.",
    ("already_fixed", "no_change"): "Thank you, you spotted a real problem, and our team has already sorted it out. Please reload the question to see the current version.",
    ("not_actionable", "no_change"): "Thanks for reporting. We checked this question and couldn't find a problem; if something still looks wrong, tell us which part.",
}

# ---------------------------------------------------------------- urgency (PENDING §7 D)
URGENCY_WEIGHTS = None
