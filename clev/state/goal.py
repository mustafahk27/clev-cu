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


# Words ending in "s" that aren't plurals.
NO_STEM = frozenset(
    "news status series species campus bonus canvas atlas alias gps ios macos".split()
)


def stem(word: str) -> str:
    if word in NO_STEM:
        return word
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


# Normalize wording so a goal and an element meet on one concept word. Applied to both sides
# before tokenizing ("Log in" ~ "login", "»" ~ "next").
_PHRASES = [
    (re.compile(r"\b(?:log|sign)[\s-]*(?:in|on)\b"), " login "),
    (re.compile(r"\b(?:log|sign)[\s-]*(?:out|off)\b"), " logout "),
    (re.compile(r"\bsign[\s-]*up\b|\bregister\b"), " signup "),
    (re.compile(r"\S+@\S+\.\w+"), " email "),  # placeholder "name@example.com" is an email field
    (re.compile(r"[»›→]"), " next "),
    (re.compile(r"[«‹←]"), " prev "),
]
# Applied after stemming: word -> concept.
SYNONYMS = {
    "more": "next", "older": "next",
    "previous": "prev", "newer": "prev",
    "newest": "new", "latest": "new", "recent": "new",
    "basket": "cart", "bag": "cart", "trolley": "cart",
    "remove": "delete", "trash": "delete",
    "preference": "setting",
    "mail": "email", "e": "", "signin": "login", "logon": "login",
}  # fmt: skip


def tokens(text: str) -> list[str]:
    text = text.lower()
    for pattern, concept in _PHRASES:
        text = pattern.sub(concept, text)
    out = []
    for w in _WORD.findall(text):
        if w in STOPWORDS:
            continue
        w = SYNONYMS.get(stem(w), stem(w))
        if w:
            out.append(w)
    return out


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
