"""sidekick.interaction.call — Bobby answers out loud when someone only calls its name

Overview
    "Bobby!" with nothing after it used to get a nod and a flick of the antennas. People meeting
    Bobby for the first time took the silence for a broken robot (owner, 2026-11-01, block #92).
    A short spoken answer — 「喺度！咩事呀？」 — now plays at once. Its clips are synthesized
    when the voice front end starts, so the answer comes as fast as a person's: no model call
    and no TTS round trip on the call itself.
Design
    A few phrases per language. They are picked at random, never the same twice in a row, in
    the caller's language (the household's when unknown). They are synthesized once per run
    through the TTS session's one-clip call, in the household's own voice, and kept in memory,
    default language first. A phrase whose clip is not ready (TTS still busy or down) comes
    back without one and the caller says it through the normal stream. These are answers to a
    call, not fillers: they never come before a reply (block #76). Every one invites the next
    sentence, so the session then waits as it does after a question.
Depends on
    sidekick.audio, sidekick.log.

See Also
--------
    AGENTS.md "Interaction" (trigger 1, `wake_name`), PLAN.md block "[2026-11-01 #92]".

"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable, Iterable

from sidekick.audio import AudioClip
from sidekick.log import Log

CALL_ANSWERS: dict[str, tuple[str, ...]] = {
    "yue": ("喺度！咩事呀？", "係？我喺度。", "我喺度，你講啦。", "嗯？咩事呀？"),
    "zh": ("我在！什么事？", "嗯？我在。", "在呢，你说。"),
    "en": ("Yes? I'm here.", "Hi! What's up?", "I'm listening."),
}

Synthesize = Callable[[str], Awaitable[AudioClip | None]]


class CallAnswers:
    """The phrases and their clips; `pick()` chooses the next answer."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.clips: dict[str, AudioClip] = {}
        self._last: str | None = None

    def phrases(self, language: str | None) -> tuple[str, ...]:
        """The answers in a language (Cantonese when it has none)."""
        return CALL_ANSWERS.get(language or "", CALL_ANSWERS["yue"])

    async def prepare(self, synthesize: Synthesize, languages: Iterable[str | None]) -> int:
        """Synthesize every phrase not yet held, in the order of `languages`; how many are ready."""
        for language in dict.fromkeys(languages):  # first-seen order, no repeats
            for text in self.phrases(language):
                if text in self.clips:
                    continue
                try:
                    clip = await synthesize(text)
                except Exception as exc:  # TTS down: the stream says it when needed
                    Log.warning(f"call answer {text!r} not synthesized: {exc!r}")
                    continue
                if clip is not None and clip.duration_s > 0.1 and clip.sample_rate == 16000:
                    self.clips[text] = clip  # the speaker plays 16 kHz as it comes
        Log.info(f"call answers ready: {len(self.clips)}")
        return len(self.clips)

    def pick(self, language: str | None) -> tuple[str, AudioClip | None]:
        """The next answer (never the last one again) and its clip when it is ready."""
        options = [text for text in self.phrases(language) if text != self._last]
        text = self.rng.choice(options)
        self._last = text
        return text, self.clips.get(text)
