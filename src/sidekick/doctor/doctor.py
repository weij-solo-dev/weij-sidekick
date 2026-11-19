"""sidekick.doctor.doctor — DoctorSession: is Banana ready, and what is missing?

Overview
    The readiness list that replaced the first-run wizard (PLAN.md block #44). One function
    answers "can Banana hold a conversation right now, and if not, what do I fix where?" for the
    dashboard (rail card, sidebar dots, the Live empty state, the System page) and for the
    service's start gate. Three layers, cheapest first:

    - **local** — the **prerequisites** (Python, the config, every bound slot's provider and
      credentials, free disk: what must hold before Banana starts, the start's first step) and
      the on-host models, then — while the service runs — every module's own `check()` items
      (the robot's daemon / link / camera / microphone, the voice front end, the agent's model
      call, contacts, channels, recording, extensions; block #86), collected through the
      service. No network, no side effects, < 1 s; cached for `LOCAL_TTL_S` so the 1 Hz health
      poll can show it. While stopped the report holds the prerequisites and models only.
    - **probe** — one real call per slot through `ConfigSession.probe` (the same call the CLI
      and the service cards use); costs API calls, so only on demand.
    - **loopback** — a 0.6 s tone through the speaker while the microphone listens (speaker,
      microphone and audio DSP in one go) and the camera frame's brightness; the voice front end
      is held meanwhile so the tone is not taken for speech.
Design
    Layer 5 like `app` and `cli`: it may import any module, nothing imports it except those.
    Items are plain data (`schemas.py`): a level (`ok` / `warn` / `bad`), a detail and the tab
    that fixes them; `ready` is "no `bad` row", `warn` rows are advice. The layers are kept
    separately and concatenated into one report, so a probe result stays visible next to the
    refreshed local rows until the next probe. `run()` refuses to overlap itself (the report says
    which layer is running). The probe callable is injectable for tests. `start()` logs the local
    summary and every failing row, so a missing key or model is named in the terminal too.
    `ensure_models()` downloads the models that are missing (the start's second step); the
    service calls `prerequisites()` and `ensure_models()` through the bound methods `app.py`
    hands it, so the two sessions never import each other.
Depends on
    sidekick.log, sidekick.storage, sidekick.config, sidekick.audio, sidekick.body, sidekick.asr,
    sidekick.llm, sidekick.tts, sidekick.vad, sidekick.contact, numpy.

See Also
--------
    AGENTS.md "Readiness", PLAN.md block "[2026-10-27 #44]".

"""

from __future__ import annotations

import asyncio
import math
import queue
import shutil
import sys
import time
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from sidekick.asr import ASRKeywordBackend, ASRSenseVoiceBackend
from sidekick.audio import tone
from sidekick.body import BodySession, FloatArray
from sidekick.config import ConfigProbeOutcome, ConfigSession, ConfigSpec, load_catalog
from sidekick.contact import FaceIdentifier, VoiceIdentifier
from sidekick.log import Log
from sidekick.storage import StorageSession
from sidekick.vad import VADSileroBackend

from .schemas import LAYERS, DoctorItem, DoctorReport

ProbeFn = Callable[[ConfigSpec], Awaitable[dict[str, ConfigProbeOutcome]]]
SAMPLE_RATE = 16000
SLOT_TABS = {"llm": "agent", "asr": "voice", "tts": "voice", "vad": "voice"}
SLOT_TITLES = {"llm": "LLM slots", "asr": "ASR slots", "tts": "TTS slots", "vad": "VAD slot"}


def _dbfs(samples: FloatArray) -> float:
    if len(samples) == 0:
        return -100.0
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return 20.0 * math.log10(rms) if rms > 1e-6 else -100.0


class DoctorSession:
    """Owns the last report and runs the layers."""

    shared: ClassVar[DoctorSession]

    LOCAL_TTL_S = 5.0
    MIN_FREE_GB = 2.0
    DARK_FRAME = 25.0  # mean 8-bit brightness below which YuNet finds nothing (measured 19)
    LOOPBACK_RISE_DB = 3.0  # the DSP cancels most of the echo; a few dB is all that gets through
    TONE_S = 0.6
    PRE_S = 0.4
    POST_S = 0.3

    def __init__(
        self, config: ConfigSession | None = None, storage: StorageSession | None = None
    ) -> None:
        self.config = config or ConfigSession.shared
        self.storage = storage or StorageSession.shared
        self.body: BodySession | None = None
        self.interaction: Any = None
        self.contacts: Any = None
        self.record: Any = None
        self.service: Any = None
        self._probe_fn: ProbeFn | None = None
        self._layers: dict[str, list[DoctorItem]] = {}
        self._local_at = 0.0
        self._ts = 0.0
        self._running: str | None = None

    def setup(
        self,
        *,
        body: BodySession | None = None,
        interaction: Any = None,
        contacts: Any = None,
        record: Any = None,
        service: Any = None,
        probe: ProbeFn | None = None,
    ) -> None:
        """Hand over the peers the checks look at (all optional)."""
        self.body = body
        self.interaction = interaction
        self.contacts = contacts
        self.record = record
        self.service = service
        self._probe_fn = probe

    @property
    def spec(self) -> ConfigSpec | None:
        """The current spec (follows every save)."""
        return self.config.spec

    async def start(self) -> None:
        """Log the local summary: the last lines of the start-up log name what blocks Banana."""
        report = self.local(force=True)
        Log.info(f"readiness: {report.summary()} (details on the dashboard's System page)")
        for item in report.items:
            if not item.ok:
                Log.warning(f"readiness {item.level}: {item.title}: {item.detail} → {item.tab}")

    # ------------------------------------------------------------------ reports

    def report(self) -> DoctorReport:
        """The layers run so far, concatenated in layer order."""
        items: list[DoctorItem] = []
        layers: list[str] = []
        for layer in LAYERS:
            if layer in self._layers:
                items.extend(self._layers[layer])
                layers.append(layer)
        service = str(self.service.state) if self.service is not None else None
        return DoctorReport(self._ts, tuple(items), tuple(layers), self._running, service)

    def local(self, force: bool = False) -> DoctorReport:
        """Refresh the local layer when its cache is stale (or `force`) and return the report."""
        now = time.monotonic()
        if force or "local" not in self._layers or now - self._local_at > self.LOCAL_TTL_S:
            self._layers["local"] = self._local_items()
            self._local_at = now
            self._ts = time.time()
        return self.report()

    def live(self) -> dict[str, Any]:
        """The last verdict for the Live page, without running a check (memory only)."""
        report = self.report()
        failing = [item for item in report.items if item.level != "ok"]
        return {
            "ready": report.ready,
            "summary": report.summary(),
            "bad": report.bad,
            "warn": report.warn,
            "failing": [
                {"title": item.title, "level": item.level, "tab": item.tab} for item in failing[:4]
            ],
            "checked_s": round(time.time() - report.ts) if report.ts else None,
        }

    def snapshot(self) -> dict[str, Any]:
        """What the health poll carries: the verdict plus the rows that need attention."""
        return self.local().as_dict(failing_only=True)

    async def run(self, layers: Iterable[str] = LAYERS) -> DoctorReport:
        """Run the requested layers in order; a run already in progress is not doubled."""
        wanted = [layer for layer in LAYERS if layer in set(layers)]
        if self._running is not None:
            return self.report()
        try:
            for layer in wanted:
                self._running = layer
                if layer == "local":
                    self.local(force=True)
                elif layer == "probe":
                    self._layers["probe"] = await self.probe()
                else:
                    self._layers["loopback"] = await self.loopback()
                self._ts = time.time()
        finally:
            self._running = None
        report = self.report()
        Log.info(f"readiness ({', '.join(wanted)}): {report.summary()}")
        return report

    # ------------------------------------------------------------------ local layer

    def prerequisites(self) -> list[DoctorItem]:
        """What must hold before Banana starts (the start's first step, block #84).

        Python, the config, every bound slot's provider and credentials, free disk.
        """
        version = sys.version.split()[0]
        items = [
            DoctorItem(
                "python",
                "Python 3.12",
                "ok" if sys.version_info[:2] == (3, 12) else "bad",
                version,
                "system",
            )
        ]
        spec = self.spec
        if spec is None:
            items.append(DoctorItem("config", "config.json", "bad", "missing", "system"))
            return items
        items.extend(self._slot_items(spec))
        items.extend(self._disk_items())
        return items

    async def ensure_models(
        self, progress: Callable[[str], None] | None = None
    ) -> list[DoctorItem]:
        """Download the on-host models that are missing (the start's second step)."""
        models = self.storage.layout.models_dir
        wanted: list[tuple[str, Callable[[Path], bool], Callable[[Path], Any]]] = [
            (
                "Silero VAD",
                lambda m: (m / "silero_vad.onnx").exists(),
                VADSileroBackend.ensure_model,
            ),
            ("SenseVoice", ASRSenseVoiceBackend.model_present, ASRSenseVoiceBackend.ensure_model),
            ("keyword spotter", ASRKeywordBackend.model_present, ASRKeywordBackend.ensure_model),
            ("speaker (CAM++)", VoiceIdentifier.model_present, VoiceIdentifier.ensure_model),
            ("face (YuNet + SFace)", FaceIdentifier.models_present, FaceIdentifier.ensure_models),
        ]
        for name, present, fetch in wanted:
            if present(models):
                continue
            if progress is not None:
                progress(f"downloading {name}…")
            try:
                await asyncio.to_thread(fetch, models)
            except Exception as exc:  # the items below name what is still missing
                Log.error(f"model download {name}: {exc!r}")
        return self._model_items()

    def _local_items(self) -> list[DoctorItem]:
        items = self.prerequisites()
        if self.spec is None:
            return items
        items.extend(self._model_items())
        service = self.service
        if service is not None and service.running:
            items.extend(self._module_items(service.checks()))
        return items

    @staticmethod
    def _module_items(checks: list[dict[str, Any]]) -> list[DoctorItem]:
        """The running modules' check items as readiness rows (`off` = not configured: ok)."""
        return [
            DoctorItem(
                str(check.get("id", "module")),
                str(check.get("title", "")),
                "ok" if check.get("level") in ("ok", "off", None) else str(check["level"]),
                str(check.get("detail", "")),
                str(check.get("tab", "system")),
            )
            for check in checks
        ]

    def _model_items(self) -> list[DoctorItem]:
        models = self.storage.layout.models_dir
        speech = {
            "Silero VAD": (models / "silero_vad.onnx").exists(),
            "SenseVoice": ASRSenseVoiceBackend.model_present(models),
            "keyword spotter": ASRKeywordBackend.model_present(models),
        }
        identify = {
            "speaker (CAM++)": VoiceIdentifier.model_present(models),
            "face (YuNet + SFace)": FaceIdentifier.models_present(models),
        }
        missing = [name for name, present in speech.items() if not present]
        items = [
            DoctorItem(
                "models.speech",
                "speech models",
                "bad" if missing else "ok",
                f"missing: {', '.join(missing)} (downloaded when Banana starts)"
                if missing
                else " · ".join(speech),
                "voice",
            )
        ]
        missing = [name for name, present in identify.items() if not present]
        items.append(
            DoctorItem(
                "models.identify",
                "identification models",
                "warn" if missing else "ok",
                f"missing: {', '.join(missing)} (downloaded on first use)"
                if missing
                else " · ".join(identify),
                "contact",
            )
        )
        return items

    def _slot_items(self, spec: ConfigSpec) -> list[DoctorItem]:
        catalog = load_catalog()
        items: list[DoctorItem] = []
        for kind, title in SLOT_TITLES.items():
            problems: list[str] = []
            bound: list[str] = []
            for slot_kind, name, slot in spec.bound_slots():
                if slot_kind != kind:
                    continue
                key = f"{kind}.{name}"
                bound.append(f"{name} → {slot.provider}")
                preset = catalog.get(slot.provider)
                if preset is None:
                    problems.append(f"{key}: unknown provider {slot.provider!r}")
                    continue
                have = spec.credentials.get(slot.provider, {})
                missing = [f for f in preset.credential_fields() if not have.get(f)]
                if missing:
                    problems.append(f"{key}: {slot.provider} {', '.join(missing)} missing")
            if not bound:
                problems.append("no slot bound")
            items.append(
                DoctorItem(
                    f"slots.{kind}",
                    title,
                    "bad" if problems else "ok",
                    "; ".join(problems) if problems else " · ".join(bound),
                    SLOT_TABS[kind],
                )
            )
        return items

    def _disk_items(self) -> list[DoctorItem]:
        items: list[DoctorItem] = []
        try:
            free_gb = shutil.disk_usage(self.storage.layout.home).free / 1e9
            items.append(
                DoctorItem(
                    "disk",
                    "free disk",
                    "ok" if free_gb > self.MIN_FREE_GB else "bad",
                    f"{free_gb:.1f} GB",
                    "system",
                )
            )
        except OSError as exc:
            items.append(DoctorItem("disk", "free disk", "warn", repr(exc), "system"))
        return items

    # ------------------------------------------------------------------ probe layer

    async def probe(self) -> list[DoctorItem]:
        """One real call per bound slot."""
        spec = self.spec
        if spec is None:
            return [DoctorItem("probe", "service probe", "bad", "no config", "system", "probe")]
        probe = self._probe_fn or self.config.probe
        outcomes = await probe(spec)
        self.config.save(spec)  # the probe may have resolved a provider's region
        items: list[DoctorItem] = []
        for key, outcome in outcomes.items():
            kind = key.split(".", 1)[0]
            target = "/".join(x for x in (outcome.provider, outcome.model) if x)
            detail = (outcome.message or outcome.kind)[:160]
            if target:
                detail = f"{target} · {detail}" if outcome.ok else f"{detail} ({target})"
            items.append(
                DoctorItem(
                    f"probe.{key}",
                    key,
                    "ok" if outcome.ok else "bad",
                    detail,
                    SLOT_TABS.get(kind, "system"),
                    "probe",
                    outcome.latency_ms,
                )
            )
        if not items:
            items.append(
                DoctorItem("probe", "service probe", "bad", "no slot bound", "system", "probe")
            )
        return items

    # ------------------------------------------------------------------ loopback layer

    async def loopback(self) -> list[DoctorItem]:
        """Speaker → microphone and the camera, with the voice front end parked."""
        body = self.body
        if body is None or not body.status().connected:
            return [
                DoctorItem(
                    "loop.body", "speaker → microphone", "warn", "no body", "body", "loopback"
                )
            ]
        held = False
        if self.interaction is not None and getattr(self.interaction, "started", False):
            await self.interaction.hold("readiness check")
            held = True
        try:
            return await asyncio.to_thread(self._loopback_blocking, body)
        finally:
            if held:
                self.interaction.release_hold()

    def _loopback_blocking(self, body: BodySession) -> list[DoctorItem]:
        items: list[DoctorItem] = []
        q = body.subscribe_audio()
        pieces: list[FloatArray] = []

        def collect(seconds: float) -> None:
            deadline = time.monotonic() + seconds
            while q is not None and time.monotonic() < deadline:
                try:
                    pieces.append(q.get(timeout=0.05))
                except queue.Empty:
                    continue

        try:
            collect(self.PRE_S)
            started = time.monotonic()
            body.begin_speech_turn()
            body.speak(tone(self.TONE_S))
            collect(self.TONE_S + self.POST_S)
            drained = body.wait_quiet(self.TONE_S + 3.0)
            played_in = time.monotonic() - started
        finally:
            if q is not None:
                body.unsubscribe_audio(q)
        items.append(
            DoctorItem(
                "loop.speaker",
                "speaker",
                "ok" if drained else "bad",
                f"tone played in {played_in:.1f} s" if drained else "the tone did not drain",
                "body",
                "loopback",
            )
        )
        samples = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)
        pre_n = int(self.PRE_S * SAMPLE_RATE)
        tone_n = int(self.TONE_S * SAMPLE_RATE)
        if q is None or len(samples) < pre_n + tone_n // 2:
            items.append(
                DoctorItem(
                    "loop.mic",
                    "microphone hears the speaker",
                    "warn",
                    "no microphone capture"
                    if q is None
                    else f"only {len(samples) / SAMPLE_RATE:.1f} s of audio arrived",
                    "body",
                    "loopback",
                )
            )
        else:
            before = _dbfs(samples[:pre_n])
            during = _dbfs(samples[pre_n : pre_n + tone_n])
            rise = during - before
            heard = rise >= self.LOOPBACK_RISE_DB
            items.append(
                DoctorItem(
                    "loop.mic",
                    "microphone hears the speaker",
                    "ok" if heard else "warn",
                    f"{before:.0f} → {during:.0f} dBFS ({rise:+.0f} dB)"
                    + (
                        ""
                        if heard
                        else " · tone not heard: check the volume (the DSP cancels echo)"
                    ),
                    "body",
                    "loopback",
                )
            )
        frame = body.frame(wait_s=0.5)
        if frame is None:
            items.append(
                DoctorItem("loop.camera", "camera", "warn", "no frame", "body", "loopback")
            )
        else:
            mean = float(np.mean(frame))
            dark = mean < self.DARK_FRAME
            items.append(
                DoctorItem(
                    "loop.camera",
                    "camera",
                    "warn" if dark else "ok",
                    f"mean brightness {mean:.0f}/255 · {body.camera_fps():.0f} fps"
                    + (" · too dark for faces, add light" if dark else ""),
                    "body",
                    "loopback",
                )
            )
        return items
