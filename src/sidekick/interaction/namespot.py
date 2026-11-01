"""sidekick.interaction.namespot — fuzzy wake-name spotting on local transcripts

Overview
    IDLE speech segments are transcribed locally (SenseVoice) and this module decides whether
    "Bobby" was said — in English, Cantonese or Mandarin, through any of the configured aliases
    — and returns the utterance with the name removed so "Bobby，今日天氣點呀" becomes one turn.
Design
    Normalisation lowercases, drops punctuation and spaces (CJK has none). Exact alias substring
    is a hit with score 1.0; otherwise a sliding window of the alias length (±1) is compared with
    `difflib.SequenceMatcher` and the best ratio is the score. "BB" inside a sentence is never
    the name: it scored 0.8 against "bob", and BB is how a Cantonese parent calls a small child
    (「听到啦 BB」); a bare "BB" still is, the way the child calls Bobby (block #89). The
    remainder is the utterance without the name: the matched span goes, then every name left at
    its start or end ("芭比芭比芭比", "BB BOBY"), and a name in the middle becomes the robot's
    own ("讲畀芭比听" → "讲畀Bobby听"), so the agent never reads its own name as somebody else's;
    leading particles (呀 / 啊 / 呢 / , …) are trimmed. No model, no training — one mechanism
    for all three languages (PLAN.md block #9).
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Interaction" trigger 1 (`wake_name`).

"""

from __future__ import annotations

import contextvars
import difflib
import re
from collections.abc import Iterable

from .schemas import NameMatch

_PUNCT = re.compile(r"[\s,.;:!?，。；：！？、…·\-—_~～\"'“”‘’()（）\[\]【】《》<>]+")
_LEADING_PARTICLES = ("呀", "啊", "阿", "呢", "喂", "哎", "嘅", "吖", "哦", "呐", "吧")
_NAME_TAILS = ("比", "畢", "碧", "必")
_CURRENT_NAME: contextvars.ContextVar[str] = contextvars.ContextVar("sidekick_name", default="")
_LEADING_JUNK = re.compile(r"^[\s,，、。！？!?:：…]+")
_SEP = r"[\s,，、。！？!?:：…]*"
_SEP_SOFT = r"[\s,，、:：]*"  # before a name at the end: the final 。？ stays
_ECHOES = ("bb",)  # stripped beside a name, never a name by itself
_FINAL_MARKS = ("？", "?", "！", "!", "。")


def _alias_pattern(alias: str) -> str:
    """An alias as a regex, spaces allowed between its characters.

    A Latin one also takes the letters SenseVoice glues to it ("BOBYE") and never starts inside
    a word.
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


class NameSpotter:
    """Matches the robot's name and aliases in a transcript."""

    def __init__(self, name: str, aliases: Iterable[str] = (), threshold: float = 0.75) -> None:
        self.name = name
        self.threshold = threshold
        seen: list[str] = []
        for alias in (name, *aliases):
            norm = normalize(alias)
            if norm and norm not in seen:
                seen.append(norm)
        # Longer aliases first so "bobby" wins over "bob".
        self.aliases = sorted(seen, key=len, reverse=True)
        names = "|".join(_alias_pattern(alias) for alias in self.aliases)
        # Next to a real name, "BB" is the same call ("BB BOBY"); alone it is a baby.
        edges = "|".join(_alias_pattern(alias) for alias in (*self.aliases, *_ECHOES))
        self._edge_start = re.compile(rf"^{_SEP}(?:{edges}){_SEP}", re.IGNORECASE)
        self._edge_end = re.compile(rf"{_SEP_SOFT}(?:{edges})(?={_SEP}$)", re.IGNORECASE)
        self._inner = re.compile(rf"(?:{names})", re.IGNORECASE)

    def match(self, text: str) -> NameMatch:
        """Spot the name; `remainder` is the rest of the utterance."""
        norm = normalize(text)
        if not norm:
            return NameMatch(False, 0.0, None, "", text)
        best_score = 0.0
        best_alias: str | None = None
        best_span: tuple[int, int] | None = None
        for alias in self.aliases:
            index = norm.find(alias)
            if index >= 0:
                best_score, best_alias, best_span = 1.0, alias, (index, index + len(alias))
                break
            if len(alias) < 2:
                continue
            for width in (len(alias), len(alias) + 1, max(2, len(alias) - 1)):
                for start in range(0, max(1, len(norm) - width + 1)):
                    window = norm[start : start + width]
                    if window == "bb" and norm != "bb":
                        continue  # "…听到啦 BB" is a parent calling a child (block #89)
                    score = difflib.SequenceMatcher(None, alias, window).ratio()
                    if score > best_score:
                        best_score, best_alias, best_span = score, alias, (start, start + width)
        hit = best_score >= self.threshold and best_span is not None
        remainder = norm
        if hit and best_span is not None and best_alias is not None:
            token = _CURRENT_NAME.set(self.name)
            try:
                lead = len(norm) - len(norm.lstrip("".join(_LEADING_PARTICLES)))
                inside = best_span[0] > lead and best_span[1] < len(norm)
                if best_score >= 1.0 and inside:  # "我同Bobby讲": renamed, not cut out
                    remainder = self._tidy(text)
                else:
                    remainder = self._tidy(self._remainder(text, norm, best_alias, best_span))
            finally:
                _CURRENT_NAME.reset(token)
        return NameMatch(hit, round(best_score, 3), best_alias if hit else None, remainder, text)

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
        """The utterance without the name, keeping the original punctuation when possible."""
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
            # SenseVoice glues mis-heard letters to the name ("BO比I 今日…"): drop the whole
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
            # "BOB 比今日…": SenseVoice often splits the name into a Latin stub plus a Chinese
            # character for the second syllable. Only an incomplete Latin stub (a prefix of the
            # full name) swallows that character; a full "bobby" leaves "比較好" alone.
            tail = text[end:].lstrip()
            full = normalize(self_name) if (self_name := _CURRENT_NAME.get()) else ""
            if (
                alias.isascii()
                and full
                and alias != full
                and full.startswith(alias)
                and tail[:1] in _NAME_TAILS
            ):
                end = len(text) - len(tail) + 1
            remainder = (text[:start] + " " + text[end:]).strip()
        else:
            remainder = (norm[: span[0]] + norm[span[1] :]).strip()
        remainder = _LEADING_JUNK.sub("", remainder)
        while remainder and remainder.startswith(_LEADING_PARTICLES):
            remainder = _LEADING_JUNK.sub("", remainder[1:])
        remainder = remainder.strip()
        final = text.rstrip()[-1:]
        if remainder and final in _FINAL_MARKS and not remainder.endswith(final):
            remainder += final  # "今日天氣點呀 Bobby？" is still a question
        return remainder

    def without_name(self, text: str) -> str:
        """The utterance without the name when present (keeps original text otherwise)."""
        match = self.match(text)
        return match.remainder if match.hit else text
