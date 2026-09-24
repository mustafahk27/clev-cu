"""Parse subgoals: tokens for ranking, and literal values to type (plan §10)."""

from __future__ import annotations

import re
from dataclasses import dataclass

TYPE_VERBS = frozenset({"type", "enter", "fill", "write", "input"})
# Instruction verbs that describe the action, not the target; dropped from goal words.
ACTION_VERBS = (
    frozenset("open click go goto select press tap choose navigate visit hit find".split())
    | TYPE_VERBS
)
STOPWORDS = frozenset(
    "a an the to of in on at for from into onto with by and or is are be this that these those "
    "it its as up out so then than there here page".split()
)
_QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”|\'([^\']+)\'')
_WORD = re.compile(r"[a-z0-9]+")


def stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS]


def extract_literal(subgoal: str) -> str | None:
    """The quoted value in a subgoal like 'Type "Muscat" into the search box'."""
    m = _QUOTED.search(subgoal)
    return next(g for g in m.groups() if g) if m else None


@dataclass(frozen=True)
class Goal:
    text: str
    is_typing: bool  # the subgoal asks to type text somewhere
    literal: str | None  # value to type, if the subgoal quotes one
    tokens: frozenset[str]  # words describing the target (excludes the value to type)
    described: str  # target description as normalized tokens, for whole-phrase matching

    @classmethod
    def parse(cls, subgoal: str) -> Goal:
        words = _WORD.findall(subgoal.lower())
        is_typing = bool(words) and words[0] in TYPE_VERBS
        literal = extract_literal(subgoal)
        # For typing, the quoted text is the value, not a description of the target.
        described = _QUOTED.sub(" ", subgoal) if is_typing else subgoal
        target = [t for t in tokens(described) if t not in ACTION_VERBS]
        return cls(subgoal, is_typing, literal, frozenset(target), " ".join(target))
