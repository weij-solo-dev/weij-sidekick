"""sidekick.interaction.pipeline — one turn: clip → ASR → agent tokens → sentences → bidi TTS → speaker

Overview
    `TurnPipeline.run_turn()` executes a turn end to end and records the latency marks that
    decide product quality: speech end → transcript → first token → first audio out → quiet.
    `TTSStreamKeeper` owns one long-lived bidirectional TTS session (connecting costs ~2 s; a
    turn ends with `flush`, not a reconnect) and reopens it when the vendor closes it.
    `SentenceSplitter` turns LLM deltas into sentence-sized fragments for the TTS server.
    The server only starts on a sentence end or a flush (a clause ending in a comma waited
    2.7 s, measured 2026-10-29): when the first clause of a reply is still open `EAGER_FLUSH_S`
    after it was sent, the keeper flushes it mid-turn so speech starts about 0.6 s later instead
    of after the whole first sentence (block #71); a short first sentence still goes out whole.
    The server leaves only ~0.2 s between its sentences, the same as a comma inside one, so a
    full stop had no pause of its own (block #76): every sentence that ends in 。！？；… is
    flushed as it is sent, the server's `flushed` marks exactly where its audio ends (its own
    cuts inside a long comma run do not), and the keeper puts `sentence_pause_s` of silence
    before the next sentence's audio, less whatever silence the speaker already had.
Design
    The turn is cancellable at any point (barge-in): cancelling the task cancels the agent
    stream, sends `task_cancel` to TTS and flushes the speaker. ASR is utterance-based (MiniMax
    has no real-time input); the `asr.local` slot is used as a fallback when the primary fails
    and, when `shadow_asr` is on, run alongside for the dashboard comparison. `[express:…]` and
    `[style:…]` tags in agent text are stripped before synthesis: expressions play through the
    expression mapper, a style sets the body's energy for this reply only (natural again when
    the reply ends or is interrupted).
Depends on
    sidekick.log, sidekick.audio, sidekick.asr, sidekick.tts, sidekick.body, sidekick.channel.

See Also
--------
    AGENTS.md "Streaming pipeline", PLAN.md block #11 findings 5–6.

"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from sidekick.asr import ASRResult, ASRSession
from sidekick.audio import AudioClip
from sidekick.body import BodySession
from sidekick.channel import ChannelMessage
from sidekick.log import Log
from sidekick.tts import TTSSession, TTSStream

from .expression import ExpressionMapper
from .schemas import Responder, TurnResult, TurnTiming

# A run of sentence ends: 。！？；, newlines, an ellipsis, an English full stop before a space.
SENTENCE_END = re.compile(r"(?:[。！？!?；;\n]|…|\.\.\.|\.(?=\s))+")
# A fragment that ends a sentence (closing quotes and brackets may follow).
SENTENCE_FINAL = re.compile(r"(?:[。！？!?；;\n…]|\.)[\s」』”’）)\]]*$")
SOFT_BREAK = re.compile(r"[，,、：:]")
# The first clause of a reply still waiting for its sentence end this long is flushed (block #71).
EAGER_FLUSH_S = 0.15
PCM_RATE = 16000  # the TTS streams and the speaker both run at 16 kHz
# Waiting for the speaker: the audio still queued plus this much before looking again.
QUIET_MARGIN_S = 2.0
# Emoji and pictographs: a voice cannot say them (😂 reached the speaker on 10-31, block #89).
EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d\u20e3]+")


def speakable(text: str) -> str:
    """The text without emoji (a space left by one is folded into its neighbour)."""
    if not EMOJI.search(text):
        return text
    return re.sub(r"[ \t]{2,}", " ", EMOJI.sub("", text)).strip(" \t")


class SentenceSplitter:
    """Accumulate deltas; emit fragments the TTS server can start on."""

    def __init__(self, soft_min_chars: int = 4, hard_max_chars: int = 30) -> None:
        self.soft_min_chars = soft_min_chars
        self.hard_max_chars = hard_max_chars
        self.buffer = ""

    def feed(self, delta: str) -> list[str]:
        """Return complete fragments."""
        self.buffer += delta
        out: list[str] = []
        while True:
            if self.buffer.count("[") > self.buffer.count("]") and len(self.buffer) < 200:
                break  # an expression tag like [express:happy] is still open; never cut inside it
            match = SENTENCE_END.search(self.buffer)
            if match is not None:
                cut = match.end()
            else:
                soft = None
                if len(self.buffer) >= self.soft_min_chars:
                    for found in SOFT_BREAK.finditer(self.buffer):
                        if found.end() >= self.soft_min_chars:
                            soft = found.end()
                            break
                if soft is not None:
                    cut = soft
                elif len(self.buffer) >= self.hard_max_chars:
                    cut = self.hard_max_chars
                else:
                    break
            fragment = self.buffer[:cut].lstrip().rstrip(" \t\r")  # a newline still ends it
            self.buffer = self.buffer[cut:]
            if fragment:
                out.append(fragment)
        return out

    def flush(self) -> str:
        """Whatever is left."""
        rest, self.buffer = self.buffer.strip(), ""
        return rest


class TTSStreamKeeper:
    """One bidirectional TTS session reused across turns."""

    def __init__(
        self,
        tts: TTSSession,
        body: BodySession,
        slot: str = "primary",
        on_first_audio: Callable[[], None] | None = None,
        sentence_pause_s: float = 0.3,
    ) -> None:
        self.tts = tts
        self.body = body
        self.slot = slot
        self.on_first_audio = on_first_audio
        self.sentence_pause_s = sentence_pause_s
        self._stream: TTSStream | None = None
        self._reader: asyncio.Task[None] | None = None
        self.turn_done = asyncio.Event()
        self.turn_audio_bytes = 0
        self.turn_first_audio: float | None = None
        self.error: str | None = None
        self.connects = 0
        self.sentences_in_flight = 0
        # Each task_flush sent and not yet acknowledged, in order: "clause" (the eager first
        # clause), "sentence" (a sentence just sent) or "final" (the turn's end).
        self._flushes: deque[str] = deque()
        self.final_flush = False  # the turn's last flush was sent: its ack ends the turn
        self.eager_flushes = 0
        self.pauses = 0  # silences put between sentences
        self._pause_due = 0.0  # silence owed before the next audio (s)
        self._play_end = 0.0  # when the speaker runs out of what was pushed (monotonic)

    @property
    def flushes_pending(self) -> int:
        """task_flush sent, task_flushed not yet back."""
        return len(self._flushes)

    @property
    def connected(self) -> bool:
        """Whether a session is open."""
        return self._stream is not None

    async def ensure(self) -> TTSStream | None:
        """Open the session when needed."""
        if self._stream is not None:
            return self._stream
        if not self.tts.supports_streaming(self.slot):
            return None
        started = time.monotonic()
        try:
            self._stream = await self.tts.open_stream(self.slot)
        except Exception as exc:
            self.error = repr(exc)
            Log.error(f"tts stream open failed: {exc!r}")
            return None
        self.connects += 1
        self.error = None
        self._reader = asyncio.create_task(self._read(self._stream), name="tts-reader")
        Log.info(f"tts stream connected in {(time.monotonic() - started) * 1000:.0f} ms")
        return self._stream

    async def _read(self, stream: TTSStream) -> None:
        try:
            async for event in stream.events():
                if event.kind == "audio":
                    if self.turn_first_audio is None:
                        self.turn_first_audio = time.monotonic()
                        if self.on_first_audio is not None:
                            self.on_first_audio()
                    self.turn_audio_bytes += len(event.audio)
                    self.play(event.audio)
                elif event.kind == "flushed":
                    kind = self._flushes.popleft() if self._flushes else "final"
                    if kind == "sentence":
                        self.owe_pause()
                    elif kind == "clause":
                        self._pause_due = 0.0  # a comma: the server's own gap is right
                    if self.final_flush and not self._flushes:
                        self.turn_done.set()
                elif event.kind == "canceled":
                    self.turn_done.set()
                elif event.kind in ("finished", "error"):
                    if event.kind == "error":
                        self.error = event.message
                        Log.warning(f"tts stream error: {event.message} (code {event.api_code})")
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = repr(exc)
            Log.error(f"tts reader: {exc!r}")
        finally:
            self.turn_done.set()
            if self._stream is stream:
                self._stream = None
            try:
                await stream.aclose()
            except Exception:
                pass

    def begin_turn(self) -> None:
        """Reset per-turn marks."""
        self.turn_done.clear()
        self.turn_audio_bytes = 0
        self.turn_first_audio = None
        self._flushes.clear()
        self.final_flush = False
        self._pause_due = 0.0

    def owe_pause(self) -> None:
        """A sentence just ended: the next audio waits `sentence_pause_s` after it."""
        self._pause_due = self.sentence_pause_s

    def play(self, audio: Any) -> None:
        """Push audio to the speaker, after the pause a finished sentence is owed (block #76).

        The pause counts from when the speaker runs out: silence it already had (a tool round,
        a slow model) is not added again.
        """
        now = time.monotonic()
        if self._pause_due > 0.0:
            owed = self._pause_due - max(0.0, now - self._play_end)
            self._pause_due = 0.0
            if owed >= 0.02:
                self.body.speak(bytes(2 * int(owed * PCM_RATE)))
                self.pauses += 1
        self.body.speak(audio)
        self._play_end = now + self.body.speaking_remaining_s()

    async def send(self, text: str) -> bool:
        """Push a fragment; False when no session is available."""
        stream = await self.ensure()
        if stream is None:
            return False
        try:
            await stream.send(text)
        except Exception as exc:
            Log.warning(f"tts send failed: {exc!r}")
            self._stream = None
            return False
        return True

    async def flush(self) -> None:
        """End of turn: its acknowledgement (after any mid-turn flush) ends the turn."""
        self.final_flush = True
        if self._stream is not None:
            try:
                self._flushes.append("final")
                await self._stream.flush()
            except Exception as exc:
                Log.warning(f"tts flush failed: {exc!r}")
                self.turn_done.set()
        else:
            self.turn_done.set()

    async def flush_now(self) -> None:
        """Mid-turn: synthesize what the server holds now (an open first clause)."""
        if self._stream is None or self.final_flush:
            return
        try:
            self._flushes.append("clause")
            self.eager_flushes += 1
            await self._stream.flush()
        except Exception as exc:
            Log.warning(f"tts eager flush failed: {exc!r}")

    async def end_sentence(self) -> None:
        """A sentence was just sent: flush it, so its end is known and the pause follows it."""
        if self._stream is None or self.final_flush:
            return
        try:
            self._flushes.append("sentence")
            await self._stream.flush()
        except Exception as exc:
            Log.warning(f"tts sentence flush failed: {exc!r}")

    async def cancel(self) -> None:
        """Barge-in: drop server-side text and audio."""
        if self._stream is not None:
            try:
                await self._stream.cancel()
            except Exception as exc:
                Log.warning(f"tts cancel failed: {exc!r}")
        self.turn_done.set()

    async def wait_turn(self, timeout_s: float) -> bool:
        """Wait for `flushed` (or an error)."""
        try:
            await asyncio.wait_for(self.turn_done.wait(), timeout_s)
            return True
        except TimeoutError:
            Log.warning(f"tts flush not confirmed within {timeout_s:.0f}s")
            return False

    async def close(self) -> None:
        """Finish and tear down."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                await stream.finish()
            except Exception:
                pass
            try:
                await stream.aclose()
            except Exception:
                pass
        if self._reader is not None and not self._reader.done():
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass


class TurnPipeline:
    """ASR → responder → TTS → speaker, with timing."""

    def __init__(
        self,
        asr: ASRSession,
        tts: TTSSession,
        body: BodySession,
        responder: Responder,
        expressions: ExpressionMapper,
        asr_slot: str = "local",
        tts_slot: str = "primary",
        tts_fallback_slot: str | None = "fallback",
        shadow_asr: bool = True,
        sentence_pause_s: float = 0.3,
    ) -> None:
        self.asr = asr
        self.tts = tts
        self.body = body
        self.responder = responder
        self.expressions = expressions
        self.asr_slot = asr_slot
        self.asr_other_slot = "primary" if asr_slot == "local" else "local"
        self.tts_slot = tts_slot
        self.tts_fallback_slot = tts_fallback_slot
        self.shadow_asr = shadow_asr
        self.keeper = TTSStreamKeeper(
            tts, body, tts_slot, self._first_audio, sentence_pause_s=sentence_pause_s
        )
        self._timing: TurnTiming | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self.last_shadow: dict[str, Any] | None = None
        self._shadow_task: asyncio.Task[ASRResult] | None = None
        self._shadow_log_task: asyncio.Task[None] | None = None
        self.turns = 0
        self.current_text = ""
        self.last_raw_transcript: str | None = None

    def _first_audio(self) -> None:
        if self._timing is not None and self._timing.first_tts_audio is None:
            self._timing.first_tts_audio = time.monotonic()

    async def warm_up(self) -> None:
        """Open the TTS session ahead of the first turn."""
        await self.keeper.ensure()

    async def transcribe(self, clip: AudioClip, language: str | None) -> ASRResult:
        """Turn ASR on `asr_slot`, the other slot as fallback; optional shadow run for comparison."""
        other = self.asr_other_slot if self.asr.is_ready(self.asr_other_slot) else None
        started = time.monotonic()
        if self.shadow_asr and other is not None:
            self._shadow_task = asyncio.create_task(
                self.asr.transcribe(other, clip, language, task="turn.shadow"), name="asr-shadow"
            )
        result = await self.asr.transcribe(self.asr_slot, clip, language, task="turn")
        if not result.success and other is not None:
            Log.warning(f"asr {self.asr_slot} failed ({result.error_message}); using {other}")
            result = await self.asr.transcribe(other, clip, language, task="turn.fallback")
        if self._shadow_task is not None:
            task, self._shadow_task = self._shadow_task, None
            self._shadow_log_task = asyncio.create_task(
                self._finish_shadow(task, other or "", result, started), name="asr-shadow-log"
            )
        return result

    async def _finish_shadow(
        self, task: asyncio.Task[ASRResult], slot: str, primary: ASRResult, started: float
    ) -> None:
        try:
            shadow = await task
        except Exception as exc:
            Log.warning(f"shadow asr failed: {exc!r}")
            return
        self.last_shadow = {
            "turn_slot": self.asr_slot,
            "turn_text": primary.text,
            "turn_ms": primary.latency_ms,
            "shadow_slot": slot,
            "shadow_text": shadow.text if shadow.success else None,
            "shadow_ms": shadow.latency_ms,
            "agree": bool(
                shadow.success
                and primary.success
                and (shadow.text or "").strip() == (primary.text or "").strip()
            ),
        }
        Log.info(
            f"asr shadow: {self.asr_slot}={primary.text!r} ({primary.latency_ms and round(primary.latency_ms)} ms) "
            f"vs {slot}={shadow.text!r} ({shadow.latency_ms and round(shadow.latency_ms)} ms)"
        )

    async def run_turn(
        self,
        speaker: str,
        language: str | None,
        clip: AudioClip | None = None,
        text: str | None = None,
        speech_end: float | None = None,
        strip_name: Callable[[str], str] | None = None,
        on_text_in: Callable[[str], None] | None = None,
        on_speaking: Callable[[bool], None] | None = None,
    ) -> TurnResult:
        """Run one turn; cancellation (barge-in) is handled via `asyncio.CancelledError`."""
        self.turns += 1
        timing = TurnTiming(speech_end=speech_end)
        self._timing = timing
        text_in = (text or "").strip()
        try:
            if clip is not None and not text_in:
                result = await self.transcribe(clip, language)
                timing.asr_done = time.monotonic()
                if not result.success or not (result.text or "").strip():
                    return TurnResult(
                        False,
                        "",
                        "",
                        language,
                        timing,
                        error=result.error_message or "empty transcript",
                    )
                text_in = (result.text or "").strip()
                self.last_raw_transcript = text_in
                if strip_name is not None:
                    text_in = strip_name(text_in) or text_in
                if result.language and not language:
                    language = result.language
            else:
                timing.asr_done = time.monotonic()
            if on_text_in is not None:
                on_text_in(text_in)
            if not text_in:
                return TurnResult(False, "", "", language, timing, error="nothing to answer")
            message = ChannelMessage("voice", speaker, text_in, language=language)
            return await self.speak_reply(message, timing, on_speaking)
        except asyncio.CancelledError:
            await self.interrupt()
            return TurnResult(False, text_in, "", language, timing, interrupted=True)
        finally:
            self._timing = None

    async def speak_reply(
        self,
        message: ChannelMessage,
        timing: TurnTiming,
        on_speaking: Callable[[bool], None] | None = None,
    ) -> TurnResult:
        """Stream the responder's reply through TTS to the speaker."""
        splitter = SentenceSplitter()
        self.current_text = ""
        self.body.set_style("natural")  # a `[style:…]` tag lasts one reply
        self.keeper.begin_turn()
        self.body.begin_speech_turn()
        await self.keeper.ensure()
        spoken: list[str] = []
        sent_any = False
        pending_tags: list[str] = []
        eager: asyncio.TimerHandle | None = None
        eager_state = "first"  # → "armed" (first clause open) → "done"
        loop = asyncio.get_running_loop()

        def fire() -> None:
            nonlocal eager_state
            eager_state = "done"
            self._tasks.add(task := loop.create_task(self.keeper.flush_now()))
            task.add_done_callback(self._tasks.discard)

        try:
            async for delta in self.responder.respond(message):
                if timing.first_token is None:
                    timing.first_token = time.monotonic()
                for fragment in splitter.feed(delta):
                    final = bool(SENTENCE_FINAL.search(fragment))
                    sent = await self._say_fragment(
                        fragment, spoken, pending_tags, timing, on_speaking, final
                    )
                    sent_any |= sent
                    if not sent or eager_state == "done":
                        continue
                    if final:  # the server starts on its own
                        eager_state = "done"
                        if eager is not None:
                            eager.cancel()
                    elif eager_state == "first" and self.keeper.connected:
                        eager_state = "armed"
                        eager = loop.call_later(EAGER_FLUSH_S, fire)
        finally:
            if eager is not None:
                eager.cancel()
        rest = splitter.flush()
        if rest:  # the turn's last words: the final flush follows
            sent_any |= await self._say_fragment(rest, spoken, pending_tags, timing, on_speaking)
        text_out = " ".join(spoken).strip()
        if not sent_any:
            return TurnResult(
                True, message.text, "", message.language, timing, no_reply=not text_out
            )
        await self.keeper.flush()
        # The server synthesises faster than it speaks, but a story is a minute of audio.
        await self.keeper.wait_turn(timeout_s=max(30.0, len(text_out) / 3.0))
        # The server may acknowledge the flush before its last audio frames land; give them a moment.
        for _ in range(30):
            if self.keeper.turn_audio_bytes > 0 and self.body.speech_turn_first_push() is not None:
                break
            await asyncio.sleep(0.05)
        await asyncio.to_thread(self._wait_spoken, len(text_out))
        self.body.set_style("natural")
        timing.first_audio_out = self.body.speech_turn_first_push()
        timing.turn_end = time.monotonic()
        if on_speaking is not None:
            on_speaking(False)
        return TurnResult(True, message.text, text_out, message.language, timing)

    def _wait_spoken(self, chars: int) -> bool:
        """Block until the speaker has played what the turn queued.

        A turn is over when Bobby stops talking, not after a fixed wait: the 30 s cap this
        replaced declared a 50 s story finished 20 s early, and the session's silence timeout
        ran out while Bobby was still telling it (block #89). Bounded by the reply's length
        (no voice is slower than two characters a second) in case the player never drains.
        """
        cap = time.monotonic() + 30.0 + chars / 2.0
        while (left := cap - time.monotonic()) > 0:
            remaining = self.body.speaking_remaining_s()
            if self.body.wait_quiet(min(remaining + QUIET_MARGIN_S, left)):
                return True
        Log.warning(f"speaker still busy {30.0 + chars / 2.0:.0f}s after a turn's last audio")
        return False

    async def _say_fragment(
        self,
        fragment: str,
        spoken: list[str],
        pending_tags: list[str],
        timing: TurnTiming,
        on_speaking: Callable[[bool], None] | None,
        final: bool = False,
    ) -> bool:
        split = ExpressionMapper.split_tags(fragment)
        if split.style is not None:
            self.body.set_style(split.style)  # before the expressions, so they take its energy
        for name in split.expressions:
            self.expressions.express(name)
        clean = speakable(split.text)
        if not clean:
            return False
        if timing.first_sentence is None:
            timing.first_sentence = time.monotonic()
            if on_speaking is not None:
                on_speaking(True)
        spoken.append(clean)
        self.current_text += clean
        if await self.keeper.send(clean):
            if final:
                await self.keeper.end_sentence()
            return True
        if not await self._fallback_say(clean):
            return False
        if final:
            self.keeper.owe_pause()
        return True

    async def _fallback_say(self, text: str) -> bool:
        slot = self.tts_fallback_slot
        if slot is None or not self.tts.is_ready(slot):
            return False
        result = await self.tts.infer(slot, text, task="turn.fallback")
        clip = result.to_clip()
        if clip is None:
            Log.warning(f"fallback tts failed: {result.error_message}")
            return False
        if self._timing is not None and self._timing.first_tts_audio is None:
            self._timing.first_tts_audio = time.monotonic()
        self.keeper.play(clip)
        self.keeper.turn_done.set()
        return True

    @property
    def timing(self) -> TurnTiming | None:
        """The marks of the turn in progress (None between turns)."""
        return self._timing

    async def interrupt(self) -> None:
        """Hard stop: drop TTS text/audio and flush the speaker."""
        await self.keeper.cancel()
        self.body.stop_speaking()
        self.body.set_style("natural")

    async def close(self) -> None:
        """Tear down the TTS session."""
        await self.keeper.close()
