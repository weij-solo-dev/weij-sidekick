# sidekick Agent Guide

This file is the harness for coding agents working in this repository. Read it in full before
touching code. `CLAUDE.md` only points here. Developers read `README.md` / `README_CN.md`. Every
plan item, discussion record and research note lives in `PLAN.md`, newest block first.

## Scope

sidekick is a desktop home-butler agent service. A Reachy Mini robot is its body; its brain runs on
a Mac mini or a Raspberry Pi. It is OpenClaw-like in shape: one always-on process, pluggable
channels, a self-built agent runtime with tools / MCP / skills, memory, automations and a heartbeat.
Target hardware is Reachy Mini **Lite** first (USB-tethered, daemon on the host) and Reachy Mini
**Wireless** later (daemon on the robot's CM4).

Current context (2026-10-26): development happens on the owner's Mac with the Lite connected over
USB. The robot is named **Banana** (it was "Bobby" until 2026-11-20, block #94); the name is the
wake name and is fixed by the code, not configurable. MiniMax is the first
provider for LLM, ASR and TTS, used in streaming form where the vendor offers one; every service
slot (LLM, ASR, TTS, VAD) can be bound to a different provider later (ElevenLabs, local models,
…). Spoken languages are Mandarin first, then English and Cantonese (Cantonese came first
until block #94). Channels
are Telegram and WeChat (personal WeChat through Tencent's iLink bot protocol). The project is a
product prototype for one household, not published to any store; there is a single interaction
mode for every family member, and guests may talk to the robot. First-run setup (provider keys,
languages, member enrollment, TV zone, channel pairing) is driven by a **readiness list**, not a
wizard: the dashboard's System page says what is missing and on which tab to fix it, and every tab owns
its own parameters (block #44).
Touch input is the antennas; head-touch detection is deferred (no touch sensor, no IMU on Lite).

## Non-negotiable principles

1. **Keep complexity low.** Prefer the standard library and a few vetted packages. Prefer one
   mechanism over two. If a feature can be an extension instead of a core module, make it one.
2. **The `agent` module is fully self-built.** No LangChain, LlamaIndex, AutoGen or similar. MCP
   uses the official `mcp` Python SDK only as a transport client.
3. **The provider framework mirrors weij-scoop** (`/Users/weij/Workspaces/weij-scoop`, Swift):
   declarative provider presets, a thin user spec, `apply()` that merges them into backends, a
   fixed backend shape, one `Session` per service, every model call traced. Section
   "Provider framework" below is the Python rendering of that design, extended to four services
   (`llm`, `asr`, `tts`, `vad`) with named slots, where local models are just another provider.
4. **Poetry + Python 3.12 + src layout.** `pyproject.toml` uses the PEP 621 `[project]` table;
   `requires-python = ">=3.12,<3.13"` to match the robot's `apps_venv`.
5. **Documentation lives in exactly four places:** this file, `PLAN.md`, `README*.md`, and the
   docstring header of every module file. There is no `docs/` directory.
6. **English everywhere** — code, comments, docstrings, logs, `AGENTS.md`, `PLAN.md`, `README.md`.
   `README_CN.md` is the only Chinese file.
7. **Never drive the robot from the agent.** The agent emits messages and named expressions; the
   `interaction` module turns them into speech and motion through a single control owner.
8. **Everything beyond the core is an extension.** Integrations (media center, Home Assistant,
   news, robot tools) are packaged as extensions that contribute tools, MCP servers, skills,
   subagent profiles and watchers through one protocol, and are managed (CRUD) on the dashboard.
9. **Secrets never enter chat, docs or the repository.** Credentials go into
   `.derived_data/config.json` (mode 0600) through the CLI or the dashboard, and are masked in
   every log line and trace row.
10. **Run from the repository root.** All runtime state lives in `./.derived_data/` (git-ignored);
    `SIDEKICK_HOME` overrides the location.

## Repository layout

```text
weij-sidekick/
├── AGENTS.md            harness + module yellow pages (this file)
├── CLAUDE.md            "@AGENTS.md"
├── PLAN.md              timestamped blocks: todo, discussion, decision, research, progress
├── README.md            developer overview with flow diagrams (English)
├── README_CN.md         same, Chinese
├── pyproject.toml       Poetry / PEP 621
├── src/sidekick/
│   ├── app.py           assembles every module (the runtime)
│   ├── cli.py           command-line entry point (`sidekick startup` / `close`)
│   └── <module>/        one flat directory per core module, see rules below
├── extensions/          bundled extensions, one flat directory each (robot, news, media, home)
├── tests/               flat pytest files: test_<module>_<topic>.py
└── .derived_data/       runtime state, git-ignored: config.json, *.db, logs/, audio/, models/,
                         extensions/ (user-installed), cache/, recordings/ (24 h ring of chunks)
```

The import root is `src/sidekick/`, so modules are `sidekick.agent`, `sidekick.body`, …. This
avoids top-level names colliding with PyPI packages while keeping the one-directory-per-module
shape. Dependency chain: `app.py → <module>/<module>.py → <module>/<submodule>.py`.

## Module structure rules

- A module is a directory `src/sidekick/<module>/`. **No nested sub-directories.** Data files a
  module needs (provider presets, dashboard HTML) sit flat in the directory with a module-specific
  prefix, e.g. `config/provider_minimax.json`, `dashboard/dashboard_index.html`.
- `<module>/<module>.py` is the **façade**: it owns the module's `<Area>Session` class and public
  API, and it is the only file that assembles the submodules. `__init__.py` contains only
  re-exports from the façade.
- Every other `.py` file in the directory is a **submodule**: one focused component, with its own
  schemas, helpers and storage code. Submodules may import sibling submodules but never the façade.
  Shared types go in `schemas.py`; small stateless helpers in `utils.py`.
- **Cross-module imports go through the façade only:** `from sidekick.llm import LLMSession`,
  never `from sidekick.llm.v1_chat_completion import …`.
- **Dependencies are one-way.** The allowed-import table in "Architecture" is the contract;
  `tests/test_architecture.py` parses imports with `ast` (in `src/` and `extensions/`) and fails
  on any edge not in the table.
- Class names carry the area prefix like Scoop (`LLMResult`, `TTSBackend`, `BodySession`); file
  names do not, because the package path already does.
- **Extensions** follow the same flat rule: `extensions/<name>/` holds `extension.json`
  (manifest), optional `tools.py`, `watchers.py`, `skill_<topic>.md`, `mcp.json`. No
  sub-directories. User-installed extensions live in `.derived_data/extensions/<name>/` with the
  same shape.
- **Every module file starts with a docstring header** in this shape. The façade header carries
  the module's technical design; a submodule header carries that component's design.

```python
"""
sidekick.<module>.<file> — <one line>

Overview
    What this file owns and why it exists.
Design
    The technical approach, the decisions behind it, and the invariants it enforces.
Depends on
    sidekick modules and third-party packages it imports.
See also
    AGENTS.md "<section>", PLAN.md block "<id>".
"""
```

## Core rules (invariants)

Each is stated once here and enforced in one place. Breaking one is a behavior change — say so.

| # | Invariant | Enforced in |
|---|---|---|
| 1 | **Dependency direction.** A module imports only modules listed for it in the allowed-import table. | `tests/test_architecture.py` |
| 2 | **Façade-only imports** across modules; `__init__.py` re-exports only. | `tests/test_architecture.py` |
| 3 | **Declarative configuration.** Endpoints, models, voices, credential fields, defaults live in `config/provider_*.json`, never in code. | `config/catalog.py` |
| 4 | **Fixed backend shape.** A `*Configuration` dataclass plus a backend class implementing the service protocol; `infer`/`transcribe` returns a fully populated `*Result` including `api_code`. No extra factory layers. | `config/config.py` `make_*_backend` single `match api` |
| 5 | **Trace every model call.** All LLM / ASR / TTS calls go through `*Session` so they land in that service's trace table. | `llm/llm.py`, `asr/asr.py`, `tts/tts.py` |
| 6 | **Never log secrets.** Keys are masked to first/last 4 chars + length before any log line or trace row. | `log/log.py` `mask_secret` |
| 7 | **SQLite pattern.** Open/close a connection per operation; schema create/migrate when the database path is set; multi-step writes in `BEGIN IMMEDIATE` … `COMMIT`. | `storage/storage.py` |
| 8 | **Database file names carry a version suffix** (`dialogue_v1.db`), bumped only for a non-migratable schema change. | `storage/storage.py`, `app.py` |
| 9 | **Logging is uniform and English.** One façade, one format, `info0()` marks function entry. | `log/log.py` |
| 10 | **Single motion owner.** Exactly one control loop calls the robot's `set_target`; everything else enqueues. | `body/motion.py` |
| 11 | **Agents never wake, sleep or torque the robot.** The platform does; `body` only mirrors state. | `body/reachy.py` |
| 12 | **One timeline, filtered views.** All messages from all channels append to one dialogue timeline, each row in a conversation (the room while turns follow within minutes, a chat per chat id); the LLM sees a per-turn view of its own conversation, filtered by visibility, within a character budget. | `agent/dialogue.py` |
| 13 | **Sensitive tools confirm first.** A tool declared `confirm=True` runs only after the speaker explicitly confirms in the same conversation. | `agent/tools.py` |
| 14 | **Replies go back to the originating channel** by default; cross-channel delivery is an explicit automation action. | `agent/agent.py`, `automation/tools.py` |
| 15 | **Developer surfaces always ship.** The dashboard is in every build, bound to loopback. | `dashboard/dashboard.py` |
| 16 | **`PLAN.md` before code.** A new block is appended before non-trivial work starts, and the yellow pages are updated when a module's public surface changes. | this file, `PLAN.md` |
| 17 | **Ambient audio stays local.** Only utterances accepted by the engagement policy are sent to cloud ASR; VAD, keyword spotting and speaker identification run on the host. | `interaction/engagement.py` |
| 18 | **Every engagement decision is traced** with its scores (VAD, keyword, speaker, DoA, face) and a short audio clip, pruned after 7 days, so thresholds are tuned from real household data. | `interaction/trace.py` |
| 19 | **Tools come from the agent and the modules above it.** Each registers its own into the `AgentSession` it is given in `setup`: the agent its built-in tools, `automation` its scheduling tools, the extension loader an extension's (while sidekick runs, as extensions are enabled and disabled). Modules below the agent define no tools; their capabilities reach it through an extension (`robot`). | `tests/test_architecture.py` (imports), `extension/extension.py`, `automation/automation.py` |
| 20 | **Interruption is two-stage.** Speech from a qualifying source ducks playback first; a hard stop needs sustained speech, a stop word, the wake name or an antenna touch. Backchannels never stop the robot. | `interaction/barge_in.py` |
| 21 | **One composition rule.** `app.py` constructs every session and calls `setup` / `start` / `stop` in dependency order — the console's in `start` / `stop`, the runtime modules' through the service, which runs `setup_service` and the ordered modules `app.py` hands it — no control flow, closures or wiring of its own. Whatever a module hooks into a peer (tools into the agent, a subscription on the perception bus, an adapter into the channel registry, its own housekeeping) happens in that module's `setup` / `start` and is undone by its `stop`. | `tests/test_architecture.py` (parses `app.py`) |
| 22 | **Automation belongs to the main agent.** Only the main agent creates, cancels and runs jobs: the scheduling tools and `delegate` are `main_only` (never in a subagent's set, whatever its allowlist says) and every job is one main-agent turn. Subagents are experts for one domain, reached through `delegate`. | `agent/tools.py` (`for_allowlist`), `automation/automation.py` |
| 23 | **Memory follows identity.** Facts belong to a contact or the household, never to an unnamed speaker (`person:N`, `guest:N`, who hold voice / face vectors only); a new contact never takes an existing contact's id, so identities never merge by name. Facts written from conversations come only from named participants who spoke; a private chat's facts stay with their teller, household facts only come from open conversations, and health, money and relationships only from the person themselves (always private). | `agent/memory.py` (`remember`), `agent/writer.py` (`_apply`), `contact/contact.py` (`create`) |
| 24 | **Memory never slows a turn.** No model call and no search for memory on a turn's path: the memory block is read from SQLite once per conversation and frozen; the memory writer only writes closed (or long) conversations and steps aside while a turn is in flight. | `agent/agent.py` (`memory_block`), `agent/writer.py` |
| 25 | **The process is the CLI's, the service is the dashboard's.** `sidekick startup` / `close` start and close the process; the dashboard never spawns or signals one — its power control starts and stops Banana's service inside it, a start checking the prerequisites and each module proving it works (`check()`), a stop turning the robot off. Every runtime module's session lives as long as the process: `setup` may run again while stopped, `stop` releases everything `start` took, `start` works again (blocks #82–#87). | `service/service.py`, `tests/test_service_lifecycle.py` (cycles), `tests/test_architecture.py` (dashboard and doctor import no `subprocess` / `signal`) |

## Architecture

```text
Layer 5  app.py · cli.py · dashboard · doctor · service   assemble, operate, inspect, check
                                                 readiness, start / stop Banana
Layer 4  automation                              jobs, scheduler, event jobs, heartbeat; its own
                                                 scheduling tools for the main agent
         extension + bundled extensions          robot · news · media · home: tools, MCP, skills,
                                                 subagent profiles, watchers
Layer 3  agent                                   swarm: main agent + subagents, dialogue, memory,
                                                 the tool protocol and registry, MCP, skills, delivery
Layer 2  interaction · perception · contact · channel · record
Layer 1  llm · asr · tts · vad · config · body
Layer 0  log · storage · audio
```

Allowed imports (the contract for rule 1):

| Module | May import from `sidekick.` |
|---|---|
| `log` | — (stdlib only) |
| `audio` | — (numpy only) |
| `storage` | `log` |
| `llm` | `log`, `storage` |
| `asr` / `tts` / `vad` | `log`, `storage`, `audio` |
| `body` | `log`, `audio` |
| `config` | `log`, `storage`, `audio`, `llm`, `asr`, `tts`, `vad` |
| `channel` | `log`, `storage` |
| `contact` | `log`, `storage`, `audio` |
| `perception` | `log`, `storage`, `audio`, `body`, `contact` |
| `interaction` | `log`, `storage`, `audio`, `body`, `asr`, `tts`, `vad`, `channel`, `contact`, `perception` |
| `agent` | `log`, `storage`, `llm`, `channel`, `contact`, `perception` |
| `automation` | `log`, `storage`, `agent`, `perception` |
| `extension` | `log`, `storage`, `agent`, `automation`, `perception` |
| `record` | `log`, `storage`, `audio`, `body` (interaction state arrives through a callable injected by `app.py`) |
| `extensions/*` (bundled or user) | `log`, `storage`, `audio`, `llm`, `body`, `contact`, `perception`, `interaction`, `agent`, `extension` |
| `service` | `log`, `storage`, `config` (everything else arrives as `app.py`'s bound methods) |
| `dashboard`, `doctor`, `app.py`, `cli.py` | any module |

Composition (invariant 21): `app.py` loads and applies the config (backends into the service
sessions) and constructs every session once. Its `start()` is the **console** — readiness, the
dashboard — and hands the **service** (block #82) its composition: `setup_service()` (each runtime
module's `setup` with the current spec and the peers it needs) and the modules in start order —
body (daemon, connection), contacts, channels, voice front end, agent, automation, perception,
recorder, extensions. The service runs them on the owner's Start (and at boot when it was left
running), each `start` followed by the module's `check()`, and `stop`s them in reverse on Stop or
exit; the console stays as long as the process. That is all `app.py` does. Every hook a module places on a
peer is placed by that module: `automation` registers its tools into the agent and subscribes to
the bus, `interaction` registers its voice adapter and subscribes to `gaze.mutual`, `channel`
builds its Telegram / WeChat adapters, the extension loader registers an extension's
contributions (and withdraws them on disable), `contact` enrolls Banana's own voice and prunes
unnamed people, the service traces prune themselves. Because every session exists before any is
set up, a module can be handed a bound method of a peer set up later (the agent gets the voice
front end's `speak` / `can_speak`, the recorder its `telemetry`).

## Module yellow pages

Status legend: `planned` (not yet in tree), `wip`, `stable`. Details live in each module's façade
header; this table is the index.

| Module | Status | Overview | Key submodules |
|---|---|---|---|
| `log` | wip | Logging façade over stdlib `logging`: uniform format, `info0` entry marker, `mask_secret`, stderr + rotating file sink under `.derived_data/logs/`, and an in-memory ring of the newest warnings and errors (`Log.recent()`, `Log.counts()`) for the Live page. Pure logging; no storage dependency. | `log.py` |
| `audio` | wip | Layer-0 audio primitives shared by vad / asr / tts / body / interaction: `AudioClip` (mono float32 at a sample rate), WAV encode/decode, PCM16 conversions. Imports numpy only. | `audio.py` |
| `storage` | wip | Runtime home (`./.derived_data/`, override `SIDEKICK_HOME`) and layout (incl. `recordings_dir`); `Database` (connection per operation, `PRAGMA user_version` migrations run inside the script's own transaction, `transaction()`); JSON spec files written atomically with mode 0600; streaming downloads + tar.bz2 extraction for models; `TraceTable` base used by every service trace (`recent`, `between` for replay; built with `retention_days` it prunes itself at most hourly as it writes — the service traces keep 10 days; a column declared later is added to an existing table) and `RecentCalls`, a service's in-memory tail of calls (last call, medians, errors per hour, calls in flight) for the Live page; `backup()` / `restore()` tar.gz the home without models, cache, logs, extension state and recordings (restore refuses a non-empty home unless forced, config.json back to 0600). `service_path` is `service.json` (the owner's last Start / Stop, block #87). | `storage.py`, `schemas.py`, `database.py`, `trace.py` |
| `llm` | wip | `LLMSession` with named **slots** (`fast`, `smart`), each bound to a provider + model by config; `LLMBackend` protocol over chat messages with tool calling and SSE streaming; `v1_chat_completion` backend (MiniMax `/v1/chat/completions` verified live incl. Cantonese tool calls) with one pooled HTTP client per backend kept alive 120 s and `warm(connections)` (a fresh client per call paid a 1.3 s TLS handshake through this Mac's proxy, half the first token — block #71); **hedged streams** (`stream(…, hedge_after_s)`, block #78: no `start` from the provider by then → the same request again, the first to answer is streamed, the other cancelled as `hedge lost`, not an error; one MiniMax call in twenty waited 9–13 s for its first token); `LLMResult` (incl. `first_token_ms`) + trace; `live()` per slot from `RecentCalls` plus hedges sent and won. A slot's `setup` closes the backend it replaces (its pooled connections; also for `asr` / `tts` / `vad`), and `ConfigSession.release()` unbinds every slot when the service stops (block #87). | `llm.py`, `schemas.py`, `v1_chat_completion.py`, `trace.py` |
| `asr` | wip | `ASRSession` with slots `primary` (MiniMax `asr-1.0`, verified live with `yue`), `local` (SenseVoice via sherpa-onnx; ~0.1 s per clip on this Mac, used for turns by default since 2026-10-26, cloud as shadow comparison) and `kws` (sherpa-onnx open-vocabulary keyword spotter for the wake name: CMU phones for English, pinyin for Chinese, keyword lines in `robot.keywords`; for "Banana" the lexicon's phones and the long-a variant at score 2.0 / threshold 0.2, block #94); `ASRBackend.transcribe(clip, language)`; `ASRStreamingBackend` protocol reserved for real-time vendors. Its HTTP backend (`minimax_speech_to_text`) keeps one pooled client per event loop (no TLS handshake per call); `live()` per slot from `RecentCalls`. SenseVoice and the keyword spotter `preload()` at the service's start (no 0.35 s on the first utterance) and `close()` their model when unbound. SenseVoice decodes `zh` in a Mandarin household and `auto` otherwise (the local preset's `per_language`; in `auto` some Mandarin came out as Cantonese, block #94). | `asr.py`, `schemas.py`, `minimax_speech_to_text.py`, `sherpa_sensevoice.py`, `sherpa_kws.py`, `trace.py` |
| `tts` | wip | `TTSSession` with slots `primary` (MiniMax bidirectional WebSocket `/ws/v1/t2a_v2_bidi`, PCM 16 kHz, verified live: connect ~2 s once, first audio ~0.8 s per turn) and `fallback` (HTTP `/v1/t2a_v2`); `TTSStream` protocol with send / flush / cancel / finish and typed events; per-language voice and `language_boost`; `synthesize(text)` returns one clip (the `fallback` slot when bound) for callers that only need audio, such as Banana's own voice enrolment, and `voice()` names the voice it speaks with. The HTTP fallback keeps one pooled client per event loop; `live()` per slot from `RecentCalls`. | `tts.py`, `schemas.py`, `minimax_ws.py`, `minimax_sync.py`, `trace.py` |
| `vad` | wip | `VADSession` with slot `primary`; `VADBackend` protocol (feed / is_speech / pop_segments / flush / reset) over 16 kHz float32; `silero_sherpa` detector factory via sherpa-onnx, model downloaded on demand. Verified on a real clip. | `vad.py`, `schemas.py`, `silero_sherpa.py` |
| `config` | wip | Provider presets (`provider_minimax.json`, `provider_local.json`) + user `ConfigSpec` (pydantic) + `apply()` / `probe()`; binds every slot (`llm.fast`, `llm.smart`, `asr.primary`, `asr.local`, `tts.primary`, `tts.fallback`, `vad.primary`) to a provider + model via one `match api` per service; probe tries every region on any failure because keys are region-bound, persists the first that works, and classifies failures (network / credentials / voice / incomplete / api / http); `preset_spec(name)` renders the deployment profiles `default` / `dev` / `lite-mac` / `wireless` (daemon on the robot, WebRTC media) / `pi` (lighter perception and VAD, FLAC + 540p recording), `profile_of(spec)` classifies a spec; `telegram_paired()` persists a chat that paired (the Telegram adapter's callback) and `slot_supports(service, slot, capability)` answers "does `llm.smart` see images"; the `recording` section (chunk length, retention, disk floor, size / fps / bitrate, audio codec, root) feeds `record`. `release()` unbinds every slot (the service stopped: connections closed, models dropped); the retired `body.stop_daemon_on_exit` is dropped on load — a stop of the service always turns the robot off. Block #94: `ROBOT_NAME` / `ROBOT_ALIASES` / `ROBOT_KEYWORDS` are the robot's fixed name and how it is heard — a home written under a retired name takes them on load —; `drop_foreign_voices()` unpins a voice that belongs to another language than its slot's (on load, and in `with_language()`, the dashboard's change of the household language); the default language is `zh`. | `config.py`, `schemas.py`, `catalog.py`, `provider_*.json` |
| `body` | wip | Reachy Mini adapter behind a body-agnostic API (`BodyBackend`): `reachy.py` over the SDK + daemon REST (status, DoA, face target), `null.py` for no-robot runs and tests; `BodySession` owns the **motion owner thread** (look pose + the **speech sway** (`sway.py`: our parameterised port of the SDK's head wobble — the paced player feeds every pushed frame with its playback instant, the DSP (RMS → VAD → envelope → loudness × `master` → six oscillators) yields one offset per 50 ms hop, the owner adds the hop due now; `ConfigBody.sway`, master 0.5 by default vs the SDK's 1.5, yaw halved; the SDK wobble is off unless `body.sdk_wobble`) + **Banana's own expressions** (`expression.py` + `expression_library.json`, block #50: 51 entries authored for Banana — beats, emotions, performances and the thinking states; offset curves (monotone cubic keys + enveloped sines, mirrorable, loops and chains) the owner sums in three layers — `state`, `beat`, `express` — on top of the gaze, so an expression never takes the eyes off the person; intensities × `energy` = `body.expressiveness` × the reply's style (calm 0.6 / natural 1.0 / lively 1.45, also scaling the sway); the sway reports phrase onsets of Banana's own audio and the owner sometimes adds a small beat nod; `gaze_held()` makes the face servo wait while an `express`-layer expression turns the head (the thinking state keeps the eyes on the person, block #80); there is no idle breathing any more — the owner retired it (block #80); the SDK's recorded moves, `play_move()` and their sound effects are not used), the only `set_target` caller), the **touch detector** (antenna commanded-vs-present with hysteresis; a side arms only once its measured angle has reached the command, so an antenna blocked when the head looks up never reads as a press — block #80), the **audio pump / paced player** (fan-out capture, −12 dB ducking, flush), a status monitor mirroring wake/sleep and keeping the last 30 s of DoA readings (`doa_between(start, end)`: the median of a stretch of speech, the chip's speech-flagged readings first, with the share that agree — a single reading is ±50° noisy and the one at a sentence's end is the room, block #80); `setup(config)` binds the body config (again before each start of the service, block #87), `start()` brings the robot up — `reachy-mini-daemon` spawned when `body.manage_daemon` is on and it is down, its backend started (the robot woken) when it answers stopped, then the connection and a bounded wait for the first telemetry, camera frame and microphone audio — and `stop()` turns it off: disconnect, then the daemon sidekick spawned is stopped (SIGINT: the sleep move, camera and audio released) or another daemon is asked to sleep (REST); each run has its own stop event and `check()` reports daemon, connection, telemetry, camera and microphone; `daemon.py` starts/stops `reachy-mini-daemon` for `start()` / `stop()` (rotating its log at a spawn), `dsp.py` probes and reboots the XVF3800 audio chip when it stops answering. `telemetry()` returns one `BodyTelemetry` sample (commanded pose from the motion owner, measured head pose and joints from the SDK's cached state stream, antenna angles, mic / speaker levels and 20 ms peak rings, DoA, face, `camera_fps`) for the Live feed and the recorder; the **frame pump** thread is the only reader of the SDK camera (each frame is handed out once and a read blocks ≤ 20 ms; the daemon's local IPC feed is capped at **10 fps** by `IPC_FPS` in the SDK's media server) and `frame()` hands the latest frame to every consumer — recorder, MJPEG stream, face detector — so none of them starves the others; `camera_fov()` derives the field of view from the SDK intrinsics, `current_look()` exposes the owner's eased pose for the face servo; `subscribe_speaker()` taps what goes to the speaker; `model.py` reduces the SDK URDF to the display model (`display_model()`, allowlisted `mesh_path()`) the dashboard renders in 3D. **Manual control**: `take_control(holder)` puts the motion owner in manual mode — unmarked commands (attention, expressions, robot tools) are dropped and counted — and `manual_pose()` carries the whole target (head yaw / pitch / roll / height, body yaw, both antennas; clamped to the limits in `schemas.py`), `gesture` / `express` accept `manual=True`; `release_control()` eases the posture back to neutral (body yaw is sent to the daemon only while held and for 3 s after). A **moving window** (`moving()` / `moving_until()`, `moving` in telemetry) covers looks that change the direction, gestures, emotions and controller poses — not the antennas — so the voice front end can discount motor noise. Verified live on the Lite. `live()` gives the Live page the body's vital signs from memory (state, daemon, control and holder, the expression on each motion layer, sway, style, volume, last antenna touch); `BodyDaemon.cached_status()` serves the dashboard's 1 Hz health poll without an HTTP call each time. | `body.py`, `schemas.py`, `reachy.py`, `null.py`, `motion.py`, `expression.py`, `expression_library.json`, `sway.py`, `touch.py`, `media.py`, `model.py`, `daemon.py`, `dsp.py` |
| `channel` | wip | `ChannelAdapter` protocol, `ChannelMessage` / `ChannelReply`, `ChannelSession` registry + reply router (replies return to the originating channel). `setup(handler, config, credentials, home, on_telegram_paired)` builds the remote adapters itself, each only when enabled and holding a bot token. Adapters: `voice` (registered by `interaction`), `telegram.py` (raw Bot API long polling over `httpx`, chat-id allowlist, pairing by one-time code `/pair <code>`), `wechat.py` (personal WeChat via Tencent's iLink bot protocol as read from `@tencent-weixin/openclaw-weixin` 2.4.10: QR login → bot token, `getupdates` long poll with persisted `get_updates_buf`, `sendmessage` echoing the per-user `context_token`, stale-token pause; text + voice transcripts, media later). Both tested against mocked backends; live use needs the owner's bot token / phone scan. Telegram private chats and WeChat (one-to-one) arrive with `metadata.private`, so their rows and memory stay with their person (block #70); `live()` (each adapter's counters, last message in / out, poll task alive, pause) and `activity()` (messages in and out) feed the Live page. `setup` rebuilds the remote adapters it built from the config before each start (a stopped adapter's client is closed); `check()` reports each adapter polling (advice, never blocking; `off` when none is configured). | `channel.py`, `schemas.py`, `telegram.py`, `wechat.py` |
| `contact` | wip | `ContactSession`: profiles in `contact_v1.db` (name, aliases, notes, language, owner flag, remote ids for Telegram/WeChat), voice identification with sherpa-onnx 3D-Speaker CAM++ zh/en (192-d, ~15 ms per clip, cosine ≥ 0.5; two TTS voices separate at 0.8–0.9 vs 0.1–0.2), face detection + embedding with OpenCV YuNet + SFace (128-d, cosine ≥ 0.363, TV-zone mask), enrollment by averaging (the dashboard's guided Contacts flow — three prompted captures straight from the mic, then camera frames — or ticked listening clips), `embed_voice()` / `voice_similarity()`, the **people seen** store (`person:n` rows in `contact_v1.db` whose voice / face centroids share the `embeddings` table, so a returning stranger is recognised through the normal `identify_*` path; `new_person`, `fold_person`, `person_ready` (≥ 6 utterances over ≥ 2 sessions or ≥ 8 in one, not asked in a day, not declined in a week), `promote_person` moves the centroids to a new contact — `create` always takes a free id (`阿明_2`), never overwriting a contact (block #63) —, `forget_person`, `prune_people` after 7 days unseen), `brighten_frame()` (gamma lift of dark frames before YuNet; the evening living room measured 19/255), the reserved `self` contact enrolled by `start()` from three clips of the `synthesize` function its `setup` receives (when `contacts.enroll_self` is on and it is missing, or was made from another TTS voice than `setup`'s `voice` names now — a change of the household language changes the voice, block #94 —, in the household's language) so echo residuals are recognised as the robot, `start()` also forgetting unnamed people unseen for a week, then daily, `resolve_speaker()` so one person is one memory scope across channels (bound remote ids, the dashboard's `owner` once an owner contact exists, a `person:n` befriended or merged in this run). **One voice, one identity across days (block #80):** a named voice (contact or `self`) at the threshold wins over a closer unnamed person, a voice in the uncertain band (0.35–0.5) of a contact comes back as `Identification.near` (not identified, not a stranger), `identify_vector()` matches an embedding the caller already has, `learn_voice()` folds an utterance identified as a contact into its centroid (running weight capped at 50, so new rooms and hours keep moving it), and `merge_person()` hands an unnamed person to the contact whose voice they are (≥ 4 utterances, centroid ≥ 0.55 and 0.1 clear of the next contact; `start()` sweeps the stored people with `merge_people()`) — merging by voice evidence, never by name. Display names are cached 30 s (any contact change drops the cache); `live()` gives the latest voice / face identification and the counts (members, owner, people seen, ready to befriend; SQL at most every 30 s). `stop()` drops the voice and face models (the store stays open for the Contacts page); `check()` counts the household (advice only, block #86). | `contact.py`, `schemas.py`, `store.py`, `voice.py`, `face.py` |
| `perception` | wip | `PerceptionSession` event bus (typed `PerceptionEvent`, pattern subscriptions, 200-event history, `events_v1.db` for `severity >= notice`) and core sources as `Watcher`s: `camera.py` presence from the daemon's face tracker **and our own YuNet detector** (10 Hz on a gamma-lifted 640 px copy of the frame — the servo rate —, identification of the largest face at 1 Hz, every detection handed to `on_face()` listeners; `faces()` gives normalised boxes with names for the dashboard overlay, `local_face()` the largest one for the attention servo and for presence when the daemon is blind) — `face.seen`, `gaze.frontal`, `presence.enter` after 1 s, `presence.leave` after 60 s, and **`gaze.mutual`** once per gaze episode (a centred face turned toward the camera by YuNet's landmark ratio, tall enough, for ≥ `mutual_gaze_s` = 2.5 s; carries the identified contact, whose `last_seen` the identification touches); `audio.py` speech-onset events with direction. `presence()` feeds the delivery policy; `agent.on_event` runs `event` jobs. Extension watchers subclass `Watcher`. `live()` (presence, faces, today's counts of arrivals, mutual gazes, greetings, watchers' last poll) and `activity()` (bus events of severity info and up) feed the Live page. The body watchers are made at `start()` (the body is connected by then) and dropped at `stop()`; `on_face` listeners and bus subscriptions are kept once whatever the restarts; `check()` reports our face detector (block #87). | `perception.py`, `schemas.py`, `camera.py`, `audio.py`, `watcher.py` |
| `interaction` | wip | Voice front end: `frontend.py` (VAD thread with 1 s pre-roll → events; a segment's direction is the median of the DoA readings during its speech, block #80), `namespot.py` (the wake name on local SenseVoice text + filler detection: the aliases as SenseVoice wrote them, and the name itself loosely, word by word — never a loose alias or a window across words, which took "nana", "Panama" and "a banner and a" for the name; every name at a turn's edges removed, one inside renamed "Banana", blocks #89 / #94), `call.py` (Banana's spoken answers to a bare call, synthesized at start, never the same twice in a row, block #92), `engagement.py` (SLEEPING → IDLE → ENGAGED ↔ SPEAKING; `answer_timeout_s` (15 s) instead of `session_timeout_s` after a reply that asks, block #89; speech begun before the deadline holds the session, block #92; triggers `wake_name` (SenseVoice **or** `asr.kws`), `touch`, `robot_initiated`; `gaze` lands with `contact`; in a session two different known contacts are `other speaker`, anything else is decided by the direction, and a known voice replaces an unknown or unnamed session speaker — block #80), `barge_in.py` (duck → confirm by duration / stop word / name / touch; backchannels resume), `pipeline.py` (turn: ASR → responder → sentence fragments → one long-lived bidi TTS session → paced speaker, latency marks, shadow ASR; each finished sentence flushed, then `sentence_pause_ms` of silence before the next — block #76; the turn lasts until the speaker has played everything, however long; no emoji reaches TTS — block #89), `attention.py` (DoA turn only for an accepted segment or the wake name whose direction readings agree (≥ 0.5), ≥ 15° hysteresis (20° inside a session), never over a face tracked by the daemon or by our servo in the last 1.5 s; the **face servo** — `face_tracker: own` by default: every 10 Hz detection of our detector becomes an angle through the camera's field of view and a `gain` (0.7) step from the owner's current eased pose, so the face stays centred while nods and glances compose; back to neutral 2 s after the face is lost; `face_tracker: daemon` keeps the SDK tracker with the weights, which never centres below 1.0 and silences every other head motion at 1.0; listening cues; while idle, **scanning glances** every 8–15 s within ±40° held 2–3 s and **sound glances** toward a clear sound (≥ −35 dBFS for ≥ 0.6 s, one per 8 s, never the TV / self sector), both paused by a face and never a word), `initiative.py` (the hard rules before Banana speaks first: a `gaze.mutual` of a **known** contact away ≥ 2 h (`sociability` normal; chatty 30 min; quiet never), outside quiet hours, under the daily cap → `greet.due`), `expression.py` (`[express:name]` → Banana's own library by name, alias or unique prefix; `[style:lively|calm|natural]` sets the energy of that reply only), conversation body language in `attention.py` (`ack` when a turn is accepted, then **thinking** — the `think` state tilts the head a little with the antennas swaying in turn, `think_long` after 2.5 s changes the tilt's side slowly; the eyes stay on the person and the face servo keeps running (block #80: the sideways glances read as looking around) — ended before the first word; `heard_again` returns to listening when they talk meanwhile; a `yield` beat ends a reply; `mm_hm` backchannel nods at the `pause` events the front end reports inside their sentences), `trace.py` (every decision with clip, 7-day prune), `voice_channel.py`; `InteractionSession` applies the rules and guards against the robot's own voice (echo similarity, `self` voice identification), TV sector and unknown-direction speech; every accepted segment is speaker-identified (`contact`) — except one with less than 1.0 s of speech (a short call of the name in a clip that is mostly pre-roll embedded the room); an unknown voice becomes a `person:n` in the contact store at once (session-only `guest:n` when there is no store) unless it is in a contact's uncertain band or has less than 1.2 s of speech, counts as unknown for the gates but is the turn's speaker; a turn without an identity of its own takes the session's speaker; three uncertain utterances of a session whose mean clears the threshold make the session that contact; an utterance identified as a contact (or uncertain inside that contact's session) is learned into the contact's voice, and an unnamed person who turns out to be a contact's voice is merged into it, the session renamed (block #80); every accepted utterance folds its voice vector and — when the largest face's image azimuth agrees with the DoA — the face vector into that person, and `person.ready` is published on the perception bus when the person has been heard enough (the befriending task, block #35); the session carries the contact id (or `guest:n`), `speaker_gate strict` rejects unknown voices, the `gaze` trigger (frontal face from `perception` + enrolled voice + matching direction) opens a session without the name, and the speaker's preferred language drives the turn. speech the front end flags `self_motion` (began and ended inside the body's moving window) never ducks playback and is traced as `self motion`; `captions()` (`listening` only inside a session, raw `speech_open`, last heard text with `heard_by`, said text) feeds the Live subtitles and `telemetry()` the recorder's rows; `set_config()` applies a changed section live; `setup` registers the `voice` adapter with the channel registry it is given and takes the recorder's microphone reader; `start()` listens only with a connected body and a bound VAD; `can_speak()` / `speak()` are the agent's voice hooks for unprompted messages (front end running, body awake, someone present or presence off; `speak` answers False when nothing was said); `clip_for(row_id)` returns a decision's audio from the file under `audio/` or, when the recorder runs, sliced from the ring (`clip_source` = `RecordSession.read_mic`, so `audio/` stays empty); `hold(reason)` / `release_hold()` park the front end for the Robot tab's controller (events dropped, the turn cancelled, `say()` without attention changes; release restores the idle posture). `live()` is the Live page's Now and Turn cards: the machine, the time left before a session times out, the turn in progress with its marks so far (`TurnTiming.marks()`, the first audio from the body) or the last one, the newest decisions, attention, initiative and the TTS link; `activity()` gives the decisions worth a line (rejected ambient segments stay on Voice); at speech onset inside a session and on a wake-name hit it asks the responder to warm its LLM connection (`warm()`, duck-typed). Restartable (block #87): `start()` registers its touch / state callbacks once (stable session methods forwarding to the run's front end), takes the body's state as it is (setup ran before it connected), preloads SenseVoice and waits up to 8 s for the TTS link; `stop()` joins the front end, cancels the warm-up and puts the machine to sleep; `check()` reports listening, SenseVoice, the wake-name spotter and the TTS link (a dead link or recogniser aborts a start). | `interaction.py`, `schemas.py`, `frontend.py`, `namespot.py`, `call.py`, `engagement.py`, `barge_in.py`, `pipeline.py`, `attention.py`, `initiative.py`, `expression.py`, `voice_channel.py`, `trace.py` |
| `agent` | wip | The swarm: `Agent(profile)` runs the ReAct loop (`loop.py`: streamed text, tool calls executed concurrently, re-prompt, `NO_REPLY`); `AgentSession` owns the main agent (`fast` slot, its own tools `remember/forget/recall`, `skill_*`, `mcp_*`, `time_now`, `delegate`, plus `automation`'s `schedule/jobs_list/job_cancel`) and config-defined subagents (`smart`; `set_subagent()` / `roster()` / `configure_main()` for the dashboard's Swarm view, each profile with its `origin`), the **tool protocol** (`Tool` / `ToolContext` / `ToolResult`, the `main_only` flag — `delegate` and the scheduling tools never reach a subagent, invariant 22) and the tool registry with confirm gating (`tools.py`, invariant 13: parked call runs on the speaker's yes), the timeline (`dialogue.py`: L0, every row in a **conversation** — the room while turns follow within 5 min, a chat within 15 min — and the context view of the turn's own conversation, rebuilt tool steps, the earlier part of a long one as its rolling summary), the memory pyramid (`memory.py`: L2 **facts** with provenance — scope, subject, teller, channel, visibility, explicit / inferred, category, valid until, sources, superseded instead of deleted —, L1 **episodes** — title, summary, follow-ups, participants, one per conversation —, digests; `block()` renders a speaker's memory block, `search()` backs `recall`), the **memory writer** (`writer.py`: after a conversation closes, one `smart` call writes its episode and the facts worth keeping; the rules of invariant 23 decide what is kept; a nightly pass expires dated facts, digests and merges; never on a turn's path, invariant 24), skills (`skills.py`, Markdown CRUD), MCP (`mcp.py`, official SDK as transport, tools as `mcp.<server>.<tool>`), background delegation (`delegate` with `mode=async`: an in-memory `task-…` whose result a follow-up main turn relays) and the delivery policy (`in_person` / `remote` / `both` / `auto`, voice through the `say` / `can_speak` hooks the voice front end hands to `setup`). It knows no jobs: `automation` calls `run_job_turn()` (one main-agent turn on a job's prompt, then delivery) and `delivered_since()` (the heartbeat's "already said" list). Speaker display names from `contact` in the prompt; remote ids (`tg:42`) and the dashboard's `owner` resolve to contacts so memory is per person across channels (facts kept under `owner` before an owner contact existed move to it on its first turn); memory belongs to contacts and the household only — `remember` refuses an unnamed speaker with a hint to befriend, `forget` never reaches another person's facts (invariant 23, block #63); the context view rebuilds past tool-call steps from the tool rows, so old replies show the calls behind them; unnamed-speaker labels (`person:N`, `guest:N`) are for tool calls only — a prompt rule forbids them and `run_main` scrubs any from the streamed reply, so they are never spoken, sent or shown. Each conversation's prompt carries its memory block, built once from SQLite and frozen (`memory_block`); the system prompt runs from the most stable part to the per-turn line, so a provider's prefix cache can reuse it. The main agent's LLM connection is kept open (`KEEP_WARM_S`; two connections while it hedges) and warmed when someone starts talking (`warm()`); a turn someone waits for is hedged after `main_hedge_s` (block #78). For the Live page the session follows every turn in flight (state, step, tool, first token) and keeps the newest (`live()`, `activity()`, `memory_live()`). Verified live: tool calls from Cantonese speech and dashboard chat. `start()` makes one real call per model slot the agents use (`fast`, `smart`, concurrently; it also opens the connection the first turn uses) and `check()` reports them — a `fast` that does not answer aborts a start; `stop()` waits for its cancelled tasks (block #86). | `agent.py`, `schemas.py`, `loop.py`, `tools.py`, `dialogue.py`, `memory.py`, `writer.py`, `skills.py`, `mcp.py` |
| `automation` | wip | `AutomationSession` (layer 4, above the agent): everything that makes Banana act at a time or on an event, always as one main-agent turn whose answer is delivered by policy — reminders and recurring tasks (`cron` / `at` jobs in `automation_v1.db`, `jobs.py`: store + 5-field cron matcher), `event` jobs fired by the perception bus (the robot extension's `befriend` / `greet`, a user's "when someone comes home…"), the scheduler (`scheduler.py`: one job at a time, a quiet-hours predicate), and the heartbeat (`heartbeat.py`: a built-in `cron` job — Banana's periodic look for news the household has not heard, usually `NO_REPLY`; not a system tick, nothing subscribes to it; its prompt carries its last run and what was already said unprompted, from the agent). `setup(db, config, agent, perception)` wires itself (invariant 21): it registers its `main_only` tools `schedule` / `jobs_list` / `job_cancel` (`tools.py`) into the agent and subscribes `on_event` to the bus; the agent never imports it. `automation.enabled` is the master switch (scheduler, event jobs, heartbeat and the tools, live through `apply()`); quiet hours silence the heartbeat, never a user's reminder. Only the main agent creates, cancels and runs jobs (invariant 22). `live()` (the job running now, the next timed jobs with their countdown — refreshed each scheduler tick —, the heartbeat's next run and last result, quiet hours, runs today) and `activity()` (job runs) feed the Live page. Jobs that fell due while Banana was stopped run at the first tick after a start, a late one with its original time in the prompt ("it comes late"; a task that only made sense at its time — a wake-up call — is reported as missed instead, block #89); `check()` reports the scheduler and how many were sent (block #87). | `automation.py`, `schemas.py`, `jobs.py`, `scheduler.py`, `heartbeat.py`, `tools.py` |
| `extension` | wip | `ExtensionSession`: discovers `extensions/` (bundled) and `.derived_data/extensions/` (user), validates `extension.json` (`ExtensionManifest`), keeps installed/enabled/settings in `extension_v1.db`, imports `tools.py` / `watchers.py` as a private package (`sidekick_ext_<name>.*`, so siblings import relatively), and on enable routes each contribution to its owner — tools (`origin=extension:<name>`), skills, MCP servers and the subagent profile into `agent`, **automations** (static event jobs from the manifest, built-in, `JobStore.ensure_builtin`) into `automation`, watchers into `perception`; disable removes exactly those. It is the one module that wires and unwires while sidekick runs, because extensions come and go from the dashboard. `install` (path or git URL), `update` (git pull), `remove`, `set_settings` (required keys + primitive types, secrets masked). `ExtensionContext` hands an extension its settings, state dir and the core sessions it may use — built by the loader from the peers its `setup` receives. `live()` gives the active extensions, their tool count and each watcher's last poll and errors. `check()` reports each enabled extension active and its watchers' errors (advice). | `extension.py`, `schemas.py`, `loader.py`, `registry.py` |
| `dashboard` | wip | Loopback FastAPI app with flat static HTML/JS: a **module list on the left** ("Sidekick", then one entry per core module with an icon and a status dot, the active one tinted; on phones a sticky bar with a menu button naming the current module, the list dropping down when tapped; the theme follows the system) and **one page per module on the right, filled with that module's submodule cards** — there is no fixed monitor rail any more: **Live is the monitor of every module** (camera, 3D body and Now on top; the dialogue — watching only — and the activity stream, the Turn card and one card per core module below), the camera and the 3D body are single views (one MJPEG stream, one WebGL context) whose cards move into Body's slots when Body opens, telemetry is on Body, the level meters on Voice, the readiness summary on System. **One entry per core module directory** — Live (`interaction` + `perception`: the conversation), Voice (`interaction`'s speech pipeline), Body, Agent (its views: swarm, tools, MCP, skills, memory, timeline, test, settings), Automation, Contact, Channel, Record, Extension, System (`config` · `doctor` · `storage` · `log` · `dashboard`); a status dot per tab = the worst readiness level of that module merged with its runtime state; old deep links (`#robot`, `#timeline`, …) alias to the new entries (and views: `#tools` → `#agent/tools`). **Every tab aggregates its own monitoring, parameters and debugging (block #44)**: a parameter lives where its effect is watched, rendered by one **parameter-card** renderer from `GET /api/config/schema` (type, bounds, choices, description straight from the pydantic fields; a change posts to `POST /api/config/{section}` at once and the card says "applied" or "takes effect at the next start"), and the services a module uses are configured on that module's tab by one **service-card** renderer per slot (provider, model / voice / speed, the provider's write-only key with "shared with …", Probe). **Live** = now, a module's page = depth (blocks #67 / #69): camera (MJPEG, gamma-lifted when dark, faces boxed with names, the measured rate — 10 fps is the daemon's IPC cap), the 3D body (vendored Three.js r160, SDK meshes posed from the measured head pose and joints) and **Now** (the engagement state, the session's addressee, trigger, turns and seconds left, mic / speaker bars with peak hold, listening, attention, initiative budget, the TTS link, the newest three decisions) on top; below, the **dialogue** (one screen tall: the timeline's user and assistant rows of every channel — voice, Telegram, WeChat, the test card; Banana's own deliveries marked 主动 — as bubbles with day separators, earlier pages when scrolled to the top, the live "listening / thinking / saying" line, a *latest* button; no composer, turns are typed on Agent → Test; the readiness verdict as the empty state while Banana is not ready) above the **activity** stream (what every module did, newest first, module chips as the filter), and on the right the **Turn** card (the turn in progress, else the last: heard and said text, the time to the first word, a waterfall of ASR → first token → TTS → speaking, a chip per tool call) above one card per core module in two designed column stacks — Agent, Services (per slot: median time, median first token, last call, errors per hour, how often a call was asked twice and the second answered first), Memory, Automation, Channel | System (readiness, host vitals — load, CPU, resident memory, event-loop lag, the Pi's temperature —, warnings and errors in 10 min), Body, Perception, Contact, Record, Extension; a card's title opens its module page. The 10 Hz frames of the `/api/live` WebSocket carry the meters, pose, faces and captions; once a second they also carry `modules` (every session's in-memory `live()`) and `activity` (`live.py`); host vitals come from `vitals.py` (standard library only); the 1 Hz `/api/health` poll keeps the daemon status, the recording totals and the contacts cached. **Robot** = the controller on the left (*Take control* parks the voice front end and hands the motion owner to the page; sliders for head / height / body yaw / antennas, gestures, emotions) with the capability tests (mic capture, speaker tone / sweep / replay, say + expression, snapshot, video clip; `robot.py`, files under `cache/robot/`), and the body's parameters on the right (Motion: expressiveness, sway switch + liveliness slider, SDK wobble, volume; the **Expressions** card plays any entry of the library with an intensity and previews the thinking state; Attention: face tracker own / daemon, servo gain, daemon weights, idle scan, sound glances, detection rate, mutual gaze; Sway detail folded; Daemon & connection). **Voice** = the speech pipeline in four views: **Decisions** (the mic / speaker meters and the engagement state in one card, the decisions table with clips and clip-based voice enrollment, 25 rows with *show more*), **Hear** (VAD / ASR local / primary / kws service cards and the thresholds | wake-name aliases and keyword lines, triggers & turns — speaker gate, the turn's ASR slot and shadow, session timeout —, words and the TV sector), **Speak** (TTS primary / fallback side by side, household language, **Pacing** — the pause after a full stop, block #76), **Traces** (ASR, TTS; 12 rows with *show more*). Timeline. **Memory** (block #70: one card per profile — the household and each person — with the digest and the facts by category, their provenance as tags, superseded ones folded away; add a fact; the writer's state and *write now*; the episodes by day, a click opening the conversation and the facts it produced). **Agent** = one **view** at a time from the bar at the top of the page (block #59: a page that outgrows about two screens shows one view per submodule, the bar carries the key numbers — Tools 30 · MCP 0 · Skills 5 · Memory 4 —, deep links `#agent/tools`; a view is one full-width board or two independent column stacks and has no sub-headings, so no row leaves a hole; Agent, Voice, System, Channel): **Swarm** (blocks #76 / #78: one card per agent from `GET /api/agent/agents`, the **main agent** first — answers every turn, its slot, tools, turns, the hedge —, then each subagent — what it does, slot, the tools it gets, skills, tasks, origin —; the main agent's window shows its rules (read-only, from the code), the tools it gets with the main-only ones marked and its settings — slot, steps, reply cap, context, `main_hedge_s` — applied at once; a subagent's window edits yours — name, slot, what it does, role, tools / skills / MCP allowlists with the names to pick from, max steps, timeout; `PUT` / `DELETE /api/agent/subagents/{name}` write `agents.subagents` and apply at once — and shows an extension's read-only; then background tasks, last error and the latest LLM calls with *show more*; `#subagents` deep-links here), **Tools** (every registered tool in one grid sorted by origin, the origin chips — agent core, automation, each extension, each MCP server — as the filter), **MCP** and **Skills** — one card per item with a clamped summary and tags (asks first, main agent only, parameter / tool counts, origin, off), a click opening the item's **details window** (`<dialog>`: a tool's description, parameters and the agents that may call it; an MCP server's command or URL, last error, the names of the secrets it gets and its tools, *Remove*; a skill's Markdown in an editor with *Save* / *Delete*); the add button in the board's head, an empty board saying what belongs there —, **Memory**, **Timeline**, **Test** (a real turn typed as the owner or a contact: the reply, `NO_REPLY` or the error, total time and first words, a chip per tool the turn called — arguments and result on click), **Settings** (the LLM fast / smart service cards). **Automation** = its status (switch, scheduler, runs, quiet hours, the tools it gives the main agent), the Scheduler parameters, Initiative (sociability, quiet hours) and the Jobs table. **Channel** = **Channels** (Telegram token + pairing code, WeChat state, presence) · **Events** (the perception bus). **Contacts** (household table, the guided enrollment — details → three prompted voice takes → face frames with the live preview —, people seen with Befriend / Forget — editing a contact keeps its id, prints and facts (`PUT /api/contacts/{id}`), deleting one deletes their facts —, Recognition thresholds, the TV zone drawn on a camera frame). Extensions. **Replay** (day strip of 5-minute chunks, video + synced tracks, canvas tracks, the 3D body at that moment; plus the recording parameters). **System** = **Readiness** (the status card, the full table with *Check everything* (local · probe · loopback) and *Local checks*) · **Logs** · **Config** (the dashboard address, Backup (`POST /api/system/backup`), the masked config). Write routes re-apply backends so a test turn works without a restart. **Service (blocks #82–#87):** the **power control** at the bottom of the module list (state and since; its panel offers Start, or Restart and Stop; the phone's menu button carries its dot), the blocking **start dialog** (one line per step — configuration, models, then each module — with the module's check items under it, ✓ / ! / ✗ / —, a link to the tab that fixes a failing item, OK once it settles; a stop shows no dialog), toasts for what happens with no dialog open (a start at boot that failed, a 409 "Banana is stopped"), Live's "Banana is stopped" card with Start, runtime-only controls disabled and the runtime tabs' dots grey while stopped, System's Service card (remembered choice, last start / stop); `GET` / `POST /api/service`; runtime routes answer 409 while stopped and writes then only save; "takes effect at the next start" offers *Restart now*. `LoopbackGuard`: a loopback Host on every request (any port: an SSH tunnel works) and a loopback Origin on writes and the live socket. WeChat's QR login is on Channel; System → Logs shows the robot daemon's log too. | `dashboard.py`, `api.py`, `live.py`, `vitals.py`, `robot.py`, `replay.py`, `dashboard_index.html`, `dashboard_app.js`, `dashboard_live.js`, `dashboard_robot.js`, `dashboard_robot3d.js`, `dashboard_replay.js`, `dashboard_three.module.min.js`, `dashboard_stl_loader.js`, `dashboard_orbit_controls.js` |
| `record` | wip | `RecordSession`: one daemon thread records the body into 5-minute chunk directories `recordings/YYYY-MM-DD/HH-MM-SS/` — `video.mp4` (H.264 via GStreamer `appsrc`, Apple `vtenc_h264_hw` / Pi `v4l2h264enc` / `x264enc`, 1280×720 @ 10 fps ≈ 1 Mbps, fragmented MP4 so a crash loses ≤ 2 s), `mic.wav`, `speaker.wav` (silence-padded to the wall clock), `telemetry.jsonl.gz` (10 Hz body telemetry + the interaction extra), `chunk.json` (refreshed every 30 s). Retention (24 h) and a free-disk floor (20 GB: prune oldest, then pause) keep the volume safe; FLAC option for the Pi; chunks left open by a crash are repaired at start. Readers: `days()`, `chunks()`, `chunk()`, `telemetry()`, `chunk_file()`, `status()`. `start()` records only with a connected body; `mic_reader()` hands interaction `read_mic` when the ring keeps WAV audio; `read_mic(start, end)` slices microphone audio across chunks (the open one read raw past its header) — the Listening page's decision clips and voice enrollment come from here instead of a second copy under `audio/`. The façade also exports `VideoWriter`, `WavTrack` and `encoder_name` for the dashboard's test clips. CLI `sidekick record status|prune`. `live()` gives the live counters plus the cached totals (the chunk walk runs on a worker, at most every 30 s); `cached_status()` serves the health poll. A stop event per run (a thread left over never revives); `check()` reports the ring and free disk (advice). | `record.py`, `schemas.py`, `video.py`, `tracks.py`, `chunks.py` |
| `doctor` | wip | `DoctorSession` (Layer 5, may import any module): the readiness list that replaced the first-run wizard (block #44). Three layers — **local** (Python, the on-host models, every slot bound to a provider whose credentials are present and whose session backend is bound, daemon / body / microphone, the audio DSP when the daemon is down, the voice front end, free disk, the recording state, household members and Banana's own voice, channel tokens; no side effects, cached 5 s for the health poll), **probe** (one real call per slot through `ConfigSession.probe`, the resolved region saved), **loopback** (a 0.6 s tone through the speaker while the microphone listens — speaker, microphone and DSP in one go —, the camera frame's brightness; the voice front end is held meanwhile). `DoctorItem` = level ok / warn / bad, a detail and the dashboard tab that fixes it; `DoctorReport.ready` = no bad row, `warn` is advice; `run(layers)` never overlaps itself; `snapshot()` (failing rows + verdict + worst level per tab) rides on `/api/health`. its `start()` logs the local summary and every failing row. `live()` is the last verdict without running a check (the Live page's System card). Since block #87 the local layer is the **prerequisites** (`prerequisites()`: Python, the config, every bound slot's provider and credentials, free disk — the service's start gate) plus the models plus, while the service runs, every module's own `check()` items collected through it; its own body / front-end / recording / people / channel rows went to those modules. `ensure_models()` downloads missing models (the start's second step). While stopped the verdict is "stopped · ready to start" or "stopped · N to fix before starting". | `doctor.py`, `schemas.py` |
| `service` | wip | `ServiceSession` (Layer 5; imports `log`, `storage`, `config`): Banana's service started and stopped inside the process (blocks #82–#87). One state machine (`stopped → starting → running → stopping`), one transition at a time (`ServiceBusy` → 409), run as a background task the dashboard follows. A **start** re-reads and applies the config, checks the prerequisites (any `bad` and nothing starts), downloads missing models, runs `setup_service`, then each module's `start()` and `check()`; a module with a `bad` item (or a `start` that raises) aborts it and everything started is stopped again; `warn` runs marked, `off` shows a dash. A **stop** stops the modules in reverse and unbinds the service backends (`ConfigSession.release`); a Stop is remembered when it begins, and a process exit waits for a stop in flight (only a start is cancelled; block #89: Stop then `sidekick close` ran two stops at once and lost the choice). The owner's last choice is kept in `service.json` (a process exit is not a choice): `sidekick startup` brings Banana back only when it was left running. `status()` (state, remembered choice, the current or last transition with its steps and items), `checks()` (the running modules' items for readiness), `live()`. | `service.py`, `schemas.py` |
| `app.py` | stable | Composition only (invariant 21): `boot()` = home + logging + config load/apply + every session constructed; `setup_service()` = every runtime module's `setup` with the current spec (the service runs it before each start); `start()` = the console — doctor, the service session (its composition and the runtime modules in start order: body, contacts, channels, voice front end, agent, automation, perception, recorder, extensions), the dashboard — then the service's own start (Banana when left running); `stop()` = the service (the robot turns off), then the dashboard. No control flow, closures or wiring of its own — `tests/test_architecture.py` parses it. | — |
| `cli.py` | stable | Two commands (block #85): `sidekick startup` — the main process in the background (a first config for this host when the home has none; `sidekick.pid`; output in `logs/sidekick.out.log`; waits for the dashboard and prints its address; "already running" when it is) — and `sidekick close` (SIGTERM: Banana's service stops and the robot turns off, then the dashboard). Everything else is on the dashboard. | — |

Bundled extensions (`extensions/`):

| Extension | Contributes |
|---|---|
| `robot` | Tools `look` (camera snapshot; described by the `smart` slot when its provider has vision — an optional `question` says what to look for, a dark frame is gamma-lifted first and the model says only what it clearly sees), `express`, `look_at`, `who_is_here`, `privacy_mode` (confirm), `enroll_voice` (conversational enrollment: the next utterances of the current speaker, inside that session only, ≤ 90 s; an unnamed speaker is befriended as with `befriend`, a named one learns into their own contact only — never a lookup by name, block #63), `set_volume`, and befriending: `people_seen`, `befriend(person_id, name, language)` (not confirm-gated: the owner decided befriending is the agent's own behaviour), `decline_befriend`; skills `robot body` (Banana's expressions by kind, the style tags), `befriending`, `storytelling` (a lively style, one expression on each real beat, short spoken paragraphs; calm for bedtime); `express` lists the library in its description; automations `befriend` on `person.ready` and `greet` on `greet.due` (both delivery `in_person`; the agent may answer `NO_REPLY`); skill `initiative` (when Banana may speak first). Enabled by default. |
| `news` | Feed sources ported from Scoop `SCPSync` (RSS / Atom / JSON Feed, Hacker News top stories, Telegram public channels), `feeds` watcher → `feed.update`, tools `news_latest` / `news_search` / `news_sources`, `news` subagent on `smart`, skill `briefing`. Enabled by default with BBC Chinese + Hacker News. |
| `media` | qBittorrent (`qbt_list`, `qbt_add` confirm) and Jellyfin (`jellyfin_search`, `jellyfin_now_playing`) tools, `downloads` watcher → `media.download_done`, `media` subagent; settings carry URLs and credentials (secrets masked). Disabled until configured. |
| `home` | Home Assistant tools `ha_entities`, `ha_state`, `ha_call` (and `ha_call_sensitive` with confirmation for locks / alarms / covers), `states` watcher → `ha.state` for configured entities, `home` subagent. Disabled until configured. |

## Core designs

### Agent swarm

- **One runtime, two roles.** `Agent(profile)` is the only agent class. An `AgentProfile` has:
  `name`, `role` (system prompt), `llm_slot` (`fast` | `smart` | custom), `tools` allowlist,
  `mcp_servers` allowlist, `skills` allowlist, `memory_scope`, `max_steps`, `timeout_s`.
- **Main agent** owns every inbound turn (its card heads Agent → Swarm; its own knobs apply at once,
  `configure_main`). A turn someone waits for is hedged: no first word after `main_hedge_s`
  (2.5 s) → the same request again, the first to answer wins (block #78); jobs and relays are not.
  It must answer fast, so it runs on the `fast` slot with a
  small tool set: `reply`, `delegate`, `recall`, `remember`, `schedule` (automation's), plus a few
  instant lookups. Its job is conversation and intent routing, not long work. It may answer
  `NO_REPLY` when an utterance was not addressed to it. It alone creates, cancels and runs
  automation jobs (invariant 22).
- **Subagents** are domain workers (news, media, home, companion, research, …) registered by
  extensions or defined in config (`agents.subagents`, created, edited and deleted on Agent →
  Subagents and applied at once; a profile's `origin` is `core`, `user` or `extension:<name>`,
  and an extension's subagent is read-only there, block #76). They run on the `smart` slot by default and see only their own
  tools, MCP servers and skills — never a `main_only` tool (`delegate`, the scheduling tools),
  whatever their allowlist says. They are experts for one domain: they receive a task plus a
  context slice, run the ReAct loop and return a result; a follow-up they want goes back to the
  main agent in that result (as OpenClaw's sub-agents, which always lose `cron`).
- **Delegation** is a tool call: `delegate(agent, task, mode)`. `mode=sync` blocks the turn until
  the subagent returns (bounded by its timeout) and the main agent composes the reply.
  `mode=async` (background delegation) returns a task id (`task-…`) at once; the subagent runs as
  an in-memory background task, and its result is appended to the timeline as an internal note
  that a follow-up main-agent turn relays to the person through the delivery policy. It is
  delegation, not automation: started by a conversation, never persisted.
- **ReAct loop** (`loop.py`): build context view → call LLM with tool schemas (streaming) →
  execute tool calls (confirm-gated, concurrent where independent) → append tool results → repeat
  until a final message or `max_steps`. Every step is appended to the timeline with
  `visibility=internal`.
- **Tools** (`tools.py`, the tool protocol in `schemas.py`): `Tool` has `name`, `description`,
  `parameters` (JSON schema), `handler(args, ctx) -> ToolResult`, `confirm` (bool), `origin`
  and `main_only`. Besides the agent's own, tools are registered by the modules above the agent
  that implement this protocol, each in its own `setup` (invariant 19): `automation` its
  scheduling tools, the extension loader an extension's.
- **MCP** (`mcp.py`): a registry of server configs (stdio or HTTP) persisted in SQLite, each with
  `origin` (`user` or `extension:<name>`); each server's tools are surfaced into the registry
  under a namespace. CRUD tools `mcp_add`, `mcp_remove`, `mcp_list`, `mcp_enable`.
- **Skills** (`skills.py`): a skill is a Markdown document with a `name` and `description`
  header, OpenClaw-style, stored in SQLite with `origin`. The description list is injected into
  the owning agent's prompt; a short body (≤ 1,200 characters) comes along, a longer one is
  loaded on demand with `skill_read` (block #71: a story no longer waits for a read). CRUD tools
  `skill_create`, `skill_update`, `skill_delete`, `skill_list`, `skill_read`.

### Dialogue and memory

Memory is a pyramid written from the conversations themselves (blocks #65–#70): **L0** the
timeline, **L1** one episode per conversation, **L2** facts about each person and the household.

- **Timeline — L0** (`dialogue.py`): one append-only table. Message fields: `id`, `ts`, `channel`,
  `speaker` (contact id, `guest:<n>` or agent name), `role` (`user` | `assistant` | `tool` |
  `internal`), `content`, `attachments`, `visibility` (`public` | `private` | `internal`),
  `reply_to`, `delivered_to`, `conversation`. A **conversation** is the room (`voice`) while
  turns follow each other within 5 minutes, or one chat (channel + chat id; the test card per
  speaker) within 15 minutes (`agents.memory_voice_gap_min` / `memory_text_gap_min`); its id is
  readable (`voice@20261029-185600`). Telegram private chats and WeChat arrive `private`, so a
  private chat is a conversation of its own and its rows are private. The raw timeline is never
  rewritten.
- **Context view**: per turn, the agent gets the rows of its own conversation within
  `context_chars`, filtered by visibility (`internal` steps only for the agent that produced
  them), user rows labelled with display names when several people talk, plus the memory block.
  Past tool calls are rebuilt from the tool rows (an assistant message with the calls, then the
  results cut to 400 characters), because a reply whose calls are hidden teaches the model to
  answer without them (block #63); each step carries the words said before its calls, and the
  reply after them shows only the model's own last words (`reply`), never the platform's
  acknowledgement (block #76). When a long conversation outgrows the budget, the summary of
  its earlier part (its rolling episode) leads the view. Other conversations — other people's
  chats, old test turns — never enter a turn's prompt; they reach it only as memory.
- **Episodes — L1** and **facts — L2** (`memory.py`, `memory_v1.db`): an episode has a title, a
  summary, follow-ups with dates (a question to ask after an event), the participants, its
  visibility (private when the conversation was a private chat) and its source conversation. A
  fact is one short sentence with its provenance: `scope` (whose profile — a contact or the
  household), `subject`, `teller`, `channel`, `visibility`, `origin` (`explicit`: the `remember`
  tool or the dashboard; `inferred`: the writer), `category` (identity, style, preference,
  routine, date, health, money, relationship, other), `valid_until`, `sources` (rows) and
  `episode`. A changed fact is superseded and kept as evidence; only a person's own `forget`, the
  dashboard and deleting a contact delete facts. An episode deleted on the dashboard (or with its
  contact) keeps an empty `deleted` marker, so the writer does not write it again (block #76). A
  scope whose facts outgrow its share of the
  block gets a digest.
- **The memory writer** (`writer.py`): one background task. When a conversation closes it reads
  it once and writes the episode and the facts with one call on the `smart` slot
  (`agents.memory_slot`, traced as `memory.writer`); a long conversation is also written every 12
  user turns. The model proposes, the code decides (invariant 23): facts only from named
  participants who spoke; household facts only from open conversations; a private chat's facts
  stay with their teller; health, money and relationships only from the person themselves and
  always private; what someone says about another person stays in the teller's scope; a person
  may correct what is known about them; an explicit household fact is changed only by its teller;
  at most 8 facts a conversation; unnamed people only appear as "a visitor" in an episode. Not
  written: the test card, job and heartbeat turns, subagent steps, conversations without a user
  turn. At start it catches up on the last 7 days; a failed write is retried up to 3 times. Each
  night (`agents.memory_nightly_hour`) it expires dated facts, writes digests and merges
  duplicates in large scopes (a merge that would retire more than a quarter is refused).
- **The memory block** (`MemoryStore.block`, `AgentSession.memory_block`): built from SQLite once
  per conversation and speaker and frozen for it (invariant 24: no model, no search on a turn):
  the speaker's facts — their private ones only in their private chat —, the household's, the
  last conversations they took part in (the newest with its summary when recent) and the
  follow-ups due; about `agents.memory_block_chars`. An unnamed speaker gets the household's
  facts only. Tools: `remember` (explicit facts, private in a private chat or for a sensitive
  category), `forget` (the speaker's own matching facts, else the household's), `recall`
  (keywords over the speaker's facts, the household's, the other members' open facts — what was
  said openly is shared — and the episodes they may see; an episode id opens its conversation).
  Personalization (a child's age, a parent's commute) is memory, not a mode. Memory follows
  identity (invariant 23, block #63): an unnamed speaker keeps no facts (the `remember` tool tells
  the agent to befriend first), deleting a contact deletes their facts and private episodes, and
  facts the dashboard kept under `owner` move to the owner contact once one exists.

### Automations, heartbeat, delivery

- **The `automation` module** (layer 4, above the agent; blocks #55–#57) owns all of it: the job
  store, the scheduler, the event jobs and the heartbeat. Its `setup` registers the main-only
  tools `schedule` / `jobs_list` / `job_cancel` into the agent and subscribes `on_event` to the
  perception bus; a due job or a fired event becomes one main-agent turn
  (`AgentSession.run_job_turn`) with a prompt framed here. `automation.enabled` is the master
  switch — scheduler, event jobs, heartbeat and tools — applied live.
- **Job** (`automation/schemas.py`): `id`, `name`, `trigger` (`cron` | `at` | `event{type,
  filter}`), `prompt`, `delivery` (`in_person` | `remote` | `both` | `auto`), `owner`, `channel`,
  `state`, run bookkeeping, `builtin`. A job names no agent: every job runs on the main agent.
  Natural language from a user becomes a job through the `schedule` tool; the scheduler executes
  deterministically.
- **Heartbeat** (`automation/heartbeat.py`) is a built-in periodic job for the main agent: look
  for something new since its last run that the household has not heard, then either speak/send
  or stay silent (`NO_REPLY`). It is a consumer, not a system tick: nothing subscribes to it or
  depends on it — periodic work registers as a scheduler job and event sources publish on the
  perception bus (block #52). The scheduler knows it only as the predicate it silences in quiet
  hours.
  Reminders are spoken by their own jobs, never by the heartbeat. Its prompt carries its last run
  time and everything delivered on Banana's own initiative in the last day, with times, because
  the timeline view has none — without that it re-announced a past reminder every half hour
  (2026-10-28, block #47). A delivered message is one timeline row (`delivered_to` + the policy);
  the job's own turn does not record it a second time.
- **Delivery policy** `auto`: if `perception` says someone is present in the room and the body is
  awake, speak through the voice channel (opening an engaged session for follow-ups); otherwise
  send to the job's remote channel (the chat the request came from); `both` does both. The policy
  lives in the agent (`deliver`), because it writes the timeline and background results use it
  too. Event jobs (`trigger = event{type, filter}`) are fired by the perception bus through
  `AutomationSession.on_event`.

### Interaction: engagement, interruption, languages

The voice front end decides *when the robot is being talked to* and *when it should stop talking*
before any cloud call is made.

```text
SLEEPING ──antenna | wake name | schedule──► IDLE ──trigger──► ENGAGED ◄──► SPEAKING
   ▲                                          ▲                  │
   └──────────── long idle ───────────────────┴── timeout / bye ─┘
```

- **IDLE** (awake, ambient): the mic stream runs VAD → for each speech segment: local name
  spotting, speaker identification, DoA; perception reports faces, gaze and presence. Nothing is
  sent to cloud ASR. The body glances at people and sounds and keeps a social presence (it no
  longer breathes: the owner retired the idle bob, block #80).
- **Triggers** IDLE → ENGAGED, each individually switchable in config:
  1. `wake_name` — every IDLE speech segment is transcribed **locally** by the `asr.local` slot
     (SenseVoice via sherpa-onnx; one model covers Mandarin, Cantonese and English) and checked
     for the fixed name **Banana**: its aliases are the spellings SenseVoice really wrote
     (`bananna`, `ananna`, `banaa`, `把娜娜`, … — list tunable on the Voice tab) and are matched
     as written, and the name itself is also matched loosely, word by word (a spelling nobody
     has seen yet, "VANANA", still wakes it). Nothing else is loose (block #94): loose aliases
     took "nana" and "Panama" for the name, windows across words found it in "a banner and a",
     and a loose three-character alias would take 「娜娜」 for 「把娜娜」 — as "BB", a parent
     calling a child, once passed for the first name's "bob" (block #89). This replaces
     keyword-spotting models, which exist only for Mandarin/English. The
     sherpa-onnx open-vocabulary keyword spotter (`asr.kws`, English phones + pinyin, keyword lines
     in `robot.keywords`) runs on the same segment and a hit on **either** detector counts: each
     hears what the other misses. On 55 synthesized utterances SenseVoice wrote the name 52
     times and the spotter found 40 (it misses the Mandarin-accented ones), together all 55;
     12 minutes of speech without the name woke it only on English "bandana" and "banner"
     (block #94). A short content-less
     segment just before ("Banana," cut off by the pause) is merged into the check. The segment
     minus the name becomes the first turn, so "Banana，今天天气怎么样" is one turn: every name at
     its start or end goes ("BANANNA BANANA" is only the name), one in the middle becomes
     "Banana", so the agent never takes its own name for someone else's. Only the name: the
     antennas flick and Banana answers out loud at once (「我在！什么事？」, a clip made at
     start, no model call —
     first-time callers took the silence for a broken robot, block #92) unless they are already
     talking again; the session then waits as after a question. Open to everyone, including
     guests.
  2. `gaze` — a frontal face within range whose direction matches the speech DoA **and** an
     enrolled voice. Unknown voices cannot trigger by gaze because a TV may be in view. The main
     agent double-checks addressing and may answer `NO_REPLY`.
  3. `touch` — today an antenna push: the two antennas are low-stiffness motors; pushing one past
     0.3 rad is read from its joint angle, so it is a physical button with zero false positives and
     safe for the hardware. A touch means "I'm talking to you"; it also starts enrollment and is
     the always-available hard stop. Head-tap detection is deferred: the Lite has no touch sensor
     and no IMU; it would need commanded-vs-measured head-pose deviation, which false-triggers
     during the robot's own motion. On Wireless the head IMU makes tap detection straightforward.
     `body` exposes one `touch` event so the source can change without touching `interaction`.
  4. `robot_initiated` — an automation or heartbeat that speaks to a present person opens a
     session for follow-ups.
- **ENGAGED**: a session with an `addressee` (contact or `guest`), a `direction`, a
  `last_activity`. Every VAD segment that matches the session (same speaker id, or same DoA sector
  within tolerance when the speaker is unknown) goes to ASR without any wake name. The session
  ends on silence timeout (default 8 s after the robot stops speaking — the turn ends when the
  speaker has played everything, however long the story; `answer_timeout_s` 15 s after a reply
  that ends with a question; speech that began before the silence ran out holds the session
  until its segment is decided — the timer used to close sessions under people mid-sentence,
  13 times on 10-30/31, block #92; extended while the addressee's face stays frontal), on a closing
  utterance (再見 / 就這樣 / 多謝 / bye), or when the main agent returns `NO_REPLY` twice in a
  row. Block #89: a 30 s cap on the wait for the speaker ended every story's turn 20 s early,
  and the child's answers to 「你估下…？」 came after the session had closed.
- **TV in view**: the Contacts tab marks a *TV zone* on a camera frame and the Voice tab a *DoA
  sector*. Faces inside the zone are ignored for gaze and presence; speech from the sector never
  triggers gaze and is ignored in IDLE unless it contains the wake name. The robot's own TTS voice
  is enrolled as the `self` contact so residual echo fails speaker identification.
- **Speaker gate** (`speaker_gate`): `off` (anyone can trigger anything), `soft` (default:
  enrolled contacts trigger by name or gaze; unknown voices only by name or antenna), `strict`
  (enrolled only). Speaker embeddings come from sherpa-onnx speaker models; thresholds live in
  config and are tuned on the dashboard's listening monitor.

**Attention and initiative (block #38).** Banana may always look but rarely speaks first, and
every time it does there is a reason from an event and a rule, never from wanting to chat.

- *Attention* is deterministic and body-level and never speaks: while IDLE the head takes a slow
  scanning glance every 8–15 s (a random direction within ±40°, held 2–3 s, back to neutral —
  the camera's horizontal field is 90°, so people off to the side are never found otherwise),
  glances toward a clear sound (orient only; ≥ −35 dBFS for ≥ 0.6 s, one per 8 s, never the TV
  or self sector), and stops glancing the moment a face is seen. **Face tracking is ours**
  (block #40): the detector's 10 Hz observations drive a proportional servo through the motion
  owner (pixel offset → angle via the camera intrinsics, 0.7 of it per step from the current
  eased pose, 0.35 s easing), so the face stays centred and nods / glances still
  compose; the daemon's blended tracker is an option (`face_tracker: daemon`). The camera
  watcher raises `gaze.mutual` once per episode of a centred face turned toward the camera for
  ≥ 2.5 s. **Self-motion gating:** the motion owner exposes its moving window (looks,
  expressions of 6° or more, controller poses; not the antennas, the small beats or
  the slow thinking state), the front end flags speech that began and ended inside it, and such
  speech never ducks playback and is traced as `self motion`.
- *Conversation* (block #50) is body language, never speech: a small `ack` when a turn is
  accepted; while the agent works Banana **thinks** — the head tilts a little, the antennas sway
  in turn, and after 2.5 s the tilt slowly changes side with a small "hmm" and a slow antenna
  tick, while the eyes stay on the person (block #80: the owner read the old sideways glance
  as looking around, 「说话过程又有东张西望」; a DoA turn inside a session needs a direction its
  readings agree on, 20° away, and no face in view); the state ends before the first word; while speaking the head
  sways with the voice and sometimes nods on a new phrase; a `yield` beat ends the reply; while
  they talk, a small `mm_hm` nod at their pauses (at most one per 3.5 s). Emotions come only
  from the agent (`[express:…]`, most replies none), and `[style:lively]` (stories, play with
  children) / `[style:calm]` (comfort, bad news) scale one reply; `body.expressiveness` is the
  household's baseline.
- *Initiative* goes through the agent and a budget: `gaze.mutual` of a **known** contact who was
  away ≥ 2 h (voice / face `last_seen`), outside quiet hours, under the daily cap, at most once
  an hour per person → `greet.due` → the robot extension's `greet` automation; the agent writes
  one short greeting in their language or answers `NO_REPLY`. Unknown people never qualify
  (befriending is their path), sounds never qualify, safety events (`audio.cry`, `audio.alarm`)
  will be the only exception. The `sociability` setting (`quiet` never speaks first, `normal`
  2 h / 6 a day, `chatty` 30 min / 12 a day) is the owner's knob; everything beyond the greeting
  rule is deliberately left blank until this has been watched in the household.

**Interruption (two-stage barge-in, invariant 20).** Users must be able to cut the robot off, but
a family room is full of speech that is not for the robot.

- **Who may interrupt**: the addressee (speaker id, or the session's DoA sector when unknown);
  anyone who says a stop word (停 / 等一下 / 等陣 / stop / 收聲) or the wake name; an antenna touch.
- **Stage 1 — duck** (within ~100 ms of speech onset from a qualifying source): lower playback by
  12 dB, stop queuing further TTS sentences, lift the antennas as a listening cue, keep buffering
  the audio from onset.
- **Stage 2 — confirm**: hard stop when the speech lasts ≥ 700 ms, or a stop word / wake name is
  spotted, or an antenna is touched. A hard stop cancels TTS playback and the running LLM stream,
  turns the head to the speaker, and feeds the buffered utterance to ASR as the next turn.
- **Otherwise** (a short backchannel such as 嗯 / 好 / 哦 / laughter): restore volume and continue,
  optionally with a small nod.
- **Long content** (stories, briefings) is spoken in paragraphs with a ~1 s pause between them;
  during the pause the interruption threshold is lower, and 繼續 / 下一段 resumes.
- Every duck / resume / stop decision is traced with its scores and clip (invariant 18).

**Streaming pipeline.** `LLM tokens → sentence fragments (first comma after 4 chars, or sentence
end) → bidi TTS WebSocket → PCM 16 kHz frames → paced body speaker (≤ 250 ms ahead so ducking and
stops react fast)`, with the "thinking" tilt right after end-of-speech. Target: first audible word
≤ 2.5 s after the user stops speaking. Measured 2026-10-26 on the Lite: local SenseVoice ASR
~0.1 s, MiniMax `fast` first token 2.2–3.0 s, first audio 3.0–4.5 s, so the LLM is the budget; the
turn ASR slot is `interaction.asr_slot` (default `local`; MiniMax `asr-1.0` takes ~2.6 s and runs
as a shadow for the dashboard comparison). The first-word pass of 2026-10-29 (block #71): the
LLM's HTTPS connection is kept open and warmed (a fresh TLS handshake through this Mac's proxy
cost 1.3 s per call); `fast` is MiniMax-M3.1-Flash with minimal reasoning (median first token
~1.5 s at the evening peak, steadier than M3 with thinking off at ~2.4 s, and more honest about
missing tools); the system prompt stays the same for a conversation and the per-turn line leads
the turn's message, so MiniMax's prefix cache (`cached_tokens`) covers the role, skills, memory
block and history; the TTS server only starts on a sentence end or a flush, so a first clause
still open after 150 ms is flushed; time questions are answered from the context line; short
skills (≤ 1,200 characters: storytelling, briefing) ride in the prompt instead of a `skill_read`
round. Block #76 (after the owner's first test: 「好，等我睇下」 before nearly every reply, and no
pause where the punctuation is): the main agent calls tools without announcing them, and a short
spoken acknowledgement (「好，等我睇下。」) goes out only when nothing has been said yet and a
step's tools are still running after 0.4 s — the camera, a subagent, the network; local tools
answer within 0.12 s. It is a `filler` event, kept in the transcript but never shown back to the
model, which had copied it into its own replies. The TTS server leaves ~0.2 s between its
sentences, the same as a comma inside one, so every sentence that ends in 。！？；… is flushed as
it is sent and the keeper puts `interaction.sentence_pause_ms` (300 ms) of silence before the
next sentence's audio, less the silence the speaker already had (measured on the robot: full
stops ~0.5 s, commas ~0.2 s). MiniMax ASR has no real-time input (its `stream=true`
is SSE output for an uploaded file); `ASRStreamingBackend.transcribe_stream` exists so a real-time
vendor or incremental local SenseVoice can be swapped in later without touching the pipeline.

**Languages.** Household default and per-contact preference (set at enrollment), priority
Mandarin → English → Cantonese since block #94 (`languages.default` = `zh`). The wake name is an
English word; its aliases are how SenseVoice writes it from Mandarin and English speakers.
ASR: MiniMax `language` header = the speaker's preference when known, else the household's;
SenseVoice decodes `zh` in a Mandarin household and `auto` otherwise (in `auto` it took some
Mandarin for Cantonese). TTS: per-language voice and `language_boost` (`Chinese` for Mandarin,
`Chinese,Yue` for Cantonese); a voice follows its slot's language — one pinned for another
language is dropped when the household language changes — and the robot's own voice print is
made again from the new voice. LLM: the turn's context line names the reply language and the
role its register — natural spoken Mandarin in Simplified characters, colloquial written
Cantonese (係 / 唔 / 嘅) in Traditional ones, never formal written Chinese — and the examples in
the skills are Mandarin, because the model repeats the examples it is given.

**Fallbacks**: every trigger, gate and interruption parameter is a config switch; the listening
monitor shows live scores and the last N accepted / rejected / ducked segments with audio, so a
misbehaving rule is turned off or re-tuned without code changes.

### Body

- Wraps `reachy_mini.ReachyMini` behind `BodySession`: `connect()`, `state` (asleep / awake /
  gravity-compensation mirrored from the daemon), `express(name)`, `look_at(direction)`,
  `track_face(on)`, `play_audio(pcm16k)`, `frames()` / `audio()` publishers, `doa()`, antenna
  events. `null.py` implements the same API for development without hardware; `--sim` uses the
  MuJoCo daemon unchanged.
- Lite and Wireless differ only in `host` and media backend selection, which come from config.
- Expressions are Banana's own (`expression_library.json`, block #50), played by the motion
  owner as offsets on top of the gaze. Pollen's recorded moves are not used: `play_move()`
  blocked the motion thread for up to 20 s (no gaze, no sway, no touch) and played a sound
  effect into the same speaker as the voice (block #46).

### Provider framework (config / llm / asr / tts)

- **Presets** `config/provider_<id>.json`: `id`, `name`, `console_url`, `credentials` (fields
  with `secret`), `regions` (`domestic` | `overseas` | `global`), `capabilities` (`tools`,
  `vision`, `streaming`, `asr`, `tts`), and service blocks `llm`, `asr`, `tts` each with `api`,
  `url{region}`, `model`, `params`, `extra_body`, `per_language`, `credential_map`, plus
  `default_voice` / `voices`. MiniMax: LLM via `v1_chat_completion`
  (`/v1/text/chatcompletion_v2`), ASR via `minimax_speech_to_text` (`/v1/speech_to_text`, model
  `asr-1.0`, multipart WAV), TTS via `minimax_sync` (`/v1/t2a_v2`); domestic host
  `api.minimaxi.com`, overseas `api.minimax.io`.
- **Four services, named slots.** Presets may carry `llm`, `asr`, `tts` and `vad` blocks. The
  catalog includes `provider_local.json` for on-host models (`asr: sherpa_sensevoice`,
  `vad: silero_sherpa`; no credentials, region `global`), so "local" is not a special case.
  Planned vendor presets: `minimax` (first), `local`, later `elevenlabs` (TTS, Scribe ASR),
  `volcengine`, `qwen`, `openai`, `gemini`.
- **Spec** (`.derived_data/config.json`, mode 0600): `credentials{provider_id → {field → value}}`,
  `region`, `languages{default, …}`, and `slots`: `llm.fast`, `llm.smart`, `asr.primary`,
  `asr.local`, `tts.primary`, `tts.fallback`, `vad.primary`, each `{provider, model?, voice?,
  speed?}`, bound on the dashboard's service cards; mixing vendors is just editing slots. Plus non-provider sections `robot` (the fixed name
  `Banana`, its aliases and keyword lines; a retired name is replaced on load), `body`, `channels.telegram`, `channels.wechat`, `agents`, `interaction`
  (triggers, gate, thresholds, TV zone / sector, barge-in parameters, attention and sociability),
  `body.sway` (the speech sway's master, per-axis amplitudes / frequencies, loudness window,
  timings, speaker latency), `body.expressiveness` (how big Banana's expressions and speech
  movements are overall; the retired `emotions_dataset` / `emotion_sound` / `stop_daemon_on_exit`
  keys are dropped on load). Every user-facing field carries a `description`; the dashboard renders
  its parameter cards from the JSON schema (`GET /api/config/schema`). The retired `onboarding`
  section is dropped on load.
- **apply()** merges preset + spec + resolved region into `ProviderSpec{api, params, credentials}`
  per slot, builds the backend in a single `match api` per service, and calls
  `*Session.shared.setup(slot, backend)`. **probe()** builds the real backends and makes one call
  per slot, so bad keys, models or voices fail at save time on the dashboard (Probe).
- **Results** carry `success`, `output`, `provider`, `api`, `model`, `api_key_hint`, `usage`,
  `status_code`, `api_code` (vendor's in-body code, e.g. MiniMax `base_resp.status_code`),
  `error_message`. Content-policy refusals are detected by code/token, never by prose.
- **Streaming (MiniMax).** LLM: SSE on `chatcompletion_v2` with tool calls, consumed token by
  token. TTS: bidirectional WebSocket `/ws/v1/t2a_v2_bidi` (text in, server-side sentence
  buffering, audio out) as primary; HTTP `/v1/t2a_v2` with `stream=true` as fallback; request PCM
  at 16 kHz so chunks go straight to the robot speaker without decoding (format and sample-rate
  options to be verified against the T2A reference at implementation time). ASR: HTTP upload with
  `stream=true` SSE deltas; `language` header supports `zh`, `yue`, `en`; max 500 s / 50 MB; no
  real-time input endpoint.

### Contact and identification

- A contact is a household member: `id`, `name`, `aliases`, `notes`, `language`, `is_owner`,
  remote ids (Telegram chat id, WeChat id), voice embeddings, face embeddings. Unknown people are
  `guest:<n>` for the duration of a session. A reserved `self` contact holds the robot's own TTS
  voice embedding. There are no roles and no modes; personalization is memory and notes.
- **Enrollment**: voice — three to five short utterances, embeddings averaged, stored with the
  model id; face — several frames from the camera, detected with OpenCV YuNet and embedded with
  OpenCV SFace (ONNX models shipped in `.derived_data/models/`). Both via the dashboard or a
  conversational flow started by an antenna press ("我是爸爸，记住我的声音").
- **Identification**: `identify_voice(pcm) -> (contact | None, score)` and
  `identify_face(image) -> (contact | None, score)`; `interaction` fuses the two when a frontal
  face and matching DoA coincide with speech.
- **One voice, one identity from day to day** (block #80). A voice enrolled one evening scored
  0.41–0.54 against itself the next morning (another hour, another place in the room) and was
  split into a new `person:n`, whose centroid of that morning then beat the contact on every
  sentence. So: a contact at the threshold wins over a closer unnamed person; 0.35–0.5 to a
  contact is *uncertain* (`near`) — never a new person, the session's speaker inside a session,
  and three of them whose mean clears the threshold identify the session; less than 1.0 s of
  speech is not identified and less than 1.2 s never starts a person; utterances identified as a
  contact keep teaching its centroid (weight capped at 50); an unnamed person whose centroid
  reaches 0.55 with one contact (≥ 4 utterances, 0.1 clear of the next) is merged into it.
  Replayed on that morning's clips: no new person, the session known by its fourth sentence,
  later sentences 0.58–0.77.
- **Befriending** (block #35): strangers are not enrolled through a wizard. Every unknown voice
  becomes a `person:n` whose voice (and, when the DoA agrees with the largest face, face)
  accumulates silently while they talk; unpromoted people hold vectors only, never memory, and
  expire after 7 days unseen. When a person has been heard enough, `person.ready` fires the
  robot extension's `befriend` automation: the main agent, following the `befriending` skill,
  asks the name in conversation, confirms it, asks whether they want to be remembered, and
  calls `befriend` — its own social judgement, no owner approval. The Contacts page lists
  people seen with a manual Befriend / Forget. Identities never merge by name (block #63): a
  person befriended under a household member's name becomes a second contact (`爸爸_2`), and
  `enroll_voice` from a `person:n` befriends them rather than starting another contact.

### Extensions

- **Manifest** `extension.json`: `name`, `version`, `description`, `tools` (python file exposing
  `TOOLS`), `watchers` (python file exposing `WATCHERS`), `skills` (list of `skill_*.md`), `mcp`
  (list of server configs or `mcp.json`), `subagent` (profile), `automations` (built-in event
  jobs: `name`, `event`, `prompt`, `delivery`, `filter`), `settings` (JSON schema shown on the
  dashboard; values stored in the registry, secrets masked).
- **Lifecycle**: `install` (from `extensions/`, a path or a git URL into
  `.derived_data/extensions/`), `enable`, `disable`, `remove`, `update`. Enabling registers the
  extension's contributions with `origin=extension:<name>`; disabling removes exactly those.
- **Dashboard** lists extensions with status, settings forms and the contributed tools / skills /
  MCP servers; skills are editable inline.

### Perception

- `EventBus` with typed events (`presence.enter`, `presence.leave`, `face.seen`,
  `face.identified`, `face.unknown`, `gaze.frontal`, `gaze.mutual`, `person.ready`, `greet.due`,
  `audio.cry`, `audio.alarm`, `feed.update`,
  `job.done`, `ha.state`, …), each with `severity`. Sources run as asyncio tasks; automations and
  `interaction` subscribe. The bus keeps a short in-memory history and persists events of
  `severity >= notice`.

### Storage and data directory

- `./.derived_data/` (override with `SIDEKICK_HOME`): `config.json`, `service.json` (the owner's
  last Start / Stop), `sidekick.pid` and `reachy_daemon.pid` (the processes sidekick runs),
  `dialogue_v1.db`,
  `memory_v1.db`, `automation_v1.db`, `contact_v1.db`, `skills_v1.db`, `mcp_v1.db`,
  `extension_v1.db`, `events_v1.db`, `llm_trace_v1.db`, `asr_trace_v1.db`, `tts_trace_v1.db`,
  `engagement_trace_v1.db`, `logs/` (`sidekick.log`, `sidekick.out.log` of the background process,
  `reachy-daemon.log` rotated at 50 MB), `audio/` (engagement clips), `models/` (sherpa-onnx and
  OpenCV ONNX models, downloaded on first run), `extensions/`, `cache/`, `recordings/` (the 24 h
  ring; `recording.root` can point it at another disk).
- Trace tables and engagement clips auto-prune (10 days / 7 days); recordings by
  `recording.retention_hours` and the free-disk floor; dialogue and memory are never pruned
  automatically.

### Recording and replay

- `record` runs the robot's black box: every 5 minutes a new chunk directory receives the camera
  (H.264 MP4, reduced to 720p @ 10 fps so a day is ≈ 11 GB at most and a few GB in a quiet room),
  the microphone and the speaker feed (16 kHz PCM WAV, each ≈ 2.8 GB per day; FLAC on the Pi),
  and 10 Hz telemetry rows (commanded and measured head pose, joints, antennas, levels, DoA,
  face, plus the interaction state and captions handed in by `app.py`; gzip ≈ 45 MB per day).
  Dialogue, decisions and perception events are not duplicated: they are already timestamped in
  SQLite and are queried by time range (`between()`) when a chunk is replayed.
- Chunks roll on the clock, descriptors are written at open, every 30 s and at close, the MP4 is
  fragmented, and WAV headers of a chunk left open by a crash are repaired on the next start, so
  a power cut costs at most seconds, never the chunk.
- Retention is 24 h by default and a free-disk floor pauses recording (after pruning the oldest
  chunks) instead of filling the volume; Live's Record card shows the state.
- The Replay tab is the control room: a day strip, the chunk video with its two audio tracks in
  sync, canvas tracks (envelopes, engagement state, dialogue / ASR / TTS markers, rejected
  decisions, events), click-to-seek, and the 3D body posed from the telemetry row under the
  cursor. The same 3D component renders the live robot on the Live tab.

### Dashboard and CLI

- Dashboard binds `127.0.0.1:8787` (the Reachy daemon owns 8000). There is no wizard and no
  global Settings page: the console is a module list on the left and one page per core module on the
  right, each page made of that module's submodule cards (monitoring, parameters, debugging) —
  **Live** (now: camera, 3D body and Now on top; the dialogue — one screen, for watching — and
  the activity stream; the Turn card and one card per core module from each session's
  in-memory `live()`, blocks #67 / #69), **Voice**
  (views: Decisions, Hear, Speak, Traces), **Body** (3D body and camera side by side, telemetry, controller + tests, the body's parameters), **Agent** (views:
  Swarm — one card per agent, the main agent first, the latest LLM calls —, Tools / MCP / Skills — one card per item,
  a click opening its details window —, Memory, Timeline, Test — a real turn typed as one of
  the household —, Settings — main-agent knobs, LLM service cards), **Automation**
  (status, scheduler, initiative, jobs), **Contact** (enrollment, recognition, TV zone), **Channel**
  (views: Channels, Events), **Record** (the 24 h ring, recording parameters), **Extension**,
  **System** (views: Readiness, Logs, Config). One entry per core module directory.
  A page that outgrows about two screens shows one view per submodule, switched by a bar at its
  top that carries the key numbers; a view is one full-width board or two independent column
  stacks with no sub-headings, so no row leaves a hole (blocks #59–#61: Agent, Voice, System,
  Channel). No board is
  hidden or dragged by hand: the order is designed, not configured.
  Plain HTML + JS, no build step; Three.js r160 (MIT) is vendored as flat
  `dashboard_three.module.min.js` / `dashboard_stl_loader.js` / `dashboard_orbit_controls.js`
  so the page works offline.
- **Readiness (block #44).** The `doctor` module answers "can Banana talk now, and what do I
  fix where?" in three layers: local (static, no side effects, refreshed every few seconds),
  probe (one real call per slot) and loopback (speaker → microphone, camera brightness). Items
  carry ok / warn / bad, a detail and the tab that fixes them; `ready` means no bad row. The
  verdict shows on System's status card (the failing rows with jump links and a *Check*
  button), on Live's System card, as the sidebar dots, in the Live empty state and as the full
  table on System. Because readiness is computed from the live state rather than
  a one-time flag, an expired key, a deleted model or an unplugged robot reappear on the list by
  themselves.
- Taking control from the Robot tab is the one sanctioned way to drive the body by hand: the
  motion owner stays the only `set_target` caller (invariant 10), the voice front end is parked
  rather than stopped, and *Release* restores the idle posture. Test files (`mic-*.wav`,
  `snapshot-*.jpg`, `video-*.mp4` + `video_mic-*.wav`) live in `.derived_data/cache/robot/`,
  newest 20 kept.
- **The process and the service** (blocks #82–#87). The CLI starts and closes the process —
  `sidekick startup` (in the background; a first config for this host when there is none: macOS
  `lite-mac`, a Linux ARM board `pi`; prints the dashboard's address) and `sidekick close` — and
  nothing else: readiness, configuration, the daemon, channels (Telegram pairing, WeChat's QR
  login), enrollment, extensions and backup are on the dashboard. The dashboard lives as long as
  the process; its power control (the bottom of the module list) starts and stops Banana's
  service in it. A start runs in a blocking dialog that ticks each step: the configuration
  check (the prerequisites; anything missing and nothing starts, the tabs that fix it turn red),
  the models (downloaded when missing), then each module coming up and proving it works — the
  robot (daemon spawned, woken, telemetry, camera, microphone), contacts, channels, the voice
  front end (VAD, SenseVoice loaded, the wake-name spotter, the TTS link), the agent (one real
  call per model slot), automations (jobs missed while stopped are sent now), perception,
  recording, extensions. A stop shows nothing: the robot sleeps and its daemon exits, the
  models and connections are released (measured: 1.2 GB running, 0.12–0.44 GB left after a run
  — onnxruntime and OpenCV keep part — and the daemon's 0.6 GB freed), and the dashboard with
  every data page (contacts, memory, jobs, Replay, traces, logs) stays. The choice is
  remembered across restarts.

## Conventions

- **Async first.** asyncio everywhere; blocking SDK or GStreamer calls run in threads
  (`asyncio.to_thread`) or in `body`'s dedicated motion thread; the audio front end runs in its
  own thread and hands decisions to the loop.
- **Sessions.** Each façade exposes `<Area>Session` with a class-level `shared` instance and a
  `setup(...)` method that receives its config and the backends or peers it needs, and wires
  itself into them there (invariant 21); `start()` / `stop()` when it runs or cleans anything,
  `stop()` safe on a session that never started. Only `app.py` (and, for the runtime modules,
  the service it composes) calls them. Tests construct their own instances. A runtime module's
  session is restarted in place (block #83): `setup` may run again while stopped (its wiring
  idempotent: register by key, subscribe once), `start()` acquires the run's resources
  (threads with a stop event of their own, tasks, clients, models, subprocesses), `stop()`
  releases all of them and returns it to "set up" — its store-backed calls keep working for the
  dashboard — and `check()` returns its readiness items (`ok` / `warn` / `bad` / `off`), which a
  start shows under the module and which abort it when `bad` (block #86).
- **Schemas** are `dataclass(frozen=True, slots=True)` or `pydantic` models where validation is
  needed (config, manifests, tool arguments). Do not mix in one module.
- **Errors.** Backends never raise for provider failures; they return a `*Result` with
  `success=False`. Programming errors raise.
- **Dependencies.** Allowed third-party packages are listed in `pyproject.toml` with a one-line
  reason comment each. In tree: `httpx` (all HTTP), `websockets` (MiniMax TTS
  WebSocket), `pydantic` (config, presets), `numpy`, `sherpa-onnx` (VAD, local ASR, keyword
  spotting, later speaker embeddings), `reachy-mini` (robot SDK + daemon), `fastapi` + `uvicorn`
  (dashboard), `mcp` (official MCP client, transport only), `segno` (QR codes for the WeChat
  login, pure Python), `opencv-python-headless` (face detection and embedding). GStreamer
  (PyGObject) is used through the `reachy-mini` dependency only (recording), imported lazily.
  Browser-side, Three.js r160 (MIT) is vendored into `dashboard/` (owner sign-off in PLAN.md
  block #24). Adding a dependency requires owner sign-off and a `PLAN.md` note.
- **Tests.** `pytest`; `tests/test_<module>_<topic>.py`; markers `hardware`, `network`, `slow`.
  `tests/test_architecture.py` is mandatory and runs in CI.
- **Formatting / linting.** `ruff` (format + lint, `I` and `D` rules on), `mypy --strict` on
  `src/`.
- **Secrets** never enter the repository or the conversation with a coding agent. `.env` is for
  local development only and is ignored.

## PLAN.md protocol

- Newest block first. Block heading: `## [YYYY-MM-DD #n] <Kind>: <title>` where `Kind` is one of
  `Research`, `Discussion`, `Decision`, `Todo`, `Progress`.
- A `Status board` section at the top is kept current: phase, next up, open questions.
- Before non-trivial work: add a `Todo` or `Decision` block. After: add a `Progress` block and
  tick items. Never rewrite history blocks; append corrections.

## Workflow for coding agents

1. Read this file, then the `Status board` and the newest blocks of `PLAN.md`.
2. Find the module in the yellow pages, then read its façade header and the relevant submodule
   headers.
3. Append a `PLAN.md` block describing the change before writing code.
4. Implement inside the module structure rules; update headers and the yellow pages if the public
   surface changed.
5. Run the verification checklist. Append a `Progress` block.

## Verification checklist

- `poetry run pytest` passes, including `tests/test_architecture.py`.
- `poetry run ruff check . && poetry run ruff format --check .` clean.
- `poetry run mypy src` clean.
- No secret in any log line or trace row (grep for key prefixes in `.derived_data/logs`).
- Yellow pages and module headers reflect the change; `PLAN.md` has the block.
