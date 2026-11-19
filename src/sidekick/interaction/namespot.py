"""sidekick.interaction.namespot — wake-name spotting on local transcripts

Overview
    IDLE speech segments are transcribed locally (SenseVoice) and this module decides whether
    the robot's name was said — "Banana", through any of the configured aliases — and returns
    the utterance with the name removed so "Banana，今天天气怎么样" becomes one turn.
Design
    Two ways to hear the name, the strict one first. **Aliases as written**: normalisation
    lowercases and drops punctuation and spaces (CJK has none), and an alias found in it is a
    hit with score 1.0 — the aliases are the spellings the recogniser really wrote ("BANANNA",
    "ANANNA", 「把娜娜」). **The name itself, loosely, word by word**: every Latin word of the
    text whose length is within one letter of the name is compared with it by
    `difflib.SequenceMatcher`, and the best ratio is the score ("VANANA" 0.83), so a spelling
    nobody has seen yet still wakes the robot. Only the name, and only whole words (block #94):
    with every alias matched loosely, "ananna" took "NANNA is not coming" and "banaa" took
    "Panama" and "nana"; with windows sliding over the text without its spaces, "a banner and
    a" and "cabana near" held a "banana"; and two characters of a three-character alias score
    0.8, the threshold, so 「把娜娜」 would have taken a person called 娜娜 — as "BB", a parent
    calling a child, was once taken for the first name's "bob" (block #89). What still comes
    that close is an English word one letter away ("bandana"). The remainder is the utterance
    without the name: the match goes, then every name left at its start or end ("BANANNA
    BANANA"), and a name in the middle becomes the robot's own ("我想跟 BANANNA 说句话" →
    "我想跟 Banana 说句话"), so the agent never reads its own name as somebody else's; leading
    particles (呀 / 啊 / 呢 / , …) are trimmed and a final ？ stays. No model, no training — one
    mechanism for every language (PLAN.md block #9).
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Interaction" trigger 1 (`wake_name`), PLAN.md block "[2026-11-20 #94]".

"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

from .schemas import NameMatch

_PUNCT = re.compile(r"[\s,.;:!?，。；：！？、…·\-—_~～\"'“”‘’()（）\[\]【】《》<>]+")
_LEADING_PARTICLES = ("呀", "啊", "阿", "呢", "喂", "哎", "嘅", "吖", "哦", "呐", "吧")
_LEADING_JUNK = re.compile(r"^[\s,，、。！？!?:：…]+")
_SEP = r"[\s,，、。！？!?:：…]*"
_SEP_SOFT = r"[\s,，、:：]*"  # before a name at the end: the final 。？ stays
_FINAL_MARKS = ("？", "?", "！", "!", "。")
_LATIN_WORD = re.compile(r"[A-Za-z]+")
LOOSE_MIN = 5  # a name shorter than this is never matched loosely (two of three letters: 0.8)


def _alias_pattern(alias: str) -> str:
    """An alias as a regex, spaces allowed between its characters.

    A Latin one also takes the letters SenseVoice glues to it ("BANANAS") and never starts
    inside a word.
    """
    body = r"\s*".join(re.escape(ch) for ch in alias)
    return rf"(?<![a-z]){body}[a-z]*" if alias.isascii() else body


def _is_word_char(ch: str) -> bool:
    return not ch.isspace() and not _PUNCT.match(ch)


def normalize(text: str) -> str:
    """Lowercase, no punctuation, no spaces."""
    return _PUNCT.sub("", text.strip().lower())


def is_filler(text: str | None, fillers: Iterable[str] = ()) -> bool:
    """A transcript with no content: empty, a single character, or a known filler/hallucination."""
    norm = normalize(text or "")
    if not norm:
        return True
    if len(norm) <= 1:
        return True
    return norm in {normalize(f) for f in fillers}


def _finish(remainder: str, text: str) -> str:
    """Trim what led the name (punctuation, particles) and keep the utterance's final mark."""
    remainder = _LEADING_JUNK.sub("", remainder.strip())
    while remainder and remainder.startswith(_LEADING_PARTICLES):
        remainder = _LEADING_JUNK.sub("", remainder[1:])
    remainder = remainder.strip()
    final = text.rstrip()[-1:]
    if remainder and final in _FINAL_MARKS and not remainder.endswith(final):
        remainder += final  # "今天天气怎么样 Banana？" is still a question
    return remainder


class NameSpotter:
    """Matches the robot's name and aliases in a transcript."""

    def __init__(self, name: str, aliases: Iterable[str] = (), threshold: float = 0.75) -> None:
        self.name = name
        self.threshold = threshold
        self.canonical = normalize(name)  # the only spelling matched loosely
        seen: list[str] = []
        for alias in (name, *aliases):
            norm = normalize(alias)
            if norm and norm not in seen:
                seen.append(norm)
        # Longer aliases first so "bananna" wins over "banana".
        self.aliases = sorted(seen, key=len, reverse=True)
        names = "|".join(_alias_pattern(alias) for alias in self.aliases)
        self._edge_start = re.compile(rf"^{_SEP}(?:{names}){_SEP}", re.IGNORECASE)
        self._edge_end = re.compile(rf"{_SEP_SOFT}(?:{names})(?={_SEP}$)", re.IGNORECASE)
        self._inner = re.compile(rf"(?:{names})", re.IGNORECASE)

    def match(self, text: str) -> NameMatch:
        """Spot the name; `remainder` is the rest of the utterance."""
        norm = normalize(text)
        if not norm:
            return NameMatch(False, 0.0, None, "", text)
        lead = len(norm) - len(norm.lstrip("".join(_LEADING_PARTICLES)))
        for alias in self.aliases:  # a spelling the recogniser wrote, as written
            index = norm.find(alias)
            if index < 0:
                continue
            inside = index > lead and index + len(alias) < len(norm)
            # "我想跟Banana说句话": renamed by `_tidy`, not cut out
            rest = (
                text if inside else self._remainder(text, norm, alias, (index, index + len(alias)))
            )
            return NameMatch(True, 1.0, alias, self._tidy(rest), text)
        score, span = self._loose(text)  # the name itself, word by word
        if span is None or score < self.threshold:
            return NameMatch(False, round(score, 3), None, norm, text)
        before, after = text[: span[0]], text[span[1] :]
        inside = len(normalize(before)) > lead and bool(normalize(after))
        rest = before + (self.name if inside else " ") + after
        return NameMatch(
            True, round(score, 3), self.canonical, self._tidy(_finish(rest, text)), text
        )

    def _loose(self, text: str) -> tuple[float, tuple[int, int] | None]:
        """The Latin word closest to the name: its ratio and where it is in `text`."""
        name = self.canonical
        if len(name) < LOOSE_MIN or not (name.isascii() and name.isalpha()):
            return 0.0, None
        best, span = 0.0, None
        for found in _LATIN_WORD.finditer(text):
            word = found.group().lower()
            if abs(len(word) - len(name)) > 1:
                continue
            score = difflib.SequenceMatcher(None, name, word).ratio()
            if score > best:
                best, span = score, found.span()
        return best, span

    def _tidy(self, text: str) -> str:
        """Names at the start or end removed (repeatedly), one in the middle renamed."""
        previous = None
        while previous != text:
            previous = text
            text = _LEADING_JUNK.sub("", text)
            while text and text.startswith(_LEADING_PARTICLES):
                text = _LEADING_JUNK.sub("", text[1:])
            text = self._edge_start.sub("", text, count=1)
            text = self._edge_end.sub("", text, count=1).strip()
        return self._inner.sub(self.name, text).strip()

    @staticmethod
    def _remainder(text: str, norm: str, alias: str, span: tuple[int, int]) -> str:
        """The utterance without an alias, keeping the original punctuation when possible."""
        letters = r"[a-z]*" if alias.isascii() else ""
        pattern = re.compile(
            r"[\s,，、。！？!?:：]*"
            + letters
            + r"\s*".join(re.escape(ch) for ch in alias)
            + letters
            + r"[\s,，、。！？!?:：]*",
            re.IGNORECASE,
        )
        found = pattern.search(text)
        if found is not None:
            start, end = found.start(), found.end()
            # SenseVoice glues mis-heard letters to the name ("BA娜娜 今天…"): drop the whole
            # short token around the match when it mixes Latin letters with other characters.
            while start > 0 and _is_word_char(text[start - 1]):
                start -= 1
            while end < len(text) and _is_word_char(text[end]):
                end += 1
            token = text[start:end].strip()
            mixed = any(ch.isascii() and ch.isalpha() for ch in token) and any(
                not ch.isascii() for ch in token
            )
            if not (mixed and len(token) <= 6):
                start, end = found.start(), found.end()
            remainder = text[:start] + " " + text[end:]
        else:
            remainder = norm[: span[0]] + norm[span[1] :]
        return _finish(remainder, text)

    def without_name(self, text: str) -> str:
        """The utterance without the name when present (keeps original text otherwise)."""
        match = self.match(text)
        return match.remainder if match.hit else text
