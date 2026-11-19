"""sidekick.asr.sherpa_kws — open-vocabulary keyword spotting (the wake name) via sherpa-onnx

Overview
    A recognizer whose whole vocabulary is the robot's name: the zipformer keyword-spotting
    model (`sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`, ~3 M parameters, English phones +
    Mandarin pinyin) scans a clip for the configured keyword token sequences and
    `transcribe()` returns the matched labels (e.g. `"banana"`) or an empty text. It complements
    SenseVoice name spotting: each hears what the other misses. With the first name, "Bobby",
    SenseVoice heard it through a speaker one time in three while this model caught every clean
    utterance (PLAN.md block #13); with "Banana" SenseVoice writes the name nearly every time
    and this model finds 40 of 55 synthesized utterances, missing the Mandarin-accented ones
    (block #94).
Design
    Same shape as every ASR backend (`*Configuration` + `transcribe(clip) -> ASRResult`,
    invariant 4) so it binds to the `asr.kws` slot through the ordinary `match api`. Keywords are
    declarative token lines in the sherpa format (`B AH0 N AE1 N AH0 @banana`; pinyin tokens
    work the same way, `b ā n à n à @label`) taken from `robot.keywords`; the backend writes them
    to a keywords file next to the model. English words are looked up in the model's `en.phone`
    lexicon when a keyword is given as plain text (`banana @banana`). Decoding runs in a worker
    thread; a pooled spotter is reused per thread.
    `spot_stream()` offers incremental spotting for a future always-on mode.
Depends on
    sidekick.log, sidekick.storage, sidekick.audio, numpy, sherpa-onnx (lazy).

See Also
--------
    AGENTS.md "Interaction" trigger 1 (`wake_name`), PLAN.md blocks "[2026-10-26 #13]",
    "[2026-11-20 #94]".

"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from sidekick.audio import AudioClip
from sidekick.log import Log
from sidekick.storage import StorageSession

from .schemas import ASRResult

API_NAME = "sherpa_kws"
MODEL_NAME = "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
MODEL_URL = (
    f"https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/{MODEL_NAME}.tar.bz2"
)
DEFAULT_KEYWORDS: tuple[str, ...] = (
    "B AH0 N AE1 N AH0 @banana",
    "B AH0 N AA1 N AH0 @banana",
)


@dataclass(frozen=True, slots=True)
class ASRKeywordConfiguration:
    """Model directory, keyword lines and detector sensitivity."""

    model_dir: Path
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS
    keywords_score: float = 1.5
    keywords_threshold: float = 0.25
    num_trailing_blanks: int = 1
    num_threads: int = 1
    chunk: int = 16
    pad_s: float = 0.3
    provider: str = "local"
    extra: dict[str, Any] = field(default_factory=dict)


class ASRKeywordBackend:
    """Keyword-only recognizer."""

    def __init__(self, configuration: ASRKeywordConfiguration) -> None:
        self.configuration = configuration
        self._spotter: Any = None
        self._lock = threading.Lock()
        self._keywords_path: Path | None = None

    @staticmethod
    def ensure_model(models_dir: Path) -> Path:
        """Download and extract the model if needed."""
        return StorageSession.shared.ensure_download(
            MODEL_URL, models_dir / f"{MODEL_NAME}.tar.bz2", extract=True
        )

    @staticmethod
    def model_present(models_dir: Path) -> bool:
        """Whether the model files exist."""
        return (models_dir / MODEL_NAME / "tokens.txt").exists()

    def preload(self) -> None:
        """Load the spotter now (the service's start), not on the first segment."""
        self._load()

    @property
    def loaded(self) -> bool:
        """Whether the spotter is in memory."""
        return self._spotter is not None

    def close(self) -> None:
        """Drop the spotter (the slot was replaced or the service stopped)."""
        with self._lock:
            self._spotter = None

    # ---------------------------------------------------------------- keywords

    def _lexicon(self) -> dict[str, str]:
        path = self.configuration.model_dir / "en.phone"
        table: dict[str, str] = {}
        if not path.exists():
            return table
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                word, _, phones = line.strip().partition(" ")
                if word and phones:
                    table.setdefault(word.upper(), phones.strip())
        return table

    def keyword_lines(self) -> list[str]:
        """Resolve plain English words through the lexicon; pass token lines through."""
        lexicon: dict[str, str] | None = None
        lines: list[str] = []
        for raw in self.configuration.keywords:
            text = raw.strip()
            if not text:
                continue
            body, _, label = text.partition("@")
            tokens = body.strip().split()
            if tokens and all(
                token.isalpha() and token.islower() and token.isascii() for token in tokens
            ):
                if lexicon is None:
                    lexicon = self._lexicon()
                phones = [lexicon.get(token.upper()) for token in tokens]
                if all(phones):
                    body = " ".join(p for p in phones if p)
                else:
                    Log.warning(f"keyword {raw!r}: word not in lexicon; skipped")
                    continue
            lines.append(body.strip() + (f" @{label.strip()}" if label.strip() else ""))
        return lines

    def _write_keywords(self) -> Path:
        path = self.configuration.model_dir / "sidekick_keywords.txt"
        lines = self.keyword_lines()
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        Log.info(f"{len(lines)} keyword line(s) -> {path.name}")
        return path

    def _load(self) -> Any:
        with self._lock:
            if self._spotter is None:
                import sherpa_onnx

                cfg = self.configuration
                d = cfg.model_dir
                if not (d / "tokens.txt").exists():
                    raise FileNotFoundError(f"kws model missing: {d}")
                self._keywords_path = self._write_keywords()
                started = time.monotonic()
                self._spotter = sherpa_onnx.KeywordSpotter(
                    tokens=str(d / "tokens.txt"),
                    encoder=str(d / f"encoder-epoch-13-avg-2-chunk-{cfg.chunk}-left-64.int8.onnx"),
                    decoder=str(d / f"decoder-epoch-13-avg-2-chunk-{cfg.chunk}-left-64.onnx"),
                    joiner=str(d / f"joiner-epoch-13-avg-2-chunk-{cfg.chunk}-left-64.int8.onnx"),
                    keywords_file=str(self._keywords_path),
                    num_threads=cfg.num_threads,
                    keywords_score=cfg.keywords_score,
                    keywords_threshold=cfg.keywords_threshold,
                    num_trailing_blanks=cfg.num_trailing_blanks,
                )
                Log.info(f"loaded keyword spotter in {(time.monotonic() - started) * 1000:.0f}ms")
            return self._spotter

    # ---------------------------------------------------------------- spotting

    def spot(self, clip: AudioClip) -> list[str]:
        """Synchronous: labels of keywords found in the clip."""
        spotter = self._load()
        cfg = self.configuration
        pad = np.zeros(int(cfg.pad_s * clip.sample_rate), dtype=np.float32)
        samples = np.concatenate([pad, clip.samples.astype(np.float32, copy=False), pad])
        stream = spotter.create_stream()
        stream.accept_waveform(clip.sample_rate, samples)
        stream.input_finished()
        hits: list[str] = []
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            result = spotter.get_result(stream)
            if result:
                hits.append(str(result))
                spotter.reset_stream(stream)
        return hits

    async def transcribe(self, clip: AudioClip, language: str | None = None) -> ASRResult:
        """Keyword labels as text (space separated), empty when none."""
        started = time.monotonic()
        try:
            hits = await asyncio.to_thread(self.spot, clip)
        except Exception as exc:
            Log.error(f"kws failed: {exc!r}")
            return ASRResult(
                False,
                None,
                self.configuration.provider,
                API_NAME,
                MODEL_NAME,
                "-",
                language=language,
                duration_s=clip.duration_s,
                error_message=repr(exc),
                latency_ms=(time.monotonic() - started) * 1000.0,
            )
        latency = (time.monotonic() - started) * 1000.0
        if hits:
            Log.info(f"keyword(s) {hits} in {clip.duration_s:.2f}s clip, {latency:.0f}ms")
        return ASRResult(
            True,
            " ".join(hits),
            self.configuration.provider,
            API_NAME,
            MODEL_NAME,
            "-",
            language=language,
            duration_s=clip.duration_s,
            latency_ms=latency,
        )

    def spot_stream(self) -> KeywordStream:
        """An incremental spotter for always-on use."""
        return KeywordStream(self._load())


class KeywordStream:
    """Feed chunks, get keyword labels as they are spotted."""

    def __init__(self, spotter: Any) -> None:
        self._spotter = spotter
        self._stream = spotter.create_stream()

    def feed(self, samples: np.ndarray, sample_rate: int = 16000) -> list[str]:
        """Push audio; returns labels spotted so far in this call."""
        self._stream.accept_waveform(sample_rate, np.asarray(samples, dtype=np.float32))
        hits: list[str] = []
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            result = self._spotter.get_result(self._stream)
            if result:
                hits.append(str(result))
                self._spotter.reset_stream(self._stream)
        return hits
