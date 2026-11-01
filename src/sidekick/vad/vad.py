"""sidekick.vad.vad — VADSession façade

Overview
    Binds the `primary` slot to a detector factory; consumers call `create()` to get their own
    stateful detector. Config decides the backend (`silero_sherpa` first).
Design
    No tracing here: engagement decisions, not raw VAD frames, are what gets traced
    (invariant 18), and that happens in `interaction`.
    A slot's `setup` drops the factory it replaces (block #87).
Depends on
    sidekick.log.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from sidekick.log import Log

from .schemas import VADBackend, VADFactory

_closing: set[asyncio.Task[None]] = set()  # replaced backends closing on the loop


def _close(backend: Any) -> None:
    """Release what a replaced or unbound backend holds (pooled connections, a loaded model).

    `aclose()` runs on the running loop when there is one (kept referenced until done),
    otherwise `close()` when the backend has it.
    """
    aclose = getattr(backend, "aclose", None)
    if callable(aclose):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            task = loop.create_task(aclose())
            _closing.add(task)
            task.add_done_callback(_closing.discard)
            return
    close = getattr(backend, "close", None)
    if callable(close):
        try:
            close()
        except Exception as exc:  # pragma: no cover - teardown best effort
            Log.warning(f"closing {type(backend).__name__}: {exc!r}")


class VADSession:
    """Holds a detector factory per slot."""

    shared: ClassVar[VADSession]

    def __init__(self) -> None:
        self._slots: dict[str, VADFactory] = {}

    def setup(self, slot: str, factory: VADFactory | None) -> None:
        """Bind or unbind a slot; the factory it replaces is closed."""
        old = self._slots.pop(slot, None)
        if factory is not None:
            self._slots[slot] = factory
        if old is not None and old is not factory:
            _close(old)
        if factory is not None or old is not None:
            Log.info(f"slot {slot} -> {type(factory).__name__ if factory else None}")

    def is_ready(self, slot: str) -> bool:
        """Whether a slot has a factory."""
        return slot in self._slots

    def slots(self) -> list[str]:
        """Bound slot names."""
        return sorted(self._slots)

    def create(self, slot: str = "primary") -> VADBackend:
        """A fresh detector for one audio stream."""
        factory = self._slots.get(slot)
        if factory is None:
            raise RuntimeError(f"slot {slot} has no VAD backend")
        return factory()


VADSession.shared = VADSession()
