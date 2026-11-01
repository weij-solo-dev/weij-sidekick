# sidekick

A desktop home-butler agent with a body. sidekick runs as one always-on Python service on a Mac mini
or a Raspberry Pi, uses a [Reachy Mini](https://huggingface.co/docs/reachy_mini/index) robot as
its eyes, ears, voice and face, and talks to the household through the robot and through remote
channels such as Telegram and WeChat. It is OpenClaw-like in shape — gateway, channels, a self-built agent
runtime with tools / MCP / skills, memory, automations, heartbeat — with the robot as its embodied
node.

Status: **Phases 0–6 done, console v3 landed** — the robot wakes on "Bobby", listens, answers in Cantonese through
MiniMax, can be interrupted; the self-built agent has tools, memory written from the conversations
themselves (L0 timeline → L1 episodes → L2 facts per person and household), skills, MCP, reminders
and a heartbeat; Telegram and WeChat (iLink) channels and presence events are in; household members are
identified by voice and face; extensions add robot tools, news briefings, the media center and Home
Assistant. The local console opens on a **Live** page that monitors every module right now (camera
stream, a 3D Reachy Mini posed from the real joints, the engagement state, the dialogue, the turn in
progress with its time to the first word, one card per module, the activity stream), has a **Robot** page that gathers every robot figure and lets you take
the body over to test motion, microphone, speaker, camera and video, records the last **24 hours** of
video, audio and telemetry in 5-minute chunks, and replays them like a control room (video,
tracks, scrubber, 3D pose). Deployment profiles (`lite-mac`, `wireless`, `pi`), login services and
backups are in the CLI. See `PLAN.md` for the status board and
roadmap. Coding agents start at `AGENTS.md`. 中文说明见 `README_CN.md`.

## What it will do

- Talk with every family member, know who is speaking (voice and face), remember what matters to each of them.
- Keep the child company: stories with expressions, show-and-tell explanations, learning games.
- Deliver briefings: news, weather, calendar, show updates.
- Run automations: timed reminders and event-driven rules, delivered in person or remotely.
- Watch the room: presence, strangers, alarming sounds; expose a `/look` to the owner's phone.
- Orchestrate the home media center and smart home through existing services (Jellyfin,
  qBittorrent, Home Assistant) instead of reimplementing them.

## Architecture at a glance

```text
                         ┌─────────────────────────── sidekick process ───────────────────────────┐
  Telegram ──► channel ─►│   ┌──────────── automation ───────────┐      ┌──── dashboard ─────┐    │
                         │   │ reminders · cron · event jobs     │      │ a page per module  │    │
                         │   │ heartbeat · its own tools         │      │ boards · traces    │    │
                         │   └─────────┬───────────────▲─────────┘      └────────────────────┘    │
                         │             ▼ due job       │ calls schedule (main agent only)         │
                         │   ┌────────── agent (swarm) ──────────┐                                │
  voice ───► interaction─┼──►│ main agent ──delegate──► subagents│                                │
   ▲  │                  │   │ dialogue · memory · tool protocol │                                │
   │  ▼                  │   │ MCP · skills · delivery policy    │                                │
  body (Reachy adapter)  │   └───────────────┬───────────────────┘                                │
   ▲  │                  │                   │ llm · asr · tts  ◄── config (provider presets)     │
   │  ▼                  │   perception: presence · faces · sounds ──► event jobs   storage · log │
  Reachy daemon :8000    └────────────────────────────────────────────────────────────────────────┘
   (motors, camera, mics, speaker)                       ▲
                                                         │ API
                                        Jellyfin · qBittorrent · Home Assistant · feeds
```

Layers and the one-way dependency rule (the full allowed-import table is in `AGENTS.md`):

```text
L5  app.py · cli.py · dashboard · doctor
L4  automation                     jobs, scheduler, event jobs, heartbeat, its scheduling tools
    extension + extensions/        robot · news · media · home: tools, MCP, skills, subagents, watchers
L3  agent                          main agent + subagents, dialogue, memory, tool protocol, MCP, skills
L2  interaction · perception · contact · channel · record
L1  llm · asr · tts · vad · config · body
L0  log · storage · audio
```

One composition rule holds for every module: `app.py` constructs the sessions and calls `setup`,
`start` and `stop` in dependency order, nothing else; whatever a module hooks into a peer (tools
into the agent, a subscription on the perception bus, an adapter into the channel registry) it
does in its own `setup` and undoes in its own `stop`. `tests/test_architecture.py` parses
`app.py` to keep it that way.

## How a voice turn flows

```text
mic (16 kHz, hardware AEC) ──► body.AudioPump ──► interaction.frontend (Silero VAD, 1 s pre-roll,
                                                   streaming keyword spotter "Bobby")
        │ speech segment + direction of arrival
        ▼
interaction.engagement  IDLE: local SenseVoice + keyword spotter ─► wake name? ──no──► traced, dropped
                        ENGAGED: same speaker / direction? ─────────────────────► accept
        │ accepted utterance (never sent to the cloud before this point)
        ▼
interaction.pipeline    asr (local SenseVoice ~0.1 s; MiniMax asr-1.0 as shadow ~2.6 s)
                          │ text
                          ▼
                        agent.main (MiniMax fast slot, streaming; first token ~2.4 s)
                          │ text deltas ─► sentence fragments (first comma after 4 chars)
                          ▼
                        tts primary (MiniMax bidirectional WebSocket, one session for all turns)
                          │ PCM 16 kHz chunks
                          ▼
body.AudioPlayer (≤ 250 ms queued, live gain for ducking) ──► robot speaker (head wobbles)
```

Measured on the Lite on 2026-10-26: first audible word 3.0–4.8 s after the person stops talking,
of which the LLM's first token is 2.1–3.0 s. Every decision (accepted, rejected, ducked, stopped,
echo) is stored with its scores and a clip and shown on the dashboard's listening monitor.

Barge-in: speech from the addressee's direction ducks playback at once; sustained speech, a stop
word (停 / 等一下 / stop), the wake name or an antenna touch cancels playback and the LLM stream and
the interrupting utterance becomes the next turn; backchannels (嗯 / 好) restore the volume. The
robot's own voice is recognised by comparing what the microphone heard with what is being said and
its direction is learned as a sector that can never interrupt. Attention: the mic array's
direction-of-arrival turns the head toward the speaker; the daemon's face tracking takes over while
engaged. All motion passes through one control owner in `body`.

## How a remote turn and the swarm work

```text
Telegram message ──► channel.telegram ──► agent.main
                                            │
                       ┌────────────────────┼─────────────────────┐
                       ▼                    ▼                     ▼
                  answer directly     delegate(sync)        delegate(async)
                                            │                     │
                                            ▼                     ▼
                                      subagent "media"      subagent "news"
                                      tools: qbittorrent,   tools: feeds, summarize
                                      jellyfin · MCP ·      skills: briefing style
                                      skills                      │
                                            │                     ▼
                                            ▼            result ─► timeline (internal)
                                   result ─► main composes      ─► relayed by a follow-up turn
                                            │
                                            ▼
                               reply ─► originating channel (Telegram)
```

One dialogue timeline stores every message from every channel. Each message carries `speaker`,
`channel` and `visibility`; the LLM sees a filtered per-turn view, never a raw replay, so a child's
chat and an adult's private remote instruction do not leak into each other.

## How automations run

```text
"remind me at 8 to take the pills"  ──► main agent ──► schedule tool ──► job {at 08:00, prompt, delivery}
"tell me if someone unknown shows up" ─────────────────────────────────► job {event: face.unknown}
                                        (automation's tools, main agent only)

perception event bus                     automation: scheduler · event jobs
  presence · faces · audio · feeds ─────►  match trigger ─► one main-agent turn with the job prompt
  job.done · ha.state                              │
                                                   ▼
                                    agent: delivery policy
                                   owner in the room? ──yes──► speak (voice channel)
                                           │ no
                                           └────────────► send (Telegram)
```

`automation` is its own module above the agent: the job store, the scheduler, the event jobs and
the heartbeat live there, and its `setup` registers the scheduling tools into the agent and
subscribes to the perception bus. Only the main agent creates, cancels and runs jobs; subagents
are experts for one domain and never see these tools. `automation.enabled` switches all of it
off — scheduler, event jobs, heartbeat and the tools — and on again, live.

The heartbeat (`automation/heartbeat.py`) is a built-in periodic job: the main agent looks for
something new since its last run that the household has not heard yet, then speaks, sends, or
stays silent. It is not a system tick that other modules listen to; nothing depends on it.
Reminders are spoken by their own jobs, never by the heartbeat; it is told when it last ran and
what Bobby already said unprompted that day, so it does not repeat itself.

## Provider framework

One declarative preset per vendor (`src/sidekick/config/provider_<id>.json`) holds everything fixed:
endpoints per region, models, extra body, credential fields, voices, capabilities, for the `llm`,
`asr`, `tts` and `vad` services. On-host models are just another provider (`local`). The user
supplies credentials, region and languages, and binds each service **slot** to a vendor:
`llm.fast` for the main agent, `llm.smart` for subagents, `asr.primary` / `asr.local`,
`tts.primary` / `tts.fallback`, `vad.primary`. MiniMax everywhere is the default; mixing in
ElevenLabs or a local model is editing one slot. Saving probes every service through the real backend so a bad key or voice fails
immediately. Every model call is traced to SQLite and visible on the dashboard. This is the same
design as the weij-scoop iOS app, rendered in Python.

## Extensions

Everything beyond the core is an extension: a flat directory with an `extension.json` manifest that
contributes tools, MCP servers, skills, a subagent profile and event watchers through one protocol.
Bundled extensions live in `extensions/` (`robot`, `news`, `media`, `home`); user-installed ones in
`.derived_data/extensions/`. The dashboard lists, enables, disables, configures and removes them.

```text
extension.json ──► loader ──► registry (enabled, settings)
      │                           │
      ├── tools.py       ───────► agent tool registry   (origin = extension:<name>)
      ├── mcp.json       ───────► agent MCP registry
      ├── skill_*.md     ───────► agent skills store
      ├── subagent       ───────► agent swarm
      └── watchers.py    ───────► perception event bus
```

## Starting and stopping Bobby

The command line only starts and closes sidekick; Bobby itself is switched on the dashboard.

```text
sidekick startup ──► the process: dashboard · data pages · readiness · service    (sidekick close ends it)
                          │
     power control ──► Start: a dialog ticks every step, each module proving it works
     (bottom of the        configuration (keys, slots, disk) ─ anything missing: nothing starts,
      module list)         │                                  the tab that fixes it turns red
                           models (downloaded when missing)
                           robot     daemon spawned · woken · telemetry · camera · microphone
                           contacts · channels
                           voice     VAD · SenseVoice loaded · wake-name spotter · TTS link
                           agent     one real call per model slot
                           automation (reminders missed while stopped: sent now)
                           perception · recording · extensions
                   └──► Stop: the modules in reverse; the robot sleeps, its daemon exits,
                         models and connections released; the dashboard stays
```

A module that cannot prove itself (no microphone, a model slot that does not answer) aborts the
start and everything started is stopped again; advice (no Telegram token, the camera warming up)
runs marked. The choice is remembered: `sidekick startup` brings Bobby back only when it was left
running, and reminders that fell due while it was stopped are sent at the next start, saying they
come late.

## Console: every tab owns its parameters

There is no global Settings page and no setup wizard. A parameter lives on the tab where its effect is
watched (the sway slider next to the 3D body, the VAD thresholds next to the decisions), rendered
from the config's pydantic schema and applied on change; the services a module uses (LLM slots on
Agent, ASR / TTS / VAD slots on Voice) are configured on that module's tab, with keys stored once
per provider. Readiness replaces the wizard: a list of what is missing and where to fix it,
computed from the live state, so an expired key or an unplugged robot shows up by itself.

```text
Modules  a list on the left, one entry per core module: Live · Voice · Body · Agent · Automation · Contact ·
         Channel · Record · Extension · System; each page is that module's submodule cards (no fixed monitor
         rail); a long page shows one view at a time from a bar at its top that carries the counts (Agent,
         Voice, System, Channel)
Live     now (a module's page is the depth): camera (MJPEG, lifted when dark, faces boxed) · 3D body · Now
         (state, addressee, seconds left, meters, the newest decisions) on top; the dialogue (one screen,
         every channel, watching only) and the activity stream (what every module did); the Turn card
         (heard / said, time to the first word, ASR → first token → TTS → speaking, a chip per tool) and one
         card per module: Agent · Services · Memory · Automation · Channel · System · Body · Perception ·
         Contact · Record · Extension      ← /api/live: 10 Hz frames, every live() + activity once a second
Body     left: the 3D body (SDK URDF meshes, measured pose + joints) with the camera beside it, telemetry (commanded vs measured pose,
         joints, antennas, levels, DoA, face, daemon), the controller (Take control → sliders for head / height / body yaw / antennas, gestures,
         emotions) and the tests (mic capture, speaker tone / sweep / replay, say, snapshot, video);
         the Expressions card (Bobby's own library, intensity, a thinking preview);
         right: the body's parameters (expressiveness, sway + liveliness, attention, daemon)  ← /api/robot/*
Voice    views: Decisions (meters, engagement state, decisions with clips) · Hear (VAD / ASR service cards,
         thresholds, wake name, triggers, words, TV sector) · Speak (TTS service cards, language, the pause
         after a full stop) · Traces
Agent    views: Swarm (a card per agent — the main agent first: its rules, tools and settings; subagents:
         yours created / edited / deleted, an extension's read-only — and the latest LLM calls) ·
         Tools (one grid, origin chips) · MCP · Skills (a card per item → details window) · Memory (profiles: facts by person with where they came
         from; episodes by day → the conversation; the writer) · Timeline · Test (a real turn typed as one of the
         household: reply, tools called, timings) · Settings (LLM fast / smart)
Automation  status · scheduler · initiative · jobs (reminders, recurring, event jobs, the heartbeat)
System   views: Readiness (verdict, Check, failing rows, recording / providers / uptime, the full table:
         local · probe · loopback) · Logs · Config (dashboard address, backup, masked config)
Channel  views: Channels (Telegram token + pairing, WeChat, presence) · Events (the perception bus)
Record   every 5 min: video.mp4 (H.264 720p@10fps) · mic.wav · speaker.wav · telemetry.jsonl.gz · chunk.json
         24 h retention · free-disk floor
Replay   day strip → chunk video + synced audio tracks → canvas tracks (envelopes, state band, dialogue /
         decision / event markers) → scrub → 3D body at that moment
```

## Memory: what Bobby keeps from a conversation

```text
L0 timeline    every message, in a conversation: the room while turns follow within 5 min, a chat within
   │           15 min — a turn's prompt sees only its own conversation
   ▼ the conversation closes (5 / 15 min quiet; a long one every 12 turns) — never during a turn
memory writer  one `smart` call → an episode + proposed facts → the rules decide what is kept:
   │           named speakers only · a private chat stays with its teller · household facts only from
   │           open conversations · health / money / relationships only first-person, private ·
   │           a change supersedes, never deletes · the test card, jobs and subagents write nothing
   ▼
L1 episode     title · summary · follow-ups ("睇牙順唔順利？" the day after) · participants · conversation
L2 facts       per person and the household: category · teller · channel · asked / inferred · until ·
   │           sources;  nightly 03:00: expire dated facts · digest a profile that outgrew the prompt ·
   │           merge duplicates (refused past a quarter)
   ▼ a new conversation starts
memory block   read once from SQLite and frozen — no model, no search on the turn: the speaker's facts
               (private ones only in their private chat), the household's, the last conversations with
               them, follow-ups due   ·   `recall` → facts, episodes, an episode's conversation
```

## Befriending: how a stranger becomes a name

```text
unknown voice ──► person:N (voice centroid; face when the sound direction matches the largest face)
   heard enough (≥ 6 turns over ≥ 2 visits, or 8 in one) ──► event person.ready
   ──► automation "befriend" → main agent + befriending skill: 「你叫咩名？」→ confirm → 「想唔想我記住你？」
   ──► tool befriend(person_id, name) → a contact with everything collected · no owner approval
   not seen for 7 days ──► forgotten            Contacts page: "People seen" with Befriend / Forget
   until befriended: voice / face only — `remember` keeps nothing for a person:N, and a name the
   household already has becomes a second contact (爸爸_2), never a merge (block #63)
```

A known voice stays known from day to day (block #80): a contact at the threshold beats a closer
person:N, a voice just under it (0.35–0.5) is never a new person and three such sentences of one
conversation identify it by their mean, a sentence under 1 s ("Bobby") is not identified at all,
every recognised sentence keeps teaching the contact's voice, and a person:N that turns out to be
a contact's voice (centroids ≥ 0.55) is merged into it — by voice, never by name.

## Listening: when does the robot respond?

```text
SLEEPING ──daemon wakes the robot──► IDLE ──trigger──► ENGAGED ◄──► SPEAKING
   ▲                                  ▲                  │
   └──────── daemon sleeps it ────────┴── timeout / bye ─┘

IDLE     local only: VAD · keyword spotter · SenseVoice name check · DoA · faces   (no cloud ASR)
trigger  "Bobby" (keyword spotter on the live mic feed, or SenseVoice text with fuzzy aliases) ·
         antenna touch · robot-initiated speech · (gaze + enrolled voice: Phase 4)
ENGAGED  session with an addressee (speaker id or direction); follow-ups need no wake name until
         8 s of silence after Bobby stops talking (15 s after Bobby asked a question; a sentence
         begun in time always counts), "再見", or two NO_REPLY answers. The name alone gets a
         spoken answer at once ("喺度！咩事呀？")
SPEAKING two-stage interruption: qualifying speech ducks −12 dB; ≥ 0.9 s of speech, a stop word,
         the wake name or an antenna touch stops; fillers, backchannels and the robot's own echo never do
```

The robot never wakes or sleeps itself: the Reachy daemon does both — spawned when Bobby's
service starts, stopped (the sleep move) when it stops. Every decision is traced with its scores and a short clip, and the dashboard's listening
monitor shows them live, so thresholds and triggers are tuned on real household data instead of
guessed.

### Looking around, speaking first

Two layers sit on top of the machine. **Attention** never speaks: while idle the head takes a slow
glance at a random direction every 8–15 s (the camera only sees 90°), turns toward a clear sound
to see who made it, and keeps a face it sees centred (our own detector at 10 fps drives a servo
through the motion owner, so nods still show; there is no idle breathing any more); a face that stays centred and turned
toward the camera for 2.5 s is a *mutual gaze*. While Bobby speaks, its head sways with its own
voice — our port of the SDK's wobble, with a "liveliness" slider on Body (a third of the SDK's
default) and every amplitude and frequency in `body.sway`. **Expressions are Bobby's own** — 51
offset curves (conversational beats, emotions, performances, the thinking states) played on top
of the gaze, never with a sound. In a conversation Bobby gives a small nod when it has heard
you, tilts its head a little while it thinks with the antennas swaying in turn (the tilt
changes side with a small "hmm" if it takes longer) and keeps its eyes on you, sometimes nods on a new
phrase while it talks, and nods "mm-hm" at your pauses; emotions come only when the agent
feels one (`[express:laugh]`, most replies none), and `[style:lively]` (stories, play with
children) or `[style:calm]` (comfort, bad news) scales one reply on top of the household's
`body.expressiveness`. Speech that starts and ends while Bobby's own head
motors run is marked as self motion and never ducks playback. **Initiative** goes through the agent
and a budget: a known household member's first mutual gaze after two hours away becomes a
`greet.due` event, the robot extension's `greet` automation asks the agent for one short greeting
(or `NO_REPLY`), and the `sociability` setting on the Automation page — quiet / normal / chatty —
decides how often that may happen. Sounds and strangers never make Bobby speak first.

## Repository layout

```text
src/sidekick/
  app.py          assembles all modules (runtime)
  cli.py          `sidekick startup | close` (everything else is on the dashboard)
  <module>/       one flat directory per core module
    <module>.py   façade: the module's Session and public API, assembles submodules
    <component>.py
    schemas.py · utils.py
extensions/       bundled extensions, one flat directory each
tests/            flat pytest files, including the architecture test that enforces one-way imports
.derived_data/    runtime state (git-ignored): config.json, SQLite files, logs, audio clips, models, recordings/
AGENTS.md         harness and module yellow pages (for coding agents)
PLAN.md           timestamped plan, decisions, research
```

## Getting started

```bash
# requirements: Python 3.12, Poetry 2.x, a Reachy Mini Lite on USB
# run every command from the repository root; state lives in ./.derived_data/
poetry install
poetry run sidekick startup     # sidekick in the background; prints http://127.0.0.1:8787/
poetry run sidekick close       # Bobby stops (the robot sleeps), then sidekick
```

A fresh home gets a first config for the host (macOS: the Lite on USB; a Linux ARM board: the Pi
profile); with `$MINIMAX_API_KEY` set the key is filled in for development. On the dashboard,
System lists what is still missing (the MiniMax key goes on the Agent tab's service cards) and the
power control at the bottom of the module list starts Bobby; then say "Bobby，今日天氣點呀？" or
push an antenna. Telegram (bot token, pairing code) and WeChat (QR login) are on Channel,
extensions on Extension, backups on System; without a robot, Body → Daemon & connection sets the
daemon to a mockup simulation or the body to `null`.

## License

TBD.
