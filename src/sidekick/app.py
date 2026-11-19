"""sidekick.app — the runtime that assembles every module

Overview
    `App.boot()` creates the data directory, configures logging, loads and applies the config
    (service backends into the LLM / ASR / TTS / VAD sessions) and constructs every session.
    `App.start()` starts the **console** — readiness, the dashboard — and hands the **service**
    (everything Banana does) to `ServiceSession`, which starts it when the owner left it running;
    `App.stop()` stops the service and then the console; `App.run()` keeps the process alive
    until a signal arrives. `App.setup_service()` binds every runtime module to the current spec;
    the service calls it before each start (blocks #85–#87).
Design
    One composition rule for every module (invariant 21, PLAN.md block #56): this file
    constructs the sessions and calls `setup`, `start` and `stop` — no control flow, no
    closures, no wiring of its own. Whatever a module hooks into a peer (tools into the agent, a
    subscription on the perception bus, an adapter into the channel registry, its own
    housekeeping) happens inside that module's `setup` / `start` and is undone by its `stop`.
    Every session exists before any is set up, so a module can be handed a bound method of a
    peer set up later (the agent gets the voice front end's `speak` / `can_speak`, the
    recorder its `telemetry`). The process and the service have separate lifecycles (block
    #82): the dashboard lives as long as the process, and the runtime modules are started and
    stopped by the service, in the order given here — the body first, because perception, the
    recorder and the voice front end look at whether it connected; extensions last, so their
    tools see every peer — and in reverse. The sessions are singletons for the whole process
    (block #83): a restart runs `setup_service` and the modules' `start` again on the same
    objects. `*Session.shared` instances are replaced with the app's own so every module sees
    one storage home.
Depends on
    every sidekick module.
"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from pathlib import Path

from sidekick import __version__
from sidekick.agent import AgentSession
from sidekick.asr import ASRSession
from sidekick.automation import AutomationSession
from sidekick.body import BodySession
from sidekick.channel import ChannelSession
from sidekick.config import ConfigSession, ConfigSpec
from sidekick.contact import ContactSession
from sidekick.dashboard import DashboardContext, DashboardSession
from sidekick.doctor import DoctorSession
from sidekick.extension import ExtensionSession
from sidekick.interaction import InteractionSession
from sidekick.llm import LLMSession
from sidekick.log import Log, configure_logging
from sidekick.perception import PerceptionSession
from sidekick.record import RecordSession, RecordSettings
from sidekick.service import ServiceSession
from sidekick.storage import StorageSession
from sidekick.tts import TTSSession
from sidekick.vad import VADSession

BUNDLED_EXTENSIONS = Path(__file__).resolve().parents[2] / "extensions"


class AppNotInitialized(RuntimeError):
    """No config spec yet (`sidekick startup` writes a first one)."""


@dataclass(frozen=True, slots=True)
class AppHealth:
    """What `boot()` established."""

    version: str
    home: Path
    slots: dict[str, str] = field(default_factory=dict)

    def lines(self) -> list[str]:
        """Printable summary."""
        out = [f"sidekick {self.version}", f"home: {self.home}"]
        out.extend(f"slot {name}: {binding}" for name, binding in sorted(self.slots.items()))
        return out


class App:
    """The process."""

    def __init__(self, home: Path | None = None, log_level: str = "INFO") -> None:
        self.storage = StorageSession(home)
        StorageSession.shared = self.storage
        self.config = ConfigSession(self.storage)
        ConfigSession.shared = self.config
        self.log_level = log_level
        self.spec: ConfigSpec | None = None
        self.health: AppHealth | None = None

    def boot(self) -> AppHealth:
        """Create the home, configure logging, load and apply the spec, construct the sessions."""
        layout = self.storage.ensure_layout()
        configure_logging(self.log_level, layout.logs_dir)
        Log.info0(f"sidekick {__version__} home={layout.home}")
        spec = self.config.load()
        if spec is None:
            raise AppNotInitialized(f"no config at {layout.config_path}; run `sidekick startup`")
        self.spec = spec
        slots = self.config.apply(spec)
        self.health = AppHealth(__version__, layout.home, slots)
        self.construct(spec)
        return self.health

    # ------------------------------------------------------------------ wiring

    def construct(self, spec: ConfigSpec) -> None:
        """Every session exists before any is set up."""
        self.body = BodySession.make(spec.body, self.storage.layout.home, spec.robot.name.lower())
        self.contacts = ContactSession()
        self.perception = PerceptionSession()
        self.agent = AgentSession(LLMSession.shared)
        self.automation = AutomationSession()
        self.channels = ChannelSession()
        self.interaction = InteractionSession()
        self.record = RecordSession()
        self.extensions = ExtensionSession()
        self.doctor = DoctorSession(self.config, self.storage)
        self.dashboard = DashboardSession()
        self.service = ServiceSession()
        BodySession.shared = self.body
        ContactSession.shared = self.contacts
        PerceptionSession.shared = self.perception
        AgentSession.shared = self.agent
        AutomationSession.shared = self.automation
        ChannelSession.shared = self.channels
        InteractionSession.shared = self.interaction
        RecordSession.shared = self.record
        ExtensionSession.shared = self.extensions
        DoctorSession.shared = self.doctor
        DashboardSession.shared = self.dashboard
        ServiceSession.shared = self.service

    def setup_service(self) -> None:
        """Bind every runtime module to the current spec (the service, before each start)."""
        spec = self.config.spec
        assert spec is not None
        layout = self.storage.layout
        self.body.setup(spec.body, layout.home, spec.robot.name.lower())
        self.contacts.setup(
            layout.db_path("contact"),
            layout.models_dir,
            spec.contacts,
            synthesize=TTSSession.shared.synthesize,
            voice=TTSSession.shared.voice,
            language=spec.languages.default,
        )
        self.perception.setup(
            self.body, layout.db_path("events"), spec.perception, contacts=self.contacts
        )
        self.agent.setup(
            home=layout.home,
            agents=spec.agents,
            default_language=spec.languages.default,
            say=self.interaction.speak,
            can_speak=self.interaction.can_speak,
            contacts=self.contacts,
        )
        self.automation.setup(
            layout.db_path("automation"), spec.automation, self.agent, self.perception
        )
        self.channels.setup(
            self.agent.handle,
            spec.channels,
            spec.credentials,
            layout.home,
            on_telegram_paired=self.config.telegram_paired,
        )
        self.record.setup(
            RecordSettings.from_config(spec.recording, layout.recordings_dir),
            self.body,
            extra=self.interaction.telemetry,
        )
        self.interaction.setup(
            self.body,
            ASRSession.shared,
            TTSSession.shared,
            VADSession.shared,
            spec.interaction,
            spec.robot,
            self.agent,
            trace_path=layout.db_path("interaction_trace"),
            audio_dir=layout.audio_dir,
            default_language=spec.interaction.language or spec.languages.default,
            contacts=self.contacts,
            perception=self.perception,
            quiet_hours=spec.automation.quiet_hours,
            channels=self.channels,
            clip_source=self.record.mic_reader(),
        )
        self.extensions.setup(
            layout.db_path("extension"),
            BUNDLED_EXTENSIONS,
            layout.extensions_dir,
            layout.home / "extension_state",
            self.agent,
            self.perception,
            automation=self.automation,
            spec=spec,
            body=self.body,
            contacts=self.contacts,
            interaction=self.interaction,
            llm=LLMSession.shared,
            vision=self.config.slot_supports("llm", "smart", "vision"),
        )

    async def start(self) -> None:
        """Start the console (readiness, the dashboard), then the service when it was left on."""
        spec = self.spec
        assert spec is not None
        layout = self.storage.layout
        self.doctor.setup(
            body=self.body,
            interaction=self.interaction,
            contacts=self.contacts,
            record=self.record,
            service=self.service,
        )
        self.service.setup(
            config=self.config,
            state_path=layout.service_path,
            prepare=self.setup_service,
            modules=[
                ("body", self.body),
                ("contacts", self.contacts),
                ("channels", self.channels),
                ("interaction", self.interaction),
                ("agent", self.agent),
                ("automation", self.automation),
                ("perception", self.perception),
                ("record", self.record),
                ("extensions", self.extensions),
            ],
            prerequisites=self.doctor.prerequisites,
            models=self.doctor.ensure_models,
        )
        self.dashboard.setup(
            DashboardContext(
                self.config,
                spec,
                body=self.body,
                interaction=self.interaction,
                agent=self.agent,
                automation=self.automation,
                perception=self.perception,
                channels=self.channels,
                contacts=self.contacts,
                extensions=self.extensions,
                record=self.record,
                log_path=layout.logs_dir / "sidekick.log",
                doctor=self.doctor,
                service=self.service,
            ),
            spec.dashboard.host,
            spec.dashboard.port,
        )
        await self.dashboard.start()
        await self.doctor.start()
        await self.service.start()

    async def stop(self) -> None:
        """Stop the service (the robot turns off), then the console."""
        Log.info0()
        await self.service.stop()
        await self.dashboard.stop()

    async def run(self) -> None:
        """Boot, start, then stay up until SIGINT/SIGTERM."""
        health = self.boot()
        for line in health.lines():
            Log.info(line)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # pragma: no cover - windows
                pass
        try:
            await self.start()
            Log.info("running; `sidekick close` stops it")
            await stop.wait()
        finally:
            Log.info("stopping")
            await self.stop()
