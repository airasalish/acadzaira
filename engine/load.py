"""Stage 1–2: load organiser data and normalise each question (pure code, no LLM).

Production HTML is messy (unclosed <span>s, options inline in the question HTML, option
letters sometimes inside MathML). We never rewrite stored HTML here; we only derive
read-only views (plain text, options) used by checks and guards. Edits always operate on
the raw stored strings (engine/edits.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from engine import config


def load_json(name: str) -> Any:
    return json.loads((config.DATA_DIR / name).read_text(encoding="utf-8"))


def load_all() -> tuple[dict, list, dict]:
    """Return (questions by _id, reports, taxonomy)."""
    questions = load_json("questions.json")
    reports = load_json("reports.json")
    taxonomy = load_json("taxonomy.json")
    return {q["_id"]: q for q in questions}, reports, taxonomy


# ---------------------------------------------------------------- text views

_WS = re.compile(r"\s+")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def mathml_to_text(html: str) -> str:
    """Plain text of an HTML+MathML fragment: tags stripped, MathML reduced to its
    token text (so `<mn>4</mn>` reads as `4`), whitespace collapsed."""
    soup = _soup(html)
    for m in soup.find_all("math"):
        m.replace_with(" " + m.get_text(" ") + " ")
    return _WS.sub(" ", soup.get_text(" ")).strip()


def text_without_math(html: str) -> str:
    """Plain text with every <math> element removed. Used to look for raw LaTeX/HTML
    leaks, which only count when they appear outside MathML."""
    soup = _soup(html)
    for m in soup.find_all("math"):
        m.decompose()
    return _WS.sub(" ", soup.get_text(" ")).strip()


def compact(text: str) -> str:
    """Whitespace-free, case-folded form for value matching (`9 × 10 − 2` == `9×10−2`)."""
    return _WS.sub("", text or "").casefold()


# ---------------------------------------------------------------- options

_MARK = re.compile(r"\(\s*([A-D])\s*\)")


def split_options(question_text: str) -> tuple[str, dict[str, str]]:
    """Split plain question text into (stem, {letter: option text}).

    Options are marked "(A) … (B) …". The stem may itself contain "(A)" (e.g. "Assertion (A):"),
    so we take the LAST "(A)" that is followed, in order, by "(B)". Letters that never appear
    are absent from the dict; an option whose text is empty maps to "".
    """
    marks = [(m.group(1), m.start(), m.end()) for m in _MARK.finditer(question_text)]
    start = None
    for i, (letter, _, _) in enumerate(marks):
        if letter == "A" and any(l == "B" for l, _, _ in marks[i + 1:]):
            start = i
    if start is None:
        return question_text.strip(), {}
    chain: list[tuple[str, int, int]] = []
    last = -1
    for letter, s, e in marks[start:]:
        # accept letters in strictly increasing order; a repeated/out-of-order mark is option text
        idx = config.OPTION_LETTERS.index(letter)
        if idx > last:
            chain.append((letter, s, e))
            last = idx
    stem = question_text[: chain[0][1]].strip()
    options: dict[str, str] = {}
    for i, (letter, _, e) in enumerate(chain):
        end = chain[i + 1][1] if i + 1 < len(chain) else len(question_text)
        options[letter] = question_text[e:end].strip()
    return stem, options


# ---------------------------------------------------------------- normalised question

@dataclass
class NormQ:
    id: str
    qtype: str
    raw: dict                      # the untouched stored record
    question_html: str
    solution_html: str
    answer: Any                    # str for scq/integerQuestion, list for mcq
    question_text: str
    solution_text: str
    stem_text: str
    options: dict[str, str]
    updated_at: str
    error_history: list = field(default_factory=list)
    ques_images: list = field(default_factory=list)
    solution_images: list = field(default_factory=list)

    @property
    def body(self) -> dict:
        return self.raw.get(self.qtype) or {}


def normalise_question(q: dict) -> NormQ:
    qtype = q["questionType"]
    body = q.get(qtype) or {}
    qhtml = body.get("question") or ""
    shtml = body.get("solution") or ""
    qtext = mathml_to_text(qhtml)
    if qtype in ("scq", "mcq"):
        stem, options = split_options(qtext)
    else:
        stem, options = qtext, {}
    return NormQ(
        id=q["_id"],
        qtype=qtype,
        raw=q,
        question_html=qhtml,
        solution_html=shtml,
        answer=body.get("answer"),
        question_text=qtext,
        solution_text=mathml_to_text(shtml),
        stem_text=stem,
        options=options,
        updated_at=q.get("updatedAt") or "",
        error_history=list(q.get("errorHistory") or []),
        ques_images=list(body.get("quesImages") or []),
        solution_images=list(body.get("solutionImages") or []),
    )
