"""sidekick.interaction.expression — named expressions and styles from the agent to the body

Overview
    The agent emits text plus optional tags (invariant 7: it never drives motors).
    `[express:name]` plays one of Banana's own expressions (`body/expression_library.json`, by
    name or by one of its aliases — `happy` → `delighted`, `laughing` → `laugh`, `是` → `nod`)
    and `[style:lively]` / `[style:calm]` / `[style:natural]` sets how big the rest of the reply
    is performed. `split_tags()` takes both out of the text so they are never spoken.
Design
    Resolution: the antenna cues `listening` / `relax`, then the library (case-insensitive names
    and aliases), otherwise ignored with a log line. What the agent asks for plays on the
    motion owner's `express` layer, so it sums with the automatic beats and the speech sway
    and keeps the gaze. A style tag only changes the energy of the reply it starts; the pipeline
    sets `natural` again when the reply ends, so there is never a mode to switch back.
Depends on
    sidekick.body, sidekick.log.

See Also
--------
    AGENTS.md "Agent swarm" (messages and named expressions), "Body"; PLAN.md block
    "[2026-10-28 #50]".

"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sidekick.body import STYLE_ENERGY, BodySession
from sidekick.log import Log

TAG = re.compile(r"\[\s*(express|style)\s*:\s*([^\]\s]+)\s*\]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TagSplit:
    """A text fragment with its tags taken out."""

    text: str
    expressions: tuple[str, ...] = ()
    style: str | None = None


class ExpressionMapper:
    """Resolve expression names against the body's library."""

    def __init__(self, body: BodySession) -> None:
        self.body = body

    def resolve(self, name: str) -> str | None:
        """Canonical name, or None when unknown."""
        key = name.strip().lower()
        if key in ("listening", "relax"):
            return key
        spec = self.body.expression(key)
        return spec.name if spec is not None else None

    def express(self, name: str, intensity: float = 1.0) -> bool:
        """Play an expression; False when unknown."""
        key = self.resolve(name)
        if key is None:
            Log.info(f"unknown expression {name!r} ignored")
            return False
        if key == "listening":
            self.body.listening()
        elif key == "relax":
            self.body.relax()
        else:
            self.body.express(key, intensity=intensity)
        return True

    @staticmethod
    def split_tags(text: str) -> TagSplit:
        """Take `[express:…]` and `[style:…]` tags out of agent text."""
        expressions: list[str] = []
        style: str | None = None
        for kind, value in TAG.findall(text):
            if kind.lower() == "express":
                expressions.append(value)
            elif value.lower() in STYLE_ENERGY:
                style = value.lower()
        clean = TAG.sub("", text)
        clean = re.sub(r"[ \t]{2,}", " ", clean).strip()
        return TagSplit(clean, tuple(expressions), style)
