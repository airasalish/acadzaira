"""Stage 10: build, match, apply and markup-check surgical edits (pure code).

Edit shapes (docs/PLAN.md §2):
  text fields   {"field": "question"|"solution", "find": str, "replace": str}   find occurs exactly once
  scq/integer   {"field": "answer", "find": "B", "replace": "D"}                 find == stored string
  mcq answer    {"field": "answer", "find": [..], "replace": [..]}               find deep-equals stored list;
                                                                                  replace is canonical
`field` names a key inside the question's type body (q[q.questionType][field]).
"""
from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Any

from lxml import etree

from engine import config
from engine.checks import is_canonical_mcq

TEXT_FIELDS = ("question", "solution")
EDIT_KEYS = {"field", "find", "replace"}


def get_field(q: dict, field: str) -> Any:
    if field == "questionType":
        return q.get("questionType")
    return (q.get(q["questionType"]) or {}).get(field)


def count_matches(stored: Any, find: Any, field: str) -> int:
    """How many times `find` matches the stored value. A surgical edit needs exactly 1.
    - list (mcq answer): 1 if deep-equal (same elements, same order, same types) else 0
    - answer string: 1 if exactly equal else 0 (so find '2' can never hit key '20')
    - text: overlapping substring count
    """
    if isinstance(stored, list) or isinstance(find, list):
        return 1 if isinstance(stored, list) and isinstance(find, list) and stored == find else 0
    if not isinstance(stored, str) or not isinstance(find, str) or find == "":
        return 0
    if field == "answer":
        return 1 if stored == find else 0
    return sum(1 for i in range(len(stored)) if stored.startswith(find, i))


def shape_errors(edit: Any, qtype: str) -> list[str]:
    """Structural validation of an edit object for a question of this type."""
    if edit is None:
        return []
    if not isinstance(edit, dict) or set(edit) != EDIT_KEYS:
        return [f"edit must have exactly keys {sorted(EDIT_KEYS)}"]
    f, find, rep = edit["field"], edit["find"], edit["replace"]
    if f in TEXT_FIELDS:
        if not (isinstance(find, str) and isinstance(rep, str) and find):
            return [f"{f} edit needs non-empty string find and string replace"]
        if find == rep:
            return ["find and replace are identical"]
        return []
    if f == "answer":
        if qtype == "mcq":
            if not (isinstance(find, list) and isinstance(rep, list)):
                return ["mcq answer edit must use JSON lists for find and replace"]
            if not is_canonical_mcq(rep):
                return [f"mcq replace {rep!r} is not a list of single option letters"]
        elif qtype == "scq":
            if not (isinstance(find, str) and isinstance(rep, str) and rep in config.OPTION_LETTERS):
                return [f"scq answer edit needs string find and a single option letter, got {rep!r}"]
        elif qtype == "integerQuestion":
            if not (isinstance(find, str) and isinstance(rep, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", rep)):
                return [f"integer answer edit needs a numeric string replace, got {rep!r}"]
        if find == rep:
            return ["find and replace are identical"]
        return []
    return [f"field {f!r} is not editable by this engine"]


def apply_edit(q: dict, edit: dict) -> dict:
    """Return a deep copy of the record with the edit applied. Caller must have checked
    count_matches == 1."""
    new = copy.deepcopy(q)
    body = new[new["questionType"]]
    f = edit["field"]
    if isinstance(edit["find"], list) or f == "answer":
        body[f] = copy.deepcopy(edit["replace"])
    else:
        body[f] = body[f].replace(edit["find"], edit["replace"], 1)
    return new


# ---------------------------------------------------------------- markup safety

_MATH_BLOCK = re.compile(r"<math\b.*?</math>", re.S | re.I)
_TAG = re.compile(r"<\s*/?\s*([a-zA-Z][\w:-]*)")


def _inside_tag(s: str, pos: int) -> bool:
    """True if position `pos` falls between a '<' and its '>' (i.e. inside a tag)."""
    lt, gt = s.rfind("<", 0, pos), s.rfind(">", 0, pos)
    return lt > gt


def _balanced_angles(s: str) -> bool:
    depth = 0
    for ch in s:
        if ch == "<":
            depth += 1
            if depth > 1:
                return False
        elif ch == ">":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def markup_errors(before: str, find: str, replace: str) -> list[str]:
    """An edit must not break stored markup. Production HTML is not well-formed (unclosed
    <span>s), so we check what the edit itself can break:
      1. the find span must not start or end inside a tag;
      2. find and replace must each contain only complete tags;
      3. every <math> block that is new after the edit must parse as XML;
      4. tag counts change exactly as find → replace implies.
    """
    errs = []
    i = before.find(find)
    if i < 0:
        return ["find not present"]
    if _inside_tag(before, i) or _inside_tag(before, i + len(find)):
        errs.append("find starts or ends inside an HTML tag")
    if not _balanced_angles(find) or not _balanced_angles(replace):
        errs.append("find/replace contains a partial tag")
    after = before.replace(find, replace, 1)
    old_blocks = Counter(_MATH_BLOCK.findall(before))
    for block in _MATH_BLOCK.findall(after):
        if old_blocks[block] > 0:
            old_blocks[block] -= 1
            continue
        try:
            etree.fromstring(block.encode("utf-8"))
        except etree.XMLSyntaxError as e:
            errs.append(f"new MathML does not parse: {e}")
    expect = Counter(_TAG.findall(before)) - Counter(_TAG.findall(find)) + Counter(_TAG.findall(replace))
    if Counter(_TAG.findall(after)) != expect:
        errs.append("tag structure changed beyond the edit")
    return errs
