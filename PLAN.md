# PLAN

Running plan, discussion records and research notes for sidekick. **Newest block first.** Block
heading format: `## [YYYY-MM-DD #n] <Kind>: <title>`, `Kind` ∈ Research · Discussion · Decision ·
Todo · Progress. History blocks are never rewritten; corrections are appended as new blocks.

## Status board

- **Phase:** roadmap complete (Phases 0–6, block #23), **console v3 landed** (blocks #26–#32:
  persistent monitor rail, Live chat, Robot controller, Memory page, 24 h recording, Replay)
  the **first live-session fixes** (blocks #33–#34: steady gaze, faces in the dark, guests
  told apart, guided enrollment, clips from the ring), **befriending** (blocks #35–#37:
  people seen, `person.ready`, the agent's own befriending task) and the **attention /
  initiative layers** (blocks #38–#39: scanning and sound glances, mutual gaze, self-motion
  gating, greeting a known person after an absence, sociability setting) and the **frame pump +
  own face servo** (block #40: 10 fps camera shared by every reader, the face kept centred) and
  the **own speech sway** (blocks #41–#43: the SDK wobble replaced by a parameterised port with
  a liveliness slider).
- **Done 2026-10-27 afternoon (blocks #44–#45):** every tab owns its parameters (13 tabs,
  Voice tab, service cards per module, schema-driven parameter cards; Settings / Setup /
  Traces / Logs gone) and the `doctor` readiness module replaced the wizard (rail card, dots,
  Live empty state, System page). **Next up:** the owner's acceptance review; the CLI
  `doctor` brief; a daylight / lamp-on session to confirm face
  tracking, the servo and the first real `gaze.mutual` → `greet.due` on the real camera.
  Nothing committed yet. Owner rule: daemon only through `sidekick daemon`.
- **Done 2026-10-28 (blocks #46–#47):** emotion moves play without the library's sound effects
  (they talked over Bobby's voice; `body.emotion_sound` on Body → Motion turns them back on); the
  heartbeat no longer re-announces an old reminder, and a delivered message is one timeline row;
  unnamed-speaker labels (`person:6`) are never spoken or shown (block #48); **Bobby's own
  expressions and conversational body language** (blocks #49–#51: 51 authored expressions on
  three motion layers, thinking / backchannel / turn-yield, `[style:…]` per reply,
  `body.expressiveness`, the storytelling skill). The heartbeat stays as it is (owner).
- **Open questions (owner):** keep local SenseVoice as the turn ASR (0.1 s, MiniMax 2.6 s as
  shadow)? enable MiniMax `service_tier: priority` (−0.3 s first token, pricing)? speaker volume
  below 100 to reduce self-echo?
- **Done 2026-10-29 (blocks #52–#58):** one composition rule for every module (`app.py` only
  constructs and calls `setup` / `start` / `stop`, enforced by a test), the `automation`
  module above the agent (jobs, scheduler, event jobs, heartbeat; main agent only; a real
  master switch), Tools / MCP / Skills boards with a details window, an Automation page.
- **In review 2026-10-29 (blocks #59–#64):** dashboard layout — no per-page show / hide or
  dragging; a long page shows one view per submodule from a bar at its top, a view is one board
  or two column stacks with no sub-headings: Agent (Swarm · Tools · MCP · Skills · Memory ·
  Timeline · Test · Settings), Voice, System, Channel. Live's dialogue card shows the whole
  conversation from the timeline, for watching only; turns are typed on Agent → Test. Memory
  follows identity (blocks #63–#64): unnamed speakers keep no facts, identities never merge by
  name, voice enrollment stays in its session, past tool calls are back in the context view.
  Open: a code guard for replies that claim a result without the tool (block #64).
- **Done 2026-10-29 (blocks #68–#74), in review:** memory written from the conversations in
  three levels (L0 conversations → L1 episodes → L2 facts with provenance; the writer after a
  conversation ends; a frozen memory block per conversation; invariant 24: memory never slows a
  turn) — live, no shadow week, the owner tests it; Live as the monitor of every module (Now,
  Turn, eleven module cards from in-memory `live()`, the activity stream, host vitals); the
  first-word pass (blocks #72 / #75): the LLM connection kept open (first token 2.6 s → 1.2 s
  for the same prompt), `fast` = MiniMax-M3.1-Flash with minimal reasoning (1.5 s vs 2.4 s at the
  evening peak), a cache-friendly prompt, the first clause flushed to TTS, fewer model rounds.
  **Owner:** test memory (enroll first), watch the Turn card, decide the proxy rule.
- **Done 2026-10-30 (blocks #76–#77), in review:** the spoken acknowledgement only before a slow
  tool and never shown to the model (it was before nearly every reply and the model copied it);
  tools called without announcing them; a real pause after 。！？ (Voice → Speak → Pacing, 300 ms
  over the voice's own ~0.2 s); Agent → Subagents (create / edit / delete yours, an extension's
  read-only); an episode deleted on the dashboard stays deleted. Then (blocks #78–#79): the main
  agent's calls are hedged (no first word after 2.5 s → asked again; A/B max 19.4 s plain vs
  2.6 s hedged) and the main agent heads Agent → Swarm with its rules, tools and live settings.
  **Owner:** listen to the pauses, try Swarm, watch "asked twice" on Live's Services card.
- **Done 2026-10-30 (blocks #80–#81), in review:** after the owner's Cantonese session — one
  voice stays one identity from day to day (a contact beats a closer unnamed person, an
  uncertain band that is never a stranger, a session's mean, learning, merging split voices;
  the owner's split `person:25` merged back), a sentence's direction is the median of its
  readings (the four sentences dropped as `other direction` would pass), the eyes stay on the
  person (thinking without the sideways glance, no turn on one stray reading), breathing
  retired, no false touch from a jammed left antenna (it cannot reach +43° once the head turns
  ≥ 25°: **owner to check**), and SenseVoice stays the recogniser (best of every local
  Cantonese model; MiniMax no better). **Owner:** talk to Bobby again; choose whether to try a
  cloud recogniser with Cantonese hotwords.
- **Proposed 2026-10-30 evening (block #82), owner to decide:** start / stop the service from
  the dashboard while the process stays with the CLI — the service switched inside `sidekick
  run` (fresh runtime sessions for every start, the dashboard and data pages up while stopped,
  the robot asleep while stopped, the owner's choice remembered); four decisions listed there.
  Owner chose option A with each module's singleton session restarted in place (block #83);
  the four decisions are still open. Then (block #84): a start gate on the readiness list
  (toast + red tab dots), and a stopped footprint of only the dashboard and data pages —
  measured 61 MB set up but never started, 0.12–0.44 GB after a run in the same process
  (onnxruntime / OpenCV keep memory) → recommended: the service in its own process.
  Decided (block #85): one process after all (the residual is fine), a blocking dialog that
  ticks every start / stop step, the robot off (daemon stopped) while stopped, Stop
  remembered, missed reminders sent at start, the CLI reduced to `startup` + `close`.
  Then (block #86): a start brings each module up and proves it (robot daemon / wake / link,
  one real LLM call, models preloaded, TTS connected; contacts need no check).
  **Done (blocks #87–#88), in review:** power control at the bottom of the module list, a blocking
  start dialog of per-module checks, the robot off while stopped, the CLI down to `startup` /
  `close`. **Owner:** try it.
- **Done 2026-11-01 (blocks #89–#90), in review:** fixes from the family's session of 10-31:
  - stories no longer cut off: the turn ends when the speaker does, and Bobby waits 15 s after
    asking;
  - "BB" in a sentence is a child, not the name; every name is stripped from a turn, and a bare
    call is answered;
  - no emoji spoken; `look` brightens dark frames and takes a question; no offers to make tea;
  - Stop + `close` no longer overlap or lose the choice; a wake-up call missed while stopped is
    reported as missed.
  **Owner:** a story with 思源; decide whether the power panel shows the next timed job.
  Then (block #92, owner: 「聊着聊着就没反应」「只喊 bobby 没回话以为坏了」): speech that began
  before the silence ran out holds the session (13 sessions had closed under people
  mid-sentence; 12 of them now kept), and a bare call gets a spoken 「喺度！咩事呀？」 at once
  (pre-synthesized, no model call).
- **Done 2026-11-20 (blocks #94–#95), in review:** the robot and its wake name are **Banana**
  (name, aliases and keyword lines fixed by the code; a home under the old name is migrated on
  load; aliases matched as written, the name itself loosely and word by word); **Mandarin** is
  the default language (voice, cloud ASR, SenseVoice `zh`, replies; a voice follows the
  household language, the robot's own voice print follows the voice); the confirm gate takes
  no confirmation from the model; merged to `main`. Measured on synthesized voices only.
  **Owner:** the first real "Banana" on the robot; decide how 思源 is spoken to.
- **Resolved 2026-10-26:** hardware (Lite on this Mac), provider (MiniMax, streaming, per-slot
  vendor binding incl. `vad`), robot name Bobby (fixed), channels (Telegram + personal WeChat via
  iLink), integrations as extensions, single interaction mode, guests allowed with TV-safe gating,
  two-stage interruption, antenna touch now / head tap deferred, languages Cantonese → English →
  Mandarin, no publishing, state in `./.derived_data/`.

---
- **Research 2026-11-01 (blocks #91 and #93), owner to decide:** a host for the Lite on its own.
  Owner: the Lite → Wireless conversion is feasible with Seeed parts (staff have done it) and a
  small footprint is a goal; block #93 puts two conversion routes into the comparison (A: Seeed's
  CM4 controller board + power board + battery, price pending the owner's link / quote; B: a
  CM5 / CM4 on a nano carrier inside the Lite's foot, ≈ ¥900–1,500) — the smallest option, the
  robot plus one cable. Otherwise: a new Mac mini M6 at the 国补 price (≈ ¥4,300–4,929, zero
  porting) or an N150 mini PC (≈ ¥1,100–1,600, one to three days of Linux work), each in a
  20–22 cm plinth. Chinese report: https://claude.ai/artifact/QMYsxdKdirGgCRrc1Rcfio

## [2026-11-20 #95] Progress: Banana, Mandarin by default, the confirm gate; merged to `main` (block #94)

- **The name.**
  - `config`: `ROBOT_NAME` / `ROBOT_ALIASES` / `ROBOT_KEYWORDS` are the defaults of `robot`. A
    home whose config carries another name loses its name, aliases and keyword lines on load
    and takes these; a home already on the name keeps the aliases its owner tuned.
  - Keyword spotter: `B AH0 N AE1 N AH0` and `B AH0 N AA1 N AH0`, score 2.0 / threshold 0.2
    (`provider_local.json`).
  - Aliases: `banana`, `bananna`, `ananna`, `banaa`, `baana`, `bnaa`, 把娜娜, 巴娜娜, 芭娜娜,
    爸娜娜, 吧娜娜.
  - *Changed while building — the matcher is stricter than block #94 planned.* Aliases are
    matched as written; only the name itself is matched loosely, and word by word.
    - With every alias matched loosely, "ananna" took "NANNA is not coming" and "banaa" took
      "Panama", "cabana" and "nana".
    - With windows sliding over the text without its spaces, "a banner and a" and "cabana
      near" held a "banana".
    - What still passes: an English word one letter away ("bandana", a garbled "banner").
    - A loosely matched name takes the Latin word it sits in on the original text, so an
      English sentence keeps its spaces ("VANANA what's the weather" → "what's the weather").
  - The persona ("You are Banana … your name is the English word, never the fruit: that is
    香蕉"), every prompt, skill and dashboard string; comments and module headers.
- **The wake path, measured with the defaults** (SenseVoice text + the matcher, the spotter,
  either): the 55 utterances with the name — text 52, spotter 40, either 55; the 53 short ones
  without — none; 12.2 min of running speech cut by the VAD into 37 segments — five wake-ups,
  all in the English passage written to provoke them ("bandana", "banner"), none in the
  Mandarin passages or in this home's microphone of 11-20. SenseVoice also wrote BNANNA on
  MiniMax's own sample: the loose match took it (0.83).
- **Mandarin.**
  - `languages.default` = `zh`, order zh → en → yue; `LANGUAGES` in that order.
  - SenseVoice: `per_language` in the local preset — `zh` for a Mandarin household, `auto`
    otherwise. With `zh` the Mandarin sentences `auto` got wrong come out right; the name is
    found as well (52 vs 54 of 55 by text, 55 either way with the spotter).
  - `ConfigSession.drop_foreign_voices()` (on load) and `with_language()` (the dashboard's
    `POST /api/config/languages`): a voice pinned from another language's list is dropped; a
    voice the catalog does not list (the owner's own) stays.
  - `TTSSession.voice()` names the voice `synthesize` speaks with; `ContactSession` keeps it
    in the `self` contact's notes and enrolls the robot's voice again when it differs, with
    texts in the household's language.
  - Model-visible text: the role's register rule (Mandarin in Simplified characters, Cantonese
    as before), the skills' example phrases, the memory writer's examples, the refusal line
    and the acknowledgements per language, 39 Mandarin words for the expressions, Mandarin
    stop / closing / backchannel words, the unpaired-WeChat reply.
  - The dashboard's Chinese labels (the Live card, the language names) are Mandarin.
- **The confirm gate.** `loop.py` no longer reads `confirmed` from the arguments; the test
  fails on the old code (the skill was deleted on the model's own word).
- **This home** (`.derived_data`, not in git; copies of `config.json` and `contact_v1.db` in
  `cache/before-94/`): the config saved once after the load (Banana, the two Cantonese voices
  unpinned → 「Chinese (Mandarin)_Warm_Girl」, the word lists that were still the old defaults
  → the new ones, language order zh first); 发瘟鸡 and 黎思源 no longer prefer `yue` — they
  follow the household's language (Contacts → edit to change it back). The robot's own voice
  print is made again at the next start.
- **Verification.**
  - 264 tests pass, 6 skipped (the live ones); ruff, format and mypy are clean.
  - Live, against MiniMax with this home's key: every slot probes (both TTS slots in the
    Mandarin voice, domestic region), cloud ASR hears 「banana，今天天气很好…」 with `zh`, the
    model answers 「我叫Banana，是家里的小管家机器人。」; a turn marked `yue` is still answered
    in Cantonese.
  - **Not run on the robot.** The owner had closed sidekick at 00:09 and the work was done at
    night; the wake name has only met synthesized voices. The first real "Banana" through the
    robot's microphone is the owner's.
- **Stale text.** README (the CLI sentence, the gaze trigger, `service` in layer 5),
  `pyproject.toml` (two comments), the live test's header.
- **Branches.** Four commits on `phase1-prototype` (the gate, the name, the language, the
  documents), fast-forwarded into `main` and pushed.
- **Owner, to try.**
  - 「Banana，今天天气怎么样？」 from across the room, and the name alone.
  - A Mandarin speaker with an accent on "banana": the spotter misses those, SenseVoice has to
    write them. New spellings show on Voice → Decisions; add them on Voice → Hear → Wake name.
  - Whether 思源 is to be spoken to in Mandarin: the voice and the recogniser are the
    household's, one language at a time.
- **On another Mac.** `git clone`, `poetry install`, `poetry run sidekick startup`; a fresh
  home is written for the host with Banana and Mandarin. To bring this household along: System
  → Config → Backup here, then unpack the archive into `.derived_data/` there before the first
  `startup` (models are downloaded at the first Start; nothing reads `restore()` since block
  #85).

## [2026-11-20 #94] Decision + Todo: the wake name is Banana, Mandarin is the default language, the confirm gate, `main`

- **Owner (2026-11-20):**
  - 「唤醒词变更为 banana」
  - 「asr、tts 语种变更为普通话」
  - Merge to `main` and commit: sidekick is to be deployed on another Mac.
  - The issues named after reading the project (below) are left to my judgement.
- **Context: the run of 11-20 00:03–00:09**, the first of blocks #89–#92 on the robot.
  - The 08:00 wake-up missed for 19 days was reported once, as missed. A bare call got
    「係？我喺度。」 0.1 s after the name.
  - The owner had set the household language to 普通话 on the dashboard and spoke Mandarin; the
    replies stayed Cantonese in the Cantonese voice. Both TTS slots carried an explicit voice
    (a pinned voice survives a change of the household language), and the two contacts'
    language is `yue`.
- **Decisions.**
  1. *The name and the wake name stay one thing* (block #9), and it is now **Banana**:
     `robot.name`, its aliases and keyword lines, the persona, every prompt, skill and
     dashboard string. A home whose config still carries the retired name gets the new name,
     aliases and keyword lines when it is loaded: the name is fixed by the code, not by the
     home.
  2. *Detection, measured* on synthesized utterances — the macOS voices that pronounce the
     word (five English, Tingting, Meijia) and MiniMax's Mandarin and English voices: 55
     with the name, 53 short ones without (巴拿马, 把那个拿来, 娜娜, bandana, cabana, Panama) and
     12.2 min of running speech without it, 5 min of them this home's microphone on 11-20.
     - Keyword spotter: the lexicon line `B AH0 N AE1 N AH0` finds 32/55 at score 1.5 /
       threshold 0.25; with `B AH0 N AA1 N AH0` 37/55; at 2.0 / 0.2 40/55 and no false alarm;
       at 2.5 / 0.15 the first false alarm. Pinyin lines bring nothing (1,520 combinations:
       18/55) and `b ǎ n à n à` fires on 「把那边的那个拿过来」.
     - SenseVoice writes the name BANANA, BANANNA, ANANNA, BANAA, once 把娜娜: these are the
       aliases. A Mandarin speaker's "banana" is what the spotter misses and SenseVoice hears.
     - The rules written for "Bobby" go: "BB" beside a name, the 比 tail after a Latin stub.
       A short alias (under five characters) is never matched against a shorter window:
       「把娜娜」 would otherwise take 「娜娜」 (ratio 0.8, the threshold) for the name.
  3. *Mandarin is the default language*: `languages.default` = `zh`, order zh → en → yue, the
     Mandarin voice.
     - SenseVoice in `auto` decodes some Mandarin as Cantonese (「把那个拿来」 → 「爸妈佢妈嚟」,
       「不那么难」 → 「本我嘅人」; `zh` gets both right): a `zh` household tells it `zh`.
     - Changing the household language resets a voice pinned for another language.
     - The robot's own voice print belongs to the voice it was made from: it is enrolled again,
       in the household's language, when the TTS voice changes.
  4. *The confirm gate takes no word from the model.* `loop.py` let a call through when the
     model put `confirmed: true` in its arguments; no schema declares it, no test used it,
     and invariant 13 says the speaker confirms.
  5. *Stale text*: README and `pyproject.toml` still name CLI commands block #85 removed.
  6. Not changed: a name heard as a closing phrase (「拜拜」 for "Bobby" on 11-20) — the new
     name does not sound like one.
- **Todo** (done: block #95).
  - [x] The confirm gate, with a test.
  - [x] `config`: name, aliases, keyword lines, spotter sensitivity; the retired name on load.
  - [x] `namespot`: the Bobby rules out, the short-alias rule in; tests on the new name.
  - [x] Persona, prompts, skills, dashboard strings, comments and module headers.
  - [x] Mandarin defaults; SenseVoice language; the voice reset; the self voice.
  - [x] This home: config, the pinned voice, the contacts' language.
  - [x] AGENTS, README / README_CN, `pyproject.toml`; tests, ruff, mypy; `main`.

## [2026-11-01 #93] Research: the conversion revisited after the owner's feedback — Seeed parts, size as a criterion

**Owner (2026-11-01 evening).** The Lite → Wireless conversion is feasible with parts bought from
Seeed Studio; Seeed staff have done it; a small footprint is a goal in its own right. Block #91
called the conversion "not available" from Pollen's store and GitHub alone — that was incomplete,
and this block supersedes its conversion verdict.

**Seeed's public channels, re-checked 2026-11-01.** The seeedstudio.com product pages that could
be opened list two Reachy Mini SKUs — Wireless 100090917 (USD 499, in stock) and Lite 100025004
(USD 399, in stock), both from the China warehouse; no board, battery, upgrade-kit or Dev Pack
page was found. But the bazaar search is JS-rendered (not enumerable from here), the Seeed forum
search was unreadable, the 2026-01 Seeed blog post returned 403 and seeed.cn misredirected — so
"no parts listed" means "not in the pages that could be fetched", not a verdict. The owner's link
/ SKU / contact is needed to price the parts.

**Wireless internals (HF datasheets, reflash guide, community).** A CM4 controller board
(socketed CM4104016 under a fan + heatsink, 2.4 / 5 GHz patch antenna, SW1 debug / download
switch, USB2 flashing port, motor bus on UART3, CSI camera, mic-array connector, a USB-C host
port that does not charge), a foot power board (charger + BMS interface, switch / LED), the
2000 mAh / 6.4 V / 12.8 Wh LiFePO4 pack taped into the foot, an accelerometer; 1.475 kg vs the
Lite's 1.350 kg. The OS images (`reachy-mini-os` releases) and the Reachy Mini Flasher (rpiboot +
bmaptool) are public; a reflash is a factory reset, "expert only". Community CM4 → CM5 swaps on
the stock carrier broke the camera (ribbon J8 → J10), the XVF3800 capture and the H.264 path:
the image is bound to the carrier.

**Two conversion routes, now in the report.**
- **A. Official parts** (needs Seeed to sell them): the head CM4 controller board + antenna +
  cooling, the foot power board, the battery pack, cables; reflash `reachy-mini-os`. No public
  price — placeholder ¥1,000–2,000 (the Wireless − Lite list gap is USD 100; parts sold singly
  cost more; a CM4104016 is ≈ USD 100–130 after the 2026 rises, unverified). Afterwards Bobby's
  brain is a CM4 (Pi 4 class, 4 GB shared with the daemon, 16 GB eMMC): the recording ring goes
  to a USB stick on the base's host port or away, perception below the `pi` profile; the CM4's
  v4l2 H.264 encoder works with `record`. The Lite's USB-device workflow and warranty are lost.
- **B. Internal host, no Seeed parts**: keep the Lite electronics; a CM5 (or CM4) on a nano
  carrier — Waveshare CM5-NANO-A 55 × 40 mm ≈ £11, CM4-NANO-B 56 × 41 mm ≈ USD 22 — in the foot
  where the Wireless keeps its battery, a short USB lead to the inside of the base's USB-C port,
  a 7 V → 5 V / 3 A buck from the Lite's power input, heatsink + small fan. ReachyPi (Pi 5) and
  Toon-nooT (Pi 4B) already run the daemon on a Pi over USB; this only moves the Pi inside.
  ¥900–1,500 estimate (CM module prices unverified). Open: the Lite's foot cavity (undocumented;
  measure after the three screws underneath), heat in a closed foot (a CM5 draws 6–8 W under
  load; the Wireless's own CM4 has a fan), no hardware H.264 on a CM5 (x264 or 540p); on a CM4
  sidekick runs at the `pi` profile.

**Size is now a column of the comparison.** Conversion A or B = the robot plus one cable (the
charger for A, the 7 V supply for B): the smallest of every option. Every external host needs a
20–22 cm plinth or an under-desk bracket with a grommet.

**Recommendation by priority.** Only the robot on the desk → conversion A if Seeed quotes the
parts, else B; most headroom and no porting → Mac mini M6 at the 国补 price in a 22 × 22 × 10 cm
plinth; lowest cost → an N150 box in a 20 × 20 × 8 cm plinth. The report (same artifact,
version 2) carries the revision note, the new section and the table.

**Owner to supply.** The Seeed link / SKU / contact and the parts price; a measurement of the
Lite's foot cavity. **For sidekick, unchanged plus one item:** the Linux small-host profile from
block #91 must also fit a CM4 / CM5 (4 GB, no ring or an external disk, the `pi` perception
settings).

Sources: Seeed Wireless https://www.seeedstudio.com/Reachy-Mini-Wireless-p-6568.html · Seeed
Lite https://www.seeedstudio.com/Reachy-Mini-Lite-p-6567.html · HF Wireless hardware
https://huggingface.co/docs/reachy_mini/en/platforms/reachy_mini/hardware · HF reflash guide
https://huggingface.co/docs/reachy_mini/main/en/platforms/reachy_mini/reflash_the_rpi_ISO ·
reachy-mini-os https://github.com/pollen-robotics/reachy-mini-os/releases · CM4 → CM5 thread
https://github.com/geerlingguy/raspberry-pi-pcie-devices/issues/800 · Toon-nooT
https://github.com/Toon-nooT/reachy-mini-lite-to-wireless-pi-setup · ReachyPi
https://huggingface.co/Domotick/ReachyPi · Waveshare CM5-NANO-A https://www.waveshare.com/cm5-nano-a.htm
· Waveshare CM4-NANO-B https://www.waveshare.com/product/raspberry-pi/boards-kits/compute-module-4-4s-cat/cm4-nano-b.htm

## [2026-11-01 #92] Decision + Progress: sessions closed under people mid-sentence; a bare call gets a spoken answer

- **Owner:**
  - 「昨晚体验时，经常聊着聊着就没反应，需要重新激活对话。」
  - 「如果单纯喊 bobby，虽然天线会动，但第一次使用的用户都会感觉困惑，他们都因为机器人没有回它话，
    以为机器人坏了。」
- **Diagnosis: every session end of 10-29 to 10-31, with what was said in the 30 s after it.**
  - 13 timeouts fired **while someone was talking**. The silence timer never looked at the
    microphone.
  - Example, 10-31 14:08: 思源 began 2.3 s after 「做咩？咁叫我。」 and talked for 7.8 s. The 8 s
    timer closed the session 5.7 s into his sentence, and the sentence was rejected as
    `no wake name`. The same happened to 发瘟鸡 (10-30 22:27) and to `person:29` (10-30 20:58).
  - 7 more began within 5 s after a timeout. Most followed a question: block #89's 15 s
    covers them.
  - The stories of 10-31 22:4x are block #89's 30 s cap.
  - In-session rejections played no real part: `other direction` was the 10-30 morning, fixed in
    #80; `other speaker` happened 3 times.
- **Decided and built.**
  - [x] *Speech holds the session.* The tick passes the onset of the speech going on now (self
    motion excluded). Speech that began before the deadline keeps the session until its segment
    is decided; speech that begins later does not, so a TV cannot keep a session alive.
    - Replay of the 13 cut-off sentences through the new rule and the session matching: 12 are
      accepted (all of 思源's and 发瘟鸡's). The rejected one is 发瘟鸡 explaining Bobby to 思源
      inside 思源's session (`other speaker`, right).
    - Cost: two 20 s Mandarin talk-show segments would be held as well, and the agent has to
      answer `NO_REPLY`.
  - [x] *A bare call is answered out loud, at once.* This replaces block #89's model turn 1.5 s
    later, which still left 3–4 s of silence.
    - `interaction/call.py` (`CallAnswers`) holds a few phrases per language: 「喺度！咩事呀？」,
      「係？我喺度。」, 「我喺度，你講啦。」, 「嗯？咩事呀？」; zh / en sets as well. They are
      synthesized when the front end starts (the household's voice, the one-clip TTS call, in
      the background after the TTS link), picked at random, and never repeated twice in a row.
    - Played straight to the speaker as SPEAKING (the echo guard knows the text), so it is heard
      about 0.1 s after the name is recognised.
    - No model call, no timeline row; traced as `say · call answered`.
    - The session then waits as after a question (15 s).
    - Skipped when they are already talking again ("Bobby, … 今日天氣點呀").
    - A new turn or a barge-in stops it; a name over a story stops the story and answers.
    - A phrase not yet synthesized goes through the stream.
  - [x] Tests: the hold, the call answers, the answer on the fake voice stack (no responder
    message, no cloud ASR, the next sentence is the turn).
  - [x] AGENTS (trigger 1, ENGAGED, the `interaction` row and its submodules), README /
    README_CN.
- **Verification.** 260 passed, 6 skipped; ruff, format and mypy are clean. Not yet on Bobby:
  the process is closed (block #90).
- **Owner, to try:**
  - A first-time caller saying only 「Bobby」.
  - A long sentence after Bobby's reply.
  - Whether `session_timeout_s` 8 s is still too short for the household (Voice → Hear).

## [2026-11-01 #91] Research: a host for the Lite on its own — Mac mini, Pi 5, N150 mini PC, or Wireless

**Question (owner).** The Lite runs tethered to the Mac Studio and must work on its own (mains
power allowed). Candidates: a second-hand Mac mini, a Raspberry Pi (or similar), or converting
the Lite into a Wireless with bought parts. Hard requirement: it must look finished — no visible
cables, no bare boards; a printed enclosure is acceptable when nothing is sold.

**Method.** Four web research passes on 2026-11-01 (Pollen docs / FAQ / store, HF docs and blog,
GitHub issues, Seeed wiki, CNX, Phoronix, Notebookcheck, IT之家, 什么值得买, V2EX, JLC3DP),
synthesized into a Chinese buyer's report with 146 sources:
https://claude.ai/artifact/QMYsxdKdirGgCRrc1Rcfio (private artifact). The Chrome extension was
not connected, so JD / Tmall / 闲鱼 / 拼多多 prices are dated secondary reports, not live pages;
the report ends with 21 prices to confirm by hand.

**Facts that decide it.**
- The Lite is not powered over USB: a 7 V / 5 A adapter plus one USB-C data cable leave the base
  (Pollen FAQ; HF Lite hardware page). Two cables whatever the host; the host needs only a USB 2.0
  data port.
- Lite → Wireless is not possible, officially: FAQ "The electronics architecture differs between
  the two versions, so a direct upgrade isn't possible." The Wireless head board is a CM4 carrier
  (CM4104016: 4 GB, 16 GB eMMC, Wi-Fi) with an accelerometer; its foot holds a 12.8 Wh LiFePO4
  pack with a BMS. The store sells no boards, batteries or shells; no schematics, Gerbers or BOM
  are published (38 visualisation STLs only; the OnShape / STEP release is issue #15, open since
  2025-06; #708 closed "not planned"); reachy-mini-os "can only be used with the Wireless
  version". Nobody has documented an internal conversion: a real one means designing a CM4
  carrier — an engineering project, not a purchase.
- A Wireless bought whole is USD 499 / EUR 435 (≈ ¥3,350–3,550 before shipping and duty; Seeed
  on AliExpress showed USD 699 in 2026-03; up to 90 days lead time, ~5 months reported by one
  Chinese buyer). Its CM4 is Pi 4 class — weaker than a Pi 5 — with 4 GB shared with the daemon
  and 16 GB eMMC too small for the 24 h ring; 24/7 use still needs the charger cable. Worth it
  only for a battery-mobile Bobby and the Wireless-only USD 149 wheeled base (early 2027).
- Raspberry Pi 5 is the worst compute per yuan of 2026 after four memory-driven price rises
  (8 GB board USD 180, 16 GB USD 305; CN 8 GB kits ¥1,989–2,199; Waveshare 16 GB out of stock),
  has no hardware H.264 encoder (RP-010033 white paper: libx264, ≈ 10–25 % of one core for
  720p10), and Pi OS Trixie ships Python 3.13 (Ubuntu 24.04 gives 3.12). The AI HAT+ is
  unreachable from onnxruntime. In its favour: 2.7–3.6 W idle, power-on with mains, and ReachyPi
  (HF Domotick, 2026-06) proves the daemon drives a stock Lite from a Pi 5 over USB.
- Intel N150 mini PCs (零刻 EQ14, 极摩客 G3 Plus; 16 GB + 512 GB) are the Linux optimum: GB6
  1,255 / 3,093 (≈ 1.6× / 1.9× a Pi 5), VA-API H.264 encode (Intel iHD, ADL-N), Ubuntu 24.04 =
  Python 3.12 and x86 wheels; the EQ14 has an internal PSU (126 × 126 × 39 mm, 8–9 W idle,
  21–32 W load, 23.5–24.4 dB(A)); mini PCs get the 15 % 国补 on JD. Prices on record are
  2024–25 (¥999–1,199 for 16 + 512); 2026 memory prices push them up — estimate ¥1,100–1,600,
  to confirm. BIOS "Restore AC Power Loss" exists but is reported missing on some units.
- Mac mini: the M4 was discontinued 2026-09-22 (the 2026 line is M6 / M5 Pro; Apple had raised
  the M4 to ¥5,999 in 2026-06). M6 16/256 lists ¥6,999, but JD 自营 with 国补 was ¥4,929
  (2026-10-26, region-limited) and 拼多多 百亿补贴 ¥4,699 (2026-10-18–21). Zero porting
  (sidekick already runs on macOS with VideoToolbox), 4 W idle / 70 W peak, 24 dB measured idle,
  12.7 cm square with an internal PSU, and the only host with "Start up when power is connected"
  (macOS 26.5+, 2024-or-later Mac mini): a smart plug gives a remote hard reset, which also
  answers the power button on the underside. Used prices rose through 2026: M1 8/256
  ¥2,200–2,300, M1 16/256 ≈ ¥2,500–3,000 (extrapolated), M4 16/256 ¥3,300–4,000 — a used M4 is
  squeezed by the subsidised M6; a used M1 16 GB is the floor for no Linux work (no
  power-on-when-connected: `pmset autorestart` + a UPS).
- RK3588 boards (hardware encoder only on the vendor 6.1 kernel via MPP; the NPU slower than one
  A76 core for SenseVoice in sherpa-onnx's own numbers) and the Jetson Orin Nano Super (no NVENC,
  ¥2,070 MSRP) need a reason this stack does not have.

**Looks.** No community stand, dock or Pi-hiding base for Reachy Mini exists (Printables,
MakerWorld, Thingiverse, Cults3D, the Pollen forum; 2026-11-01). So the answer is the same for
every host: a plinth under the robot — 20 × 20 × 8 cm for an N150 box or a Pi, 22 × 22 × 10 cm
for an M4 / M6 Mac mini (its bottom intake needs ~1.5 cm), 24 × 24 × 6 cm for a 2020 / 2023 Mac
mini — holding the host, the robot's 7 V brick and a 2–3-outlet strip, one AC cord out the back,
vents at the back and bottom only, the foot's three screw holes reproduced in the top plate so
the 1.35 kg robot cannot creep. Derive it from the open `body_foot_3dprint` part (CC BY-NC-SA).
Finish: MJF PA12 dyed black looks bought (JLC3DP; SLS nylon ¥310–580 for 300–400 g, FDM matte
PETG ¥25–80). Measure first: the foot's diameter and screw pattern, the rear connector heights,
the brick, the host. The no-print alternative: a ¥38–60 under-desk bracket for a Mac mini and a
grommet in the desk under the robot. A Pi goes in an Argon ONE V3 M.2 (all ports on one face) or
the 52Pi metal case; both have fans and need vents in the plinth.

**Comparison (host + hiding + cables, estimates).** New Mac mini M6 ¥4,400–5,600 (zero porting,
most headroom, warranty) · used M1 16 GB ¥2,600–3,700 (zero porting, no warranty) · N150 mini
PC ¥1,200–2,200 (1–3 days of Linux work) · Pi 5 8 GB ¥1,800–2,800 (2–4 days, performance at the
edge, the `pi` profile mandatory) · Wireless ¥3,500–5,000 (a second robot with a weaker brain) ·
conversion: not available.

**Recommendation.** Buy the M6 16/256 at the 国补 price while the 双11 quota lasts and hide it
in a 22 × 22 × 10 cm MJF plinth (or under the desk); it frees the Mac Studio with no software
change. If the budget matters more than two or three days of work, an N150 box (EQ14 / G3 Plus
16 + 512) in a 20 × 20 × 8 cm plinth. Do not convert; do not buy a Pi 5 for this.

**For sidekick (whichever host).** Generalise the `pi` deployment profile into a "Linux small
host" profile: `record/video.py` `encoder_name` gains a VA-API element (`vah264enc` /
`vaapih264enc`) before `x264enc`; a systemd unit beside the LaunchAgent; `body/daemon.py` and
`body/dsp.py` re-verified on Linux (udev rules for `1a86:55d3` and `38fb:1001`, `dialout`, the
XVF3800 PCM1 volume, UVC `auto-exposure-priority`). The same work serves a CM4 Wireless later.
Nothing in code changes until the owner picks a host.

**Verify by hand (the report's 21-row list; the first five).** JD 自营 M6 国补 price in the
owner's city (https://u.jd.com/5GkAKk4); 拼多多 百亿补贴 M6; 闲鱼 "行情" for M1 16/256 and M4
16/256; EQ14 / G3 Plus 16 + 512 on JD with the 国补 tag; Pi 5 8 GB at waveshare.net / 创乐博.
On the robot: the adapter's nameplate (7 V vs 7.3 V, plug size) and whether the Lite enumerates
as USB 2.0 or 3.x.

Sources (the decisive ones): Pollen FAQ https://pollen-robotics.com/reachy-mini/faq/ · HF Lite
hardware https://huggingface.co/docs/reachy_mini/platforms/reachy_mini_lite/hardware · HF
Wireless hardware https://huggingface.co/docs/reachy_mini/en/platforms/reachy_mini/hardware ·
issue #15 https://github.com/pollen-robotics/reachy_mini/issues/15 · ReachyPi
https://huggingface.co/Domotick/ReachyPi · Pi 5 H.264 white paper
https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-010033-WP-1-H.264%20encoding%20performance%20on%20Raspberry%20Pi%205_series%20computers.pdf
· Apple power-on-when-connected https://support.apple.com/125517 · Apple power table
https://support.apple.com/103253 · EQ14 review
https://www.notebookcheck.net/Beelink-EQ14-mini-PC-review-Ready-to-go-HTPC-for-under-200.939127.0.html
· JD M6 国补 (IT之家 2026-10-26) https://www.ithome.com/1/018/022.htm · JLC3DP
https://www.jlc-3dp.cn/

## [2026-11-01 #90] Progress: the family's session of 10-31 (block #89)

- **Stories are no longer cut off.**
  - `speak_reply` waits until the speaker has played everything the turn queued. The bound is
    30 s plus 0.5 s per character, in case a player never drains.
  - The TTS wait grows with the reply's length.
  - After a reply that ends with a question the session waits `answer_timeout_s` (15 s, on
    Voice → Hear → Triggers & turns) instead of 8 s.
  - Replay of 22:46–22:56 against the speaker track: after each of the four stories, 思源's first
    answer came 2.6–4.5 s after Bobby stopped talking. All four now fall inside the session,
    where all four were rejected before.
  - Cost: Dad's 「出哪啦哦」 to the child, 11 s after a question, is now heard too. The agent has
    to answer `NO_REPLY`.
- **The name.**
  - "BB" inside a sentence is never the name; a bare "BB" still is.
  - Every name at a turn's start or end is removed. 「芭比波比芭比」 and 「BB BOBY」 are only the
    name. A name in the middle becomes "Bobby" (「讲个芭比嘅故事」).
  - A final ？ after a trailing name stays.
  - `芭比` and `b比` joined the default aliases and the household's `config.json` (only
    `robot.aliases` changed).
  - Only the name, and no new speech for 1.5 s: the agent gets "Bobby" and answers the call. A
    question after the name supersedes it; so does a name over a story.
  - The role lists the spellings of the name (芭比 / 爸比 / B比 / BBY …).
  - Replay of all 36,424 traced segments, old matcher vs new: 71 hits unchanged. 4 lost, all
    adults saying "BB" to or about a child (Mum ×2, 「牙仔 BB」, a Mandarin aside). 6 gained, all
    the child's calls (芭比, B比 ×2, B比Y ×2, 「芭比芭比… B比」).
- **Speaker on a name hit.** A segment that carries the name adopts its identified voice, like
  any other segment of the session, so a keyword-stream session no longer credits the child to
  `guest:n`.
- **No emoji spoken.** They are removed before TTS (`speakable`) and from a voice reply's
  transcript, so the model no longer sees its own 😂. Chats keep them.
- **`look`.**
  - The frame is gamma-lifted before the vision call.
  - The model is told the photo is dark and grainy and to say only what it clearly sees, and
    not to guess what people are doing.
  - An optional `question` is passed through ("what is on the card?").
- **Role rule:** no hands; no offers to cook, fetch or make drinks.
- **Service.**
  - A process exit waits for a stop in flight instead of cancelling it. A restart's stop no
    longer goes on to start at exit.
  - A Stop is remembered when it begins.
  - The overlap is gone: Stop followed by `sidekick close` no longer runs two stops at once.
- **Late jobs.** A task that only made sense at its time (a wake-up call, a timer) is reported
  as missed instead of done late. Missed jobs are still sent at start (owner's decision, block
  #85).
- **Verification.**
  - 258 tests pass, 6 skipped. New: `test_interaction_household.py` (6), the name-only answer on
    the fake voice stack, look in the dark with a fake vision model, an exit during a stop and
    during a restart, the new field in the schema route.
  - ruff, format and mypy are clean.
- **Not run on Bobby.** The process was closed (00:08). A start would also send this morning's
  missed 08:00 「叫醒黎思源」 into the room, so the live check is the owner's next session.
- **Owner:**
  - `service.json` still says `running`: the 00:08:38 dashboard action (Stop or Restart, the log
    cannot tell) was cut short by `close`. `sidekick startup` therefore starts Bobby, and the
    missed 08:00 job will say it was missed.
  - Then: a story with 思源 (answer the 「你估下…？」), calling 「芭比」 alone, Mum saying BB.
  - Open from block #89: the next timed job in the power panel; naming Mum (`person:14`).

## [2026-11-01 #89] Decision + Todo: the family's session of 10-31 — stories cut off, "BB", the name, the dark camera, Stop + close

On 2026-10-31 the household talked to Bobby three times (12:17, 14:04, 22:39–23:14). The
speakers were 思源 (a child, mostly), 发瘟鸡 and Mum (still `person:14`). Diagnosis from the
decisions table, the timeline, the speaker track of the recording ring and the logs; no code
changed yet.

- **Story time cut off (the worst).** Every story was ~300 characters, about 50 s of audio, and
  ended with a question (「你估下…？」). 思源 answered within 3–5 s each time. That evening 13 of
  their answers were rejected as `no wake name`: 「唔知」「讲啦」「继续讲啦」 ×4, 「你再讲多一次」. To
  get Bobby back they had to shout 「芭比芭比芭比…」.
  - Cause: `pipeline.speak_reply` waits at most 30 s for the speaker to go quiet
    (`wait_quiet(30.0)`). On a 50 s story the turn is declared over about 20 s early, and the
    8 s silence timeout then runs while Bobby is still talking.
  - Speaker track against the decisions: story 22:46:54–22:47:46, session ended 22:47:37;
    22:48:08–22:48:55, ended 22:48:51; 22:50:20–22:51:13, ended 22:51:04.
  - In the afternoon, every story turn's total is 28–31 s: the same cap.
- **"BB" is the word for baby.** Mum to the child — 「…听到啦 BB，妈妈同你讲乜嘢啊」 and
  「做乜嘢…啊 BB」 — opened two sessions. The first got `NO_REPLY`. The second got
  「唔清楚你指咩喎，你係想我幫你煮咩？」, and then `person.ready` started befriending her in the
  middle of bath time.
  - Cause: the fuzzy matcher compares the alias `bob` with 2-letter windows, and
    `ratio("bob", "bb")` = 0.8 = the threshold. The same window takes any "bo" ("about",
    "robot").
  - The child's real calls were also caught by the keyword stream (波比 / 巴比, four times).
- **The name only half removed.** 「芭比波比芭比」 lost only 波比, so the model read 「芭比 芭比」.
  It answered 「我屋企冇個叫芭比嘅人喎 😂 係咪想我講個芭比公主嘅故事？」 and then told a Barbie
  story. 芭比 is not an alias; the transcripts write the child's "Bobby" as 芭比 / B比 / BBY.
- **An emoji spoken.** 😂 in a voice reply, although the role says "no emoji".
- **A barge-in credited to a stranger.** 22:52:33 「BB」 became `guest:12`. The session had been
  opened by the keyword stream with no speaker, and a name hit inside a session never adopted
  the voice identified on it (思源 0.77).
- **The camera in the dark.** 「睇唔睇到张卡」 at 14:06: the frame (mean 26/255) went to the vision
  model untouched, with "Describe this room scene". It answered "a person sleeping beneath a
  large dark canopy", so Bobby told 思源 he was in bed. He: 「我冇瞓觉啊」. The tool cannot be
  told what to look for.
- **Offers what it cannot do.** 「屋企人鍾意飲奶茶，我幫你整杯？」 (a household fact turned into an
  offer to make tea).
- **Stop, then close.** At 00:08:38 Stop was pressed on the dashboard; 5 s later came
  `sidekick close`.
  - The exit cancelled the stop in flight and ran a second stop over it, so the body and the
    daemon were stopped twice at once.
  - The Stop choice was never saved: `service.json` still says `running`.
- **Alarms while stopped.**
  - The 10-31 08:00 wake-up (「早晨鬧鐘」, set at 21:02 the evening before) went out at 11:46.
    Bobby had been left stopped since 23:10 on 10-30: that was my own live check of block #88.
  - 思源 then asked 「你点解唔叫我嘅」 and set a daily one (`0 8 * * *`).
  - This morning's 08:00 was missed again (the process was closed at 00:08). The next start
    will say 「思源，起床啦！朝早八點喇」 hours late.

**Decision (fixes, no new behaviour beyond these).**

- [x] *A turn ends when the speaker does.* Wait for playback until the audio queued at the end of
  the turn has played, plus a margin; the TTS wait grows with the reply's length.
- [x] *Wait for an answer.* After a reply that ends with a question, the session waits
  `interaction.answer_timeout_s` (15 s) instead of `session_timeout_s` (8 s). It goes on Voice →
  Hear → Triggers & turns.
- [x] *"BB" is not the name.* No fuzzy window shorter than three letters. Replay every traced
  segment to compare old and new hits.
- [x] *The name out of the turn.* 芭比 joins the default aliases (and the household's config).
  Every name at the start or end of a turn goes; one in the middle becomes "Bobby". The role
  lists the spellings the transcripts use for the name.
- [x] *No emoji spoken.* Removed from what goes to TTS and from the spoken transcript.
- [x] *A name hit adopts the voice* identified on it, like any other segment of the session.
- [x] *`look` in the dark.* The frame is gamma-lifted before the vision call. The question says
  to state only what is clearly visible. An optional `question` ("is there a card?") is passed
  through.
- [x] *No offers beyond the tools* (role rule: no hands — no cooking, fetching, making drinks).
- [x] *Stop + close.* The exit waits for a stop in flight (only a start is cancelled), and a
  Stop's choice is saved when the stop begins.
- [x] *Late jobs.* The prompt says that a task useful only at its time (a wake-up call, a
  timer) is reported as missed instead of done late. The owner's decision stands: missed jobs
  are still sent at start.
- [x] Tests, a replay of the 10-31 evening through the new engagement timing, docs.
- **Owner, to decide:**
  - Show the next timed job in the power panel? For example: "08:00 叫醒黎思源 — said late if
    Bobby is stopped then."
  - Mum (`person:14`) and others of the household are still unnamed.

## [2026-10-30 #88] Progress: Bobby started and stopped from the dashboard; the CLI is `startup` + `close` (blocks #82–#87)

- **Owner (mid-work):** 「按钮可以放在 tab 栏底部」. The power control is the last row of the module
  list, and on phones the last row of the dropped-down list; the menu button carries its dot.
- **The service (`service` module, Layer 5).**
  - `ServiceSession` runs one transition at a time: `stopped → starting → running → stopping`.
  - A start re-reads and applies the config, checks the prerequisites (any `bad` and nothing
    starts), downloads missing models, runs `App.setup_service()`, then each module's `start()`
    and `check()`.
  - A `bad` item, or a `start` that raises, rolls back everything started. A start still in
    flight when the process exits is cancelled and rolled back.
  - A stop stops the modules in reverse and unbinds every slot (`ConfigSession.release`).
  - The owner's choice is kept in `service.json`; a process exit is not a choice.
  - Found live: the POST route ran on a worker thread (sync `def`), where `create_task` has no
    loop, so it answered 500 and left the state at "stopping". Fixed: the route is `async`, the
    task is created before the state changes, and an exit stops the modules in any state but
    stopped. A regression test drives a real `ServiceSession` through the route.
- **`app.py`.** `setup_service()` re-binds every runtime module to the current spec. `start()` is
  the console (doctor, the service with the ordered modules, the dashboard) followed by the
  service's start; `stop()` is the service, then the dashboard. Still composition only (the
  architecture test covers `setup_service`).
- **Restart contract (block #83), module by module.**
  - body: `setup(config)` re-binds the backend and daemon; one stop event per run; the REST
    client is reopened by `connect()`; the holder is cleared on stop.
  - The robot is off while stopped:
    - The daemon sidekick spawned gets SIGINT (the sleep move; camera and audio released).
    - Another daemon gets `POST /api/daemon/stop?goto_sleep`.
    - `ensure_running()` spawns the daemon, or starts its stopped backend.
    - The daemon log is rotated at a spawn: the 240 MB file is now `reachy-daemon.log.1`.
  - channel: `setup` rebuilds the adapters it built.
  - interaction: touch / state callbacks are registered once; the machine takes the body's state
    at start (setup now runs before the body connects, and it sat at SLEEPING on the first live
    run) and sleeps at stop; the TTS warm-up is cancelled and the front end joined.
  - automation: the tools are refreshed with the setup's store and the bus subscription is kept
    once (perception de-duplicates).
  - perception: the body watchers are made at `start()`; `on_face` listeners are kept by the
    session.
  - record: one stop event per run.
  - agent: awaits its cancelled tasks.
  - llm / asr / tts / vad: a slot's `setup` closes what it replaces.
  - contacts: the voice and face models are released on stop.
- **Checks (block #86).** Every runtime module has a `check()`:
  - body: daemon, connection, telemetry, camera, microphone. It waits up to 8 s for the first
    frame after a spawn — the camera warned "no frame" after a cold start with 4 s.
  - voice: listening, SenseVoice preloaded, the wake-name spotter, the TTS link (it waits up to
    8 s for it).
  - agent: one real `pong` call each on `fast` and `smart`.
  - contacts: household counts.
  - channels, automation (late jobs sent), perception, recording, extensions: advice only.
  - The doctor's local layer is the prerequisites, the models, and the running modules' checks;
    its own body / front-end / recording / people / channel rows went. While stopped its verdict
    is "stopped · ready to start" or "stopped · N to fix before starting".
- **Missed reminders** run at the first tick, a late one with "was due at HH:MM … say it comes
  late".
- **Dashboard.**
  - The power control: state, since; a panel with Start, or Restart and Stop.
  - A blocking start dialog fed by `/api/service` at 4 Hz: steps, sub-items, ✓ / ! / ✗ / —,
    links to the tab that fixes a failing item, OK once it settles. Restart shows "stopping
    first…"; Stop shows nothing.
  - Toasts: a start that failed with no dialog open; a 409 "Bobby is stopped".
  - While stopped:
    - Live shows "Bobby is stopped / stopping…" with Start.
    - The runtime tabs' dots and Live's module cards go grey.
    - The camera stream ends and reopens after a start.
    - Runtime-only controls are disabled (`data-needs-service`).
  - System gets a Service card; "takes effect at the next start" offers *Restart now*.
  - Routes: `GET` / `POST /api/service`. While stopped, 409 on say, test turns, body / robot,
    frames, enrollment from the robot, the memory writer and loopback, and MCP / extension /
    slot writes only save.
  - `LoopbackGuard`: a loopback Host on every request (any port, so tunnels work) and a loopback
    Origin on writes and the live socket. A cross-site POST got 403 live.
  - The WeChat QR login moved to Channel. Not run live: it needs the owner's phone.
  - System → Logs → robot daemon.
- **CLI.**
  - `sidekick startup`: detached; writes a first config for this host when none exists (with the
    env key for development); `sidekick.pid`; output in `logs/sidekick.out.log`; waits for
    `/api/health`.
  - `sidekick close`: SIGTERM, then a wait; SIGKILL after 60 s.
  - Every other command is gone. The hints that named them (`sidekick init`, `doctor
    --fetch-models`, `daemon start`, `telegram pair`, `wechat login`, `record`) now point at
    dashboard tabs.
  - The retired `body.stop_daemon_on_exit` is dropped on load.
- **Verification.**
  - 248 tests pass, 6 skipped. New: `test_service_session.py` (8), `test_service_lifecycle.py` —
    the real app on a null body, four start / stop cycles, no `sidekick-*` thread left, tool /
    subscription / callback counts flat, a failed model call rolls back — `test_dashboard_service.py`
    (4), the rewritten `test_cli.py`, and the architecture test's invariant 25 check.
  - ruff, format and mypy are clean. No key in the logs.
  - On Bobby:
    - Boot start 7.8–13 s: robot 1.6 s with the daemon up, 4.4–4.5 s from a cold spawn; voice
      2.6–2.9 s; agent 2.8–4.5 s.
    - Stop 5.8–6.0 s (the daemon's sleep move).
    - `sidekick close` 7 s, then `sidekick startup` up in 1 s and running after 13 s, every
      check green.
    - A Restart, a Stop and a Start from the dashboard.
- **Owner:** try the power control, Restart after a "next start" setting, `sidekick close` /
  `startup`, and the WeChat login when wanted. Nothing committed.

## [2026-10-30 #87] Todo: start / stop the service from the dashboard (blocks #82–#86)

- **Owner:** 「停止就不需要显示给用户了。开干吧」 Stop shows no dialog. The power control opens a
  small panel, and Stop there just stops; the pill shows the state.
- **Part 1: the service.**
  - [x] `service` module (Layer 5)
    - state machine, lock and remembered choice (`.derived_data/service.json`)
    - steps with sub-items, the abort policy (any `bad` stops and rolls back; `warn` runs marked)
    - autostart at boot
  - [x] `app.py`
    - `setup_service()` re-binds every runtime module with the fresh spec
    - the ordered runtime modules handed to the service
    - the console's `start()` / `stop()`
    - architecture test updated
  - [x] Restart contract (block #83)
    - body: HTTP client per connect, stop event per run, holder cleared, settings re-applied
    - channel: clients per start
    - interaction: callbacks once, warm-up cancelled, front end joined
    - automation: subscribe once
    - perception: watchers at start, `on_face` kept, `subscribe` de-duplicated
    - record: stop event per run
    - agent: MCP pool at start, tasks awaited
    - llm / asr / tts / vad: replaced backends closed, every slot unbound on stop
    - models released on stop
  - [x] Each runtime module's `check(deep)`
    - body: daemon, connection, telemetry, camera frame, microphone frames; the daemon stopped
      on stop (ours: SIGINT, else REST sleep); log rotated at spawn
    - interaction: VAD, SenseVoice and keyword spotter preloaded, TTS connected
    - agent: one real `fast` call, `smart` at warn
    - contacts: counts only
    - channels, perception, record, extensions: warn on failure
  - [x] Prerequisites gate: config, credentials, Python, disk. Missing models are downloaded as a
    start step.
  - [x] Missed reminders: sent at start, with their original time in the prompt.
  - [x] Doctor: prerequisites plus the modules' cheap checks; "stopped" is its own verdict; its
    own body / front-end / slot / recording rows go.
  - [x] Routes
    - `GET` / `POST /api/service`; `service` in `/api/health`
    - 409 "service stopped" on runtime routes
    - writes while stopped only saved
    - Origin / Host guard on every write route
  - [x] Dashboard
    - state pill and power panel (sidebar, phone bar)
    - blocking start dialog with ticks, sub-items and links
    - toast for background failures
    - red dots from the checks
    - Live "Bobby is stopped" with Start; runtime controls disabled while stopped
    - Service card on System
    - "takes effect at the next start · Restart"
  - [x] Tests: service lifecycle on the null body (start → stop → start, no leftovers,
    registrations stable, routes in both states), gate, state machine, remembered choice, write
    guard.
- **Part 2: the CLI and the dashboard gaps.**
  - [x] `sidekick startup` (detached, pid file, waits for the dashboard, prints the URL) and
    `sidekick close` (SIGTERM, waits). Every other command removed; tests rewritten.
  - [x] First `startup` writes the default config (the profile follows the host: macOS
    `lite-mac`, a Linux ARM board `pi`; Wireless is Body → Daemon & connection — no separate
    selector needed).
  - [x] WeChat QR login on Channel.
  - [x] Daemon log on System → Logs.
  - [x] Hints that name removed commands point at tabs.
- **Close-out.**
  - [x] AGENTS.md: Layer 5, the import table, the service row, app / cli / dashboard / body /
    perception / interaction / automation / doctor rows, invariants 21 and 25.
  - [x] README / README_CN.
  - [x] Module headers.
  - [x] Live check on Bobby, with timings and screenshots.
  - [x] Progress block.

## [2026-10-30 #86] Decision: a start brings each module up and proves it works

- **Owner:** 「虽然说启动，但更多是检测服务健壮性。机器人就肯定是启动 daemon，唤醒，测试链接；agent 则需要
  看看 llm 是否连通；联系人倒没有什么需要检测吧？所以每个模块按需完成启动与检查。你觉得呢？」
- **Agreed.** Each runtime module owns two things:
  - its `start()`;
  - a `check(deep)` that returns readiness items in one shape: title, level, detail, tab, time.
- The service runs `start()` then `check(deep=True)` for one module after another. The dialog
  shows the items as sub-lines under the module's line.
- **Per module (start → check → on failure):**

  | Module | Start | Check | On failure |
  |---|---|---|---|
  | Configuration | — | Block #84's prerequisites | Not started |
  | Robot | Daemon spawned, wake, connect | Telemetry flowing, a camera frame, microphone frames (silent; the speaker tone stays on "Check everything") | Abort |
  | Voice front end | VAD, keyword spotter, SenseVoice preloaded, TTS link | Models loaded, TTS connected | Abort |
  | Agent | Memory writer, MCP | One real `fast` call (first token timed); `smart` reachable | `fast`: abort; `smart`: warn |
  | Contacts | Self voice, merges | Nothing to check; members and voices counted | — |
  | Channels | Telegram / WeChat polling | `getMe` / token valid | Warn |
  | Automation | Scheduler | Missed reminders sent (count) | — |
  | Perception | Body watchers | Face detection running | Warn |
  | Recording | Recorder | First chunk open, free disk | Warn |
  | Extensions | Each enabled one | Tools and watchers ready, feeds reachable | Warn |

- An abort stops whatever has started and leaves the service stopped. A warning keeps it running,
  marked, and the module's tab gets a dot.
- **Gains.**
  - The first conversation is faster: the models are loaded and the LLM and TTS connections are
    warm before anyone speaks. Today SenseVoice loads on the first utterance (0.35 s) and the TTS
    link opens 2–3 s after start.
  - Readiness has one source. The doctor collects the modules' checks:
    - the cheap ones every few seconds while running, never a model call;
    - the deep ones at start and on "Check everything", plus its loopback.
    - Its own copies of the body, front-end, slot and recording rows go.
- **Cost.**
  - A start takes ≈ 8–12 s: daemon 3–6 s, the LLM call 1–2 s, the TTS link ≈ 2 s. Independent
    checks overlap.
  - Stop lines verify too: the daemon gone, the chunk closed, threads exited.
  - About half a day more, ≈ 2.5 days in all.
- **Pending:** owner's go.

## [2026-10-30 #85] Decision: one process, a blocking start / stop dialog, the robot off while stopped, a CLI of `startup` + `close`

- **Owner:** 「还是先以同一个进程开发，剩下的少量内存能接受。另外，启动时应该弹出一个阻塞框，列出启动项，
  每一项完成打勾，直至全部完成，让用户确认，反之亦然。停止时就关闭机器人；要记住；停止期间的提醒启动后
  立刻补发；不要加 cli 指令，甚至应该简化为 startup + close，startup 之后就启动主进程，close就关闭
  主进程，其余指令都移除。你觉得呢」
- **Decided.**
  - One process: block #83's singletons are restarted in place, models are released on stop, and
    the 0.12–0.44 GB residual is accepted.
  - Start and stop run in a blocking dialog: one line per step, ticked as it completes, then the
    owner confirms.
  - Stop turns the robot off.
  - Stop is remembered.
  - Reminders missed while stopped fire as soon as the service starts.
  - The CLI is `startup` (starts the main process) and `close` (closes it); every other command
    goes.
- **Assessment: agreed, with these specifics.**
  - **Dialog.**
    - The steps come from the server: `GET /api/service` gives each step's state, detail and
      time. Every open page shows the same dialog, and closing the browser changes nothing.
    - Start, in order:
      - check the configuration — block #84's prerequisites; the missing items are listed under
        it with links to their tabs, which turn red;
      - download missing models, with progress;
      - the robot: daemon started, wake, connect;
      - contacts;
      - channels;
      - the voice front end;
      - the agent;
      - automations, which send the missed reminders;
      - perception;
      - recording;
      - extensions.
    - Each line ends ✓, ✗ with the reason, or — (not configured). A ✗ stops whatever has started,
      the dialog shows it, and the service ends up stopped.
    - Stop runs the same lines in reverse. Because it interrupts, it first shows what is going on
      now (a conversation, a job) with Stop / Cancel.
    - The confirm button opens once the last line settles.
    - Block #84's toast stays for whatever happens with no dialog open: the start at boot
      failing, or the service failing while running.
    - `app.py` declares the order and passes it to the service session, which runs and reports
      it, so `app.py` stays composition only.
  - **The robot off.**
    - Stop disconnects, then stops the daemon when sidekick started it. SIGINT puts the robot to
      sleep, motors limp, releases the camera and audio, and frees the daemon's 596 MB footprint.
    - A remote daemon (Wireless) only gets `stop?goto_sleep=true`.
    - Start spawns the daemon again.
    - Measured on 2026-10-26: the daemon was ready 3–6 s after its spawn, and its stop with the
      sleep move took 6 s. So a start takes ≈ 5–8 s and a stop ≈ 7 s.
    - The XVF3800 check runs between the stop and the start.
    - The daemon log is rotated at each spawn (240 MB now).
  - **Missed reminders.** Today's behaviour, kept. The prompt carries the original time, so Bobby
    says it is late.
  - **CLI.**
    - `sidekick startup` spawns the main process detached and writes `.derived_data/sidekick.pid`.
      It waits until the dashboard answers and prints its URL, or says "already running". The
      spawned process is the same command with an internal foreground flag.
    - `sidekick close` sends SIGTERM (the service stops, the robot turns off, the process exits),
      waits and reports.
    - Removed: `init`, `doctor`, `config`, `daemon`, `say`, `telegram`, `wechat`, `enroll`, `ext`,
      `service`, `backup`, `record`, `run`.
    - Already on the dashboard: readiness, parameters, slots and Probe, say, Telegram pairing,
      enrollment, extensions (including install), backup, the recording ring.
    - Gaps to fill:
      - The first `startup` writes the default config (the gate then lists the keys), with a
        profile choice (lite-mac / wireless / pi) on System.
      - Missing models download as a start step.
      - WeChat QR login moves to Channel; today it is terminal-only.
      - The daemon log goes on System → Logs.
      - The hints that name removed commands (`sidekick init`, `doctor --fetch-models`, `daemon
        start`, `telegram pair`, `wechat login`) point at tabs instead.
    - Later, on request:
      - Backup restore, on System while stopped.
      - Start at login: `service install` goes, so until then Bobby comes back after a reboot
        only with `sidekick startup`.
- **Order.**
  1. The service: the lifecycle split, the restart contract and model release, the gate, the
     dialog, the toast, the robot off, the remembered choice, readiness.
  2. The CLI down to `startup` / `close`, and the dashboard gaps.
  - About two days in all. Each part ends with tests, a live check and screenshots.
- **Pending:** owner's go.

## [2026-10-30 #84] Discussion: a start gate, and what stays in memory while stopped

- **Owner:** 「好像还是不符合我预期，我需要启动时进行检测，确认必要参数都配置完成才能启动，否则提示 toast
  以及 tab 添加红点。所以关闭时，内存不应该有过多占用（除了 dashboard，以及回看查询数据能力），你觉得呢」
- **Start gate: agreed. The readiness list (block #44) becomes the gate.**
  - The local items split into two groups:
    - **Prerequisites** are configuration: Python, `config.json`, the speech models, every bound
      slot's provider and credentials, and free disk.
    - **Runtime** items are checked only while running: daemon, body, microphone, DSP, voice
      front end, recording.
  - Start, including the start at boot, runs the prerequisites first. They are local and instant,
    with no network.
  - Any `bad` item stops the start. A toast lists what is missing, each with a link to its tab,
    and those tabs' dots turn red; the sidebar already shows each tab's worst level.
  - `warn` items (no Telegram token, no member yet) do not block.
  - Keys are not probed at Start, since that needs the network and takes seconds. Probe and
    "Check everything" stay where they are.
  - The dashboard has no toast yet; this needs one small component.
- **Memory while stopped (measured on 2026-10-30 with macOS `footprint`).**
  - Running: run75 after 11 h has a footprint of 1223 MB (RSS 1.7 GB).
  - A fresh process:
    - `import sidekick.app` takes 55 MB (numpy, fastapi, uvicorn, httpx).
    - sherpa-onnx, OpenCV and the robot SDK are imported lazily and add 24 MB when they load.
    - Loading SenseVoice adds 817 MB, YuNet + SFace 133 MB, and CAM++ 12 MB.
  - Every session constructed and set up, nothing started, which is enough for the dashboard and
    every data page: **61 MB** (scratch home, default preset).
  - Releasing models inside the same process (`del` + `gc.collect()`):
    - SenseVoice goes from 857 to 370 MB.
    - The face models stay at 189 MB; none of their memory comes back.
    - macOS `malloc_zone_pressure_relief` frees nothing more.
    - Three load / release cycles of both: 974 → 440, 682 → 123 and 533 → 305 MB. The residual
      does not grow, but 120–440 MB stays, because onnxruntime and OpenCV keep their allocations.
    - The robot SDK and GStreamer were not measured.
  - So within one process, a stopped service gets down to 61 MB only if it has not run since the
    process started. After a run it settles at 0.12–0.44 GB, plus whatever else holds memory.
- **Two ways.**
  - *One process (blocks #82–#83).*
    - Stop releases models, threads, connections and buffers.
    - Memory: 61 MB before the first start, 0.12–0.44 GB after.
    - Needs block #83's restart contract, plus releasing every model on stop.
    - A wedged native thread or a code update still needs a CLI restart.
  - *The service in its own process (recommended now).*
    - The dashboard process is `sidekick run`, still the CLI's. It holds the dashboard, every data
      page and the supervisor. Its sessions are set up and never started (61 MB).
    - Start runs the gate. Sidekick then spawns the service process
      (`python -m sidekick.cli serve`, internal), which is today's runtime with the same API on a
      Unix socket.
    - While the service runs, the dashboard process forwards `/api/*` to it (HTTP, the live
      WebSocket, MJPEG, video ranges). Every page is the same in both states, and there is one
      writer at a time.
    - Stop: the service process stops (the robot goes to sleep) and exits, and all its memory
      goes back to the OS.
    - Each module is still one singleton per process.
    - No in-place restart contract is needed, so block #83's fixes become unnecessary.
    - A native crash takes down only the service, and Restart also loads new code.
    - Costs:
      - the supervisor: spawn, stop with a timeout, and the child's log lines into the one log
        file
      - the forwarder: about 150 lines, with WebSocket and streaming
      - the light mode's route guards
      - in all, about half a day more than one process.
- **Unchanged either way:**
  - the state machine and the remembered choice
  - the robot asleep while stopped
  - the routes and the write guard
  - the dashboard controls
  - readiness
  - the CLI flags
  - missed jobs
- **Pending:**
  - the owner chooses one process or two
  - block #82's four decisions

## [2026-10-30 #83] Decision: option A of block #82, each module's singleton session restarted in place

- **Owner:** 「放在同一个进程，用方案A吧，但有点不一样。我理解每个模块都有一个全局单例服务，来提供模块
  能力。而不是新建一套模块对象。你觉得呢？」
- **Assessment: agreed, and better than #82's fresh objects.**
  - It is the project's own convention: one `<Area>Session.shared` per module (Scoop's shape),
    built once by `app.py`.
  - References stay valid. The dashboard context, the doctor, extension contexts and the
    `ChannelSession.shared` the agent looks up at run time all point at the same object, so
    nothing is swapped or re-pointed and no MJPEG stream holds a stale body.
  - A module's store-backed capabilities (contacts, memory, jobs, skills, Replay) stay available
    while stopped, because the singleton stays set up.
  - Loaded models (voice, face, SenseVoice, keyword spotter) stay in memory, so restarts are
    faster.
  - The code already assumes it: `privacy_mode` stops and starts the voice front end in place.
    Today that leaves another set of touch, state, gaze and face callbacks registered each time
    (block #82's audit); this contract fixes it.
- **The contract (new invariant 25, with block #82's process / service split).**
  - Every module's session lives as long as the process.
  - `setup(config, peers…)` binds config and peers. It may run again while stopped (a changed
    config), and its wiring is idempotent.
  - `start()` acquires the run's resources: threads, tasks, network clients, hardware,
    subprocesses.
  - `stop()` releases all of them and returns the session to "set up". Store-backed calls keep
    working; runtime calls refuse cleanly.
  - Run state resets on stop: the engagement session, a turn in flight, the manual-control holder,
    queues. Stores and model caches survive.
  - Enforced by a cycle test: every session, and the whole app with the null body, goes start →
    stop → start → stop. Threads, tasks and peer registrations must return to their baseline, and
    store calls must work while stopped.
- **What changes from block #82.**
  - No `construct_service`, no context swap, no re-pointing `.shared`.
  - `App.start_service()` re-runs every runtime `setup` with the freshly loaded spec, then
    `start()` in today's order. `App.stop_service()` stops in reverse.
  - The `service` module reloads and applies the config, then calls them. Both stay composition
    only.
- **Fixes the contract needs (from the audit).**
  - **body:**
    - The Reachy backend opens its HTTP client in `connect()` and closes it in `close()` (today
      once in `__init__`).
    - A fresh stop event per run (none revives a thread that outlived its join).
    - `controller` is cleared on stop.
    - Body settings are applied by `setup(config)` while stopped (today only `make()` reads them).
  - **channel:** Telegram and WeChat create their HTTP client in `start()` (today in `__init__`,
    closed in `stop()`).
  - **interaction:**
    - Touch, state, `gaze.mutual` and face callbacks are registered once, as stable session
      methods that forward to the current front end.
    - The TTS warm-up task is cancelled on stop, and the front-end thread is joined.
  - **automation:** subscribes to the bus once.
  - **perception:**
    - Body watchers are created in `start()`.
    - `on_face` listeners are kept by the session and handed to the camera.
    - `subscribe` ignores duplicates.
  - **record:** a fresh stop event per run.
  - **agent:**
    - The MCP pool is opened in `start()`.
    - Cancelled tasks are awaited on stop.
  - **llm / asr / tts / vad:** a slot's `setup` closes the backend it replaces.
  - **Already fine:** contacts, extension, doctor and dashboard.
- **Unchanged from block #82:**
  - the `service` state machine and the remembered choice
  - the robot asleep while stopped
  - the routes and the write guard
  - the dashboard
  - readiness
  - the CLI flags
  - missed jobs
  - the estimate (about one working day)
- **Still open:** block #82's four decisions (sleep on stop, remember Stop, missed reminders
  within 30 min, CLI `service start | stop | restart`).

## [2026-10-30 #82] Discussion: start and stop the service from the dashboard; the process stays with the CLI

- **Owner (evening of 2026-10-30):** 「dashboard 需要提供按钮，用来启动、关闭 sidekick 服务（dashboard
  对应的进程控制，还是交由 cli 来管理）」.
- **Reading.** Two lifecycles. The **process** — `sidekick run` in a terminal, or the launchd /
  systemd unit `sidekick service install` writes — is the CLI's; the dashboard lives in it and
  never starts, stops or signals a process (the daemon rule is unchanged). The **service** —
  everything Bobby does: body, voice, perception, turns, automations, channels, recording,
  extensions — is what the buttons start and stop. So: the dashboard outlives the service (else
  Stop removes the Start button); stopped means off, visibly (nothing heard, sent to the cloud,
  said, moved, answered or recorded); a start equals a fresh `sidekick run` (the config re-read,
  every "takes effect at the next start" setting applied, no duplicate tools, subscriptions or
  threads); a reboot does not undo the owner's Stop.
- **Facts (code and logs, 2026-10-30).**
  - `App.start()` sets up and starts the runtime, then the dashboard and the doctor; `App.stop()`
    takes all of it down. There is no state between "running" and "process gone".
  - Start ≈ 1 s with the daemon up (run75: boot → running in one second; models load on first
    use, SenseVoice 0.35 s; the TTS link 2–3 s later); stop ≈ 1 s, 6 s when an MJPEG stream is
    open (the server waits 5 s, then logs a `CancelledError`, run73).
  - The daemon (pid 21547) has run for 4 days; a `sidekick run` restart only reconnects to it
    (`stop_daemon_on_exit` false). After sidekick exits the robot stays awake, frozen in its last
    pose: `body.sleep_on_stop` only acts when the daemon process stops. The daemon can stop and
    start its backend without exiting: `POST /api/daemon/stop?goto_sleep=true` (sleep pose,
    motors limp, camera and audio released), `POST /api/daemon/start?wake_up=true` (backend and
    media server rebuilt). Its log is 240 MB (never rotated).
  - **Restarting the existing session objects does not work** (audit of every `setup` / `start`
    / `stop`): the Reachy backend creates its HTTP client once and closes it in `close()`, so the
    next `connect()` raises `RuntimeError`, which `_get_json` (catching `httpx.HTTPError` only)
    lets through (reachy.py:118/161/185); Telegram and WeChat close their clients the same way
    (Telegram's `getMe` then aborts `ChannelSession.start`); `InteractionSession.start` adds
    touch, state, `gaze.mutual` and face callbacks on every start and never removes them, and its
    TTS warm-up task is not cancelled on stop; `AutomationSession.setup` subscribes `on_event`
    again (event jobs would run twice); a thread that outlives its join is revived by
    `_stop.clear()`; body settings are read only in `BodySession.make()`; `config.apply()`
    replaces backends without closing their HTTP pools; `App.spec` is never refreshed (`ctx.spec`
    falls behind after Telegram pairing). Contacts, extensions and the doctor would restart
    cleanly.
  - Dashboard routes look up `ctx.<session>` per request and `LiveFeed` per frame
    (`DashboardContext` is a mutable dataclass), so the sessions behind them can be swapped; only
    `/body/stream.mjpg` holds its body for the life of the stream. With the sessions set up but
    not started the store-backed pages work (config, contacts, memory, jobs, skills, subagents,
    MCP list, Replay, decisions and clips, traces, logs, readiness); `/agent/chat` would still run
    a full turn, MCP and extension writes launch MCP servers, the robot routes answer `ok` and do
    nothing; `/say` is the only gated route.
  - `PerceptionSession.setup` creates the camera and audio watchers only when the body is already
    connected, and `on_face` drops a listener while there is no camera — the one setup that
    depends on a started peer.
  - Jobs missed while sidekick is down fire at the next start however late (`JobStore.due` takes
    every past `next_run_ts`): after a stop from 14:00 to 18:00 a 14:30 reminder fires at 18:00.
  - No Origin or Host check on the 45 write routes (33 POST, 12 PUT / DELETE): a web page open in
    the owner's browser can POST to `127.0.0.1:8787` (a form or a `no-cors` fetch needs no
    preflight). The dashboard and the doctor import neither `subprocess` nor `signal`.
- **Options.**
  - *A. Switch the service inside the process (recommended).* `sidekick run` keeps a console for
    its whole life — storage, logging, config, the dashboard server, readiness, the provider
    sessions — and starts and stops the service inside it, each start building fresh runtime
    sessions from the config re-read from disk (a process start without the process). Every data
    page keeps working while stopped, the change is small, the dashboard keeps its in-memory
    access. Cost: a native thread that wedges, or a code update, still needs a process restart
    from the CLI — where the owner put process control.
  - *B. A child process per service run.* `sidekick run` becomes a supervisor that spawns the
    runtime. Either the dashboard moves to the parent and every live read (10 Hz telemetry,
    camera frames, each module's `live()`, the controller, test turns) crosses an IPC layer, or
    it stays in the child and the parent reverse-proxies HTTP, WebSocket, MJPEG and video ranges
    and serves a reduced page while stopped (no config, contacts or memory unless re-implemented).
    OS-level isolation and new code on every restart, for a process manager plus a proxy or IPC
    layer, two processes on the same SQLite files and `config.json`, and a dashboard that manages
    processes by proxy.
- **Proposal (A).**
  1. **Lifecycle split in `app.py`, still composition only** (invariant 21): `construct` (the
     console: doctor, dashboard, the new service session), `construct_service(spec)` (Body …
     Extension, fresh, `.shared` re-pointed), `setup_service(spec)` (every runtime `setup` in
     dependency order, then the doctor's and the dashboard context's peers re-pointed — setup
     holds no threads, I/O or network), `start_service()` (today's order), `stop_service()`
     (reverse, the dashboard untouched), `start()` / `stop()` (the console). The architecture test
     covers all of them. Perception creates its body watchers in `start()` and keeps `on_face`
     listeners registered before.
  2. **A `service` module (Layer 5; imports `log`, `storage`, `config`)**: `ServiceSession`.
     `stopped → starting → running → stopping → stopped`, plus `failed`; one lock, a request
     during a transition gets 409, the current state again is a no-op. **Start** re-reads and
     applies the config (replaced backends closed), construct → setup → start, then the dashboard
     switches to the new sessions; a failure stops what started and leaves `failed` with the
     error. **Stop** stops the runtime and keeps the stopped objects for the data pages.
     **Restart** = stop + start. After a stop it lists `sidekick-*` threads and runtime tasks
     still alive ("restart sidekick from the CLI to clear them"). It remembers the owner's choice
     in `.derived_data/service.json` (wanted, when, by); `sidekick run` follows it.
  3. **The robot.** Stop disconnects, then (with `body.sleep_on_stop`, on by default; its
     description already says "put the robot to sleep on exit") the daemon stops its backend with
     `goto_sleep`; Start (with `body.wake_on_start`) starts it with `wake_up`, then connects. The
     daemon process stays up (started only by sidekick, stopped by `sidekick daemon stop`); the
     same calls reach Wireless. A Ctrl+C on `sidekick run` stops the service too, so the robot
     sleeps there as well (`sleep_on_stop: false` keeps today's frozen-awake). `BodyDaemon.start()`
     tells "reachable, backend stopped" (start it) from "unreachable" (spawn it).
  4. **Routes.** `GET /api/service` (and `service` in `/api/health`); `POST /api/service`
     `{"action": "start" | "stop" | "restart"}` → 202 with the state, the page follows through the
     1 Hz poll. While stopped: test turns, `/say`, body and robot actions and tests, frames and
     enrollment from the robot, Telegram pairing and the loopback check answer 409 "service
     stopped"; writes are saved but no live-apply hook launches anything (`refresh_mcp`, extension
     enable) — they apply at the next start. One guard on every write route: refuse a
     foreign `Origin` and a `Host` other than loopback on the dashboard's port (the CLI sends
     neither).
  5. **Dashboard.** A state pill and a power button by "Sidekick" atop the sidebar (and in the
     phone bar) open a small panel: state, since, by, what runs now (a conversation with whom, a
     job), Stop / Restart (a second click confirms) or Start. While stopped Live shows "Bobby is
     stopped" with Start, runtime-only controls are disabled with one line, data pages are
     unchanged, the runtime modules' dots are grey. System → Readiness gets a Service card (state,
     last start / stop times, leftovers, the remembered choice, the buttons). "Takes effect at the
     next start" becomes "at the next service start · Restart now", except the dashboard's own
     address (a process restart).
  6. **Readiness.** Stopped is its own verdict — "stopped (by … at …)", neutral, not bad — and the
     rows that need the runtime (daemon, body, microphone, voice front end, recording) are skipped.
  7. **CLI.** Process control unchanged (`sidekick run`, `sidekick service install | uninstall`,
     `sidekick daemon …`); `sidekick run --service on|off` overrides the remembered choice for one
     launch; `sidekick service status` also prints the process (dashboard URL, uptime) and the
     service state. Optional: `sidekick service start | stop | restart` calling the same route as
     the buttons (one mechanism; useful on a headless Pi).
  8. **Missed jobs.** When the service starts, a one-shot reminder at most 30 min late fires with
     its due time in the prompt; an older one is not spoken but shown on Automation as missed; an
     overdue recurring job (heartbeat, briefing) moves to its next slot.
  9. **Fixes the restart needs.** Interaction cancels its warm-up task on stop; a slot's `setup`
     closes the backend it replaces; the fresh spec everywhere (`App.spec`, `ctx.spec`); the new
     body knows from the pid file whether this process spawned the daemon; Live wraps every read so
     a swap never closes its socket.
  10. **Tests and verification.** `test_service_lifecycle.py` (null body, temporary home): boot,
      console, service start → stop → start → stop — no `sidekick-*` thread or runtime task left,
      tool / subscription / adapter counts stable, store-backed routes answer in both states,
      guarded ones 409 while stopped, the state machine (202 / 409 / no-op), the remembered choice
      at boot, a cross-site POST refused. The architecture test gains the composition methods and
      "dashboard and doctor never import `subprocess` / `signal`". On Bobby: Stop (the robot
      sleeps, no decisions, no Telegram poll), Start (wakes, talks), a restart applying a "next
      start" setting, ten cycles with threads and memory flat, each step timed.
  11. **Docs.** AGENTS.md (Layer 5 and the import table, a `service` row, the app / cli /
      dashboard / body / perception / interaction / automation / doctor rows, invariant 21's
      wording, a new invariant 25: the process is the CLI's, the dashboard only switches the
      service), README / README_CN diagram.
- **Decisions for the owner.** (1) Stop puts Bobby to sleep — head down, motors limp, camera and
  microphone released (recommended; else today's frozen-awake). (2) Stop is remembered across a
  reboot or process restart (recommended; else the service always starts with the process).
  (3) Reminders missed while stopped: fire within 30 min, else list them as missed (recommended;
  else today's "however late"). (4) The CLI `service start | stop | restart` (recommended: yes,
  small).
- **Estimate.** About one working day with tests and the live check; stop and start each ~3–5 s,
  mostly the robot's sleep and wake moves (not measured yet).
- **Pending:** owner decision. Nothing changed yet.

## [2026-10-30 #81] Progress: one voice one identity, the direction of a sentence, the gaze, breathing retired (block #80)

- **Direction.** `BodySession` keeps the last 30 s of DoA readings; `doa_between(start, end)` =
  the median of a stretch of speech (speech-flagged readings first) with `agreement` (share
  within 15°). The front end gives `speech_end` the direction of its speech window (onset − 0.3 s
  → end) and the keyword event its last second. `_yaw_of`: agreement < 0.5 → no direction (no
  direction test, no head turn). This morning's four rejected sentences have medians 3°, 2°, 0°,
  −2° with agreement 0.57–0.78 → accepted; the two that turned the head to −28° / 41° have
  agreement 0.38–0.39 → no turn.
- **Who is speaking.** `VoiceIdentifier.match`: a named voice (contact or `self`) at the threshold
  wins over a closer unnamed person; below it, a contact ≥ 0.35 is `Identification.near`.
  `ContactSession.identify_vector`, `learn_voice` (running weight capped at 50, the true count
  kept), `merge_person` / `merge_people` (≥ 4 utterances, ≥ 0.55, 0.1 clear of the next contact;
  swept at start). `InteractionSession`: < 1.0 s of speech not identified, < 1.2 s or `near`
  never a new person, a turn without its own identity takes the session's speaker, identified
  utterances (and uncertain ones in their contact's session) are learned, three uncertain ones
  of a session whose mean clears the threshold identify it, a merged person renames the session.
  `EngagementMachine`: two different known contacts → `other speaker`; anything else → the
  direction; a known voice replaces an unknown / unnamed session speaker.
  **Replay** (the real interaction path on a copy of last night's store, this morning's 15
  sentences in order): no new person (was 3), the session known as 发瘟鸡 at the fourth sentence
  by its mean, later sentences 0.58–0.77 (were ≤ 0.54). **Live store:** the start-up sweep merged
  `person:25` into 发瘟鸡 (0.57, 7 utterances → 10 samples); the "Bobby" fragments `person:19/20/26/27`
  forgotten (backup `scratchpad/backup80/`).
- **Gaze.** `think` / `think_long` lost their yaw (a 4–5° tilt that changes side, −3° pitch, the
  antennas); only the `express` layer holds the face servo, so tracking continues while Bobby
  thinks; a DoA turn needs agreement ≥ 0.5, no face from either tracker in 1.5 s, and inside a
  session ≥ 20° plus a second segment agreeing within 20° (a fixed source from the Mac's speaker
  read −8°, 24°, 2° as medians). Live check: while thinking yaw stayed put, roll ±4°, pitch −3°.
- **Breathing retired**: no `breathing` in `MotionState` / `MotionOwner` / `BodySession`, no
  `/api/robot/breathing`, no toggle on Body's controller, no flag on Live; idle head pose now
  constant (z 0.00 mm) between glances.
- **Touch.** A side arms only after its measured angle has come within `release_rad` of the
  command. Probe on the robot: the left antenna does not reach +43° once the head is turned ≥ 25°
  (left or right, any pitch; 20° is fine) and stays at ~10° — mechanical, to be checked by the
  owner; it was this morning's 1 Hz "touch" loop (press → `ack` → re-arm → press).
- **Prompt.** MAIN_ROLE: spoken turns are speech-recognition transcripts; read them for what was
  most likely said, ask briefly when unsure. Bench (2 × 6 misheard turns): two of them now ask
  instead of answering another question; the fast model still does not map 发返鸡 to 发瘟鸡; news
  routing unchanged (1 in 6 delegates with either prompt).
- **Recognition (owner's point 2): keep SenseVoice.** Benchmark of every Cantonese-capable offline
  model in the sherpa-onnx `asr-models` release on the 24 real clips (truth by context, CER per
  Han character / Latin word; `scratchpad/asr80/results.md`): production SenseVoice int8
  2025-09-09 17.8 % (17.7 % on the sure rows, 4/8 names, 57 ms); `language=yue` and ITN change
  nothing (auto already detects `<|yue|>` on every clip and keeps English / Mandarin); fp32 the
  same; FireRedASR2 AED 25.4 % (most names, 5/8, but invents fluent Mandarin on noisy clips,
  531 ms, 2.7 GB); WenetSpeech-Yue 31.9 %, Fun-ASR-Nano 36 %, Qwen3-ASR 0.6B 38.9 %, Paraformer
  trilingual 39.5 %, Whisper large-v3 49 % (2 s), Dolphin, the Cantonese zipformer, TeleSpeech,
  Omnilingual worse. MiniMax `asr-1.0` on the 16 accepted turns: 20.8 %, the same as SenseVoice
  on those 16, plus ~1.3 s. Spotting the name with the keyword model (pinyin approximations of
  faat wan gai) found 3/8 at best: not usable. The errors that hurt were the name (发返鸡 / 火湾鸡 /
  化翻鸡 for 发瘟鸡) and a few short sentences; with the identity fixed the agent knows the speaker
  without the name being said. Further steps need the owner: a cloud recogniser strong in
  Cantonese with hotwords (an account and key; benchmarkable on the same clips in minutes) or a
  Cantonese pronunciation table to correct household names (a new dependency).
- Tests: 232 passed, 6 skipped (new: `test_contact_voice_identity.py` — contact over a closer
  person, the uncertain band, capped learning, merging, short / uncertain speech never a new
  person —, the session-speaker rules, `doa_between`, a blocked antenna never fires, two-in-a-row
  turns, thinking keeps the servo); ruff, format, mypy clean; no key in the logs. Live check after
  the restart (run74 / run75): a three-turn test conversation from the Mac's speaker worked, its
  rows and `person:28` removed afterwards. Screenshots: `shots80/`.

## [2026-10-30 #80] Decision + Todo: the owner's Cantonese session — who is speaking, why Bobby stopped answering, the gaze, breathing retired

Owner, after talking Cantonese with Bobby on the morning of 2026-10-30: (1) 「我昨晚通过语音注册了，
名字叫 "发瘟鸡"，今天它识别不出来」; (2) 「粤语识别准确率很低」; (3) 「连续对话时，聊着聊着，他就不回了」;
then: 「我记得我已经要废弃了他呼吸的 idle 动画，而且说话过程又有东张西望」 (the request to replace
breathing with looking around was block #38's point 2; I kept breathing and added the glances).

**Diagnosis (from the decisions table, the recording ring and the contact store; no code changed).**

- *Not recognised.* 发瘟鸡 was befriended from three utterances last night (in-session scores
  0.62–0.87). This morning every utterance scored 0.41–0.54 against that centroid (another time,
  another place in the room), the first one 0.43 → below the 0.5 threshold → a new `person:25`,
  whose centroid of this morning's voice then beat 发瘟鸡 on every later utterance (0.65–0.83 vs
  ≤ 0.54). The short "Bobby" segments (0.7–0.8 s of speech inside a 1.8 s clip, most of it the
  pre-roll) made `person:26` / `person:27` (last night `person:20`). `person:25`'s centroid vs
  发瘟鸡 is 0.57: the same voice, split in two.
- *Stopped answering.* Four of the owner's sentences inside a session were rejected as
  `other direction` (「我之前同你讲过啦我叫发瘟鸡」「我叫发瘟鸡」 …), then the session timed out after
  8 s and the next sentence needed the name again. The session's speaker was the short "Bobby"
  clip's spurious person, so every later utterance was "another unnamed person" and fell to the
  direction test — and a segment's direction is **one DoA reading taken when the VAD closes the
  segment**, i.e. in the silence after the sentence. The median of the readings *during* those
  four sentences was 3°, 2°, 0°, −2° (the owner, straight ahead); the single readings were −57°,
  8° (vs a session direction of −28° set the same way), 63°, 59°. Last night the same chain
  rejected 「你咪就叫我发瘟鸡啦」 as `other speaker` right after befriending (the session's speaker
  was the "Bobby" clip's `person:20`, so the rename to 发瘟鸡 never reached it).
- *Looking around.* Each accepted segment turned the head toward that noisy reading (−28° for
  「哇你认唔认得我」, held through the whole reply), the thinking state looks up and to one side
  and then drifts to the other (yaw +12° → −8° → +10°), and the DoA turn ignored our own face
  servo (it only checked the daemon's tracker).
- *A 1 Hz "touch" loop.* With the head pitched up ≤ −15° (looking at the standing owner) the
  left antenna stops at +10° when commanded to +43° (158 of 230 samples this morning; level head:
  3 of 1033) — something behind the robot? — the detector re-armed after every antenna move and
  read that as a press, a press played `ack`, which moved the antennas and re-armed it: 20
  "touches" this morning, 11 in a row at 09:14:41–51.
- *Recognition.* Levels are fine (speech ≈ −20 dBFS, SNR ≈ 40 dB, a few first words clip at
  0 dBFS). SenseVoice (auto language — the per-call `yue` is only recorded) and MiniMax asr-1.0
  are both wrong on names and on some phrases: last night MiniMax was better (「你知唔知道係邊個啊」
  vs local 「你知唔知系中国啊」; 发瘟鸡 vs 火湾鸡), this morning worse (「我们听一听吗？」 for
  「今日天氣點啊」). A benchmark of the local Cantonese-capable models on these 24 real clips is
  running (`scratchpad/asr80/`).

**Decision.**

- [x] *Direction of an utterance* = the median of the DoA readings during its speech (the body
  keeps the last 30 s of readings; the chip's speech-flagged ones when there are any), with an
  agreement share; an utterance whose readings disagree has no direction (no head turn, no
  direction test).
- [x] *Who is speaking.* Less than 1.0 s of speech is neither identified nor a new person. A
  contact at or above the threshold wins over a closer unnamed person. A voice between 0.35 and
  the threshold of a contact is uncertain: no new person, and inside a session it is the
  session's speaker. Contacts keep learning: an utterance identified as a contact is folded into
  its centroid (running weight capped at 50, so new rooms and times still move it), and so is an
  uncertain one inside that contact's session. An unnamed person whose centroid reaches 0.55
  with a contact (≥ 4 utterances) is merged into it — at start for the people already stored
  (today `person:25` → 发瘟鸡) and whenever a person's centroid grows.
- [x] *Session matching.* Two known contacts that disagree → `other speaker`; an unknown or
  unnamed session speaker meeting a known contact is upgraded to it (direction permitting);
  everything else is decided by the robust direction. The turn's speaker is the utterance's
  identity, else the session's.
- [x] *Gaze in a conversation.* Thinking keeps the eyes on the person (no yaw; a small tilt
  that changes side, the antennas sway); the face servo keeps running while Bobby thinks; a DoA
  turn needs an agreeing direction, ≥ 20° from the current look, and no face seen by either
  tracker in the last 1.5 s.
- [x] *Breathing retired* (owner): no idle bob in the motion owner, no toggle on the Robot
  controller, no flag in telemetry / Live.
- [x] *Touch*: a side arms only after its measured angle has reached the command; a blocked
  antenna never fires, a held one fires once.
- [x] *Recognition*: decided from the benchmark (a better local model and / or the SenseVoice
  language pinned to Cantonese), plus the turn's prompt saying a name may be misheard.
- [x] Tests, docs, a replay of this morning's clips through the new identity rules, a live check.

## [2026-10-30 #79] Progress: hedged model calls; the main agent on Swarm (block #78)

- **Hedging.** `llm.py`: `stream(…, hedge_after_s)` runs each request as a `_Leg` (a task pumping
  its events into a queue) and races them on their first event (`_answered`); the loser is
  cancelled with its `lost` mark, so `RecentCalls` records it as `hedge lost` with the new
  `cancelled` flag (not in `errors_1h`; barge-in cancellations count the same way now). The
  backend yields `start` once with the first delta of any kind (a tool-only answer used to say
  nothing until its call was complete) and `warm(2)` keeps two pooled connections. The loop
  passes `profile.hedge_after_s` on turns someone waits for; `agents.main_hedge_s` = 2.5 s.
- **Measured** (real MiniMax, the main agent's prompt and tools, 45 interleaved pairs at 01:44):
  plain p50 1.23 s, p90 2.47 s, max **19.4 s** (2 calls over 3 s); hedged p50 1.25 s, p90 1.97 s,
  max **2.6 s** (none over 3 s), 3 hedges sent (7 %). In this sample the stuck call fell in the
  plain arm and the three hedged calls that crossed 2.5 s still answered first, so no second
  request won; an earlier hedged run of 40: max 2.8 s, 4 hedges, none won. Plain runs before:
  1 call in 20 at 9–13 s. The Live page's Services card now says how often a call was asked
  twice and how often the second answered first, to watch it over days.
- **Swarm.** `AgentSession.roster()` (every agent, the main agent first, with its role, the
  tools it gets, hedge, origin), `configure_main()` (slot, steps, reply cap, context, hedge,
  live), `GET /api/agent/agents`, `POST /api/config/agents` applies those knobs at once (others:
  next start; no running agent: next start). The Swarm view is a board of agent cards (main first,
  an add card while there is no subagent) above the LLM calls; the main agent's window shows its
  rules, its tools (main-only highlighted) and its settings card; the Subagents view is gone
  (`#subagents` → Swarm); Settings keeps the LLM service cards. Also fixed: the LLM calls table
  showed `[object Object]` for a camera call's question (now its text and `[image]`).
- Tests: 225 passed, 6 skipped (new: `test_llm_hedge.py` — a late answer asked again and the
  second wins, a quick one never asked twice, the first still wins when it answers first, a
  failed request does not win, a stop cancels both —, `start` on a tool-only stream, `warm(2)`,
  hedging only on turns someone waits for, `configure_main`, the roster and the live apply);
  ruff, format, mypy clean; no key in the logs. Screenshots: `shots78/`.

## [2026-10-30 #78] Decision: hedge the main agent's model calls; the main agent joins Swarm

Owner, after block #77: 「可以且应该要做对冲请求！」 and: with Subagents there should also be the
Main agent — rename to something like "agents"? would that clash with the Agent tab? My view:
not a new "Agents" view (Agent → Agents repeats the tab), but the **Swarm** view becomes every
agent — the project's own word for main agent + subagents, already the view that listed them.
Owner: 「你 Subagents 改造方案很好，就这样办」.

- [x] `LLMSession.stream(…, hedge_after_s)`: the backend yields `start` with its first delta of
  any kind; no `start` (and no end) by then → the same request again; the first to answer is
  streamed, the other cancelled (`hedge lost`, counted as cancelled, not as an error); a request
  that ends without answering does not win while the other may; the second is traced as
  `<task>.hedge`; `live()` counts hedges sent and won.
- [x] The main agent hedges turns someone waits for (voice, chats, the test card), never jobs or
  internal relays: `agents.main_hedge_s` (2.5 s ≈ the first token's p90; 0 = off). Two pooled
  connections are kept warm while it hedges, so the second request pays no TLS handshake
  (1.3 s through this Mac's proxy).
- [x] Swarm = one card per agent (`GET /api/agent/agents`), the main agent first; its window: what
  it does, its rules (MAIN_ROLE, read-only), the tools it gets (main-only marked), its settings
  (slot, steps, reply cap, context, hedge) applied at once (`AgentSession.configure_main`); the
  Subagents view folds into it (`#subagents` → Swarm); Settings keeps the LLM service cards.
- [x] Tests, docs, a real A/B of plain vs hedged calls, screenshots.

## [2026-10-30 #77] Progress: the acknowledgement, the pause after a full stop, Subagents (block #76)

- **Acknowledgement.** `loop.py`: said only when nothing has been said yet on a voice turn of
  the main agent and a step's tools are still running after `ACK_AFTER_S` = 0.4 s (once a turn,
  any step); `AgentEvent.filler` marks it. `run_main` keeps it in the transcript (`content`) and
  stores the model's own last words as `meta.reply` when they differ. Real voice test after the
  restart: one 「稍等吓。」 before the `look` turn (camera 4 s), none before the `news_latest`
  turn. The phrases now rotate 「好，等我睇下。」「稍等吓。」「等我諗諗。」.
- **Where words were said.** Tool rows carry `step` and `said`; the context view rebuilds one
  assistant message per step with `said` before its calls and `reply` after the results. Bug
  fixed on the way: the in-turn assistant message carried only the last streamed chunk of the
  words before its calls (`final_text[-1:]`), now the whole step's words, never the filler.
- **MAIN_ROLE.** "Call tools straight away, without announcing them (no 「等我睇下」 first);
  after the result, answer in a sentence or two." Bench (the real prompt and tools, 18 tool
  turns × 2 rounds): lead-in lines 12 → 0, every expected tool still called (`remember` ×2,
  `schedule`, `set_volume`, `look_at`, `look` / `who_is_here`, `news_latest`, `jobs_list`,
  `recall`). A variant asking for the answer in the same reply as the call made Flash skip
  `remember` once: not used.
- **Pause after a full stop.** `pipeline.py`: `SENTENCE_FINAL` fragments are flushed as they are
  sent (`TTSStreamKeeper.end_sentence`); the keeper records each flush's kind (clause / sentence /
  final) and, after a sentence's `flushed`, puts `sentence_pause_s` of silence before the next
  audio, less the silence the speaker already had (`play()`, `_play_end` from
  `body.speaking_remaining_s()`); the eager first clause (a comma) gets none; the fallback HTTP
  path owes the same pause. The splitter keeps runs of sentence ends (`？！`, `……`), treats an
  ellipsis and an English full stop before a space as sentence ends, and keeps a newline as the
  end of its fragment. `interaction.sentence_pause_ms` on Voice → Speak → Pacing, applied live.
  Measured on the robot's speaker track with 250 ms: full stops 0.43–0.52 s, commas 0.2–0.4 s
  (before: ~0.22 s for both); the default is **300 ms** (correction to block #76's 250).
- **Subagents.** `AgentProfile.origin` (`core` / `user` / `extension:<name>`, the loader passes
  its origin); `AgentSession.set_subagent()` builds a config subagent (setup uses it too),
  `subagents()` lists every subagent with the tools it gets; `GET /api/agent/subagents`,
  `PUT` / `DELETE /api/agent/subagents/{name}` (name `^[a-z][a-z0-9_-]{0,31}$`, not `main`, an
  existing LLM slot; an extension's subagent → 409) write `agents.subagents` and apply at once.
  Agent → **Subagents** view: cards (what it does, slot, tools it gets, skills, tasks, origin), a
  window that edits yours (allowlists with the names to pick from; choosing one replaces `*`)
  and shows an extension's read-only; `/api/agent` carries `llm_slots`; deep link
  `#subagents`. Bug fixed: `unregister_agent` left the removed subagent in the main agent's
  prompt (`agents_block` is rebuilt on both).
- **Deleted episodes stay deleted.** Found while cleaning up the test: the writer wrote an
  episode deleted on the dashboard again within minutes (its conversation had no episode any
  more), and deleting a contact had the same gap for their private episodes. Both now leave an
  empty `deleted` marker (`_EPISODE_TOMBSTONE`); listings skip it.
- **Measured, not changed: MiniMax's tail.** 40 calls of Flash with the real prompt at 00:43:
  first token p50 1.42 s, p90 2.67 s, p95 9.27 s, max 13.2 s — one call in twenty waits 9–13 s,
  and two turns of the voice test hit it (11.0 s, 7.9 s), as did one of the owner's (4.3 s).
  Proposal for the owner: a hedged request (a second identical call when no token has come by
  ~2.5 s, the first to stream wins, the other cancelled and traced) — roughly 10 % more calls.
  Also seen: the rebuilt history drops the context line of past user messages, so the prefix
  cache matches only up to the system prompt after the first turn (and sometimes not even that:
  `cached_tokens` 188 on two calls) — a later pass.
- Tests: 218 passed, 6 skipped (new: time-based acknowledgement, the model never sees it, the
  step rebuild, sentence flushes and pauses, the splitter's ends, Subagents routes, extension
  origin, deleted episodes); ruff, format, mypy clean; no key in the logs. The voice test's
  conversation (11 rows), its `person:23` and its episode (written twice) were removed.
  Screenshots: `shots76/` (Subagents board, yours, the news one, phone, Voice → Speak).

## [2026-10-30 #76] Todo: the spoken acknowledgement and the pause after a full stop; a Subagents view

Owner, after the first test of block #75 (2026-10-30): replies are much faster, but nearly
every reply opens with 「好，等我睇下」 and runs straight into what follows, with no pause where
the punctuation is. Also: there is no page to manage subagents on the dashboard. Found:

- In the owner's session every turn called a tool (`people_seen`, `befriend`, `remember`,
  `forget`, `news_latest`, `who_is_here`, `look`, `look_at`), so block #71's acknowledgement
  played before nearly every reply, though all but `look` answered within 120 ms (measured over
  all runs: local tools ≤ 0.12 s, `look` 4.4 s, `delegate` 5.6 s median).
- The model then copied it: the stored reply put the acknowledgement after the tool results in
  the rebuilt context, and the turn's next reply opened with 「好，等我睇下。」 twice (once
  from the platform, once from the model). MAIN_ROLE's own example (「好，等我睇下。」「收到，
  幫你記低。」) made Flash open 12 of 18 tool turns with such a line in a single-turn bench.
- MiniMax leaves ~0.2 s between the sentences it synthesises (80–160 ms of trailing plus
  leading silence), the same as a comma inside one sentence, so 。 sounded like ，. A pause
  marker (`<#0.3#>`) works but changes where the server cuts sentences; the server also cuts a
  long comma run on its own, so its `sentence_end` cannot tell a full stop from a comma. A
  `task_flush` after a sentence is acknowledged exactly after that sentence's audio, in order,
  and does not slow synthesis (measured).

Plan:

- [x] The acknowledgement only when nothing was said yet and a step's tools are still running
  after `ACK_AFTER_S` = 0.4 s (any step, once a turn); it is a `filler` event: spoken and kept in
  the transcript, never shown back to the model (in the turn or in a later context view).
- [x] The timeline keeps where words were said: tool rows carry `step` and `said` (the model's
  words before that step's calls), the assistant row `reply` (its last words, when the
  transcript holds more); the context view rebuilds one assistant message per step. The
  in-turn assistant message carried only the last streamed chunk before its calls; now the
  whole step's words.
- [x] MAIN_ROLE: call tools straight away without announcing them; after the result, answer in
  a sentence or two (bench: no lead-in in 18 tool turns, every tool still called).
- [x] Every sentence that ends in 。！？；… (or an English full stop) is flushed as it is sent;
  after its `flushed` the next audio waits `interaction.sentence_pause_ms` (250 ms, Voice →
  Speak → Pacing), minus whatever silence the speaker already had (a tool round is never
  lengthened); after the eager first clause (a comma) no extra pause. The splitter keeps runs
  of sentence ends together (`？！`, `……`) and treats an ellipsis and an English full stop
  before a space as sentence ends.
- [x] Agent → **Subagents** view: one card per subagent (what it does, slot, tools / skills /
  MCP, origin, turns), a details window with its role and allowlists; config-defined subagents
  are created, edited and deleted there (applied live), an extension's are shown with their
  origin.
- [x] Tests, docs (AGENTS.md, README*.md), a real voice test, screenshots.

## [2026-10-29 #75] Progress: first-word latency (block #71, steps 2–6)

Everything measured with the real main-agent prompt on this Mac, 2026-10-29 evening.

- [x] **Model for `fast`**: MiniMax-M3.1-Flash with `reasoning_effort: minimal` (it refuses
  thinking off). Twelve interleaved rounds, same prompt and tools: first token median
  **1,478 ms** (1,372–2,640) vs **2,447 ms** (1,155–4,691) for MiniMax-M3 with thinking off —
  the evening peak doubled M3's numbers (1,150 ms at 18:45, 2,314 ms at 19:50). On ten household
  prompts Flash kept quiet for the TV news, did not claim to switch on a light it has no tool for
  (M3 said 「我開咗客廳燈」) and speaks before a tool call more often. The preset now carries
  `model_extra_body` (MiniMax-M3 still gets thinking off whatever the slot), so either model can
  be picked on Agent → Settings; `models.fast` defaults to Flash.
- [x] **Prefix cache**: MiniMax reports `prompt_tokens_details.cached_tokens` (an identical
  prompt: 3,723 of 3,725 cached; a prefix is cached once it has been seen twice; a changed first
  character drops it). The system prompt (role, skills, subagents, memory block) is now stable
  for a conversation and the per-turn line (time, speaker, language, channel, a confirmation
  result) leads the turn's own message; follow-up turns read 3,456–4,096 tokens from the cache.
  The trace records `cached_tokens`. The latency gain is not separable from the server's load,
  but the cache never hurts and halves the prompt bill.
- [x] **TTS first audio**: the bidi server starts only on a sentence end or a flush (a clause
  ending in a comma waited 2.7 s; a sentence or a flush 0.6 s). A first clause still open
  `EAGER_FLUSH_S` = 0.15 s after it was sent is flushed mid-turn (the session goes on; the turn
  ends on the last flush's acknowledgement); a quick first sentence still goes out whole (a
  separately synthesized clause adds about 0.5 s of pause).
- [x] **Fewer model rounds**: time and date questions are answered from the context line (the
  model called `time_now` first: one LLM round, about 1 s); before a tool call the model says a
  few words in the same reply (「好，等我睇下。」) — 6 of 9 fresh tool turns did, first text 1.0–1.6 s
  instead of 3.0–4.5 s.
- [x] **A spoken acknowledgement** when the main agent's first step on a voice turn is only
  tool calls (`loop.py`, rotated 「好，等我睇下。」「等我諗諗。」「收到，我睇下。」; never for jobs, relays
  or subagents): a real voice turn that went to the tools heard its first word at **2.8 s**
  instead of **5.1 s** (measured with the recorded 「Bobby，今日天氣點呀」 played to the robot).
- [x] **Short skills inlined** (≤ 1,200 characters: storytelling, briefing): a story request's
  first text 1.05–1.38 s instead of ~3.2 s behind a `skill_read` round.
- [x] **Bug found**: Flash can send a second tool call under an index already used; the stream
  parser appended it (`scheduleschedule`, a failed call and a retry: 9.6 s). A new id under a used
  index is now a new call, and a repeated name is not appended.
- [x] Cleanup: the test turns' four reminders (three at 22:00 tonight, one at 07:30), four facts,
  97 test rows (test card, the voice tests) and the test voice's `person:18` were deleted
  (timeline backed up first).
- Not solved by latency work: with no weather tool the model searched the news and delegated to
  the news subagent for 「今日天氣點呀」 — about 13 s of tools after the acknowledgement. A weather
  source would be an extension (owner).
- Open (owner): (1) **the proxy** — a pooled request to `api.minimaxi.com` takes 487 ms here
  (Google 185 ms, `api.minimax.io` 297 ms): the TUN proxy seems to send mainland traffic abroad
  and back; a DIRECT rule for `minimaxi.com` could take another 0.3–0.4 s off both the first
  token and the first audio (check with `curl -o /dev/null -s -w "%{time_appconnect} %{time_total}\n" https://api.minimaxi.com/`);
  (2) `service_tier: priority` — not needed for now, Flash is steady; (3) the VAD's 0.5 s end of
  speech before a turn starts — 0.4 s would save 0.1 s but may cut people who pause.

## [2026-10-29 #74] Progress: memory in three levels (block #70)

- [x] **Privacy**: Telegram private chats (`chat.type == "private"`) and WeChat arrive with
  `metadata.private`; a private conversation's user and reply rows are `private`.
- [x] **L0** (`agent/dialogue.py`, migration 2): every row has a `conversation` —
  `voice@20261029-185600` for the room (turns within 5 min), `telegram:tg:42@…` per chat
  (15 min); the 194 earlier rows were placed by the same rule at the first start (replies follow
  the row they answer; a job's steps get none). The context view is the turn's own conversation
  (display names when several people talk, the earlier part of a long one as its rolling
  summary); subagents get their slice of it.
- [x] **L1 / L2** (`agent/memory.py`, migration 2): `facts` with provenance (scope, subject,
  teller, channel, visibility, explicit / inferred, category, valid until, sources, episode,
  superseded by), `episodes`, `digests`, `meta`; the two old facts moved over as explicit facts.
  Sensitive categories are always private; a change supersedes; `drop_scope` also drops the
  contact's private episodes.
- [x] **Memory writer** (`agent/writer.py`): a background task; a closed conversation (or a long
  one every 12 user turns) → one `smart` call (`memory.writer`, JSON) → episode + facts, with the
  rules in code (`_apply`): named participants who spoke; household only from open
  conversations; private chats stay with the teller; health / money / relationships only
  first-person and private; about another person → the teller's scope; a person may correct
  what is known about them; an explicit household fact only by its teller; ≤ 8 facts. Excluded:
  the test card, jobs, heartbeat, subagents, conversations without a user turn. Failed writes are
  retried three times; catch-up over 7 days at start; it steps aside while a turn is in flight.
  Nightly at 03:00: expire, digest (a profile over 400 characters), merge (refused past ¼).
- [x] **Memory block**: built once per conversation and speaker from SQLite and frozen
  (`AgentSession.memory_block`): the speaker's facts (private ones only in their private chat),
  the household's, the last conversations with them (the newest with its summary), follow-ups
  due. `remember` stores explicit facts with provenance; `recall` searches the speaker's, the
  household's and the other members' open facts plus the visible episodes, and opens an
  episode's conversation by id. The main role now says memory is written automatically and
  never to claim more than the block says.
- [x] **Prompt order**: role → skills → subagents → memory block → per-turn line (time, speaker,
  language, channel), so a provider prefix cache can reuse everything before the last line.
- [x] **Dashboard**: Agent → Memory = one card per profile (facts by category, tags asked /
  inferred / private / until, told by, channel, the episode it came from, superseded folded
  away), add a fact (scope, category, private), the writer's state and *write now*, episodes by
  day → a details window with the summary, follow-ups, the facts it produced and the
  conversation. Routes: `GET /api/agent/memory` (facts, episodes, digests, writer),
  `POST /api/agent/memory/write`, `GET|DELETE /api/agent/episodes/{id}`. Live's Memory card.
- [x] **Config** (`agents`): `memory_writer`, `memory_slot`, `memory_voice_gap_min`,
  `memory_text_gap_min`, `memory_block_chars`, `memory_nightly_hour`; `context_chars` now means
  this conversation.
- [x] **Verified**: the real database migrated (194 rows placed, 2 facts moved); the writer
  caught up on the 7 voice conversations of the week in 15 s (2–4 s each): visitor episodes and
  no facts, because nobody is enrolled. A synthetic family conversation on the real `smart` slot
  (temporary stores) gave: dad's switch to soy milk superseding his explicit milk-tea fact, the
  Sunday yum cha as a household fact (from mum), the daughter's birthday and Hello Kitty in
  mum's scope, the birthday surprise from dad's private chat kept private to him and absent from
  mum's block, follow-ups as questions (「睇牙順唔順利？」 for the day after). Two prompt fixes came
  out of it: a three-week calendar (「下個禮拜三」 had become a Saturday) and keeping health out of
  open summaries. Test turns: the main prompt went from about 5,850 to 3,450 tokens (the 6,000
  characters of every channel are gone), first token 1.0–1.5 s; the answer used memory
  (「記得呀，你鍾意飲奶茶」).
- [x] Tests: `test_agent_memory_writer.py` (rules, private chats, supersede, failures and
  retries, rolling, busy, nightly, migration), conversations and backfill, the block; 207 pass.
- Owner to know: facts come only from **named** people — nobody is enrolled yet, so until the
  family is on Contact, Bobby only writes visitor episodes. Bind the Telegram chat to a contact
  for facts from Telegram.

## [2026-10-29 #73] Progress: Live as the monitor (block #69)

- [x] `live()` on every session, memory only: interaction (state, session seconds left, the turn
  in flight with `TurnTiming.marks()` and the body's first audio, the newest decisions, TTS
  link), body (control, motion layers, breathing, sway, style, last touch), perception
  (presence, faces, today's counts, watchers), contact (latest identifications; counts from SQL
  at most every 30 s; display names cached), agent (turns in flight — state, step, tool, first
  token —, today's counts, first-token median, background tasks, parked confirmations),
  automation (running / next jobs, heartbeat), channel (counters, last traffic, poll alive),
  record (cached totals refreshed by a worker), doctor (last verdict), extension (watchers),
  llm / asr / tts (`storage.RecentCalls`).
- [x] `activity()` on interaction (decisions worth a line), perception (events ≥ info), agent
  (turns, tools, deliveries, background work, memory writes), automation (job runs), channel
  (messages in / out) and the log's warning ring (`Log.recent()`).
- [x] Host vitals (`dashboard/vitals.py`, standard library): load vs cores, CPU share, resident
  memory (`/proc` on Linux, `task_info` through ctypes on macOS), threads, event-loop lag (a
  probe task), the Pi's temperature.
- [x] `live.py`: `modules` + `activity` once a second on the 10 Hz WebSocket (a module that
  raises shows its error, the rest arrive); the 10 Hz frame no longer opens SQLite; `held`
  reaches the page. `/api/health`: daemon status cached 5 s, recording totals 30 s, contacts 10 s.
- [x] Page: camera · 3D body · **Now** on top; the dialogue (one screen) and the **activity**
  stream (module chips) on the left; the **Turn** card (heard / said, time to the first word,
  waterfall ASR → first token → TTS → speaking, tool chips; text turns show their first token)
  and eleven module cards in two designed stacks on the right; a card's title opens its page;
  phones: Now, Turn, dialogue, modules, activity, camera, 3D body. Screenshots: desktop, a test
  turn in flight and after, phone.
- [x] Tests: `test_dashboard_live_modules.py` (RecentCalls, vitals, channel and automation live /
  activity, the 1 Hz push surviving a broken module), turn tracking in `test_agent_session.py`.

## [2026-10-29 #72] Progress: the LLM connection kept open (block #71, step 1)

- [x] `v1_chat_completion`: one pooled `httpx.AsyncClient` per backend and event loop
  (keep-alive 120 s) instead of one per call; `warm()` opens a connection (HEAD on the host);
  a stream cancelled mid-body (a barge-in) re-warms at once; `first_token_ms` on `LLMResult` and
  in the trace (new column, added to the existing table). ASR primary and TTS fallback pool
  their clients the same way.
- [x] Agent: a keep-warm loop every 50 s (the server kept an idle connection > 60 s) and
  `warm()` at speech onset inside a session and on a wake-name hit (the voice front end calls it
  duck-typed, at most every 20 s).
- [x] Measured with the real main-agent prompt (4,839 tokens, 30 tools), six calls each:
  first token median **2,566 ms → 1,150 ms** with the pooled client. Without tools 1,000 ms
  (2,343 tokens): the 30 tool schemas cost about 0.2–0.3 s.

## [2026-10-29 #71] Todo: first-word latency

Owner (2026-10-29): "Q&A takes too long, above all from the question to hearing the first word;
that is what we optimise next — but memory must not make it worse."

**Where the time goes today** (log lines of 2026-10-26 … 10-29, `_turn_finished`): end of speech
→ first audio 3.0–4.5 s, typically 3.2–4.3 s:
- VAD hangover: the segment closes 0.5 s after the last voiced frame (`min_silence_s`), before
  the clock of `first_audio_ms` even starts;
- ASR: local SenseVoice 0.1–0.25 s;
- LLM first token 2.2–3.3 s (MiniMax-M3, thinking off; prompt 4.8–6.1k tokens: role, skills,
  30 tool schemas, the newest 6,000 characters of the timeline) — of which **about 1.3 s is a
  fresh TLS handshake on every call** (`v1_chat_completion` opens an `httpx.AsyncClient` per
  call; through the TUN proxy of this Mac — DNS 198.18.x, TCP 2 ms — the handshake to
  `api.minimaxi.com` takes 1.26–1.33 s; with one client the same request goes 1.8 s → 0.5 s,
  and the connection was still alive after 8 s idle with `keepalive_expiry=120`);
- TTS first audio about 0.8–1.0 s after the first fragment (bidi WebSocket, kept open).

**Plan** (each step measured on the Live Turn card, block #69):
- [ ] one long-lived HTTP client per LLM backend (keep-alive 120 s), warmed when someone starts
  talking in a session, so a turn never waits for a handshake; same for the ASR primary slot.
- [x] the prompt ordered for provider-side prefix caching if MiniMax caches (stable role,
  skills, memory block first; the per-turn line — time, speaker, channel — last); measure.
- [ ] fewer tool schemas on the voice path if they cost first-token time (measure first).
- [x] TTS: the first fragment sooner (today the first comma after 4 characters).
- [ ] VAD hangover: 0.5 s → shorter where the room allows (traced decisions show the cost).
- [ ] owner decisions: MiniMax `service_tier: priority` (−0.3 s, paid), a DIRECT rule for
  `minimaxi.com` in the proxy (the handshake through the TUN proxy is 1.3 s).

## [2026-10-29 #70] Todo: memory in three levels (block #66, decided #68)

- [x] **Privacy first:** Telegram private chats and WeChat (one-to-one) arrive `private`; the
  reply and tool rows of a private conversation are private too.
- [x] **L0:** every timeline row carries a conversation id — the room (`voice`) is one
  conversation while turns follow each other within 5 minutes; a chat (channel + chat id) within
  15 minutes; existing rows get theirs once, by the same rule.
- [x] **Context view = this conversation** (visibility rules kept), within `context_chars`;
  when a long conversation outgrows it, the rolling episode of its earlier part leads the view.
- [x] **L1 episodes and L2 facts** in `memory_v1.db` (migration 2: `facts` with provenance —
  scope, subject, teller, channel, visibility, explicit / inferred, category, valid until,
  superseded by, sources —, `episodes`, `digests`; the old `memory` rows move into `facts`).
- [x] **Memory writer** (agent, background task, `smart` slot, traced as `memory.writer`): a
  conversation closes after its gap and is written once — title, summary, follow-ups, fact
  operations against the scope's current facts (add / supersede / none); a long one every 12
  user turns; at start it catches up on the last 7 days. Never during a turn's hot path.
- [x] **Rules in code, not trusted to the model:** facts only for named participants and the
  household; household facts only from open conversations; a private chat's facts belong to the
  teller and stay private; health / money / relationships only first-person and private; what
  someone says about another person stays in the teller's scope, attributed; explicit beats
  inferred; supersede, never delete (only a person's own `forget` deletes).
- [x] **Memory block** built once per conversation and frozen (no model, no search on the turn):
  the speaker's profile (digest or facts; private ones only in their private chat), the
  household's, the last conversations with them (the latest with its summary), follow-ups due.
- [x] **`recall`**: facts and episodes by keywords (own, household, other members' open
  facts — the family sharing of decision 2), an episode's rows on request (L0).
- [x] **Nightly pass** (03:00): expire dated facts, digest a scope that outgrew its budget,
  merge duplicates in a large scope with the ¼ guard.
- [x] Not written from: job and heartbeat turns, subagent runs, Agent → Test.
- [x] Dashboard: Agent → Memory (profiles with sources, episodes by day, writer state, write
  now); Live Memory card. Config knobs, tests, AGENTS (invariant 23), README.

## [2026-10-29 #69] Todo: Live as the monitor (block #67, decided #68)

- [x] `live()` on each session — in-memory values only (no SQL, HTTP or directory walks):
  interaction (incl. the time left in a session and the turn in flight), body (control, motion
  layers), perception, contact, agent (turn in flight, steps and tools, background tasks,
  parked confirmations, first-token median), automation (running / next job, heartbeat),
  channel (adapter state, last message age, poll alive), record, doctor, extension, and the
  service sessions llm / asr / tts (recent calls kept in memory).
- [x] `log`: a ring of recent warnings and errors; host vitals from the standard library
  (load, event-loop lag, resident memory, the Pi's temperature).
- [x] `live.py`: module snapshots at 1 Hz and the activity stream with a per-connection cursor;
  the 10 Hz frame no longer calls `agent.snapshot()`; `held` reaches the page.
- [x] `/api/health`: daemon state, recording totals and contact counts cached.
- [x] Layout: camera · 3D body · Now on top; left the dialogue (one screen tall) and the
  activity stream; right the Turn card and the module cards in two columns; phone order Now,
  Turn, dialogue, modules, camera, 3D body. A card title jumps to its module page.
- [x] Tests, screenshots on the real robot.

## [2026-10-29 #68] Decision: memory and Live go ahead; first-word latency is next

Owner's answers to blocks #66 / #67:
1. Numbering L0 raw → L1 episode → L2 profile, OpenViking's abstract / detail inside — yes.
2. Family members: "distinguish wherever you can" — said openly in the room is shared within
   the household, private chats and sensitive topics stay with the teller.
3. **No shadow week** — land it directly; the owner tests and judges the effect.
4. Context view = this conversation + memory — yes.
5. Agent → Test turns are not written into memory.
6. Live = now, the module page = depth, one card per core module — yes.
7. Host vitals with the standard library only — yes.
8. Dialogue card one screen tall, the activity stream replaces Events — yes.

Plus: "Q&A takes too long, especially from the question to the first word heard; that is the
focus next, but memory must not regress it." Consequences: memory adds nothing to a turn's hot
path (block built once per conversation from SQLite, the writer runs after a conversation
closes) and the context gets smaller, not larger. Order: the connection fix (block #71, it
halves the first token and is one change), Live (#69: its Turn card is the instrument for the
latency work), memory (#70), the rest of the latency pass (#71).

## [2026-10-29 #67] Discussion: Live as the monitor — every module's vital signs

Owner (2026-10-29): "Live content is not enough. Live is for real-time monitoring and
observation, so it needs to show each module's core real-time data; the board has too little
data now."

**What Live shows today** (`dashboard_index.html` 371–384, `dashboard_live.js`, `live.py`):
six cards — camera, 3D body, Conversation (engagement state, session, attention, TTS link,
presence), Dialogue, Last turn, Events (the last 8 perception events as raw JSON). Agent,
automation, channels, contacts, recording, services, extensions and readiness are absent:
blocks #59–#61 moved telemetry, the level meters and readiness onto their module pages and left
Live a conversation viewer. Much is already on the wire and never drawn: `/api/live` (10 Hz)
carries the body's state, manual / moving / sway flags, levels and peaks, DoA, the session's
speaker and start, attention and initiative details, the heard text; `/api/health` (1 Hz)
carries whole snapshots of interaction, agent, automation, perception watchers, contacts (last
voice / face score, people seen) and recording.

**Not exposed anywhere yet:** the expression each motion layer is playing, the time left before
a session times out, the agent's in-flight turn and tool calls, background tasks (ids only),
parked confirmations, the next due and the running job, whether a channel's poll task is alive,
the last LLM / ASR / TTS call in memory (traces are SQL only), host vitals (load, memory,
event-loop lag), warning counts from the log.

**Found on the way:** `held` is read by Live but missing from `live.py` `INTERACTION_KEYS`, so
that badge never shows; `live.py` calls `agent.snapshot()` on every 10 Hz frame (four SQLite
opens per frame per open tab); `/api/health` calls the daemon over HTTP (2 s timeout), walks
every recording chunk directory and runs per-contact SQL every second. A page meant to stay open
all day must cost almost nothing.

**View.** The owner is right; #61 tuned Live for watching the conversation and dropped the rest.
1. **Live = now, the module page = depth.** Live answers "what is every part of Bobby doing
   right now, and is anything wrong" at a glance, read-only; a module's page keeps history,
   parameters, debugging and CRUD. A value may appear on both — compact and live on Live, with
   history and controls on the page; a card's title jumps to its page.
2. **One card per core module, one contract.** Each session gets `live()`: a small dict of
   in-memory values (no SQL, no HTTP, no directory walk), cheap at 1–2 Hz. `live.py` pushes them
   as `modules` once a second on the existing WebSocket (pose, levels, faces and captions stay at
   10 Hz) and one renderer draws every module card (status dot = readiness merged with runtime,
   three to six lines). `/api/health` stops the expensive calls (daemon state from the status
   monitor, recording totals kept as chunks open and close, counts cached).
3. **What each card shows:**

| Card | Core live values | Source (new = not exposed yet) |
|---|---|---|
| Now (interaction) | state, addressee, language, turns, time left in the session; mic / speaker bars with peak hold; speech open; ducked / held; the last three decisions with reason and scores; attention mode; greetings today / cap | `snapshot()`, `captions()`, the `recent` deque; time left new |
| Turn (interaction + agent) | the turn in progress, else the last: heard text, stages ASR → first token → first audio → done with ms, tool calls as they run (ok / error), step, interrupted / no reply | `last_turn`; the in-flight turn new |
| Body | connected, daemon state, awake / asleep, auto / manual (holder), look target, the expression on each motion layer, breathing / sway, commanded vs measured head error, last antenna touch, camera fps, volume | `status()`, `control_status()`, `telemetry()`; layers new |
| Perception | presence and since when, faces with names and scores, speech direction, mutual gazes today, watcher polls / errors | `snapshot()`; mutual-gaze count new |
| Contact | the current voice identification (name, score, runner-up), face identification, people seen / ready to befriend, members, own voice enrolled | `last_voice` / `last_face`; counts cached |
| Agent | idle / thinking (agent, step, tool), turns today, median first token, tool calls and errors today, background tasks (agent, task, age), parked confirmations, last error | in-flight state, task details new |
| Memory | facts / episodes, conversations waiting for the writer, last write | after block #66 |
| Automation | the running job, the next due job and its countdown, heartbeat next run and last result, quiet hours, runs today | next due / running job new |
| Channel | voice / Telegram / WeChat: state, age of the last message, in / out, last error | adapter attributes; poll alive new |
| Services | per slot: last call (age, ms, ok), median of the last 20, in flight, errors in the last hour; TTS link | in-memory last calls new |
| Record | state, open chunk and its age, ring hours, free disk vs floor, frames, last error | attributes; totals kept incrementally |
| System | readiness verdict, uptime, load, event-loop lag, process memory, warnings / errors in the last 10 min | doctor `report()`; host vitals and a warning ring in `log` new |
| Extension | enabled / installed, each watcher's last tick and errors | registry cached; watcher timestamps new |

4. **Layout** (desktop): top row camera · 3D body · Now; below it two stacks — left the
   dialogue (one screen tall, scrolling inside) above the activity stream, right the Turn card
   and the module cards in a two-column grid. Phone: Now, Turn, dialogue, module cards, camera,
   3D body.
5. **Activity stream instead of Events:** decisions, perception events, turns and tool calls,
   job runs, channel traffic, memory writes and warnings in one list, newest first, module chips
   as the filter — assembled from the modules' own in-memory recents, no new bus.

Open (owner): (a) points 1–2; (b) host vitals with the standard library only (load average,
event-loop lag, process memory, the Pi's temperature; no psutil); (c) the dialogue card capped
at one screen to make room; (d) the activity stream replacing Events.

## [2026-10-29 #66] Discussion: L0 / L1 / L2 memory for Bobby

Proposal after block #65: memory is written from the conversations themselves, when they end,
and loaded in three sizes.

| Level | What | Written | In a turn's prompt |
|---|---|---|---|
| **L0 conversation** | the timeline as today, never rewritten; rows gain a conversation id (voice: the engagement session; text: a run of messages with gaps under 15 min) | every message | this conversation's rows only |
| **L1 episode** | one per closed conversation: title (≤ 40 chars), summary (≤ 300), participants, channel, time, visibility (the strictest of its rows), follow-ups with dates (「爸爸 10-30 睇牙」), source rows | the memory writer when a voice session ends or a text conversation has been quiet 15 min (and every ~10 turns of a long one): one `smart` call, off the turn, traced | the last three episode titles with this speaker; follow-ups due |
| **L2 profile** | per contact and the household: facts by category (who and relations, preferences, routines and dates, health, how they like Bobby to talk), each with subject, teller, channel, visibility, explicit / inferred, sources, valid until; a digest per scope (≤ 400 chars) | `remember` at once (explicit); the writer's candidate facts consolidated against the scope's facts (add / supersede / no-op, never a hard delete); a nightly pass in quiet hours merges duplicates, expires past events, rebuilds the digests that changed and rejects a rewrite that loses more than a quarter of the facts | the speaker's and the household's digests |

- **Per turn, no model and no search:** the block is assembled from SQLite once per
  conversation and frozen for it (about 800–1,000 characters); `recall` searches L2 and L1
  with FTS5 (`trigram`; LIKE for one- or two-character words) and opens an episode's rows (L0)
  when asked. The newest 6,000 characters of every channel go away, so other people's chats
  and old test turns stop acting as examples (block #64).
- **Identity and privacy** (invariant 23, extended): facts only for named participants and the
  household; a conversation with unnamed people yields only an episode that calls them "a
  visitor"; a fact from a private chat stays private to its teller; household facts only from
  what was said openly or explicitly; what someone says about another person stays in the
  teller's scope, attributed; health, money and relationships only from first-person
  statements, never inferred; explicit beats inferred. **Before the writer runs,** Telegram
  and WeChat DMs must be marked `private` — no channel sets it today.
- **Not written from:** job and heartbeat turns, subagent runs (OpenClaw excludes the same),
  and by default the Agent → Test card.
- **Cost:** one `smart` call per conversation (2–4k tokens in, about 300 out) and one digest
  per changed scope each night; turn latency unchanged or lower.
- **Dashboard:** Agent → Memory shows each person's digest and facts by category with their
  sources (fact → episode → rows), the episodes by day and the writer's state; Live gets the
  Memory card (block #67).
- **Rollout:** (1) DMs private, conversation ids, the writer filling L1 and candidate L2 in
  **shadow** — shown on the dashboard, not injected — for about a week of real use; (2) after
  the owner's review: consolidation, digests, the new context view and FTS recall go live;
  (3) later: follow-ups feeding the greeting (「睇牙順唔順利？」), Bobby's own lessons
  (procedural memory, such as "never schedule unasked").

Open (owner): (a) the pyramid numbering — L0 raw → L1 episode → L2 profile — with OpenViking's
abstract / detail inside each level; (b) what family members may hear about each other: a fact
said openly in the room shared within the household, one from a private chat or a sensitive
one private; (c) inferred facts go live after the shadow week, marked and deletable, rather
than through a review queue; (d) the context view becomes "this conversation + memory";
(e) test turns stay out of memory.

## [2026-10-29 #65] Research: how agent memory frameworks form, tier and load memory

Owner (2026-10-29): "Memory is not only remembered when the user asks; it should be summarised
and induced from the chat history. We should design L0 / L1 / L2 levels of memory — look at
the memory framework designs first, then discuss."

**Where Bobby is** (`agent/memory.py`, `agent/dialogue.py`): one write path — the model calls
`remember` when it decides to (MiniMax-M3 skipped it in 6 of 7 turns before block #64); the
prompt gets the 12 newest facts of the speaker and the household, unranked, plus the newest
6,000 characters of every visible timeline row across all channels; the `episode` kind exists
in `memory_v1.db` but nothing writes it; no channel marks a row `private`, so a Telegram DM
would be visible in everyone's view. Volume so far: 191 rows in four days, at most seven
conversations a day.

**What "L0 / L1 / L2" means** — two usages, both read at the source:
- *Detail levels of one item* — OpenViking (Volcengine): L0 abstract (`.abstract.md`, 256
  characters by default, for vector recall and quick filtering), L1 overview (`.overview.md`,
  4,000 characters, for reranking and navigation), L2 the original content loaded on demand;
  generated bottom-up per directory. https://docs.openviking.ai/en/concepts/03-context-layers
- *An abstraction pyramid* — TencentDB-Agent-Memory: L0 Conversation (raw) → L1 Atom
  (structured facts, every 5 turns or after 600 s idle) → L2 Scenario (blocks over related
  atoms) → L3 Persona (every 50 new memories, `persona.md`); lower layers in SQLite +
  sqlite-vec, upper layers in Markdown; recall before every turn (hybrid, up to five items,
  skipped past 5 s). https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/main/README_CN.md
  — OpenBMB ClawXMemory and the MemOS plugin use the same ladder (secondary reading).

The owner's "summarise and induce from the chat history" is the pyramid; OpenViking's levels
are orthogonal and can apply inside each tier.

**Frameworks** (primary sources read 2026-10-29; vendor numbers are vendor numbers):
- *OpenViking* — `commit()` archives a session; in the background a summary, then an
  ExtractLoop reads related memories and proposes additions / edits / deletions that a
  MemoryUpdater validates and logs (`memory_diff.json`); types profile, preferences, entities,
  events, identity, soul, cases, trajectories, experiences.
  https://docs.openviking.ai/en/concepts/08-session
- *OpenClaw* — `MEMORY.md` + `USER.md` (curated, loaded at session start within a budget,
  written only by consolidation or a direct request), daily notes `memory/YYYY-MM-DD.md`
  (appended during work, never auto-injected), a silent pre-compaction flush turn, and
  "dreaming": a scheduled three-phase sweep (light, REM, deep) whose deep phase promotes
  candidates through scored gates and one bounded model turn that merges duplicates, retires
  superseded entries and keeps source anchors; pre-images are kept and a rejected rewrite falls
  back to append-only. Per-turn recall uses no model — at most three entries scoring ≥ 0.65,
  only from the curated files; a recall sub-agent runs only when a message asks about the past.
  Provenance owner / agent / untrusted / system: non-owner group members are untrusted and
  never reach the curated core; cron, heartbeat and sub-agent sessions produce no memory.
  https://docs.openclaw.ai/concepts/memory-architecture
- *Mem0* — per message pair an LLM extracts facts and compares each with its nearest memories
  for ADD / UPDATE / DELETE / NOOP (arXiv 2504.19413); its 2026 blog moves to ADD-only, old and
  new facts coexisting with timestamps, because updates and deletes destroyed context.
- *Letta / MemGPT* — pinned, size-limited memory blocks in every prompt; history and archival
  storage behind tools; sleep-time agents on a stronger model rewrite the blocks in the
  background, so the fast agent never edits memory itself.
- *Zep / Graphiti* — episodes (raw) → entities and dated fact edges → communities; a
  contradicting fact invalidates the old edge instead of deleting it (needs a graph database).
- *Generative Agents* — one memory stream ranked by recency + importance + relevance;
  reflections (insights citing their sources) once recent importance adds up.
- *MemoryOS* — short-term pages → mid-term topic segments → long-term profile, promoted by
  heat; about five LLM calls per response.
- *LangMem* — semantic / episodic / procedural memory; hot path (tools in the turn, adds
  latency) or background reflection debounced after the conversation.
- *Hermes Agent* — `MEMORY.md` (2,200 chars) + `USER.md` (1,375 chars) injected as a frozen
  snapshot per session; an over-limit write fails and the agent must consolidate; transcripts
  searched with SQLite FTS5, no model.
- *ChatGPT*, *Claude.ai* — memory written as you chat plus past-chat reference; Claude keeps
  memory per project and leaves sensitive topics out by default; internals unpublished.

**Lessons for Bobby**
1. Per-turn memory small, stable and model-free: a block built from SQLite once per
   conversation (Hermes' frozen snapshot, OpenClaw's three entries); recall with a model in
   the loop is far too slow for voice.
2. Write at natural boundaries, off the turn: session end (OpenViking), idle or every N turns
   (TencentDB), debounced (LangMem), nightly on a stronger model (OpenClaw, Letta).
3. Consolidation must not destroy evidence: keep the raw tier, cite sources, supersede with a
   time instead of deleting (Mem0 since April 2026, Graphiti, OpenClaw's pre-images and
   append-only fallback).
4. Provenance per fact — about whom, told by whom, through which channel, how visible — and
   never fold a private chat into the household or another person's scope.
5. Households are rare in these systems (most key on one user id): "about whom" and "told by
   whom" are ours to design.
6. Search raw and extracted together; SQLite FTS5 is the common local store (the `trigram`
   tokenizer for Chinese).
7. The public benchmarks (LoCoMo, LongMemEval) are single-user chat logs: judge Bobby on its
   own household timeline.

## [2026-10-29 #64] Progress: memory follows identity (block #63)

- [x] **Memory** (`agent/memory.py`, `agent/tools.py`): `MemoryStore.remember` raises on an
  unnamed scope (invariant 23); the `remember` tool resolves the speaker at call time (a person
  befriended earlier in the turn is their contact) and answers an unnamed speaker with "not
  stored … ask their name and befriend them"; `forget` deletes the speaker's own matching facts,
  else the household's; `move_scope` / `drop_scope`. The first hint also offered "scope
  household", and the model filed a stranger's peanut allergy as 「屋企有人對花生敏感」: the hint
  now points to befriending only.
- [x] **Owner**: `ContactSession.resolve_speaker("owner")` is the owner contact once one exists;
  `AgentSession.resolve_message` moves facts kept under `owner` to it on that contact's turns.
- [x] **Contacts**: `create` takes a free id (`阿明_2`; `self` / `owner` reserved), so promotion
  never overwrites a profile; `resolve_speaker` also maps a person befriended in this run.
  Dashboard: `PUT /api/contacts/{id}` edits in place (the page used to delete and re-create a
  contact, losing its prints), `DELETE` also drops the contact's facts, a hand-added fact for an
  unnamed scope is a 400.
- [x] **`enroll_voice`** (robot extension): an unnamed speaker is befriended through the same
  helper as `befriend`; a named speaker learns into their own contact only under their own name;
  `start_enrollment` answers False without an open session. **Interaction**: enrollment is bound
  to its session and `ENROLL_WINDOW_S` = 90 s, an unrecognised voice in that session is the person
  being learned (no new `person:n`), another known voice is skipped.
- [x] **Found while verifying — past tool calls were invisible.** The turn records tool results
  (`tool_call_id`, tool, arguments) but not the call step, and the context view kept a result
  only when an assistant row declared its call, so every past reply looked tool-free. Live, the
  fast model (MiniMax-M3) answered 「記低咗」 without calling `remember` in 6 of 7 test turns, the
  owner's included. `context_view` now rebuilds the call step from the tool rows (results cut to
  400 characters, `HISTORY_TOOL_CHARS`); after the fix and with the test rows removed, 3 of 3
  turns called `remember` (one also scheduled an unasked Sunday reminder, deleted). A model that
  still skips a tool is not guarded in code (open question below).
- [x] **Data** (owner: "all me"): contacts 花瘟雞 / 發返雞, people `person:6` / `person:9` and the two
  name facts deleted through the API; memory is 「屋企人鍾意飲奶茶」 (household) and 「主人鍾意飲奶茶」
  (`owner`); readiness now says nobody is enrolled. The 27 timeline rows of the verification
  turns (dashboard channel, 12:46–12:55) were deleted with the facts and the job they made, so
  they do not teach the next turns; backups of `contact_v1.db`, `memory_v1.db` and
  `dialogue_v1.db` from before are in the session scratchpad. The other 14 people seen sound
  different (cosine ≤ 0.42 to the four) and expire on their own.
- [x] Tests: unnamed scopes, scoped forget, move / drop (`test_agent_stores`), rebuilt tool steps
  (`test_agent_stores`), the memory tools and the owner's scope (`test_agent_session`), free ids
  and resolution, `enroll_voice`, the enrollment window, contact edit / delete routes
  (`test_befriending`), the 400 (`test_dashboard_api`): 190 passed, 6 skipped; ruff, mypy clean.
  Docs: AGENTS invariant 23, yellow pages (contact, agent, robot, dashboard), "Dialogue and
  memory", "Contact and identification"; headers of memory, tools, agent, dialogue, contact,
  store, interaction, robot tools; the befriending skill; README / README_CN befriending sketch.
- **Open (owner):** guard against a reply that claims a result without the tool — e.g. when the
  utterance asks to remember and the turn called no memory tool, re-prompt once (about 2–3 s more
  on those turns only) — or leave it to the prompt and the restored history.

## [2026-10-29 #63] Decision + Todo: memory follows identity — what went wrong with 花瘟雞 / 發返雞

Owner question: a data problem or a logic problem? Logic; the data is what it left behind.
Traced through the timeline, `memory_v1.db`, `contact_v1.db` and the engagement trace:

- **花瘟雞 (10-27 09:51).** `person:7` said 「你记住好啦我叫花瘟鸡」; the main agent called
  `remember` (stored under `person:7`) and 3 s later `befriend` (contact 花瘟雞, centroids
  moved, `person:7` deleted). `remember` never enforced block #35 ("unpromoted people hold
  vectors only, never memory facts") and promotion moves vectors, not facts, so the fact sits
  under an id that no longer exists (the person counter never reuses a number: no stranger
  inherits it).
- **發返雞 (10-28 01:06).** `person:9` said 「你记住啦我叫发返鸡」; the agent called
  `enroll_voice` and `remember` instead of `befriend`. `enroll_voice` created a second contact
  by name and left `person:9` (8 utterances, ready) in place; its "learn the next 3 utterances"
  was bound to no session, no speaker and no deadline, so it stayed armed for 9 hours and
  learned two wake-name utterances the next morning (10:18 `person:6`, 10:19 花瘟雞). The
  發返雞 print is those two voices: cosine 0.83 to `person:6`, 0.70 to 花瘟雞, 0.59 to
  `person:9` (threshold 0.5).
- **Latent, same family.** `ContactSession.create` ids a contact by its slug and upserts, so a
  stranger befriended under an existing name overwrites that profile (owner flag, remote ids)
  and merges the voices; `enroll_voice` looked contacts up by name, so 「我叫爸爸，記住我」 from a
  stranger fed 爸爸's print; `forget` fell back to deleting matching facts in every scope; the
  dashboard edits a contact by deleting and re-creating it (prints gone, facts orphaned when
  the name changes); a deleted contact's facts wait for the next contact with the same name;
  the dashboard's `owner` is a scope of its own that no voice turn resolves to (no owner
  contact is enrolled).
- **Owner (2026-10-29):** 花瘟雞, 發返雞, `person:6` and `person:9` were all the owner testing.

Decision: personal memory belongs to a contact (or `household`); identities never merge by name.

- [x] `MemoryStore.remember` refuses an unnamed scope (`person:N`, `guest:N`), the one place
  block #35 is enforced; the `remember` tool answers with a hint to befriend first (household
  facts still allowed) and resolves a speaker befriended earlier in the same turn.
- [x] `forget` deletes the speaker's own matching facts, else the household's; never another
  person's.
- [x] `owner` (dashboard turns, jobs made there) resolves to the owner contact once one exists;
  facts kept under `owner` move to it on that contact's first turn.
- [x] Deleting a contact deletes their facts; the dashboard edits a contact in place
  (`PUT /api/contacts/{id}`: id, prints, facts and created time kept).
- [x] `ContactSession.create` never overwrites: a taken id (or the reserved `self` / `owner`)
  gets a suffix (`阿明_2`); promotion goes through it.
- [x] `enroll_voice`: an unnamed speaker is befriended (as `befriend`, collected samples kept);
  a named speaker learns into their own contact, only when the name matches; never a lookup by
  name into someone else's print.
- [x] Voice enrollment learns only inside the session it started in, for at most 90 s; an
  unknown voice in that session is the person being enrolled (no new `person:N`).
- [x] Data (owner: "all me"): delete contacts 花瘟雞 / 發返雞, people `person:6` / `person:9` and
  the two name facts; 「主人鍾意飲奶茶」 stays under `owner` until the owner enrolls.
- [x] Tests; AGENTS (yellow pages agent / contact / interaction / dashboard, the robot
  extension row, "Dialogue and memory", "Contact and identification"); headers; the
  befriending skill.
- Dropped from block #62's proposal: moving facts on promotion; once unnamed scopes hold no
  facts there is nothing to move.

## [2026-10-29 #62] Progress: views on Voice / System / Channel; the whole conversation on Live; a test card on Agent (#61)

- [x] **Voice** = Decisions · Hear · Speak · Traces. The mic / speaker meters and the engagement
  state share one card (the duplicate 1 Hz microphone meter is gone; "playback ducked" joined the
  state line); the decisions table shows 25 rows with *show more* (120) and refreshes only while
  its view is open; Hear stacks the ASR / VAD / KWS slots and the thresholds beside wake name,
  triggers & turns and words & the TV (1,395 px); Speak puts the two TTS slots side by side
  above the language card; Traces holds the ASR and TTS traces, 12 rows each with *show more*.
- [x] **System** = Readiness (status, the full table) · Logs (the log fills its view) · Config
  (dashboard settings and backup side by side, the masked config). **Channel** = Channels
  (Telegram, WeChat, presence) · Events.
- [x] **Live**: the dialogue card reads the timeline (`DialogueStore.recent(…, conversation=True,
  before=…)`, `GET /api/agent/timeline?conversation=true&before=`): the newest 60 rows of every
  channel, earlier pages when scrolled to the top (checked: 60 → 120 → all 139, then "對話由呢度
  開始"), new rows every 2 s and at each turn's start and end while Live is open, day separators,
  Bobby's own deliveries marked 主動, cues (`express`, `style`) as notes, the live line below; a
  reader who scrolled up stays there and gets a *latest* button. No composer.
- [x] **Agent → Test**: a turn typed as the owner or a contact; `POST /api/agent/chat` now also
  returns `ms`, `first_ms` and the turn's tool calls (agent, name, arguments, result), shown as
  chips that open the details window. One real turn checked: 24.6 s, first words 9.8 s, six tool
  calls (`time_now`, `news_latest`, `delegate` and the news subagent's three).
- [x] Tests: paging and the conversation filter (`test_agent_stores`), the timeline parameters
  and the chat response's new fields (`test_dashboard_api`). Docs: AGENTS dashboard row and
  "Dashboard and CLI", README / README_CN page lists, the dialogue header.
- **Found while looking at Memory (not fixed, owner's call):** `remember` writes to the
  speaker's scope even when the speaker is an unnamed `person:N` — two names sit under `person:7`
  and `person:9`, although block #35 says unnamed people hold only voice / face vectors. Those
  two have since been befriended (contacts 花瘟雞, 發返雞), and the facts did not follow them; a
  person pruned after 7 days unseen would leave such facts behind for good.

## [2026-10-29 #61] Decision + Todo: views on Voice / System / Channel; Live shows the whole conversation; a test card on Agent

- **Owner:** go ahead with the views on the other long pages (blocks #59–#60).
- **Owner:** the conversation card on Live must show the complete, real-time conversation —
  history is missing today (the card kept only what the open page had seen, 40 lines at most) —
  and it is only for watching: no input box. Testing the agent belongs on the Agent page, as a
  test card.
- **Todo — views** (one board or two column stacks, no sub-headings):
  - [x] Voice: Decisions (meters and engagement state in one card, the decisions table) · Hear
    (ASR / VAD / keyword-spotter slots, thresholds | wake name, triggers & turns, words & the
    TV) · Speak (TTS slots | language) · Traces (ASR, TTS).
  - [x] System: Readiness (status, the full table) · Logs · Config (dashboard settings, backup,
    the masked config).
  - [x] Channel: Channels (Telegram, WeChat, presence) · Events.
- **Todo — Live**
  - [x] The conversation card reads the dialogue timeline (invariant 12): every channel's user
    and assistant rows — voice, Telegram, WeChat, the test card, messages Bobby delivered on its
    own initiative —, oldest at the top, older rows loaded when scrolled to the top, new rows
    while it is open; the live line (listening / thinking / the sentence being spoken) stays at
    the bottom; a reader who scrolled up is not pulled down.
  - [x] No composer on Live.
- **Todo — Agent**
  - [x] A Test view: type as a chosen speaker, see the reply, `NO_REPLY` or the error, the tools
    the turn called (details on click) and how long it took. Turns are real (timeline, memory,
    tools), as the Live composer's were.
- [x] Docs, tests, live restart, screenshots.

## [2026-10-29 #60] Progress: the Agent page in views (block #59)

- **Owner, during the pilot:** the Swarm view still had two column headings ("activity",
  "settings") — split it into two tabs; a tab has no sub-headings. Taken into the rule: a view
  has no sub-headings.
- [x] **Views** (`dashboard_index.html`, `dashboard_app.js`): a bar at the top of the page
  (sticky on desktop, scrolling sideways on phones) and one block per view; the route is
  `tab/view` (`#agent/tools`), the old links alias to views (`#tools`, `#mcp`, `#skills`,
  `#memory`, `#timeline`, `#traces`), a page keeps its last view for the session, and the bar
  carries the counts (Tools 30 · MCP 0 · Skills 5 · Memory 4).
- [x] **Agent = Swarm · Tools · MCP · Skills · Memory · Timeline · Settings.** Swarm: one row
  per agent (what it does, LLM slot, tools — and how many are main-only —, turns), background
  tasks, last error, then the latest 8 LLM calls (text clamped to two lines, *show more* → 40).
  Tools: one grid sorted by origin with the origin chips as the filter (their counts follow the
  search) and the origin in each card's corner, instead of a part-filled row per group. MCP /
  Skills: the add button in the board's head instead of an add card; an empty board says what
  belongs there. Memory and Timeline: full-width cards. Settings: the main-agent knobs beside
  the LLM fast / smart service cards.
- [x] `AgentSession.snapshot()` reports each agent's `description` (the Swarm table's "does");
  the dashboard API test asserts it.
- **Measured (1440 × 900):** one 8,709 px page became views that fit one screen (Swarm,
  MCP, Skills, Memory, Settings), Tools at 1,023 px with 30 tools, Timeline as long as its 80
  rows; no view leaves a hole between cards.
- [x] Docs: AGENTS dashboard row and "Dashboard and CLI" (the views rule; boards are ordered by
  design, never hidden or dragged by hand), README / README_CN page lists (also the missing
  Automation entry; "no global Settings page"), the page's header comments (the stale
  monitor-rail wording replaced).
- **Verification:** 183 passed, 6 skipped; ruff, format and mypy clean; live restart (`run49`);
  in headless Chrome: deep links and aliases, the remembered view, an origin chip, the details
  windows, *show more*; phone width 390 px (wide tables scroll inside their card).
- **Next, the owner's call:** the same rule for the other long pages — Voice (6,213 px; its
  聽 / 講 column headings break the no-sub-heading rule, e.g. Hear · Speak · Decisions ·
  Traces), System (Readiness · Logs · Config · Backup), Channel (the long events table). Body
  stays one page.

## [2026-10-29 #59] Discussion: board layout — holes and findability

- **Owner:** the Agent page has a hole here and a hole there — adjust its layout, or give every
  page board management (choose what shows, drag boards around)? The owner doubts that the
  second fixes the ugly layout, or that it helps find things on a page that keeps gaining
  boards.
- **Measured (1440 px wide):** page heights Agent 8,709 px (about ten screens), Voice 6,213,
  Channel 2,766, System 2,559, Body 2,481, Contact 1,815, Record 1,700, Extension 965,
  Automation 904. On Agent: the Swarm + Main agent stack (~520 px) stands beside the LLM fast /
  smart stack (~330 px), leaving ~190 px empty; MCP servers (no server, one add card) beside
  Skills (three rows) leaves ~280 px empty; three of the four origin groups on the Tools board
  end in a part-filled row; memory starts ~2,200 px down, the timeline ~2,700 px.
- **Causes.** (1) Rows that pair two unrelated cards whose heights depend on the data (no MCP
  server vs five skills): the hole moves whenever the data changes, so no hand placement fixes
  it. Body and Voice are built as two independent column stacks and have no hole in the
  middle. (2) No hierarchy: every board has the same weight and is fully open, settings that
  are rarely touched fill the first screen, and long tables (80 timeline rows, 20 trace rows)
  make the page long.
- **On show / hide and dragging: not recommended.** Dragging changes which cards are
  neighbours, not the mechanism that makes the holes; the first look is the default layout
  anyway (and a layout kept in one browser is not the one on the phone); a hidden board is
  harder to find, not easier; and it costs a drag-and-drop layer, saved layouts, a reset and a
  phone variant in a page without a build step, for a console one household uses. If a board
  still feels like noise after the change below, folding it to its header (remembered per
  browser) is the cheap form of "hide".
- **Recommendation — three rules for every page.**
  1. *Layout:* a view is one full-width board or two independent column stacks, never a row
     of two unrelated cards; item boards flow without gaps (a filter instead of group rows).
  2. *Order:* what is watched and used most comes first, rarely touched settings last; a long
     list inside a mixed view is capped, and its full form lives where it is the main content.
  3. *Views:* a page that outgrows about two screens splits into views, one per submodule (the
     left list stays one entry per core module), switched by a bar at the top of the page
     that carries the key numbers (Tools 30 · MCP 0 · Skills 5 · Memory 4); deep links like
     `#agent/tools`. A short page stays one view.
- **Pilot: the Agent page** (the page the owner asked about): Swarm (the main agent's state and
  settings, the subagents, the LLM slots and their latest calls) · Tools · MCP · Skills ·
  Memory · Timeline. Other pages change only after the owner has seen it; Voice and System are
  the next candidates; Body stays one view because its parameters are tuned while watching the
  3D body and the camera.
- **Pending:** the owner's verdict on the pilot and the rollout.

## [2026-10-29 #58] Progress: composition rule, `automation` module, tool / MCP / skill boards (#57)

- [x] **Composition (invariant 21).** `app.py` constructs every session in `boot()` and only
  calls `setup` / `start` / `stop`; `tests/test_architecture.py::test_app_only_composes` parses
  it (no control flow, closures, foreign attribute writes or non-lifecycle calls — checked by
  injecting a subscription, a lambda and an attribute write). The nine wirings moved:
  `BodySession.start()/stop()` (daemon when managed, connection), `PerceptionSession.setup`
  (camera / audio watchers only when enabled and connected), `ContactSession.start()/stop()`
  (Bobby's own voice from `TTSSession.synthesize`, daily pruning of unnamed people),
  `ChannelSession.setup` (Telegram / WeChat adapters; pairing persisted by
  `ConfigSession.telegram_paired`), `InteractionSession.setup` (registers `voice`, takes
  `RecordSession.mic_reader()`), `InteractionSession.start()` (needs body + VAD),
  `can_speak()` / `speak()` (the agent's voice hooks, given to `AgentSession.setup`),
  `ExtensionSession.setup` (builds each context; vision from `ConfigSession.slot_supports`),
  `DoctorSession.start()` (the readiness lines), and `TraceTable(retention_days)` prunes the
  service traces as they write (hourly at most, 10 days). `start_all` / `stop_all` of the
  channel registry are now `start` / `stop`.
- [x] **`automation` module (layer 4).** `jobs.py`, `scheduler.py`, `heartbeat.py`, `tools.py`,
  `schemas.py` (a `Job` without an agent: the column is written `main`), `automation.py`;
  `setup(db, config, agent, perception)` registers the main-only tools and subscribes
  `on_event`; `apply()` makes `automation.enabled` the real switch. The agent lost the store,
  the scheduler, `on_event`, `run_job` and the job tools, and gained `run_job_turn()` and
  `delivered_since()`; `Tool.main_only` replaces the name check on `delegate`; background
  delegation ids are `task-…`. The extension loader puts manifest automations into
  `automation` and rebuilds tools with `dataclasses.replace` (flags kept). Dashboard:
  `/api/automation`, `/api/automation/jobs…` (the `/api/agent/jobs` routes are gone), the
  config route is async so the switch starts and stops the scheduler.
- [x] **Boards.** Agent page: Tools (grouped by origin), MCP servers and Skills as card grids
  with tags; one `<dialog>` details window (a tool's parameters and who may call it; an MCP
  server's target, error, secret names — never values — and tools, *Remove*; a skill's Markdown
  editor, *Save* / *Delete*; add cards); `GET /api/agent/tools`. New Automation page (status,
  scheduler, initiative, jobs) with its sidebar entry and dot; deep links `#automations`,
  `#jobs`, `#tools`, `#mcp` resolve.
- **Behaviour changes, deliberate:** `automation.enabled` now stops what it says (block #55
  correction); a failed in-person `say` (body asleep) is no longer recorded as spoken; trace
  pruning runs at write time instead of at start and daily.
- **Verification:** 183 passed (6 skipped), ruff and `mypy --strict src` (117 files) clean. Live
  (`sidekick run` restarted twice): start-up order and log unchanged, readiness `ready · 1
  advisory`; the heartbeat kept its id and runs; `/api/agent/tools` 30 tools, the four
  `main_only` ones for `main` only; the switch toggled off (scheduler stopped, tools withdrawn,
  heartbeat paused) and on again through `POST /api/config/automation`, config back to `true`.
  Screenshots: `shots28/agent-boards.png`, `tool-schedule.png`, `skill-storytelling.png`,
  `automation.png`.

## [2026-10-29 #57] Decision + Todo: composition rule, `automation` module, tool / MCP / skill boards

- **Owner:** go ahead with blocks #55 and #56, and add management boards for tools, MCP servers
  and skills to the dashboard: every item its own card with a summary, a click opening a details
  window when the card cannot show everything.
- **Todo — composition rule (block #56), behaviour unchanged**
  - [x] `app.py` only constructs sessions and calls `setup` / `start` / `stop` in dependency order;
    the nine wirings it does itself move into the modules that need them.
  - [x] New invariant, enforced in `tests/test_architecture.py` by parsing `app.py`.
- **Todo — `automation` module (block #55, wired by its own `setup`)**
  - [x] `src/sidekick/automation/`: jobs + cron, scheduler + quiet hours, event jobs, the
    heartbeat, `tools.py` (`schedule` / `jobs_list` / `job_cancel`, main-only); `setup(…, agent,
    perception)` registers its tools and subscribes its `on_event`; `automation.enabled` is the
    real switch (scheduler, events, heartbeat, tools).
  - [x] `agent` keeps the runtime: a public "run one main-agent turn and deliver it" and "what was
    delivered unprompted since"; `Tool.main_only` (also `delegate`); background delegation ids
    `task-…`; no jobs, no scheduler, no `on_event`.
  - [x] Extension loader routes manifest automations to `automation`; the dashboard gets an
    Automation entry (jobs, scheduler) out of Agent.
  - [x] New invariant: only the main agent creates, cancels and runs jobs.
- **Todo — dashboard boards**
  - [x] Tools, MCP servers and skills on the Agent page as card grids (name, origin, a clamped
    summary, flags), a details window per card (tool parameters; MCP transport, state and tools;
    skill body), the existing management actions kept.
- [x] Docs (AGENTS layers, allowed imports, yellow pages, invariants; README / README_CN), tests,
  ruff, mypy, live restart, screenshots.

## [2026-10-29 #56] Discussion: one composition rule for every module

- **Owner:** no special cases — every module follows the same rule: either all assembly happens
  in `app.py`, or each module's `setup` assembles itself and `app.py` only calls it.
- **Audit of `app.py` today: both styles are mixed.** Modules that receive peers in `setup` and
  hook themselves in: `extension` (registers tools, skills, MCP, subagents, automations and
  watchers, also while running), `interaction` (uses body, ASR, TTS, VAD, contacts,
  perception, the agent as `Responder`), `record`, `doctor`, `dashboard`. Wiring `app.py` does
  itself: (1) `perception.subscribe("*", agent.on_event)`; (2) `_register_remote_channels`
  builds the Telegram / WeChat adapters; (3) `channels.register(interaction.voice)`;
  (4) `agent.say = …` after interaction exists; (5) the `body_can_speak` rule as a lambda over
  body and perception; (6) `interaction.clip_source = record.read_mic` and
  `trace.clip_files = False`; (7) `_enroll_self` (TTS clips into contacts); (8) `_maintain`
  (daily trace and people pruning); (9) `context_factory` and the `smart_vision` lookup.
- **Recommendation: the second rule.** Each module's `setup(config, peers…)` does everything it
  hooks into a peer (registers tools, subscribes to events, registers an adapter, starts its
  own housekeeping) and its `stop` (or an extension's disable) undoes it; `app.py` only
  constructs the sessions, calls `setup` in dependency order and `start` / `stop`. The first
  rule cannot hold for every module: the extension loader must register and withdraw
  contributions while sidekick runs (enable, disable, install, remove), so it would either be an
  exception or `app.py` would have to host the extension lifecycle. The second rule is the
  existing convention ("`setup(...)` receives its backends or peers; only `app.py` calls
  `setup`") made complete. Mutual references (agent ↔ interaction, record ↔ interaction) are
  resolved by constructing every session first and setting them up second: a peer's bound
  method can be handed over before that peer is set up.
- **Consequences:** `AutomationSession.setup(db, config, agent=…, perception=…)` registers its
  main-only tools and subscribes its `on_event` itself, and withdraws its tools when
  `automation.enabled` goes off (the owner's seventh-round shape, now the general rule); the
  nine wirings above move into the module that needs them, behaviour unchanged; a new invariant
  states the rule, enforced in `tests/test_architecture.py` by parsing `app.py` (only session
  construction and `setup` / `start` / `stop` calls).
- **Order:** this composition clean-up first, then the automation split (block #55) on it.
- **Pending:** owner decision.

## [2026-10-29 #55] Discussion: automation as its own core module, below `agent`

- **Owner:** the agent module should not be coupled with automation; the heartbeat should become
  a module of its own ("OpenClaw has cron, I think").
- **OpenClaw:** cron is the Gateway's scheduler (jobs persisted on disk; a main-session job
  queues a system event for the next heartbeat turn, an isolated job runs its own agent turn in
  a fresh session); the heartbeat is the periodic main-session turn and defers while cron work
  runs. Both are Gateway automation that calls the agent; neither is part of the agent runtime.
- **Proposal:** a core module `automation` at layer 2 (beside `channel` / `perception`) that
  imports only `log` and `storage`, never `agent`: `JobStore` and the cron matcher, the
  scheduler and quiet hours, event-job matching (`on_event`, subscribed by `app.py`), the
  prompt framing of a due job or a fired event, and the heartbeat (`heartbeat.py`, one built-in
  job — one module, not two). `app.py` injects two agent callables, as `channel` gets
  `agent.handle`: run one internal turn and deliver it by policy; what was delivered unprompted
  since a time (the heartbeat's prompt). The agent keeps the delivery policy (it writes the
  timeline, async results use it too) and neither imports nor knows jobs. `schedule` /
  `jobs_list` / `job_cancel` become a bundled extension's tools (invariant 19); manifest
  automations register with `automation`; the dashboard gets an Automation entry (jobs,
  scheduler); allowed imports: a new `automation` row, `extension` and `extensions/*` may import
  it. `automation_v1.db` and its rows stay as they are; behaviour unchanged.
- **Follow-up (owner): does `automation` implement the agent's tool protocol, registered in
  `app.py`?** No: `Tool` / `ToolResult` / `ToolContext` live in `agent`, which `automation` may
  not import, and `app.py` registers no tools (invariant 19). `automation` offers a plain API
  (add / list / cancel jobs, parse times) and knows nothing of LLMs; a bundled extension wraps
  it into `schedule` / `jobs_list` / `job_cancel`, as `robot` wraps body and perception;
  `app.py` only builds `automation`, injects the runner and loads extensions.
- **Follow-up (owner): subagents lose automation — does "subagents need none" hold?** Today
  not every agent has it: the scheduler is one per `AgentSession`; every job runs on the main
  agent (`run_job` → `run_main`; `Job.agent` is stored, never routed on); the job tools reach
  whoever's allowlist has them — main (`*`) yes, the bundled `news` / `media` / `home` no,
  config subagents (default `*`) yes, though the household has none. The assumption holds as a
  default, not as structure: a job is a promise to a person (owner, channel, confirmation come
  from the conversation only the main agent is in), its result is spoken in Bobby's voice and
  language (heavy work is delegated), and self-scheduling subagents on `smart` would multiply
  turns; a subagent that wants a follow-up says so in its result. Exceptions need no new
  structure (`Job.agent` for the runner, an explicit allowlist entry for the tools). With the
  split, the scheduling tools go to the main agent only unless a subagent names them
  explicitly (`*` does not count). Async delegation stays in `agent`: it is delegation, not
  scheduling.
- **Owner, third round:** `app.py` should assemble the agent's tools (register objects that
  implement the tool protocol); where else would the scheduling tools live? Subagents are
  experts for one domain and have no business with automation: creating and running jobs
  belongs to the main agent only. What is background delegation? Does OpenClaw have subagents,
  and do they have automation?
- **OpenClaw (official docs):** sub-agents are "background agent runs spawned from an existing
  agent run" (`sessions_spawn`), each in its own session, announcing the result back to the
  requester, who reviews it; they "always lose `gateway`, `agents_list`, `session_status`,
  `progress_card`, `cron`, `sessions_send`, and the `conversations_*` tools regardless of depth
  or role" — "tools the main agent should coordinate"; hidden helpers also lose `message`.
- **Revised proposal (supersedes the layer-2 placement above):** `automation` sits **above**
  `agent` (layer 4, beside `extension`) and imports it: it implements its own tools
  (`automation/tools.py`: `schedule`, `jobs_list`, `job_cancel` as agent `Tool`s) and calls the
  main agent directly (one internal turn + delivery; what was delivered since a time for the
  heartbeat), so no runner injection and no bridge extension. `agent` never imports it and
  reaches it only through the tool protocol. `app.py` adds `automation.tools()` to the agent;
  invariant 19 becomes "tools reach the agent through two doors: the extension loader, and
  `app.py` for the modules above the agent; modules below the agent never define tools".
- **Agreed with the owner's conclusion, made a rule (new invariant):** only the main agent
  creates, cancels and runs automation jobs — scheduling tools are main-only like `delegate`
  (a `main_only` flag enforced in `tools_for`, no allowlist override) and every job runs a
  main-agent turn (`Job.agent` goes). A job's turn may still delegate the heavy part to an
  expert. Background delegation (`delegate` with `mode=async`) stays in `agent`: an in-memory
  task started by a conversation whose result a follow-up main turn relays — OpenClaw's
  sub-agent run; it is renamed from `job-…` to `task-…` so it no longer sounds like a job.
- **Owner, fourth round:** not above — `automation` and `agent` are peers that never import each
  other, `app.py` assembles them, and the scheduling tools belong inside `automation`.
- **Agreed; this supersedes both placements above.** The only obstacle is that the tool
  protocol (`Tool`, `ToolResult`, `ToolContext`, the handler type) lives in `agent`. It moves to
  `llm`, which already owns the other half of tool calling (`LLMToolSpec`, `LLMToolCall`):
  `LLMTool`, `LLMToolResult`, `LLMToolContext`. The context drops its hard `ChannelMessage`
  field for the plain fields tools read (checked: extension tools read only the speaker; the
  agent's own read speaker, channel, message id and the confirmation; `delegate` keeps the
  inbound message as an opaque field). Then `automation/tools.py` builds `schedule` /
  `jobs_list` / `job_cancel` on it (main-only), the agent's registry and loop consume them, and
  `app.py` registers them. The other direction is injected like `channel` gets `agent.handle`:
  `app.py` hands `automation` the agent's "run one main-agent turn and deliver it" and "what was
  delivered unprompted since" functions, with plain-typed signatures. `automation` imports
  `log`, `storage`, `llm`; `extension` may import it. Invariant 19 becomes: besides the agent's
  own tools, tools reach it through two doors — `app.py` for a core module's own `tools.py`, the
  extension loader for an extension's; `body` / `perception` / `interaction` still reach it
  through the `robot` extension (they must not be driven directly, principle 7).
- **Owner, fifth round:** certainly not `llm` — the tool protocol belongs in a module that
  gathers tools, MCP and skills.
- **Agreed** (`llm` is the provider layer: model calls and their traces, not how a tool runs).
  New core module **`toolkit`**, layer 2, importing `log`, `storage`, `llm` (`LLMToolSpec`),
  `channel` (`ChannelMessage` in the context) and the `mcp` SDK. The boundary: the toolkit says
  what the agent *has*, the agent decides how and when it is *used*.
  - `toolkit`: the tool protocol (`Tool`, `ToolResult`, `ToolContext`, the `main_only` flag),
    `ToolRegistry` (allowlists, main-only filtering), MCP (registry, client pool, `mcp_*` tools,
    refresh), skills (store, `skill_*` tools, the descriptions block), `time_now`.
  - `agent` keeps the runtime and its state: profiles and the swarm, the ReAct loop, the
    confirmation gate (invariant 13 is about running a call inside a conversation), timeline,
    memory (its tools registered by the agent), `delegate` (sync / background), delivery.
  - `automation` builds its tools on the toolkit's protocol; `agent` and `automation` both
    import `toolkit` and never each other; `app.py` registers `automation.tools()` and hands
    `automation` the agent's two functions.
  - The extension loader becomes a router: tools / skills / MCP → `toolkit`, the subagent →
    `agent`, automations → `automation`, watchers → `perception`.
  - `skills_v1.db`, `mcp_v1.db`, `automation_v1.db` keep their names and rows; the dashboard
    gets Toolkit and Automation entries (skills, MCP and tools; jobs and scheduler) out of Agent.
- **Order:** two steps, each verified live: (1) `toolkit` out of `agent`, (2) `automation` out
  of `agent` on top of it.
- **Owner, sixth round:** the pattern is one module that owns the tool protocol and the global
  registry, modules that implement their own tools in their own files, the agent loading the
  list, and `app.py` registering every module's tools; laid out like that, the protocol can
  stay in `agent`, with `automation` above it depending one way.
- **Agreed; this is the recommendation (supersedes `toolkit`).** The protocol module is
  `agent` itself (`Tool`, `ToolRegistry`); the rule becomes "only modules above the agent
  define tools": `automation` (layer 4, beside `extension`) imports `agent`, keeps its tools
  in `automation/tools.py`, runs jobs and reads what was delivered through the agent's API;
  `app.py` registers `automation.tools()`; the extension loader registers an extension's. The
  agent never imports `automation`. Modules below the agent define no tools and reach it only
  through the `robot` extension — which is wanted (principle 7, invariant 11), not a gap. This
  is where extensions already sit, so it is one rule rather than a second mechanism, it mirrors
  OpenClaw (the Gateway's cron calls the agent runtime), and it is about half the change of the
  `toolkit` plan (MCP, skills and the extensions' imports stay as they are). Splitting MCP and
  skills out of `agent` is a separate question with no need today.
- **Owner, seventh round:** or `automation` receives the main agent at setup and itself
  registers its tools into it and hooks up the perception events.
- **Agreed — this is the extension module's existing pattern** (`ExtensionSession.setup(…,
  agent, perception, …)` registers tools, skills, MCP, subagents, automations and watchers
  itself), so automation and extensions follow one rule and `app.py` stays pure assembly
  (create, pass peers, start and stop in order). `AutomationSession.setup(…, agent, perception)`:
  it receives the `AgentSession` (the main agent and the tool registry live there), registers
  its main-only tools, and subscribes its own `on_event` to the bus — the event-job matcher is
  automation's; the agent only runs the turn it is asked for (`app.py` no longer subscribes
  `agent.on_event`). `automation` imports `log`, `storage`, `agent`, `perception`. Invariant 19
  becomes: only the agent and the modules above it register tools, each into the
  `AgentSession` it is given at setup (the agent its own, `automation` its scheduling tools,
  the extension loader an extension's); modules below the agent define none and reach it
  through the `robot` extension.
- **Correction (found here):** `automation.enabled` never stopped the scheduler — it only
  decides whether the heartbeat job is created or refreshed at start; reminders fire either
  way. An earlier answer told the owner it was the master switch for every job, and block #53's
  description edit said so too; the description now states what it does. With the split it
  becomes the real switch: off → scheduler stopped, scheduling tools withdrawn, heartbeat
  paused. The household runs with it on, so nothing changed in practice.
- **Owner, eighth round:** no — not inside `automation`; registering its tools and hooking its
  event callback are assembly and belong in `app.py`.
- **Agreed; final shape.** The extension loader is the exception, not the model: extensions are
  enabled, disabled, installed and removed while sidekick runs, so the loader must wire and
  unwire at runtime. Core modules are wired once, at start, and that wiring lives in `app.py`
  only (as `channels.setup(agent.handle)` and `channels.register(interaction.voice)` already
  do), so reading `app.py` shows every connection. `automation` stays passive: it offers
  `tools()` and `on_event()` and takes two plain functions in `setup` (run one main-agent turn
  and deliver it; what was delivered unprompted since a time). `app.py`:
  `automation.setup(db, spec.automation, run_turn=…, said_since=…)`,
  `agent.register_tools(automation.tools())`, `perception.subscribe("*", automation.on_event)`,
  then `start()` / `stop()` in order; the extension loader gets `automation` for manifest
  automations. `automation` imports `log`, `storage` and `agent` (the tool protocol only); it
  needs neither the agent session nor `perception`. The tools stay registered: with
  `automation.enabled` off the scheduler stops, events are ignored, the heartbeat pauses and the
  tools answer that scheduling is off. Invariant 19: tools are defined only by the agent and the
  modules above it and registered in two places — `app.py` at start (core modules) and the
  extension loader at runtime (extensions); modules below the agent define none.
- **Pending:** owner go-ahead.

## [2026-10-29 #54] Progress: the heartbeat's own submodule (block #53)

- [x] `agent/heartbeat.py` holds the job, its quiet-hours predicate and its prompt;
  `automation.py` no longer names the heartbeat (`Scheduler(silent_in_quiet_hours=…)`); the
  façade only wires it. New test: quiet hours silence the heartbeat, a reminder still plays.
- Verification: 179 passed, ruff and `mypy --strict src` (112 files) clean. The live
  `sidekick run` still runs the previous code (same behaviour; `automation_v1.db` untouched,
  the heartbeat job keeps its id and its 125 runs).

## [2026-10-28 #53] Decision + Todo: the heartbeat gets its own submodule `agent/heartbeat.py`

- **Owner (follow-up to #52):** there is no `heartbeat.py`; the heartbeat's logic is folded into
  `automation.py` — that is still a problem.
- **Agreed, by our own module rules** (one focused component per submodule): the heartbeat is
  spread over three places — its constants and `JobStore.ensure_heartbeat()` in
  `automation.py`, a name check in `Scheduler.tick` (quiet hours), and a branch in `run_job()`
  plus `_heartbeat_prompt()` in the façade. It stays inside `agent` (a separate core module
  would need the lower layers to import upward, block #52).
- **Todo**
  - [x] `agent/heartbeat.py`: `HEARTBEAT_NAME` / `HEARTBEAT_PROMPT` / `HEARTBEAT_LOOKBACK_S`,
    `ensure_heartbeat(jobs, minutes)`, `is_heartbeat(job)`, `heartbeat_prompt(job, dialogue)`;
    its header says what the heartbeat is and is not.
  - [x] `automation.py` knows nothing about the heartbeat: the scheduler takes the quiet-hours
    rule as a predicate (`silent_in_quiet_hours`), the façade passes `is_heartbeat`; no schema
    change, the job keeps its id and row in `automation_v1.db`.
  - [x] The façade only wires it (setup, `set_automation`, `run_job`).
  - [x] Tests (store, session, a quiet-hours tick); AGENTS / README / README_CN; the
    `heartbeat_minutes` description says what the turn does. Behaviour unchanged.

## [2026-10-28 #52] Discussion: is the heartbeat a module others register on?

- **Question (owner):** "nothing depends on the heartbeat" sounds wrong; by the framework's
  design it should be its own module with an interface other modules register on to receive
  heartbeat events — or is that over-design?
- **Correction to block #50:** it gave the owner's reason for "no redesign" as "nothing else
  depends on it"; the owner's words assumed the opposite ("a basic capability many modules use;
  it ran fine, so no need to change"), and that assumption was not corrected at the time. The
  decision (no redesign) is unchanged.
- **What the heartbeat is:** the OpenClaw sense of the word — a periodic agent turn (OpenClaw's
  reads a `HEARTBEAT.md` checklist and answers `HEARTBEAT_OK` when nothing needs attention), not
  a system tick and not a liveness signal. Here it is one built-in scheduler job
  (`agent/automation.py`, every 30 min outside quiet hours) whose main-agent turn usually ends
  in `NO_REPLY`. Nothing imports it or subscribes to it; liveness is what the `doctor`
  readiness list checks.
- **The registration points already exist:** time → `Scheduler` jobs (`cron` / `at`, the
  `schedule` tool, `ensure_builtin`); events → the perception bus (`subscribe(pattern)`, every
  source a `Watcher` with its own `interval_s`, event jobs declared in extension manifests such
  as `befriend` / `greet`). Every unprompted utterance (reminder, greeting, befriending, async
  result, heartbeat) leaves through the one delivery policy. A heartbeat module with listeners
  would be a third "do something periodically" mechanism (principle 1).
- **One tick does not fit the loops in the tree:** motion owner 30 Hz and face detection 10 Hz
  (threads that must not wait), scheduler 15 s, watchers 15 s (HA) / 2 min (downloads) / 30 min
  (news), maintenance once a day; a shared tick would either spin most of them or starve the
  fast ones, and one slow listener would delay the rest.
- **Recommendation:** no new module; keep the job and its name (OpenClaw's). Say in AGENTS.md
  that it is an agent job, not a tick, and where periodic work and event sources register; make
  `automation.heartbeat_minutes`' description say what the turn does. If extensions should ever
  feed it, they already publish on the bus: the heartbeat's prompt would read the notable events
  since its last run (the idea shelved in block #50) — no new interface.
- **Follow-up (owner): which module owns it, and is that a cycle?** `agent` — a built-in job of
  its automation submodule, an agent feature like reminders, not infrastructure. No cycle:
  `agent` imports only `log`, `storage`, `llm`, `channel`, and only `extension`, the bundled
  extensions' tools, `dashboard` and `app.py` import `agent` (`tests/test_architecture.py`
  passes). Lower layers reach the agent through callbacks `app.py` injects, never by import:
  `perception.subscribe("*", agent.on_event)`, `channels.setup(agent.handle)`, interaction's
  own `Responder` protocol, `body_can_speak`. So a registration point lives in the lower module
  and the listener above it; a heartbeat others register on could not sit in `agent` without
  the lower modules importing upward.
- **Pending:** owner decision.

## [2026-10-28 #51] Progress: Bobby's own expressions and conversational body language (block #50)

- [x] **Engine** `body/expression.py`: monotone cubic keys (no overshoot, flat holds) + enveloped
  sines, `ant` / `ant_alt` shortcuts, mirror, loops with open-ended oscillators (no seam),
  `then` chains; `ExpressionPlay` with intensity, speed, delayed start, cancel fade. The motion
  owner sums three layers (`state`, `beat`, `express`) after the look's easing and the
  antennas' smoothing; a new expression on a busy layer fades the old one in 0.15 s; the touch
  detector pauses while antennas are driven; `state.gaze_held` holds the face servo; the moving
  window takes expressions ≥ 6° (small beats and thinking are not motion). `play_move()`,
  `emotions()`, `play_emotion()`, `cancel_emotion()`, `body.emotions_dataset` and
  `body.emotion_sound` are gone (retired keys dropped on load; `preload_datasets` now off by
  default).
- [x] **Library** `expression_library.json` (authored, nothing converted): 19 beats, 21 emotions,
  9 performances, `think` → `think_long`; every non-state entry returns to rest; aliases
  (English, Cantonese) and a unique-prefix fallback (`delight` → `delighted`).
- [x] **Conversation**: `ack` → `think` (0.35 s later, random side) → `think_long` → gaze back at
  the first sentence; `heard_again` on their speech while thinking; `yield` after a reply;
  `mm_hm` at front-end `pause` events (≥ 0.3 s dip 14 dB under the sentence's peak after
  1.5 s of speech; ≤ 1 per 3.5 s, 70 %); beat nods on phrase onsets of Bobby's own audio (the
  sway VAD after ≥ 350 ms of quiet; ≤ 1 per 2.2 s, 55 % × energy).
- [x] **Style**: `[style:lively|calm|natural]` per reply (`STYLE_ENERGY` 1.45 / 0.6 / 1.0) ×
  `body.expressiveness` (Body → Motion, live); the sway scales with it; natural again at the end
  of every reply and on an interrupt. Agent rules: most replies no expression, one at most, only
  for a real feeling; lively for stories and children, calm for comfort and bad news. Skills:
  `robot body` lists the library by kind, new `storytelling`; the context view leaves
  `[express:…]` / `[style:…]` out of old replies (they were teaching the model to tag every
  reply).
- [x] **Dashboard**: Expressions card on Body (by kind, intensity, Think 6 s preview,
  `POST /api/body/state`), `GET /api/body/expressions`, the controller's emotion list removed,
  the say test lists the library.
- [x] **Antennas, corrected live**: positive swings an antenna *outward*; the first library had
  sadness and fear as negative offsets, which crossed the antennas inward into an X above the
  head (seen on the 3D view at ±20°). Every droop is now a large outward swing — sad +120°
  (measured ±130°, hanging at the sides), disappointed +90°, scared / annoyed / yuck +70–85°
  (flattened), sorry / bow / sigh +45–60° — and every antenna oscillation rides on a spread, so
  no entry crosses past vertical (checked by sampling every entry).
- [x] **Live (Lite, 2026-10-28 13:45)**: commanded vs measured — nod 8.0° / 6.2°, laugh pitch
  −12.9° / −15.8°, surprised antennas 55° / 58°, think → think_long chained; median tracking
  error 1.3–6.7°. Dry runs with the real `fast` slot on a copy of the owner's home: no tags on
  the time, cooking, a reminder; `delight` on a promotion; `[style:calm]` on a pet's death;
  `[style:lively]` + one beat expression on three story requests out of three.
- [x] Tests: `tests/test_body_expression.py` (library, curves, plays, layers, chains, style,
  controller hold, sway onsets, tags and aliases, attention thinking / backchannel, front-end
  pause, retired keys, pipeline style), `tests/test_agent_session.py` (tags out of the context
  view), old emotion tests rewritten. 178 offline tests, ruff, mypy clean.

## [2026-10-28 #50] Decision + Todo: own expressions, natural conversation, style, heartbeat as perception review

- **Owner decisions (2026-10-28, on block #49):** natural by default with lively for stories and
  play with children; author every expression ourselves (no conversion of Pollen's moves); build
  all three kinds; design the missing *thinking* expression; build speaking, listening and
  emotional beats. Style is not a global switch and not a "scene": storytelling is a skill.
  The heartbeat stays as it is after block #47 (owner, later the same day: nothing else depends
  on it and the morning fix stopped the nagging, so no perception redesign); its switch is the
  Scheduler card's `heartbeat_minutes` (30 by default, 0 = off).
- **Decided here:** style is per utterance — the agent writes `[style:lively]` (stories, play
  with children) or `[style:calm]` (comfort, bad news) at the start of a reply, no tag is
  natural, and the next reply starts natural again; the dashboard holds only the household's
  baseline `body.expressiveness`.
- Todo:
  - [x] `body/expression.py` + `body/expression_library.json`: keyframe channels (yaw, pitch,
    roll, x, y, z, both antennas or each) with Catmull-Rom interpolation and enveloped sine
    oscillators, kinds `beat` / `emotion` / `performance` / `state`, loops and chaining for
    states; the motion owner plays them as overlays in three layers (state, beat, express) on
    top of the look, breathing and sway — gaze kept, intensity and speed scaled, fade in / out,
    cancel at once; gestures become library entries. `play_move()` and the SDK library are no
    longer used (`emotion_sound`, `emotions_dataset` retired on load).
  - [x] Our library: beats (ack, nod, double nod, mm-hm, aha, tilt, perk, shrug, sigh, wink,
    sorry, emphasis, lean in, yield), emotions (laugh, chuckle, giggle, delighted, excited,
    surprised, amazed, touched, sad, disappointed, embarrassed, proud, relieved, confused,
    worried, annoyed, sympathetic, shy), performances (dance, groove, yawn, stretch,
    celebrate, peekaboo, look around, sneeze), states (think → think long, listen).
  - [x] Conversation in `interaction`: acknowledge → think (gaze aversion, the face servo held)
    → think long after 2.5 s → gaze back before the first word; speech beat nods on phrase
    onsets of Bobby's own audio (from the sway DSP); turn-yield at the end of a reply;
    backchannel nods at the speaker's pauses; emotions only from the agent.
  - [x] Style: `[style:…]` tags, `BodySession.set_energy()`, `body.expressiveness` on Body →
    Motion; agent rules (most replies carry no expression); skills `robot body` (the library
    by kind) and a new `storytelling`.
  - [x] Heartbeat: no redesign; `heartbeat_minutes` says "0 turns the heartbeat off" (≥ 0).
  - [x] Dashboard: an Expressions card on Body (by kind, intensity, play), the say test's list.
  - [x] Tests, docs (AGENTS, README / README_CN, headers), live check with screenshots.

## [2026-10-28 #49] Discussion: our own expression library and natural conversational motion

- **Owner (2026-10-28):** stop using the SDK's expressions and build our own library (a port of
  Pollen's plus more expressions). People talking do not emote all the time — only a real
  emotion (a big laugh) gets a special expression — so speaking and listening need natural
  motion, such as looking at the person; yet the puppets of Western children's shows are very
  exaggerated when they talk. What do we think?
- **The library, measured:** 85 recorded moves (50 Hz head pose, antennas, body yaw), Apache-2.0
  (a converted copy may live in our repository with attribution), 84 with a sound. Median
  4.6 s, 28 moves ≥ 6 s and 17 ≤ 3 s, up to 19.8 s; head yaw swings up to 90° (`curious1`),
  roll up to 59°, antenna sweeps up to 376°. They are stand-alone performances for a robot that
  is the show.
  `play_move()` blocks our motion owner for the whole move (no gaze, no sway, no breathing,
  touch paused) and can only be cancelled by stopping the audio pipeline.
- **View:** both observations point the same way. Puppeteers work by focus (the puppet looks at
  whom it talks to), sync (the mouth moves with the words — Bobby's mouth is the speech sway)
  and economy (a big reaction on a beat, then back to neutral). Muppets are exaggerated in
  amplitude, not in frequency: they do not emote on every sentence. So: a natural baseline all
  the time, an expression only on a real emotional beat, and the amplitude as a style setting —
  natural by default, lively (puppet-like) for stories and play with children.
- **Proposal (waits for the owner's go):**
  1. Own expression engine in `body`: an expression is a set of offset tracks (head yaw / pitch /
     roll / x / y / z, antennas, body yaw) the motion owner plays as an overlay, like a gesture —
     composed with the gaze / face servo and the sway, scaled in amplitude and speed, eased in
     and out, cancellable at once, silent; `play_move()` is no longer used.
  2. Library as flat data in `body/`: `expression_pollen.json` (the 85 moves converted to
     offsets, downsampled, attributed) and `expression_sidekick.json` (ours). Each entry has a
     kind: `beat` (≤ 2 s, conversation: chuckle, small nod, double nod, tilt, perk, mm-hm, aha,
     shrug, sigh, antenna wink, sorry), `emotion` (≤ 3 s, real feelings: laugh, delighted,
     surprised, touched, sad, embarrassed, proud, relieved) and `performance` (long: dances,
     sleepy, story moments — never in the middle of a reply).
  3. Natural conversation in `interaction`: speaking = gaze on the addressee, the sway, small beat
     nods on stressed phrases, a short thinking look-away before a long answer, a turn-yield at
     the end (look back, antennas up); listening = gaze held, antennas perked, small backchannel
     nods at the speaker's pauses, the existing thinking tilt after end of speech.
  4. Agent rules: most replies carry no expression, one only for a real emotion; an
     `expressiveness` setting (calm / natural / lively) on the Body page, with stories and
     children's play switching to lively.
- **Open (owner):** natural by default with lively for stories / children? Convert Pollen's moves
  as a base or author everything ourselves? Which expressions first?

## [2026-10-28 #48] Progress: unnamed-speaker labels never reach the room

- **Report (owner, 2026-10-28):** Bobby says the ids aloud — 「啱啱係 person:6 講咗句…」,
  「你係 person:7」; no numbered labels in any output.
- [x] `MAIN_ROLE`: a `person:N` / `guest:N` label is for tool calls only — never said or written;
  talk to them as 你, say you do not know their name yet when asked, 嗰位朋友 about them. The
  `befriending` skill says the same.
- [x] `run_main` scrubs the streamed reply (`_SpeakerIdScrubber`): any label, half- or
  full-width colon, becomes 呢位朋友 / 这位朋友 / "this friend" by the reply language; a label
  cut across stream chunks (`pers` + `on:6`) is held back until it resolves; the recorded row,
  the speech, the text channels and the dashboard all get the scrubbed text.
- [x] Dry run on a copy of the owner's home with the real `fast` slot (four questions about who
  is who, from unnamed and named speakers): no label in any reply.
- [x] Test: `tests/test_agent_session.py` (a label cut across chunks, the recorded row, the rule
  in the system prompt). Docs: AGENTS agent row, the façade header.

## [2026-10-28 #47] Progress: the heartbeat stops re-announcing an old reminder; one row per delivery

- **Seen while tracing #46:** the heartbeat spoke a made-up "今晚九點嘅食藥提醒" at 16:00, 20:00,
  21:30 and 22:00 on 10-27 and at 09:30, 10:00 and 10:30 on 10-28 (the only medicine job in the
  store is a one-shot at 08:00 on 10-27, long done). Its context is the recent public timeline **without
  times**, every proactive message sat there **twice** (`run_main` recorded the job's reply and
  `deliver` recorded it again), and the prompt asked for "reminders that came due" — so each
  heartbeat read its own earlier nags as news ("響咗好多次啦").
- [x] One row per delivered message: `run_main(record_reply=False)` for job turns and the async
  delegation relay; `deliver` keeps writing the row with `delivered_to` and the policy.
- [x] `HEARTBEAT_PROMPT`: reminders and scheduled tasks are spoken by their own jobs — never
  repeat, re-announce or invent one. `AgentSession._heartbeat_prompt()` adds the last run time
  and what was delivered on Bobby's own initiative in the last 24 h (`HEARTBEAT_LOOKBACK_S`),
  dated, tags stripped, newest 8: "never repeat or rephrase any of it".
- [x] Dry run on a copy of the owner's home with the real `fast` slot (nothing spoken): old prompt
  3 nags in 15 runs, new prompt 0 in 15 (all `NO_REPLY`).
- [x] `NO_REPLY` calls reach the LLM trace again (invariant 5): the loop stopped reading the
  stream at `NO_REPLY`, so its `done` event — where `LLMSession` records — never came and every
  silent heartbeat and `NO_REPLY` turn was missing from the trace. The loop now reads the step to
  its end and drops the rest. Checked on the real `fast` slot: rows with `NO_REPLY`, finish
  `stop`, ~3.6–4.0 k tokens per heartbeat.
- [x] Tests: `tests/test_agent_session.py` (one row for a delivered reminder and for the relayed
  async result; the heartbeat prompt lists what was said, without tags, and its last run; a
  `NO_REPLY` turn is traced).
- [x] Docs: AGENTS "Automations, heartbeat, delivery", README / README_CN, module headers; the
  start-up readiness line points at the System page (the rail is gone).
- **Open (owner):** the heartbeat has no input of its own today — events never reach its context,
  async results and reminders relay themselves — so it mostly costs a `fast` call every 30 min
  outside quiet hours (31 a day at 07:30–22:30, ≈ 4 k tokens each, ≈ 125 k a day). Keep it as
  is, gate it on concrete inputs (undelivered
  messages, chosen event types), or turn it off (`automation.heartbeat_minutes = 0`) until an
  extension needs it?

## [2026-10-28 #46] Progress: emotion moves play without their sound effects

- **Report (owner, 2026-10-28):** while Bobby talks and moves, odd sounds that seem to belong
  to the motion play at the same time and make the speech hard to follow; are the expressions
  the SDK's own?
- **Cause:** yes. `[express:name]` tags resolve to Pollen's recorded moves
  (`pollen-robotics/reachy-mini-emotions-library`: 85 moves, 84 with a sidecar `.ogg`), and
  `ReachyMini.play_move()` plays the move's sound by default (`sound=True`) through a separate
  GStreamer `playbin` routed to the same speaker — outside our paced player, so ducking, the
  speaker tap and the recording never see it. The log has `curious1` (11.8 s of motion and
  sound) under the reply at 10:18:51 and `cheerful1` (2.8 s) under each spoken heartbeat at
  09:30, 10:00 and 10:30.
- [x] `ConfigBody.emotion_sound` (default **off**); `BodyBackend.play_emotion(name, sound=False)`;
  the motion owner passes the façade's switch; `BodySession.set_emotion_sound()` applies a
  change live from `POST /api/config/body`; the switch sits on Body → Motion.
- [x] `BodyReachyBackend.cancel_emotion` notes that the SDK's `cancel_move()` stops the whole
  playback pipeline, Bobby's voice included (nothing calls it).
- [x] Tests: `tests/test_body_emotion.py` (default off, live switch, config → session, `sound`
  reaches `play_move`); `tests/test_dashboard_config.py` (schema field, live apply).
- [x] Docs: AGENTS (body row, Motion card, "Body"), README / README_CN.

## [2026-10-27 #45] Progress: every tab owns its parameters; readiness replaces the wizard (block #44)

- [x] **`doctor` module** (`doctor.py`, `schemas.py`; Layer 5 in the import table and
  `tests/test_architecture.py`): `DoctorSession.local()` (cached 5 s), `probe()` (injectable
  for tests), `loopback()` (tone from `audio.tone`, now shared with the Robot speaker test;
  the front end held meanwhile), `run(layers)` (no overlap), `snapshot()`; `DoctorItem` /
  `DoctorReport` (`ready`, `summary()`, `worst_by_tab()`). `app.py` builds it after the
  extensions, hands it to the dashboard and logs the local summary at start.
- [x] **config**: `ConfigOnboarding` deleted, the key dropped on load with a log line; every
  user-facing field got a `description`; `speaker_gate` is a `Literal`. CLI `init` / `doctor`
  no longer touch onboarding (the CLI's own readiness rewrite waits for the owner's brief).
- [x] **routes**: `doctor` in `/api/health`; `GET /api/doctor`, `POST /api/doctor/run?layers=`;
  `GET /api/config/schema` (pydantic → type / bounds / choices / description / nullable;
  nested objects; `flags` for `dict[str, bool]`), `GET /api/config/providers` (catalog +
  bindings + "shared with" lists), `POST /api/config/{section}` (deep merge, validate, save,
  live hooks: `interaction.set_config`, `body.configure_sway`, new `ContactSession.set_config`
  (thresholds, TV zone) and `AgentSession.set_automation` + `InteractionSession.set_quiet_hours`;
  otherwise "takes effect at the next start"), `POST /api/config/tv` partial, `SlotUpdate.speed`,
  `POST /api/system/backup`; the onboarding routes are gone.
- [x] **page**: 13 tabs (Live, Robot, Voice, Timeline, Memory, Agent, Automations, Skills & MCP,
  Channels, Contacts, Extensions, Replay, System; old hashes alias), appearance in the sidebar
  footer, the rail's System card = readiness (verdict, Check, failing rows with jump links,
  pinned while blocking), sidebar dots = worst readiness level merged with the runtime dots,
  the Live empty state shows the verdict + 檢查就緒 while not ready. One parameter-card renderer
  (`PARAMS` map → `/api/config/schema` fields; sliders for liveliness and the servo gain; a
  folded card for the 24 sway knobs) and one service-card renderer (`data-services`), trace
  tables per page (`data-trace`), the TV zone drawn on a camera frame on Contacts, the Telegram
  token field on Channels, System = full readiness table + Dashboard address + Backup + Logs +
  Config (masked).
- [x] Tests: `tests/test_doctor.py` (report levels, local layer over the null body incl. the
  cache, probe mapping + region persisted, loopback incl. a dark frame, no body / no overlap),
  `tests/test_dashboard_config.py` (providers, schema, generic section route incl. 404 / 422,
  credentials write-only, slots with speed, languages, TV zone / sector written independently,
  health `doctor`, `/api/doctor` + run, backup); `test_dashboard_onboarding.py` removed, CLI
  test updated. `pytest -m "not network"`: 162 passed; ruff / mypy --strict clean.
- [x] Live on the Lite (run 34): start-up log `readiness: ready · 1 advisory` (channels);
  "Check everything" from the page: 27 rows, every probe ok (llm 2.4–3.0 s, asr.primary 2.3 s,
  local ASR 0.34 s, kws 0.22 s, tts 2.0–3.4 s), loopback: speaker drained in 0.9 s, the
  microphone did **not** hear the 440 Hz tone (−27 → −28 dBFS: the XVF3800 cancels its own
  echo, so this row is advice, not a block), camera 43/255 at 11 fps. A parameter change from
  the Robot page round-trips ("idle_scan_hold_s: applied"). Screenshots in the review page
  (round 13).
- Docs: AGENTS (scope paragraph, layer 5 + import table, `doctor` row, dashboard / app / cli
  rows, config section, "Dashboard and CLI" + "Readiness"), README / README_CN console
  sections and the sway / sociability references.
- Open: the owner's CLI brief for `sidekick doctor` (call the same `DoctorSession`); whether the
  loopback should use a lower-frequency or longer signal the AEC lets through.
- 2026-10-27 afternoon, after a layout discussion (eight drafts on a design canvas, from a widget
  wall with drawers to a master-detail split): the owner decided to **keep the current structure**
  (sidebar, page, the monitor rail fixed on the right) and asked only for the sidebar footer to
  go — the theme now follows the system and the rail has no left / right switch; then (same
  afternoon) to try the **monitor rail fixed on the left and the pages as a tab strip across the
  top**, the sidebar gone (`.tabs` in `dashboard_index.html`, rail 340 px); the strip then
  widened to span the whole window with the brand at its left, so the rail sits below it; then
  the tabs right-aligned and **cut to one per core module directory** (Live · Voice · Body ·
  Agent · Contact · Channel · Record · Extension · System: Timeline / Memory / Automations /
  Skills & MCP folded into Agent, Replay renamed Record, Robot renamed Body; the `doctor` tab
  ids follow). Old hashes alias. Finally (2026-10-28) the owner went **back to the sidebar**: a
  module list on the left, one page per core module on the right, **no fixed monitor rail** —
  its cards moved onto their module pages (camera / conversation / last turn / events beside the
  chat on Live, 3D body + telemetry on Body, level meters on Voice, the readiness summary on
  System); the camera stream and the 3D view run only while Live or Body is open. Polish: the
  list shows only the module names (an icon each, no subtitle, just "Sidekick" as the brand — the robot's
  name may change), thin scrollbars, a sticky horizontal bar on phones. Then Live became a board:
  camera · 3D body · conversation state on top, the chat card (2 columns) · last turn / events
  below; the 3D card is a single WebGL view that moves between Live and Body on tab switch
  (`data-slot="body3d"`); the camera card does the same (`data-slot="camera"`, top of Body's
  right column), so both run only while Live or Body is open. On phones the module
  list folds into a menu button (the current module's name) that drops the list down.
  Still worth
  doing from that discussion: a `/api/board` summary so the rail cards show "last known + when +
  trend" instead of resetting at restart, and a `group` tag on config fields so parameter cards
  can be split by submodule.

---

## [2026-10-27 #44] Decision + Todo: every tab owns its parameters; readiness replaces the wizard

**Owner's framing (discussion, 2026-10-27 midday):** the dashboard is *parameter setting +
monitoring + internal debugging*, and every tab aggregates everything under its own title. So the
Settings page (a module-shaped dump of `interaction` fields) goes away and each knob moves to the
tab where one watches its effect; the services a module uses (LLM / ASR / TTS / VAD slots and
their keys) are configured on that module's tab, not on a horizontal providers page, because each
module has its own customisation needs (LLM: two slots, steps, tokens; ASR: local vs cloud,
shadow; TTS: voice per language). Keys stay stored once per provider; only the entry points
multiply. The Setup tab and the wizard go too: a wizard answers "in which order do I fill things
in", a readiness list answers "what is missing now", and only the latter stays useful after the
first run (expired key, deleted model, robot unplugged).

**Decisions**

- Tabs (13): Live · Robot · Voice · Timeline · Memory · Agent · Automations · Skills & MCP ·
  Channels · Contacts · Extensions · Replay · System. Gone: Listening (→ Voice), Setup, Settings,
  Traces (LLM → Agent, ASR / TTS → Voice), Logs (→ System). Appearance (theme, rail side) moves
  to the sidebar footer.
- Ownership rule: a parameter lives where one looks while tuning it, not where its code lives.
  Robot = `body` (daemon connection, volume, sway with a folded detail card, SDK wobble) + the
  attention knobs of `interaction` (face tracker / gain / daemon weights, idle scan, sound
  glance). Voice = the whole speech pipeline in two columns, *hear* (VAD, ASR local / primary /
  kws service cards, wake-name aliases and keyword lines, triggers, speaker gate, turn, thresholds,
  words, TV sector) and *speak* (TTS primary / fallback service cards, household language);
  Decisions and the ASR / TTS traces under them. Agent = LLM fast / smart service cards + `agents`
  + the LLM trace. Automations = `sociability` + quiet hours / heartbeat / tick. Contacts =
  recognition thresholds + the TV zone drawn on the camera frame. Replay = `recording`. Channels
  gains the Telegram token field. System = readiness (full list + Check), Logs, Config (masked),
  Backup.
- One **service card** skeleton (provider, model / voice, the provider's key field with "shared by
  N slots", Probe) rendered per slot on Agent and Voice; one **parameter card** renderer driven by
  the pydantic schema (`GET /api/config/schema`: type, bounds, choices, description, default) and
  a generic `POST /api/config/{section}` with live apply where a hook exists (`interaction`,
  `body.sway`) and an honest "takes effect at next start" note otherwise.
- **Readiness** = a new Layer-5 module `doctor` (may import any module, like `app` / `cli`):
  three layers — *local* (Python, models, slots bound with credentials, daemon / body awake, DSP,
  free disk, recording state, household members, channel tokens; < 1 s, no side effects, refreshed
  every 5 s for the health poll), *probe* (one real call per slot through `ConfigSession.probe`),
  *loopback* (a 0.5 s tone through the speaker while the microphone listens, the camera frame's
  brightness; the voice front end is held meanwhile). Items carry a level (ok / warn / bad), a
  detail and the tab that fixes them; `ready` = no `bad` item. `sidekick doctor` will call the
  same function later (owner: CLI requirements come separately).
- Where readiness shows: the rail's System card (verdict line, Check button, the failing rows
  with jump links, pinned to the top of the rail while something blocks), the sidebar dots (worst
  level per tab, merged with the runtime dots), the Live empty state (one line + the same button
  while not ready), the System page (the full list with timings). The `onboarding` config section
  is deleted (old files are migrated by dropping the key); `app.py` logs the readiness summary at
  start instead of the wizard URL.

**Todo**

- [ ] `doctor` module (`DoctorSession`, `DoctorItem`, `DoctorReport`), tests with the null body.
- [ ] `config`: drop `ConfigOnboarding`, migrate on load, field descriptions for the schema route.
- [ ] `dashboard/api.py`: `doctor` in health, `GET /api/doctor`, `POST /api/doctor/run`,
  `GET /api/config/providers`, `GET /api/config/schema`, `POST /api/config/{section}`,
  `POST /api/system/backup`, `POST /api/config/tv` partial; onboarding routes removed.
- [ ] Page rewrite: nav, sidebar footer, rail System card, Robot / Voice / Agent / Automations /
  Contacts / Replay / Channels / System sections, the two renderers, the Live empty state.
- [ ] CLI `init` / `doctor` no longer touch onboarding; `app.py` readiness log line.
- [ ] Docs: AGENTS (module table + yellow pages + dashboard section), README / README_CN.
- [ ] Verification + real-robot screenshots (owner: "完成后截图发我").

---

## [2026-10-27 #43] Progress: own speech sway landed (block #42)

- [x] `body/sway.py`: `SwayConfiguration` (28 knobs; `from_config()` duck-types `ConfigSway`),
  `SwayOffsets`, `SpeechSway` — the SDK's `SwayRollRT` DSP on numpy with timestamped hops
  (`play_at + latency_ms`), `offsets(now)` = latest due hop, held two hops, faded over
  `release_ms`; `reset()` on flush; `configure()` live; `snapshot()`.
- [x] `media.AudioPlayer.sway` fed in `_push_chunk` with the frame's scheduled start; `flush()`
  resets it. `MotionOwner.sway` added every tick (x / y clamped to ±10 mm, `head_pose` grew
  `x` / `y`), `MotionPose.swaying` → telemetry `"swaying"`. `BodySession.make` binds
  `ConfigBody.sway`, `connect(wobble=None)` follows `ConfigBody.sdk_wobble` (False), builds the
  sway for the player and the owner; `configure_sway()`; `control_status()["sway"]`. CLI `say`
  follows the config too.
- [x] `config`: `ConfigSway` (bounds: master ≤ 1.5, amplitudes ≤ 15° / 10 mm, frequencies
  ≤ 5 Hz), `ConfigBody.sway`, `ConfigBody.sdk_wobble`.
- [x] Dashboard: `POST /api/config/body` (nested `sway` merge, live apply), Behaviour card:
  "head sway while speaking" switch + "liveliness" slider (0 … 1.5) applied on release,
  Telemetry body row shows `swaying`.
- [x] Tests `tests/test_body_sway.py`: silence / master 0 / disabled → zero; a loud tone peaks
  exactly at the configured amplitudes and never above; hold then fade after the last hop;
  master scales linearly; latency shifts the hops; `configure()` live; the null body speaks a
  clip → player feeds, owner sways (pitch beyond breathing), flush resets, `configure_sway`;
  config round trip and factory; the body route merges `sway` fields and rejects out-of-range.
  `pytest -m "not network"`: 155 passed; ruff / mypy --strict clean.
- Docs: AGENTS body / dashboard rows + config sections, README / README_CN.

---

## [2026-10-27 #42] Todo: own speech sway (replace the SDK wobble)

Owner's go (10:40) on block #41.

- [ ] `body/sway.py`: `SwayConfiguration` (master, per-axis amplitude / frequency, loudness
  window, VAD and envelope timings, speaker latency), `SpeechSway` (the SDK's DSP re-done on
  numpy: 50 ms hops, RMS → VAD with hysteresis → envelope → loudness × master → six oscillators),
  timestamped hops, `offsets(now)` with hold + fade, `reset()` on flush.
- [ ] `media.AudioPlayer` feeds every pushed frame with its scheduled playback instant;
  `MotionOwner._tick` adds the current offsets (x / y translations added to `head_pose`);
  `MotionPose.swaying`; `BodySession.make` reads `ConfigBody.sway`, `connect()` turns the SDK
  wobble off unless `body.sdk_wobble`; `configure_sway()` for live changes.
- [ ] `config`: `ConfigSway`, `ConfigBody.sway`, `ConfigBody.sdk_wobble = False`.
- [ ] Dashboard: `POST /api/config/body` (partial, nested `sway`), Behaviour card slider
  "liveliness while speaking" (master 0 … 1.5) applied live.
- [ ] Tests (`tests/test_body_sway.py`), docs, live check with `/api/say`, screenshot.

---

## [2026-10-27 #41] Research: the SDK's speech wobble — what it is, what it exposes, how to own it

Owner (10:30): Bobby's head sways a lot while speaking; lively, but too much. Does the SDK expose
tuning, and if not, can we replicate the behaviour with our own parameters (we drive every motor)?

**What it is.** `BodySession.connect(wobble=True)` calls the SDK's `enable_wobbling()`. For the
Lite (LOCAL audio backend) the whole thing runs inside *our* process: the SDK's GStreamer
playback pipeline tees the speaker audio into an appsink → `HeadWobbler.feed(pcm, pts)` →
`SwayRollRT` (`reachy_mini/motion/speech_tapper.py`, "ported from the conversation app") → one
6-tuple of offsets per 50 ms hop, scheduled with `GLib.timeout_add` at the audio's playback time
→ `SetSpeechOffsetsCmd` over the WebSocket → the daemon composes the offsets as a world offset on
top of our target pose before IK (`compose_world_offset` in `backend/abstract.py`). The daemon is
also told to wobble for its own sounds (wake / sleep jingles).

**The algorithm** (`SwayRollRT.feed`): per 50 ms hop, RMS in dBFS of the last 20 ms → a VAD with
hysteresis (on ≥ −35 dBFS, off ≤ −45, attack 40 ms, release 250 ms) → an envelope follower
(gain 0.65 per hop, attack 50 ms, release 250 ms) → a loudness gain normalised between −46 and
−18 dBFS (+4 dB offset, gamma 0.9) × `SWAY_MASTER = 1.5` → six free-running sinusoids with
random phases, each scaled by `loud × env`:

| axis | frequency | amplitude (× master 1.5 at full loudness) |
|---|---|---|
| pitch | 2.2 Hz | 4.5° (→ 6.75°) |
| yaw | 0.6 Hz | 7.5° (→ 11.25°) |
| roll | 1.3 Hz | 2.25° (→ 3.4°) |
| x | 0.35 Hz | 4.5 mm |
| y | 0.45 Hz | 3.75 mm |
| z | 0.25 Hz | 2.25 mm |

**What the SDK exposes: nothing.** `enable_wobbling()` / `disable_wobbling()` take no
arguments; every number above is a module-level constant in `speech_tapper.py`. Because the
tapper runs in our process, the constants *could* be monkey-patched at start (they are read at
call time), but that is a hidden dependency on the SDK's internals and breaks on the next
release.

**Replicating it ourselves is straightforward** and fits the architecture better (invariant 10:
one motion owner; today the daemon adds the wobble behind the owner's back, so the moving window,
the controller and the telemetry never see it):

- Our `AudioPlayer` already pushes 20 ms frames at a known schedule (`_scheduled_end`, ≤ 250 ms
  ahead of real time) and taps them (`subscribe_speaker`), so the player can feed each frame plus
  its playback instant into a `SpeechSway` object (same DSP, ~80 lines, numpy only) that yields
  timestamped hop offsets.
- The motion owner's 30 Hz tick adds the hop whose time ≤ now (hold the latest) to the pose
  like breathing and gestures, before the limits; `head_pose()` grows `x` / `y` translations.
- Parameters become ours in `ConfigBody.sway`: `enabled`, `master` (0 … 1.5, suggested
  default 0.5 ≈ a third of the SDK's), per-axis amplitudes and frequencies, loudness window,
  attack / release, `latency_ms` (speaker sink delay, ~100 ms); a "liveliness" slider on Settings
  → Behaviour drives `master` live. The SDK wobble is then disabled at connect
  (`SetWobblingCmd(false)` also silences the daemon's jingle wobble — acceptable).
- Cost: one float32 RMS per 50 ms; no thread. Risk: none on the hardware side — the offsets go
  through the same clamps as everything else (the SDK's 11° yaw at full loudness is well inside).

**Recommendation.** Replicate (own `SpeechSway` in `body/`, SDK wobble off), default master 0.5,
pitch / roll / z as the main motion and yaw halved (the yaw is what reads as "shaking the
head"), slider on Settings. Waiting for the owner's go.

---

## [2026-10-27 #40] Decision + Progress: camera frame starvation and a face servo that actually centres

Owner (10:00): the camera frame rate is too low and face tracking is not smooth — "when I move
left / right in front of it the head does not follow, it looks stepwise; I expect the face to stay
in the centre of the image".

**Findings.**
- The Live camera card measured **2.3 fps** even when asking for 30. The SDK hands each frame
  out once (`appsink.try_pull_sample`, ≤ 20 ms block) and three readers were pulling: the
  recorder (10 fps), the MJPEG stream (8 fps) and the face detector (4 Hz) — each got a share.
  The daemon's local IPC feed is capped at **10 fps** (`IPC_FPS = 10`, `videorate drop-only` in
  the SDK's media server: "it also paces every client, face tracker included"); the camera
  itself captures at 30. So 10 fps is the ceiling on the Lite without patching the SDK.
- Tracking: in IDLE the daemon's tracker ran at **weight 0.3** — the daemon blends its aim with
  our pose (`linear_pose_interpolation(pose, aim, weight)`), so the head moved 30 % of the way
  and the face was never centred; at weight 1.0 (ENGAGED) the daemon ignores our pose
  entirely (`set_target_head_pose` returns before IK), so nods, breathing and glances vanish
  while a face is tracked. Our own servo only ran when the daemon was blind, from the 0.5 s
  level event, in 0.4 rad × offset steps (11° jumps every half second) — the stepping the owner
  saw.

**Decision.** (1) A **frame pump** thread in `BodySession` is the only reader of the SDK camera;
`frame()` hands the latest frame to every consumer; `camera_fps` is measured and shown on the
camera card. (2) **Face tracking is ours** (`interaction.face_tracker: own`, default): the
detector runs at 10 Hz (`perception.poll_hz`), every detection goes to `Attention.on_face()`
through `PerceptionSession.on_face()`, and the servo computes the face's angle from the pixel
offset with the camera intrinsics (`BodySession.camera_fov()`, nominal 90° × 59° otherwise),
steps `face_servo_gain` (0.7) of it from the motion owner's *current* eased pose
(`current_look()`), with a 0.03 dead band and 0.35 s easing — a pursuit, not steps — and eases
back to neutral 2 s after the face is lost. The daemon's tracker stays available as
`face_tracker: daemon` (old weights) for comparison. The Lite's intrinsics come from the SDK
(`media.camera.K`).

Progress:
- [x] `body`: `_frame_loop` pump, `frame(wait_s, max_age_s)`, `camera_fps()`, `camera_fov()`,
  `current_look()`, `BodyBackend.camera_matrix()` (Reachy: `media.camera.K` + resolution;
  null: None), `BodyTelemetry.camera_fps`.
- [x] `perception`: `CameraWatcher.face_listeners` called from `poll()`, `PerceptionSession.on_face()`,
  `ConfigPerception.poll_hz` 4 → 10.
- [x] `interaction`: `attention.on_face()` rewritten (angle from FOV, gain from the current pose,
  dead band, min period 50 ms, stale detections ignored, `servo_steps`, recentre after loss);
  `face_tracker` / `face_servo_gain` in `ConfigInteraction` and `configure()`; the façade
  registers `_on_local_face` and no longer servos from the level event; the daemon tracker is
  toggled only on change.
- [x] Dashboard: stream at 10 fps (the cap), camera header `camera N fps · daemon cap 10`,
  Telemetry face row shows our detector's offset / facing, Triggers `face tracker` select,
  Thresholds `face_servo_gain`. Robot tools `look` / `who_is_here` wait up to 0.5 s for a frame.
- [x] Tests: frame pump (shared frames, fps), servo pursuit (step size from the FOV, min period,
  dead band, pitch sign, stale detection, recentre), listener hook; the legacy daemon-mode test
  kept with `daemon_tracking = True`. 149 passed; ruff / mypy --strict clean.
- Verified live (10:09): Live camera stream **15.3 fps requested / 10.0 fps unique** (the cap),
  watcher at 10 Hz without errors. The servo itself needs a face in front of the camera — the
  owner's retest.

---

## [2026-10-27 #39] Progress: attention and initiative layers landed (block #38)

- [x] `body`: `MotionState.moving_until` + `MotionPose.moving` (`"moving"` in telemetry);
  looks that change the direction (≥ 2°), gestures, emotions and controller poses mark the
  window (duration + 0.3 s tail); breathing and antenna moves do not. `BodySession.moving()` /
  `moving_until()`.
- [x] `interaction`: `FrontEndEvent.self_motion` (onset inside the window; for `speech_end`
  the whole segment inside it + 0.5 s); the façade never ducks on a self-motion onset, ducks
  late when the speech outlasts the motion, traces content-less self-motion segments as
  `self motion`; `attention.py` scanning glances (`idle_scan*`), sound glances from
  `speech_ongoing` in IDLE (`sound_glance*`, TV / self sector excluded), `tick()` driven by the
  0.5 s loop, `snapshot()`; new `initiative.py` (`GREET_AFTER_H` quiet / normal 2 h / chatty
  0.5 h, daily cap 0 / 6 / 12, one offer per person per hour, quiet hours from the automation
  section, `last_seen` from `contact`); `gaze.mutual` subscription → `greet.due` (NOTICE) and
  an `initiative` trace row; `captions()["listening"]` only in ENGAGED / SPEAKING, raw
  `speech_open`; `set_config()`.
- [x] `perception/camera.py`: `facing_camera()` landmark ratio, `faces[i]["facing"]`,
  `gaze.mutual` once per episode (`MUTUAL_CENTRE` 0.3, re-arm after 1 s away), contacts
  touched on face identification; `ConfigPerception.mutual_gaze_s / mutual_gaze_min_height`.
- [x] `contact`: migration v3 `contacts.last_seen_ts`, `Contact.last_seen_ts`,
  `ContactStore.touch_contact`, `ContactSession.touch()` (10 s rate limit) / `last_seen()`;
  voice identification touches, befriending touches.
- [x] `config`: `interaction.sociability`, `idle_scan`, `idle_scan_min_s / max_s / yaw_rad /
  hold_s`, `sound_glance`, `sound_glance_min_dbfs / min_s / hold_s`.
- [x] `extensions/robot`: automation `greet` on `greet.due` (in person), `skill_initiative.md`.
- [x] Dashboard: Settings **Behaviour** card (sociability select, the two glance switches;
  the glance timings in Thresholds), Live shows 聆聽中 only inside a session, rail Conversation
  card row `attention` (mode · countdown · sociability), Telemetry body row `moving`.
- [x] Tests: `tests/test_initiative.py` (last-seen migration and rate limit, quiet hours,
  the greeting rules per level, façade `gaze.mutual` → `greet.due`, Settings round trip,
  captions gating), mutual gaze + landmark facing in `test_perception.py`, scanning / sound
  glances in `test_attention_and_guests.py`, the moving window in `test_body_null_session.py`,
  a self-motion segment through the full fake stack in `test_interaction_session.py` (the
  barge-in test now waits for the thinking tilt to end before interrupting). `pytest -m "not
  network"`: 147 passed; ruff / mypy --strict clean.
- Verified live after restart (09:25): the head takes a glance every 8–15 s (yaw 30°, back to
  neutral after 2.5 s; rail shows "glancing around · 2 s · normal"), `robot.greet` job active,
  the first segment inside a glance was traced as `self motion` (the room stayed `filler`),
  the Live page no longer flashes 聆聽中 in IDLE. `gaze.mutual` / `greet.due` need a lit room
  and a known face: to be confirmed in daylight.

---

## [2026-10-27 #38] Decision + Todo: attention layer and a measured initiative layer

Owner's three points after the first evening with Bobby (2026-10-27): (1) breathing seems to make
noise and "listening" flashes in the Live conversation; (2) idle Bobby should look around, find
faces, recognise them, and greet when someone looks back; (3) turn toward sounds, maybe start a
conversation — but keep measure, it is a home butler.

**Measurement (no code changed).** The first A/B (breathing on −24.6 dBFS vs held −39.9 dBFS)
coincided with the owner talking and is void. The recording ring, 100 ms RMS over every idle row
of the day split by the telemetry `manual` flag: held (breathing paused) n=1236 median −46.6 dBFS;
breathing within 90 s of a hold n=7899 median −44.4; all breathing rows n=13099 median −44.1. The
2 dB gap says the breathing motors are not a noise source. The 50 VAD segments of the last 10
minutes (median 8.9 s, texts 嗯/啊, DoA ±15° of straight ahead = the owner's desk) are ambient
sound from the room; the machine rejected every one correctly — the only fault is that the Live
page labels any open speech segment "聆聽中".

**Decision (owner agreed):** two layers.

- *Attention* (deterministic, body-level, never speaks): idle scanning glances (every 8–15 s a
  slow look at a random direction within ±40°, held 2–3 s, back to neutral; stops when a face is
  seen — the camera's horizontal field is only 90°), glances toward a clear sound in IDLE (orient
  only; rate-limited, never in the TV / self sector), gaze on faces (existing tracker + servo), a
  **mutual gaze** detector (face centred, head turned toward the camera by the YuNet landmarks,
  large enough, sustained ≥ 2.5 s → `gaze.mutual`), and **self-motion gating**: the motion owner
  exposes a "moving" window (looks, gestures, emotions, controller poses — not breathing) and the
  front end marks speech that starts and ends inside it, so it never ducks playback and is traced
  as `self motion` instead of `filler`.
- *Initiative* (agent-level, budgeted): only events reach the agent, and only after hard rules.
  First rule: a **known** contact's first mutual gaze after ≥ 2 h away → `greet.due` (NOTICE) →
  the robot extension's `greet` automation (delivery `in_person`, the agent may answer
  `NO_REPLY`). Never for unknown people (befriending has its own path), never because of a sound
  (safety events `audio.cry` / `audio.alarm` will be the exception), not in quiet hours, daily
  cap. A **sociability** setting (`quiet` / `normal` / `chatty`) on Settings: quiet = never
  speak first, normal = greet after 2 h away (cap 6 / day), chatty = after 30 min (cap 12 / day).
  Everything else (offers on mutual gaze, small talk) is deliberately left blank until we have
  watched this behave.
- *Live page*: "聆聽中" only inside a session; the rail's Conversation card keeps the raw
  `speech open` flag and shows the attention mode.

Todo:
- [ ] `body`: `MotionState.moving_until`, `MotionPose.moving`, `BodySession.moving()` /
  `moving_until()`, `moving` in telemetry.
- [ ] `interaction/frontend.py`: `FrontEndEvent.self_motion`; `attention.py`: idle scan, sound
  glance, cancellation on faces, `snapshot()`; new `initiative.py` (rules, quiet hours, daily
  cap); façade: `_ticks` drives attention, sound glances from rejected IDLE segments, `gaze.mutual`
  subscription → `greet.due`, `set_config()`, captions `listening` gated by state + `speech_open`.
- [ ] `perception/camera.py`: landmark facing test, `gaze.mutual` once per gaze episode;
  `ConfigPerception.mutual_gaze_s`, `mutual_gaze_min_height`; contacts touched on face id.
- [ ] `contact`: migration v3 `contacts.last_seen_ts`, `touch()` / `last_seen()`; interaction
  touches the identified speaker.
- [ ] `config`: `interaction.sociability`, `idle_scan*`, `sound_glance*`.
- [ ] `extensions/robot`: automation `greet` on `greet.due`, `skill_initiative.md`.
- [ ] Dashboard: Settings "Behaviour" card (sociability, idle scan, sound glance), Live idle
  label, rail attention row, telemetry `moving`.
- [ ] Tests, docs (AGENTS yellow pages + "Interaction" design, README / README_CN), screenshots.

---

## [2026-10-27 #37] Progress: befriending landed (block #36)

- [x] `contact`: migration v2 adds `people` and `counters`; `Person` schema, `is_person()`,
  `PERSON_PREFIX`; store `next_person_id / create_person / person / people / touch_person /
  mark_person / move_embeddings / delete_person / prune_people`; session `new_person` (counts
  the revealing utterance), `fold_person`, `person_ready`, `mark_person`, `promote_person`,
  `forget_person`, `prune_people`; `snapshot()["people"]`.
- [x] `perception/camera.py` keeps the largest face's SFace vector at the 1 Hz identify tick;
  `PerceptionSession.local_face_vector()`.
- [x] `interaction`: `_person_for()` (identified person keeps its id; a new voice becomes a
  person in the store, a session guest without one), `_attribute()` folds voice + the face
  whose image azimuth (half FOV 45°) is within 25° of the DoA, publishes `person.ready`
  (NOTICE) once per day per person; `rename_speaker()` after a promotion; `person:n` counts
  as unknown for the strict gate and the gaze trigger; engagement lets another unnamed person
  join under the direction rule (`is_person`).
- [x] `extension`: manifest `automations` → `JobStore.ensure_builtin / delete_builtin` on
  enable / disable. `extensions/robot`: tools `people_seen`, `befriend` (not confirm-gated),
  `decline_befriend`; `skill_befriending.md`; automation `robot.befriend` on `person.ready`,
  delivery `in_person`.
- [x] Dashboard: `GET /api/contacts/people`, `POST /api/contacts/people/{id}/promote`,
  `DELETE /api/contacts/people/{id}`; Contacts page "People seen" table (heard / sessions /
  face frames / last seen / status, Befriend with a name, Forget); `person:n` shown as 訪客 n
  in Live. `app.py` prunes unnamed people daily (7 days).
- [x] Tests: `tests/test_befriending.py` (store lifecycle incl. promotion merge and pruning,
  readiness rules, attribution + ready event with a fake perception bus, manifest automations
  + the three tools through the real extension loader, routes). `pytest -m "not network"`:
  135 passed; ruff / mypy --strict clean.
- [x] Docs: AGENTS.md (contact / interaction / extension yellow pages, robot extension row,
  manifest, "Contact and identification" befriending paragraph), README / README_CN section.
- Verified live after restart: the `robot.befriend` built-in job exists, the three tools are
  registered, `/api/contacts/people` answers. The first real stranger will create `person:1`
  the next time an unknown voice is accepted; the ask happens after the second visit.

---

## [2026-10-27 #36] Todo: befriending — people seen, readiness event, the task, Contacts section

Owner's go (2026-10-27). Implementation of block #35:

- [ ] `contact`: `people` table (migration v2) with `person:n` rows — created / last seen,
  sessions, utterances, asked / declined / ready timestamps; embeddings reuse the `embeddings`
  table under the person id, so `identify_voice()` / `identify_face()` recognise a returning
  stranger through the normal path. API: `new_person(vector)`, `fold_person(person_id,
  voice=…, face=…)`, `note_person_session()`, `people()`, `person(id)`, `person_ready(id)`,
  `mark_ready / mark_asked / mark_declined`, `promote_person(id, name, language)` (moves the
  embeddings to the new contact), `forget_person(id)`, `prune_people(days=7)` (run with the
  daily prune in `app.py`).
- [ ] `interaction`: a `person:n` identification counts as unknown for the strict gate and the
  gaze trigger but is the speaker of the turn; a new voice becomes a person at once (no
  session-only guests when the store is available; the in-memory path stays for tests); every
  accepted utterance folds its voice vector, and the largest face folds when its image azimuth
  matches the DoA and it is large and frontal; sessions are counted per person; when
  `person_ready()` turns true the session publishes `person.ready` (NOTICE) on the perception
  bus and marks it, at most once a day per person.
- [ ] `perception/camera.py`: keep the largest face's SFace vector (`local_face_vector()`), so
  attribution needs no second detection.
- [ ] `extension` manifest gains `automations` (static JSON: name, event, prompt, delivery);
  enable upserts them as built-in event jobs with `origin=extension:<name>`, disable removes
  them (`JobStore.ensure_builtin` / `delete_builtin`).
- [ ] `extensions/robot`: tools `people_seen`, `befriend(person_id, name, language)` (not
  confirm-gated — the owner's call: befriending is the agent's own behaviour),
  `decline_befriend(person_id)`; skill `skill_befriending.md`; automation `befriend` on
  `person.ready`, delivery `in_person`.
- [ ] Dashboard: `GET /api/contacts/people`, `POST /api/contacts/people/{id}/promote`,
  `DELETE /api/contacts/people/{id}`; Contacts page "People seen" table with Promote (asks for
  a name) and Forget; Live / Timeline label `person:n` as 訪客 n.
- [ ] Tests: people store (new / fold / ready / promote / prune), interaction attribution and
  the ready event with a fake contacts object, manifest automations, robot tools, routes.
- [ ] Docs: AGENTS.md (contact / interaction / extension yellow pages, "Contact and
  identification" gets a befriending paragraph, the robot extension row), README.

---

## [2026-10-27 #35] Decision: strangers become acquaintances through a befriending task, not a wizard

Discussed with the owner (2026-10-27) after the first live session. Agreed shape, no code yet:

- **Data first, silently.** The per-session guest clustering of block #34 becomes a persistent
  "people seen" store in `contact`: `person:n` with a voice centroid and sample count, face
  embeddings (the face whose image azimuth matches the DoA while that person speaks, only when
  large and frontal enough), first / last seen, sessions. Every accepted utterance folds into it;
  no prompting ("say three sentences") is needed — spontaneous speech is the better sample.
  Unpromoted people hold vectors only, never memory facts, and expire after 7 days unseen.
- **One rule, not a state machine.** A readiness check (e.g. ≥ 6 utterances over ≥ 2 sessions
  or ≥ 8 in one, ≥ 3 usable face frames, not asked in the last day) publishes `person.ready` on
  the perception bus. That is the only deterministic gate.
- **Befriending is the agent's own behaviour.** An event automation (`trigger =
  event{person.ready}`) runs the main agent with a `befriending` skill: how to open ("我哋好似
  見過幾次喇，你叫咩名？"), echo the name from the local ASR text to confirm, ask whether they
  want to be remembered, back off when declined, do not ask delivery people twice. The commit is
  one tool, `befriend(person_id, name, language)`, which renames the accumulated `person:n` into
  a contact (no re-recording). **No owner confirmation** — the owner decided this is social
  judgement, not an approval flow; the tool is not confirm-gated. The owner keeps after-the-fact
  control on the Contacts page (rename, merge, delete; a "People seen" section with sample
  counts and a Promote button that calls the same tool).
- **Multiple faces.** Attribution accumulates over sessions (DoA ↔ face azimuth, majority), so
  "raise your hand" is a fallback at most; if ever needed, a frame-difference check above the
  face box before any hand / pose model (new dependency).
- Estimated 3–4 days: persistent people store + cross-session clustering, readiness event,
  the job + skill + tool, Contacts section, tests. Waits for the owner's go.

---

## [2026-10-27 #34] Progress: block #33 landed — gaze, faces in the dark, guests, enrollment flow, rail, clips

- [x] Attention (`interaction/attention.py`): no DoA turn on a speech onset; a turn only for an
  accepted segment or the wake name, ≥ 15° hysteresis, never while a face is tracked; a
  proportional servo (`on_face`, 4 Hz, dead band 0.08) toward our own detector's face when the
  daemon's tracker is blind, driven from the front end's 2 Hz `level` events. Breathing
  ±2.5° / 5 mm (was ±1.5° / 3 mm — it did run after Release, it was just hard to see).
- [x] Faces: `contact.brighten_frame()` (gamma lift below 60/255), `embed_voice()` /
  `voice_similarity()`; `perception/camera.py` runs YuNet on a 640 px lifted copy every poll
  (config `perception.poll_hz` 2 → 4), identifies the largest face at 1 Hz, exposes `faces()`
  (normalised boxes + name) and `local_face()`, and uses ours for presence when the daemon
  reports none. The dashboard stream / snapshot are lifted the same way and the Camera card
  draws the boxes. **Limit found**: tonight's room averages 19/255 with a maximum of 96 — pure
  sensor noise after lifting (see the brightened frame sent to the owner); the lift helps from
  about 40/255 upward. Face tracking needs a lamp on; the logic is covered by tests with fakes.
- [x] Guests apart: `InteractionSession._guest_for()` clusters unknown voices by CAM++ embedding
  within the session (threshold = the contacts' voice threshold, running centroids, up to 8),
  `EngagementMachine.on_segment` lets another guest join under the direction rule, turns and
  the timeline carry the guest id, `captions()["heard_by"]` labels the Live transcript
  (contact name or 訪客 n, avatar = first character of the name).
- [x] Contacts: one guided flow — New member → details → three prompted 4 s captures straight
  from the mic (`POST /api/contacts/enroll/voice/record` → `RobotControl.capture()` →
  `ContactSession.enroll_voice`) with peak level per take → face step with the live preview and
  boxes → done; "Enroll voice / Enroll face" per row re-enter a step. Verified live: a test
  member recorded one take at −11.5 dBFS peak (deleted afterwards).
- [x] Rail: Conversation card (engagement machine; `conversation` label) vs Telemetry (`body`
  label: motors, pose, joints, antennas, levels, DoA, face); presence only in Conversation;
  Recording folded into System as one line; Audio = two level bars with peak hold.
- [x] Clips from the ring: `RecordSession.read_mic(start, end)` (open chunk read raw past the
  44-byte header), `InteractionTrace.clip_window()` / `clip_files` / 24 h file prune,
  `InteractionSession.clip_for()` + `clip_source` wired by `app.py` when the WAV ring runs, the
  clip route and both enrollment routes use it — nothing new is written under `audio/`, and
  what is there expires after 24 h. Chunk length stays `recording.chunk_minutes` = 5.
- [x] Tests: `tests/test_attention_and_guests.py` (hysteresis, face priority, servo, guest ids,
  local detector + presence fallback), ring slicing in `test_record_session.py`;
  `pytest -m "not network"` 130 passed; ruff / mypy --strict clean.
- [x] Docs: AGENTS.md yellow pages (`contact`, `perception`, `interaction`, `record`, `body`,
  `dashboard`), README / README_CN rail line, memory notes.

---

## [2026-10-27 #33] Todo: attention, faces in the dark, guests apart, enrollment flow, rail cards, clips in the ring

Owner's first real Live session (2026-10-26 night) raised seven points; what was found:

1. **Head twisting after the second turn.** Not a missing feature: while ENGAGED every VAD
   onset — including the ambient segments later rejected as "filler 嗯" — called
   `attention.on_speech(doa)`, and the XVF3800 direction jumps ±50° between those, so the head
   re-aimed at noise every 0.5 s. The daemon's face tracker, which should have held the gaze,
   was blind: the room frame averages 19/255.
2. **Two strangers.** `_identify()` returns a contact or `None`; every unknown voice in a session
   is attributed to the session's single guest id, and the Live transcript labels every voice
   line "你". Two unknown people are told apart only by direction (sector tolerance 0.6 rad).
3. **Enrollment** is split between Contacts (form) and Listening (tick clips) — awkward.
4. **Breathing after release** does work (commanded z swings ±2.9 mm, measured follows) but
   at ±1.5° / 3 mm it is hard to see.
5. **Status vs Telemetry**: both show `state` — Status = the conversation machine (idle /
   engaged / speaking), Telemetry = the body / motors (awake / asleep). Same word, different
   fields. Recording's `state` is `recording` almost always (`paused` at the disk floor,
   `error`). The scrolling waveform strips should be level bars.
6. **Faces**: the daemon tracker only; nothing drawn on the dashboard; the camera is dark.
7. **Storage**: `recordings/YYYY-MM-DD/HH-MM-SS/{video.mp4, mic.wav, speaker.wav,
   telemetry.jsonl.gz, chunk.json}` already is the per-timestamp layout (5-minute chunks,
   24 h, disk floor); `audio/` (455 MB, 5 720 files) is the per-decision clips of the
   Listening page, kept 7 days — the duplication the owner objects to.

Plan:

- [ ] Attention: no DoA turn on `speech_start`; turn only when a segment is **accepted**, by
  ≥ 15° from the current look, and never while a face is tracked (daemon or ours). Breathing
  ±2.5° / 5 mm.
- [ ] Faces in the dark: `contact.brighten_frame()` (gamma + CLAHE when the mean is low) before
  YuNet; `perception/camera.py` runs our detector at 4 Hz on `body.frame()` and identifies the
  largest face at 1 Hz, publishes `faces` (normalised boxes + name) in the snapshot and a
  `face.track` event; presence falls back to our detection when the daemon sees none;
  `attention.on_face()` servoes the head toward it (small gains, 4 Hz) when the daemon's
  tracker is blind. The dashboard stream / snapshot are brightened the same way; the Camera
  card draws the boxes with names.
- [ ] Guests apart: `ContactSession.embed_voice()` / `voice_similarity()`; a session keeps the
  embedding of each guest; an unknown voice below the similarity threshold becomes `guest:n+1`
  in the same session (DoA rule unchanged); turns, the timeline and the captions carry the
  speaker; Live labels voice lines with the contact name or 訪客 n.
- [ ] Contacts: one guided flow — "New member" → name / language / owner → voice (three
  prompted 4 s captures straight from the mic, `POST /api/contacts/enroll/voice/record`) →
  face (live preview with boxes, capture 5 frames) → done; "Enroll" on each row re-runs the
  voice / face steps; the Listening clip path stays as the expert route.
- [ ] Rail: Status labels `conversation`, Telemetry `body`; presence only in Status; Recording
  folded into System as one line; Audio = two horizontal level bars with peak hold.
- [ ] Clips in the ring: `RecordSession.read_mic(start, end)` slices `mic.wav` across chunks
  (open chunk read raw); decision rows keep `ts` / `duration`; `/api/interaction/clip/{id}`
  and enrollment resolve the clip from the ring when recording is on, so no `audio/` files are
  written (fallback when recording is off); `audio/` pruned at 24 h. Chunk length stays
  `recording.chunk_minutes` = 5 (1 is a config change away).
- [ ] Tests, docs, screenshots.

---

## [2026-10-26 #32] Progress: the monitor rail is persistent beside every page

Owner: "the Live monitor rail is very useful — make it permanent (left of the browser, right of
the tab bar, or on the browser's right) and drop the Robot page's own rail. What do you think?"
Agreed: the rail is the cockpit's instrument panel and belongs on every page; Robot then holds
only the controls, like every other page holds only its content.

- [x] `dashboard_index.html`: the shell is three grid columns — nav · rail · page (left default;
  `rail-right` swaps the order; `rail-hidden` drops the column). The rail markup moved out of
  `#tab-live` to the shell; `#tab-live` is the chat alone; `#tab-robot` is a plain content
  section (Controller, Microphone, Speaker + say, Camera tests) without camera / 3D / telemetry
  cards. A brand-row button (◫) hides / shows the rail; ≤ 1100 px the rail starts hidden and
  shows as an overlay beside the nav.
- [x] `dashboard_live.js`: the `/api/live` WebSocket opens at page load and stays open on every
  tab; `railVisible(on)` pauses / resumes only the MJPEG stream and the WebGL view;
  `subscribe(cb)` hands frames to other scripts (Robot uses it for its level labels).
  `start()` / `stop()` are now transcript-only. `dashboard_robot.js` lost its own feed, camera,
  3D and telemetry code.
- [x] `dashboard_app.js`: rail side (`sidekick.rail`) and hidden state (`sidekick.rail.hidden`,
  default hidden ≤ 1100 px). Asked where a persistent rail belongs, the recommendation (and new
  default) is **right**: the page keeps its left edge when the rail is hidden (and when the nav
  collapses), nav and page stay adjacent, tables and sliders are read from the left with the
  rail as the glance panel at the end (cause left, effect right), two fixed columns on the left
  would leave ~60 % of a 1400 px window to content, and chat apps / IDEs put inspectors right.
  Left stays one click away on Settings.
- [x] Docs: AGENTS.md dashboard yellow page, README / README_CN console section.
- [x] Owner confirmed the right side. Also reported: text runs past the Timeline card. Measured
  in the browser: card 800 px, table 986 px — a delegate error row holds an unbroken JSON
  string (`{"type":"error",…`) that set the content column's minimum width to 516 px. Fix:
  `td.wrap { overflow-wrap: anywhere }` on the free-text / JSON cells only (timeline content,
  decision text, memory text, job prompt, skill description, MCP target, event data) — on
  every cell it collapsed the short columns to one character per line — plus
  `.card { overflow-x: auto }` as the safety net; the rail's cards get `flex: none` because an
  overflow value other than `visible` lets flex items shrink below their content.

---

## [2026-10-26 #31] Progress: Telemetry card on Live, rail-side switch, Memory page

Owner feedback on block #30: (1) the Robot rail's Telemetry card is good — use it on Live too;
(2) should the monitor rail and the working column swap sides? (asked for an opinion);
(3) "I can't find memory on the dashboard".

- [x] `SidekickApp.telemetry(el, frame)` in `dashboard_app.js` renders the card for both rails;
  Live's Status card keeps only the engagement rows (state, session, reason, listening, turn,
  TTS stream, presence) and System keeps providers / agent / onboarding / uptime, so nothing
  is shown twice.
- [x] Rail side: Settings → Appearance gains "Rail right / Rail left" (`localStorage`
  `sidekick.rail`, class `rail-left` on the shell swaps the grid columns and the border on
  Live and Robot; stacked layouts below 900 px ignore it). I recommended right (nav → main →
  detail reads left to right, the composer and sliders stay next to the nav, Claude / ChatGPT
  put their context panels on the right); the owner tried both and chose **left**, so left is
  the default and the switch stays for changing back.
- [x] Memory was only a card inside the Agent page (the two facts stored on 2026-10-26 —
  owner likes milk tea, household likes milk tea — were there). It is now its own **Memory**
  page: facts with the scope resolved to a contact name, kind, time, source id, filter box,
  forget, and a "Remember" form (`POST /api/agent/memory`, `MemoryCreate`); the Agent page
  shows the fact count and points there. Reminders stay under Automations.
- [x] Tests: `test_dashboard_api.py` covers the new route; dashboard tests green; ruff / mypy
  clean.

---

## [2026-10-26 #30] Progress: flat sidebar, Robot page in two columns

Owner feedback on the block #29 screenshots: (1) the sidebar needs no groups; (2) what is
Listening? — it is the voice-pipeline monitor (mic level, engagement machine, every VAD segment's
decision with reason, name score, DoA, duration, text / reply, latency and a playable clip;
ticked clips enrol a voice); a screenshot was sent; (3) the Robot page should be two columns:
the visual monitors in one, the slider / test controls in the other.

- [x] `dashboard_index.html`: the nav is one flat list (same order as before, no group titles);
  the Robot page is a two-column grid — left column Camera (snapshot / video), Body (3D),
  Telemetry; right column Controller, Microphone, Speaker (+ say). Stacks below 980 px.
- [x] Second pass on the owner's note that equal columns look odd: the Robot page now has the
  shape of Live — controls in the main column (Controller, Microphone, Speaker + say, Camera
  tests with the snapshot / clip preview) and the same 320 px monitor rail on the right
  (camera stream, 3D body, telemetry with wrapping values). `#tab-robot` shares the `.live`
  grid and hides `.content` like Live does.
- [x] AGENTS.md dashboard yellow page updated; tests unchanged.
- [x] Found on the Listening screenshot: `/api/body/frame.jpg` (Contacts / Setup camera image)
  returned 404 now and then — the SDK hands each frame out once. `BodySession.frame(wait_s)`
  retries for up to `wait_s` (the route passes 0.5 s; `RobotControl` uses it too).

---

## [2026-10-26 #29] Progress: console v3 landed — rail with the health cards, Robot tab with a controller

Everything in block #28 is in the tree and verified on the Lite; screenshots sent to the owner.

- [x] Shell: no top bar, "Sidekick" brand, no footer, theme switch on Settings (Appearance),
  rail 320 px / 13 px type. Health tab gone; its figures are rail cards (Last turn, System,
  Recording) fed by the 1 Hz health poll, and its Speak card moved to Robot.
- [x] `body`: `MotionCommand.manual`, `MotionState.manual / body_yaw / dropped`, `LookTarget.z`,
  `MotionPose.body_yaw / manual` (telemetry rows and `/api/live` carry both); `control` and
  `pose` commands in the motion owner, limits in `schemas.py` (`YAW/PITCH/ROLL/Z/BODY_YAW/
  ANTENNA_LIMIT`); `BodySession.take_control / release_control / control_status /
  manual_pose`, `manual=True` on `gesture / express / breathing`.
- [x] `interaction`: `hold()` / `release_hold()` / `held`, `snapshot()["held"]`; `say()` leaves
  attention alone while held.
- [x] `dashboard/robot.py` `RobotControl` + routes `/api/robot`, `/control`, `/pose`,
  `/gesture`, `/express`, `/breathing`, `/test/mic|speaker|snapshot|video`, `/file/{name}`;
  `record` façade exports `VideoWriter`, `WavTrack`, `encoder_name`.
- [x] `dashboard_robot.js` + `#tab-robot` (camera + Snapshot / Record video, 3D body, telemetry
  panel, controller with seven sliders at ≤ 10 POSTs / s, gestures, emotion picker, breathing,
  microphone / speaker cards, say text).
- [x] Tests: `test_dashboard_robot.py` (hold gating, pose reaches the null backend incl. body
  yaw and height, dropped-command count, gesture / emotion / breathing, mic capture with a
  real-time feeder, tone + replay, snapshot, video (skips the assertion when GStreamer is
  missing), file allowlist), manual mode in `test_body_null_session.py`, hold in
  `test_interaction_session.py`, page markers in `test_dashboard_live.py`.
  `pytest -q -m "not network"`: 126 passed; ruff / format / mypy --strict clean.
- [x] Docs: AGENTS.md (yellow pages `body`, `interaction`, `dashboard`, `record`; "Dashboard and
  CLI"), README.md / README_CN.md (status, console section).

Measured on the Lite (21:00, dark room):

| item | value |
|---|---|
| Take control → pose yaw 25°, pitch −10°, body yaw 40°, antennas ∓60° | measured 26.4° / −9.5° / body 39.4° / −60.1° / 59.9° within ~1 s; 3D view and camera confirm the body turned |
| microphone test 3 s | 48 000 samples, peak −2.4 … 0 dBFS (clipped once), RMS −26 … −30 dBFS → the input is hot in this room, worth a listen in the Robot tab |
| speaker tone 1 s | first push 0 ms, drained in 1.02 s |
| snapshot | 1920 × 1080 JPEG, 45 KB |
| video 5 s | 49 frames @ 10 fps 1920 × 1080 through `vtenc_h264_hw`, 22 KB (dark room) + 4.9 s mic WAV |

Found while testing: the SDK's `media.get_frame()` hands each frame out once, so a snapshot
taken right after the recorder's read saw `None`; `RobotControl._grab_frame()` retries for up to
0.5 s (the video loop already tolerated it).

---

## [2026-10-26 #28] Todo: console v3 — no top bar, narrow rail with the health cards, a Robot tab with a controller

Owner feedback on the block #27 screenshots:

1. The Live top bar is unnecessary; if the awake state matters it belongs in a rail card.
2. The monitor rail is too wide.
3. The rail is for live data, so every other live figure goes there too — there is no need for
   a separate Health tab.
4. A **Robot** tab is needed: it aggregates the robot's live data and offers a controller that
   "hijacks" the robot to test each capability — microphone, speaker, camera photo, video
   recording, and motion of the body, head and antennas.
5. The sidebar shows only "Sidekick" at the top; the footer carries nothing useful (the awake
   state is visible on Live) and goes.

Plan:

- [ ] Shell: drop the top bar (the active nav entry names the page; `document.title` follows),
  brand = "Sidekick" + collapse button, no footer; the theme switch moves to Settings
  ("Appearance": system / light / dark). Rail width 400 → 320 px, 13 px type.
- [ ] Rail cards: Camera, Body (3D), Audio, Status (engagement) as before, plus **Last turn**
  (text in / out, ASR / first token / first audio / total), **System** (version, uptime,
  daemon, motors, firmware, onboarding, bound slots) and **Recording** (state, chunk, size,
  free disk) fed by the 1 Hz health poll. Health tab removed; its "Speak" card moves to Robot.
- [ ] `body`: manual control in the motion owner. `MotionCommand.manual` marks controller
  commands; while `MotionState.manual` is set every unmarked command (attention, expressions,
  robot tools) is dropped and counted, breathing pauses, and a `pose` command carries the full
  target: head yaw / pitch / roll / z, body yaw, both antennas, eased like `look()`. Body yaw is
  sent to the daemon only while held and for a few seconds after release (easing back to 0) so
  the existing behaviour (never sending it) is unchanged otherwise. `LookTarget` gains `z`,
  `MotionPose` gains `body_yaw` (telemetry rows carry it). Clamps: yaw ±60°, pitch ±35°,
  roll ±30°, z ±15 mm, body yaw ±150° (URDF limit ±160°), antennas ±150°.
  `BodySession.take_control(holder)` / `release_control()` / `control_status()` /
  `manual_pose(...)`; `gesture`, `express`, `breathing` take `manual=True`.
- [ ] `interaction`: `hold(reason)` / `release_hold()` — while held the front-end events (speech,
  keyword, touch) are dropped, a running turn is cancelled, `say()` skips the attention change,
  and `snapshot()` reports `held`; release restores the idle posture through `Attention`.
- [ ] `dashboard/robot.py` `RobotControl`: take (body control + face tracking off + interaction
  hold) / release, pose, gesture, express, breathing, and the tests — mic capture N s to WAV
  with peak / RMS, speaker tone / sweep / replay of the last capture, camera snapshot to JPEG,
  video clip N s (H.264 through `record.VideoWriter` + mic WAV). Files live in
  `.derived_data/cache/robot/` (last 20 kept) and are served by `/api/robot/file/{name}`
  (allowlisted names). One test at a time (409 when busy); pose needs the hold (409 otherwise).
- [ ] Routes: `GET /api/robot`, `POST /api/robot/control`, `/pose`, `/gesture`, `/express`,
  `/breathing`, `/test/mic`, `/test/speaker`, `/test/snapshot`, `/test/video`,
  `GET /api/robot/file/{name}`.
- [ ] `dashboard_robot.js` + `#tab-robot`: camera stream with Snapshot / Record buttons, the
  3D body, a telemetry panel (state, daemon, motors, firmware, commanded vs measured head
  pose as Euler + height, the seven measured joints, antennas commanded / measured, levels,
  DoA, face, presence, interaction state / held), the controller (Take control / Release,
  sliders for head yaw / pitch / roll / height, body yaw, antenna right / left, Centre, the
  five gestures, emotion picker + Play, breathing toggle) and the capability tests (mic record
  → stats + `<audio>`, speaker tone / sweep / replay, say text + expression, snapshot
  `<img>`, video `<video>`), all on its own `/api/live` connection while the tab is open.
- [ ] Tests: motion owner manual mode on the null body; robot routes (hold gating, pose, mic /
  speaker / snapshot / video / file allowlist); page markers; interaction hold.
- [ ] Docs: yellow pages (`body`, `interaction`, `dashboard`), "Dashboard and CLI", README /
  README_CN console section; screenshots to the owner; artifact page updated.

---

## [2026-10-26 #27] Progress: Live as a chat application, console restyled after Claude / ChatGPT web

Owner feedback on the block #26 screenshots: (1) the centre column of Live must be the main
conversation, (2) the right column lists the monitoring components one under another (camera,
3D body, …), (3) the whole console should follow the look of the Claude / ChatGPT web apps, with
a palette of our own.

Done (no server change):

- `dashboard_index.html` rewritten around a three-column shell: nav rail (248 px, collapsible),
  conversation centre (messages with avatars, user turns as bubbles on the right, Bobby's
  replies as plain text on the left, a pulsing live line for listening / thinking / saying, a
  pinned rounded composer with Enter-to-send and Shift+Enter newline, an empty state that says
  how to start), and a 400 px monitor rail with the cards stacked: Camera, Body (3D), Audio
  (mic / speaker strips), Status (key / value), Events. Below 900 px the rail stacks under the
  conversation.
- Visual system: light theme by default (cool neutral greys, white cards with 1 px borders and a
  soft shadow, indigo accent), dark theme from the system preference or the sidebar toggle
  (system → light → dark, remembered in `localStorage`), 14 px radii, pill state badges, SVG nav
  icons tinted by state. Every colour is a CSS token; the canvases (peak strips, replay tracks)
  read the tokens at draw time so they stay legible in both themes.
- Typed replies strip `[express:…]` tags and show the expression in the message meta line.
- Verified live with a typed turn through the composer (MiniMax answered in Cantonese), dark and
  light screenshots of Live and Replay sent to the owner; dashboard tests unchanged and green.

---

## [2026-10-26 #26] Progress: console v2 landed — sidebar, Live with 3D body, 24 h recording, Replay

Everything in block #25 is in the tree and verified on the Lite; screenshots sent to the owner.
Verification: `pytest -q -m "not network"` 122 passed (7 new: live feed, recorder, replay routes),
`ruff check` / `ruff format --check` clean (151 files), `mypy --strict src` clean (104 files),
log / trace secret scan clean.

- [x] A: sidebar shell (`dashboard_index.html`): four groups, SVG icons, status dots (Live state,
  Agent error, Setup pending, Replay paused / error), collapse to a 56 px rail remembered in
  `localStorage`, deep links unchanged; Agent split into Agent / Automations / Skills & MCP; the
  typed chat box moved to Live (replies land in the transcript, Timeline keeps the history).
- [x] B: `BodySession.telemetry()` (motion owner `pose_snapshot`, SDK cached head pose + joints,
  `AudioPump` / `AudioPlayer` level + 20 ms peak rings, `AudioPlayer.subscribe()` speaker tap),
  `InteractionSession.captions()` / `telemetry()` (open segment, last heard via `run_turn`'s
  `on_text_in`, said = `pipeline.current_text`), `dashboard/live.py` (`LiveFeed.frame()`,
  `mjpeg_stream()`), routes `/api/live` (WebSocket, 1–20 Hz), `/api/live/frame`,
  `/api/body/stream.mjpg` (640–1920 px, measured 8 fps), `dashboard_live.js` (peak strips,
  status line, transcript with 聆聽中… / 思考中… live line, events). Live frame on the Lite:
  measured joints `[yaw 0.018, ±0.54…0.57 × 6]`, antennas `[-0.176, 0.173]`, mic −38 dBFS.
- [x] C: `body/model.py` (URDF → 11 groups / 29 allowlisted meshes, 7.2 MB, anchors and horn balls
  for six rods), `/api/body/model`, `/api/body/mesh/<name>.stl` (allowlist, 1-day cache),
  `dashboard_robot3d.js` (Three.js r160 module + import map; views per container, shared geometry
  cache; head by measured 4×4 pose, torso + horns by measured joints, antennas by angle, rods as
  cylinders; OrbitControls). Renders in headless Chrome (SwiftShader) and in the screenshots.
- [x] D: `record` module (`record.py`, `schemas.py`, `video.py`, `tracks.py`, `chunks.py`),
  `ConfigRecording` (+ `pi` preset: FLAC, 960×540 @ 8 fps, 600 kbps, 5 GB floor),
  `StorageLayout.recordings_dir`, backup excludes `recordings`, `app.py` wiring (start after
  perception, stop first), Health card, `sidekick record status|prune`, tests on the null body
  (rolling, tracks, telemetry, retention, disk floor, presets, CLI).
- [x] E: `dashboard/replay.py` (`chunk_tracks()`: WAV peak envelopes, dialogue / decisions /
  events by time range through new `between()` helpers on `TraceTable`, `DialogueStore`,
  `PerceptionSession.stored_between`), routes `/api/record`, `/chunks`, `/{id}`, `/telemetry`,
  `/tracks`, `/file/{name}` (Starlette range requests → 206), `dashboard_replay.js` (288-cell day
  strip, video + two `<audio>` tracks kept within 0.2 s, canvas tracks, click-to-seek, 3D from
  the telemetry row, prev / next, auto-advance, mute per track).
- [x] Docs: AGENTS.md (layer 2 + import row for `record`, yellow pages for `body`, `interaction`,
  `dashboard`, `record`, `app.py`, `cli.py`, `config`, `storage`, new "Recording and replay"
  section, dashboard / CLI / dependencies text), README.md / README_CN.md (status, console
  section, layout, getting started).

Measured on the Lite (dark room, evening):

| item | value |
|---|---|
| first live chunk (272 s, closed cleanly by SIGINT) | 2 721 frames @ 10 fps, mic 272 s, speaker 272 s (padded), 2 721 telemetry rows, 18.3 MB |
| video | 0.73 MB / 272 s in the dark room (≈ 0.2 GB / day); the 1 Mbps cap gives ≈ 11 GB / day in daylight |
| audio | 8.7 MB per track per 272 s → ≈ 2.8 GB / day each |
| telemetry | 136 KB gzip per 272 s → ≈ 45 MB / day (1.36 MB raw before gzip) |
| sidekick process CPU with the recorder | ≈ 25 % of one core (VAD + KWS + 10 fps resize/encode push) |
| MJPEG 640 px | 8 fps, ≈ 4.8 KB per frame in the dark room |

Decisions taken while building (within block #24's envelope):

- MP4 is **fragmented** (`mp4mux fragment-duration=2000 streamable=true`) instead of faststart:
  a crash or power cut loses ≤ 2 s and the open chunk already plays (cv2 decoded 2 201 frames
  from a chunk still being written); Chrome plays and seeks it.
- Telemetry is gzipped at chunk close (10× smaller); the open chunk keeps the raw `.jsonl`;
  `RecordSession.telemetry()` reads both. `chunk.json` is refreshed every 30 s so the CLI and
  other processes see progress.
- The speaker track is padded with silence whenever the player is idle so both WAVs stay on the
  wall clock without an audio clock of their own.
- Live uses the measured joints when the SDK streams them (the six Stewart motors sit at
  ±0.54–0.57 rad at rest, which the URDF zero pose does not show), so the horns inside the shell
  are right even though they are hidden; rods stay straight cylinders.
- Found and fixed while watching captions: the front end dropped a too-short VAD onset without a
  `speech_end`, so "listening" stayed on; it now emits a segment-less `speech_end`.
- Screenshots of dynamic pages (WebSocket, MJPEG, WebGL) need real time, not Chrome's
  `--virtual-time-budget`; a DevTools-protocol helper in the scratchpad drives headless Chrome
  with SwiftShader and captures console errors.

Open for the owner's review: the camera looks black in the screenshots because the room was
dark; the 3D view's camera framing and colours; whether the transcript should also list rejected
segments; the recording defaults (720p @ 10 fps, 24 h, 20 GB floor) and the sidebar grouping.

---

## [2026-10-26 #25] Todo: console v2 build — owner confirmed block #24 as proposed

Owner reply (2026-10-26): "ok, start the dashboard work; send screenshots again when done." The
seven decisions in block #24 stand as proposed (Live first with the chat box, 720p @ 10 fps,
WAV with a FLAC option, vendored Three.js, simplified 3D, 5-minute chunks under the home,
build order A+B → C → D → E). Still no commit until the owner's acceptance.

Facts added by the first spike (before code):

- Forward kinematics over the SDK URDF at the zero configuration puts the `head` frame at
  identity rotation, z = 0.1496 m above the foot; the SDK's rest pose (`set_target(head=eye(4))`)
  is `head_z_offset = 0.177` m, so a reported head pose `H` renders as `T(0, 0, 0.177) · H`.
  Head meshes are expressed in the `xl_330` link; the fixed `head_frame` joint maps them into the
  `head` frame. Antenna joints and the five rod anchors (`closing_i_2`, plus the `xl_330` origin
  for leg 6) are fixed in that same frame; the six motor horns are fixed in `body_down`; a rod's
  ball sits at (0.04, 0, 0.007) in its horn frame. STL meshes are in metres, binary, ~300 KB each.
- The SDK WebSocket client caches the daemon's state stream, so `get_current_head_pose()` and
  `get_current_joint_positions()` (7 head joints = body yaw + 6 Stewart motors, 2 antennas) are
  free reads: the 3D view can rotate the real motor horns and place the measured head pose, and
  the rods become straight cylinders between horn ball and head anchor (no platform solve).
- Three.js 0.160.0 (MIT) is vendored as `dashboard_three.module.min.js` (655 KB) with
  `dashboard_stl_loader.js` and `dashboard_orbit_controls.js` from its examples; the page maps
  the bare specifier `three` with an import map. Owner sign-off: block #24 decision 4.

Checklist (ticked in the Progress block that follows):

- [ ] A: sidebar (groups, collapse to a 56 px rail, `localStorage`, status dots), Agent split into
  Agent / Automations / Skills & MCP, chat box moved to Live.
- [ ] B: `body` telemetry (`BodySession.telemetry()`, speaker tap, peak rings), interaction
  captions (`InteractionSession.captions()`), `dashboard/live.py` (10 Hz WebSocket frames, MJPEG),
  routes `/api/live`, `/api/body/stream.mjpg`, Live tab.
- [ ] C: `body/model.py` (URDF → display model), `/api/body/model`, `/api/body/mesh/<name>.stl`,
  `dashboard_robot3d.js`, Live integration.
- [ ] D: `record` module, `recording` config section, `app.py` wiring, CLI `record status|prune`,
  Health card, tests on the null body.
- [ ] E: Replay tab + `/api/record/*` routes (days, chunks, media with range requests, tracks).
- [ ] Docs (AGENTS.md import table + yellow pages + dashboard section, READMEs), verification
  checklist, screenshots to the owner.

---

## [2026-10-26 #24] Discussion: operator console v2 — sidebar, Live tab with 3D body, 24 h recording and replay

Owner request (2026-10-26, after reviewing the dashboard screenshots), restated:

1. **Navigation**: move the tabs from the top bar to a **left sidebar** that can collapse to an
   icon rail, so the content keeps the full width when wanted and the list can grow.
2. **First tab = the main conversation ("Live")**: the live camera view, microphone and speaker
   level / waveform curves, live ASR and TTS captions, the body pose, and ideally a **3D Reachy
   Mini** that moves with the real pose data in real time.
3. **24 h operation and recording**: the robot runs around the clock, so keep the last 24 h of
   everything — camera video, microphone audio, speaker audio, body pose, agent data — in
   time-sliced chunks stored per directory; the dashboard gets a **review entry** like a
   broadcast control room: video plus several tracks, a scrubber to move through time, and the
   3D robot showing the pose at that moment.

Facts checked on the dev Mac before designing:

- GStreamer in the venv (pulled by `reachy-mini`) has `appsrc`, `videoconvert`, `vtenc_h264_hw`
  (Apple hardware H.264), `x264enc`, `openh264enc`, `h264parse`, `mp4mux`, `matroskamux`,
  `splitmuxsink` (time-based file splitting), `opusenc`, `flacenc`, `wavenc`, `avdec_h264`. No
  `ffmpeg` binary. So recording needs **no new Python dependency**.
- The SDK ships `descriptions/reachy_mini/urdf/robot.urdf` + STL meshes and the MJCF model, and
  exposes `get_current_head_pose()`, `get_current_joint_positions()`,
  `get_present_antenna_joint_positions()`.
- Camera frames arrive as 1920×1080 BGR arrays (JPEG ≈ 83 KB). Mic is a 16 kHz mono fan-out
  (`BodySession.subscribe_audio`), speaker PCM passes through `AudioPlayer`, the motion owner
  holds the commanded pose at 30 Hz. Free disk: 643 GB.

### Proposed design

**A. Sidebar.** `aside` with grouped entries — Operate (Live, Health, Listening), Converse
(Timeline, Agent, Automations, Skills & MCP, Channels, Contacts), Configure (Extensions,
Settings), Inspect (Replay, Traces, Logs) — each with an icon and an optional status dot (engaged
session, extension error). A collapse toggle switches to a 56 px icon rail; the state is kept in
`localStorage`. Tab logic (`data-tab` buttons, `#hash` deep links) is unchanged. Agent is split
into Agent / Automations / Skills & MCP as AGENTS.md already lists them.

**B. Live tab** (first tab, the main conversation). Layout: camera on the left (MJPEG stream
`/api/body/stream.mjpg`, 640 px wide at ~8 fps, JPEG-encoded server-side with OpenCV), the 3D body
on the right, under them two level meters with scrolling waveform strips (mic, speaker), the
engagement state pill, and a conversation column: ASR captions (final text per segment, with a
"listening…" placeholder while a segment is open), TTS captions growing as sentences are sent
(`pipeline.current_text`), and the existing chat box for typed turns. One WebSocket
`/api/live` pushes JSON frames at 10–20 Hz: `{level: {mic, speaker, mic_wave[64],
speaker_wave[64]}, pose: {head: [x, y, z, roll, pitch, yaw], antennas: [l, r], body_yaw,
measured: {...}}, state, captions, events}`. Starlette's WebSocket support comes with FastAPI, so
no new dependency.

**C. 3D body.** Three.js (`three.min.js` + `STLLoader`) vendored as flat files
`dashboard/dashboard_three.min.js` / `dashboard_stl_loader.js` so the page works offline; the STL
meshes are served read-only from the installed SDK package (`/api/body/model/<name>.stl`,
allowlisted). v1 is a **simplified kinematic view**: base and body (yaw), head assembly placed by
the 6-DoF head pose, antennas by angle, Stewart legs drawn as straight links between the plate
anchor points taken from the URDF (no full platform solve). Commanded pose drives it at 10 Hz;
measured head pose is added if `get_current_head_pose()` proves cheap enough over the daemon
link (to verify in the first spike).

**D. Recording (`record` module, Layer 2).** New core module `src/sidekick/record/` that may
import `log`, `storage`, `audio`, `body`; `app.py` injects a telemetry provider callable so it
never imports `interaction`. Chunks of **5 min** (288 per day) under
`.derived_data/recordings/YYYY-MM-DD/HH-MM-SS/`:

```text
video.mp4        H.264 (vtenc_h264_hw on macOS, x264enc/v4l2h264enc elsewhere), 1280×720 @ 10 fps,
                 ~1 Mbps  → ≈ 11 GB / 24 h   (GStreamer appsrc → videoconvert → encoder → h264parse
                 → splitmuxsink max-size-time=5 min)
mic.wav          16 kHz mono PCM16 written with stdlib `wave`      → ≈ 2.7 GB / 24 h
speaker.wav      same, the PCM pushed to the robot speaker          → ≈ 2.7 GB / 24 h
telemetry.jsonl  10 Hz rows: ts, commanded head pose, antennas (cmd + measured), body yaw,
                 mic/speaker dBFS, engagement state, speaking, ducked, DoA, face target → ≈ 100 MB / 24 h
chunk.json       start / end ts, counts, encoder, errors
```

Total ≈ 17 GB per 24 h on the Mac defaults; `recording.retention_hours` (default 24) prunes the
oldest chunk directories; a free-disk floor (default 20 GB) pauses recording with a Health
warning instead of filling the disk. Settings also carry resolution, fps, bitrate, `audio_codec`
(`wav` default; `flac` via GStreamer for the Pi where disk is small) and the recordings root (an
external disk can be pointed at). Agent data (dialogue, tool steps, decisions, traces, events)
is already timestamped in SQLite and is queried by time range at review; nothing is duplicated.
The recorder survives daemon restarts (no frame → skip, re-open pipeline on error) and starts /
stops with `sidekick run`; `sidekick record status|prune` for the CLI.

**E. Replay tab.** A day strip of chunks (288 cells, coloured by activity), a `<video>` for the
selected chunk (range requests), and stacked tracks under it rendered on canvas: mic and speaker
waveforms from server-computed peaks (`/api/record/<chunk>/peaks`), engagement state band,
dialogue / ASR / TTS caption markers, perception events, tool calls. A scrubber maps
`video.currentTime` to the absolute timestamp, which selects the telemetry row for the 3D body
and the meters; the audio tracks can be muted individually; playback auto-advances to the next
chunk. Same 3D component as Live.

### Decisions to confirm with the owner

1. Live replaces Health as the first tab and hosts the typed chat box; Timeline stays as history.
2. Video default 1280×720 @ 10 fps ≈ 11 GB / day with 24 h retention (1080p would be ≈ 25 GB).
3. Audio as WAV chunks (simple, browser-native) on the Mac; FLAC option for the Pi.
4. Vendoring Three.js (~650 KB of JS) into `dashboard/` so the console works offline.
5. 3D v1 = simplified kinematics (no Stewart platform solve); legs as straight links.
6. 5-minute chunks under `.derived_data/recordings/`, configurable root.
7. Build order: A + B (sidebar, Live with meters / captions / state, MJPEG) → C (3D) → D
   (recorder) → E (Replay). Each step is verified live before the next.

### Checklist (pending confirmation)

- [ ] A: sidebar layout, groups, collapse, status dots; split Agent into three pages.
- [ ] B: `/api/live` WebSocket, MJPEG stream, Live tab (camera, meters, waveforms, captions,
  state, chat).
- [ ] C: vendored Three.js + STL loader, `/api/body/model/*`, kinematic body, Live integration.
- [ ] D: `record` module (video / audio / telemetry writers, chunk index, retention, disk floor),
  config section, CLI, health, tests with the null body.
- [ ] E: Replay tab, peaks / telemetry / time-range APIs, 3D scrub.
- [ ] Docs: AGENTS.md (allowed-import row for `record`, yellow pages, dashboard section),
  READMEs, PLAN progress.

---

## [2026-10-26 #23] Progress: Phase 6 landed — wizard, profiles, services, backup; roadmap complete

Checklist from block #22, all done. The roadmap (Phases 0–6) is complete; awaiting the owner's
acceptance review before any commit.

- [x] Dashboard **Setup** tab (onboarding wizard, six steps, opens automatically while
  `onboarding.completed` is false) over new write routes `/api/onboarding`,
  `/api/config/credentials` (write-only, never echoed), `/api/config/slot`, `/api/config/
  languages`, `/api/config/probe`, `/api/config/tv`; writes re-apply the service backends so the
  test turn works without a restart. `sidekick run` logs the wizard URL while pending.
- [x] `init --preset default|dev|lite-mac|wireless|pi` via `ConfigSession.preset_spec`;
  `profile_of()` for `doctor`, which now also checks free disk, profile-specific pieces
  (`webrtcbin` for Wireless, camera device on ARM Linux), the dashboard port, onboarding and the
  login service.
- [x] `service install [--dry-run]|uninstall|status` (launchd agent / systemd user unit running
  `sidekick run` from the repo root with `SIDEKICK_HOME`); `backup create|restore [--force]`
  (`StorageSession.backup/restore`, excludes models / cache / logs / extension state, safe
  extraction, config.json back to 0600).
- [x] Daily trace pruning (10 days) as an `app.py` maintenance task.
- [x] Content-policy refusals from the LLM provider (MiniMax `1026 input new_sensitive`) become a
  polite spoken refusal instead of an error reply (`REFUSAL_TEXT` in `agent/schemas.py`).
- [x] Tests: wizard routes (write-only credentials, slots, languages, TV zone, steps,
  completion), presets, `init --preset`, service unit rendering, backup round-trip (library and
  CLI), content refusal. Suite: **114 offline tests pass**; `ruff`, `mypy --strict` clean.
- [x] Docs: AGENTS.md yellow pages (`cli.py`, `dashboard`, `storage`, `config`, `app.py`),
  "Dashboard and CLI" section; READMEs.

Live on the Mac with the Lite: `sidekick doctor` 0 problems (profile lite-mac, 690 GB free,
dashboard port in use by the running service, onboarding completed, service not installed);
`service install --dry-run` prints the plist without writing it; `backup create` wrote 25 MB with
config + 11 databases + audio + extensions; the restarted `sidekick run` serves `/api/onboarding`
(MiniMax configured, 6 Cantonese voices, tts.primary bound) and the Setup tab.

Fix noted during the FastAPI work: request models must be module-level — a pydantic model defined
inside `build_router` is read as a *query* parameter under `from __future__ import annotations`.

**Addendum (same day, later):** the content-refusal change listed above had *not* actually
landed when this block was written — the editing script aborted on an earlier assertion and the
later edits in it were silently skipped; the live run kept surfacing the raw 422. Re-applied and
verified: unit test passes and the dashboard chat "有咩新聞？" now answers
「呢個話題我唔方便講，講下其他嘢好唔好？」 with a `content refused by provider` warning in the log.
Also added while taking screenshots for the owner: dashboard deep links (`/#listen` opens that
tab) and a dark-theme style for plain buttons (they were rendering with the browser default).

### Owner acceptance notes (decisions left open on purpose)

1. Turn ASR: local SenseVoice (default, ~100–160 ms) vs MiniMax cloud (2.4–2.8 s, shadow-traced).
2. `service_tier: priority` for MiniMax LLM saves ~0.3 s first token; pricing to confirm.
3. Speaker volume 70 (echo guards verified at 70; 100 produced false barge-in stops).
4. Live channel tests need a Telegram bot token and a WeChat phone scan; both are unit-tested only.
5. Gaze trigger stays off until household voices are enrolled; a quiet interrupter over the
   robot's voice is still masked — tune on the Listening monitor with real voices.
6. MiniMax (domestic) refuses Chinese-politics news items (code 1026); the news extension's
   default feeds include BBC Chinese, so consider another feed or the overseas region.
7. The MiniMax key pasted into chat earlier should be rotated.

---

## [2026-10-26 #22] Todo: Phase 6 — hardening: onboarding wizard, Wireless / Pi profiles, services, backup

### Decisions

- **Onboarding wizard** (dashboard, first run when `onboarding.completed` is false): pages
  1 household language + voice (probe TTS with a sample sentence), 2 provider + credentials with
  Save & Probe (reuses `ConfigSession.probe`), 3 members (create contacts; voice enrollment from
  the listening monitor, face from the camera snapshot), 4 TV zone + DoA sector drawn on the
  camera snapshot (`contacts.tv_zone`, `interaction.tv_sector`), 5 channels (Telegram token +
  pairing code, WeChat login status), 6 test turn (`/api/say` + the listening monitor). The
  wizard writes the spec through `/api/config/*` routes and marks `onboarding.completed`; `sidekick
  run` shows the wizard URL in its log until completed. Credentials are set through
  `/api/config/credentials` (write-only; never echoed).
- **Profiles** are config presets written by `sidekick init --preset <name>`: `lite-mac`
  (today's defaults), `wireless` (`body.host reachy-mini.local`, `media_backend webrtc`,
  `manage_daemon false` because the daemon runs on the robot), `pi` (Lite on a Raspberry Pi:
  `asr.local` SenseVoice int8 stays, `kws` on, `interaction.pre_roll_s 0.7`, perception poll
  1 Hz, `vad.primary` threshold 0.4, heartbeat 60 min). `doctor` reports which profile is active
  and checks the pieces each needs (GStreamer `webrtcbin` for Wireless, `libcamera`/`v4l2` on
  Pi, disk space, model files).
- **Services**: `sidekick service install|uninstall|status` writes a launchd agent
  (`~/Library/LaunchAgents/com.weij.sidekick.plist`, `RunAtLoad`, `KeepAlive`, logs under the
  home) on macOS and a systemd user unit (`~/.config/systemd/user/sidekick.service`) on Linux;
  both run `sidekick run` from the repository root with `SIDEKICK_HOME` set.
- **Backup / restore**: `sidekick backup create [path]` writes a tar.gz of the home without
  `models/`, `cache/`, `logs/` (config incl. secrets, every `*_v1.db`, audio clips, extensions,
  extension state); `sidekick backup restore <path>` extracts into an empty home (or with
  `--force`). Models are re-downloaded by `doctor --fetch-models`.
- Hardening: `doctor` gains checks for free disk, the audio DSP (already), the dashboard port,
  and the installed profile; `run` logs the wizard URL; trace pruning for the service traces
  (10 days) runs at start and daily from the scheduler as a built-in job.

### Checklist

- [ ] Dashboard wizard page + `/api/config/credentials`, `/api/config/slot`, `/api/config/
  languages`, `/api/onboarding/complete`; `app.py` logs the wizard URL.
- [ ] `init --preset lite-mac|wireless|pi`; `doctor` profile checks; `service install|uninstall|
  status`; `backup create|restore`; trace pruning job.
- [ ] Tests: wizard API routes, preset specs validate and probe-build, service file rendering,
  backup round-trip in a temp home, prune job.
- [ ] Docs: AGENTS.md (dashboard, cli, config yellow pages; "Dashboard and CLI" section),
  READMEs (getting started with the wizard), PLAN progress; final acceptance summary for the owner.

---

## [2026-10-26 #21] Progress: Phase 5 landed — extension module and the bundled four

Checklist from block #20, all done.

- [x] `extension/`: manifest validation, package-style loader (relative imports inside an
  extension work), registry, lifecycle (`install` from path or git, `enable`, `disable`,
  `update`, `remove`, `set_settings`), registration bridge into `agent` (tools, skills, MCP,
  subagent) and `perception` (watchers), masked secrets in the snapshot.
- [x] Bundled `robot` (7 tools, skill), `news` (feeds port from Scoop: RSS/Atom/JSON Feed,
  Hacker News, Telegram; watcher; 3 tools; `news` subagent; `briefing` skill), `media`
  (qBittorrent + Jellyfin tools, download watcher, subagent; off until configured), `home`
  (Home Assistant tools incl. confirm-gated sensitive domains, state watcher, subagent; off until
  configured). Conversational voice enrollment: `enroll_voice` tool + `InteractionSession.
  start_enrollment` learns the next utterances of the current speaker.
- [x] `app.py` loads extensions last with a context carrying every peer; CLI `ext list|enable|
  disable|install|remove|set`; dashboard Extensions page (status, settings forms from the
  manifest schema, enable/disable/update/remove, install).
- [x] Tests: lifecycle round-trip with a toy extension (tools, skill, subagent, watcher,
  settings, masking, install/remove), bundled manifests, robot tools on the null body, feed
  parsers on fixtures, HN over mocked HTTP, media/home tools over mocked HTTP. Suite: 109
  offline tests; `ruff`, `mypy --strict` clean.

Live (dashboard chat → main agent): "做個開心嘅表情" → `[express:happy]` performed; "邊個喺度呀？"
→ `who_is_here` → "我睇唔到有人喎"; "有咩新聞？" → `delegate(news)` → `news_latest` + `skill_read`
→ MiniMax refused the request with `1026 input new_sensitive` because the BBC Chinese top story
was about Chinese politics (domestic endpoint content policy). The refusal now becomes a polite
"呢個話題我唔方便講" instead of an error reply (see the follow-up fix below).

---

## [2026-10-26 #20] Todo: Phase 5 — extensions: `extension` module and the bundled four

### Decisions

- `extension` module (layer 4): `manifest.py` (pydantic `ExtensionManifest` from
  `extension.json`: `name`, `version`, `description`, `tools`, `watchers`, `skills`, `mcp`,
  `subagent`, `settings` JSON schema), `loader.py` (import `tools.py` / `watchers.py` from a
  directory with `importlib`, exposing `TOOLS: Callable[[ExtensionContext], list[Tool]]` and
  `WATCHERS: Callable[[ExtensionContext], list[Watcher]]`), `registry.py` (`extension_v1.db`:
  installed, enabled, settings values; secrets in settings masked on the dashboard), and the
  façade `ExtensionSession` with the lifecycle `install` (from `extensions/`, a path or a git URL
  into `.derived_data/extensions/`), `enable` / `disable` / `remove` / `update` and the
  **registration bridge**: enabling registers tools (`origin=extension:<name>`), skills, MCP
  servers and the subagent profile into `agent`, and watchers into `perception`; disabling removes
  exactly those (invariant 19: this is the only bridge from core to the agent's tool surface).
- `ExtensionContext` hands an extension what it may use: its settings, the `BodySession`,
  `ContactSession`, `PerceptionSession`, `InteractionSession` (for `say`), `AgentSession`
  (memory/jobs stores) and `LLMSession` — exactly the allowed-import set of `extensions/*`.
- Bundled extensions (`extensions/<name>/`, flat):
  - `robot`: tools `look` (camera snapshot described by the `smart` slot when it has vision, else
    a size/brightness summary), `express(name)`, `look_at(direction)`, `who_is_here`
    (presence + identified faces), `privacy_mode(on)` (mutes the mic feed and camera use),
    `enroll_voice(name)` (conversational enrollment: the next 3 utterances of the current speaker
    are folded into the contact — the flow AGENTS.md describes starting from an antenna press),
    `set_volume`. Skill `robot_body.md` (how to use expressions sparingly).
  - `news`: feed sources ported from Scoop `SCPSync` (RSS/Atom via stdlib `xml.etree`, Hacker
    News top stories via the Firebase API, Telegram public channels via the `t.me/s/<channel>`
    HTML), a `feed.update` watcher (interval from settings), tools `news_latest(source, n)`,
    `news_search(query)`, a `news` subagent profile on `smart`, skill `briefing.md` (morning
    briefing in colloquial Cantonese, 3 items, no URLs when spoken).
  - `media`: qBittorrent Web API (`/api/v2/auth/login`, `torrents/info`, `torrents/add`) and
    Jellyfin (`/Items`, `/Sessions`, `/Sessions/{id}/Playing`) tools, a download-completion
    watcher (`media.download_done`), `media` subagent; settings carry URLs + credentials.
  - `home`: Home Assistant REST (`/api/states`, `/api/services/<domain>/<service>`) tools
    `ha_state`, `ha_call(confirm=True for locks/alarm)`, a state watcher for configured entities
    (`ha.state`), `home` subagent.
- Dashboard Extensions page: list with status, enable/disable/remove, settings form from the
  manifest schema (secrets masked), contributed tools / skills / MCP; `sidekick ext list|enable|
  disable|install|remove`.
- Tests: manifest validation, loader with a temporary extension directory, enable/disable
  registration round-trip with a stub agent, each bundled extension's tools against mocked HTTP
  (`httpx.MockTransport`), feed parsers on fixture documents, the `robot` tools on the null body.
  Live: `robot` tools through the dashboard chat ("做個開心表情", "邊個喺度") and `news_latest`
  against a real RSS feed (network).

### Checklist

- [ ] `extension/`: `schemas.py`, `manifest.py`, `loader.py`, `registry.py`, `extension.py`.
- [ ] `extensions/robot`, `extensions/news`, `extensions/media`, `extensions/home` with
  `extension.json`, `tools.py`, `watchers.py` (where applicable), `skill_*.md`.
- [ ] `agent`: `register_subagent_profile`, skill/MCP registration by origin already present;
  `perception.register_watcher` already present.
- [ ] `app.py`: load enabled extensions after the agent, perception and interaction are up;
  CLI `ext`; dashboard page + `/api/extensions*`; architecture test covers `extensions/`.
- [ ] Docs: AGENTS.md yellow pages + `Extensions` section as built; READMEs; PLAN progress.

---

## [2026-10-26 #19] Progress: Phase 4 landed — contacts, voice and face identification

Checklist from block #18, all done.

- [x] `opencv-python-headless 5.0.0.93` added; speaker model (3D-Speaker CAM++ zh/en, 28 MB),
  YuNet (230 KB) and SFace (38 MB) download on demand into `.derived_data/models/`.
- [x] `contact/`: store (contacts + centroids with sample counts), `VoiceIdentifier` (embed ~15 ms,
  cosine match, min clip 1.0 s / enroll 1.5 s), `FaceIdentifier` (YuNet detect + SFace embed,
  TV-zone mask), `ContactSession` (CRUD, remote-id binding, `resolve_speaker`, `display_name`,
  `enroll_voice/face/self`). Tests: store math, matching, remote resolution; slow test with the real
  model on bundled clips (en vs zh speaker separate; `self` round-trip).
- [x] `interaction`: every accepted segment is identified in a thread; `self` → echo; `strict`
  gate; gaze trigger (frontal face + enrolled voice + direction); per-contact language.
- [x] `agent`: speaker display names in the prompt; remote ids resolved to contacts.
- [x] CLI `enroll <name> [--owner --language --utterances --no-face]`; dashboard Contacts page +
  `/api/contacts*`, camera snapshot `/api/body/frame.jpg`, voice enrollment from listening clips.
- [x] `app.py`: `ContactSession` wired to interaction, agent and dashboard; `self` enrolled from
  three TTS clips at first start (10 s boot).
- [x] Sentence splitter no longer cuts inside an `[express:…]` tag (a split tag was spoken aloud
  once). Suite: 102 offline tests pass; `ruff`, `mypy --strict` clean.

Live on the Lite: `self` enrolled (3 clips); the test voice scored 0.02 against `self` and ran
as `guest:1`; the robot's own residual speech was ignored by the pre-stop check. Two TTS voices
separate at cosine 0.79–0.91 (same) vs 0.12–0.24 (different). Household members can now be
enrolled by the owner with `sidekick enroll 爸爸 --owner` (4 utterances + 5 camera frames) or on
the dashboard; gaze trigger stays off by default until voices are enrolled.

---

## [2026-10-26 #18] Todo: Phase 4 — household: contacts, voice and face identification, gating

### Research (2026-10-26)

- **Speaker embeddings**: sherpa-onnx `SpeakerEmbeddingExtractor` + `SpeakerEmbeddingManager`
  (cosine search with threshold). Models in the `speaker-recongition-models` release: 3D-Speaker
  CAM++ `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx` (28 MB, zh + en, 192-d),
  ERes2Net variants (40–220 MB), WeSpeaker ResNet34 (26 MB). Choice: CAM++ zh/en advanced —
  smallest bilingual model; Cantonese is covered acoustically (speaker identity is
  language-agnostic in practice; verify on household data).
- **Faces**: OpenCV zoo YuNet (`face_detection_yunet_2023mar.onnx`, ~230 KB) for detection +
  landmarks and SFace (`face_recognition_sface_2021dec.onnx`, ~37 MB) for 128-d embeddings via
  `cv2.FaceDetectorYN` / `cv2.FaceRecognizerSF` (align → feature → cosine, threshold ≈ 0.363 per
  OpenCV docs). `opencv-python-headless 5.0.0.93` has a macOS arm64 wheel (no GUI deps).
- The robot's own voice: the `self` contact is enrolled from TTS clips so echo residuals fail
  speaker identification (AGENTS.md "Contact and identification").

### Decisions

- `contact` module (layer 2): `store.py` (`contact_v1.db`: contacts with `name`, `aliases`,
  `notes`, `language`, `is_owner`, `remote_ids` {telegram, wechat}; `embeddings` rows with
  `kind` voice|face, `model`, vector blob), `voice.py` (extractor wrapper: `embed(clip)`,
  `identify(clip) -> Identification(contact_id|None, score, kind)`, enrollment = mean of ≥ 3
  utterance embeddings, min clip 1.5 s), `face.py` (YuNet + SFace, `detect(frame)`,
  `embed(frame, face)`, `identify(frame)`, TV-zone masking hook), `contact.py` façade
  `ContactSession` with `identify_voice`, `identify_face`, `enroll_voice(name, clips)`,
  `enroll_face(name, frames)`, `enroll_self(tts_clips)`, `resolve_speaker("tg:42") -> contact
  id`, CRUD. Thresholds live in config (`contacts.voice_threshold 0.5`, `face_threshold 0.363`)
  and are tuned on the dashboard.
- `interaction` uses contacts: every accepted segment is identified (≈ 50 ms); a `self` hit
  is treated as echo; the session's `speaker` is the contact id (`guest:n` otherwise) and the
  turn's `ChannelMessage.speaker` carries it, so agent memory scopes by person automatically;
  the speaker's preferred language drives ASR hint and reply language; **gaze trigger**: a
  frontal face (perception) within 1.5 s of the segment, DoA within the sector and an enrolled
  voice (`speaker_gate soft`) opens a session without the name; `strict` gate rejects unknown
  voices everywhere.
- `agent`: speaker display names in the prompt ("Speaker: 爸爸 (owner)"), remote ids resolved to
  contacts so Telegram/WeChat/voice share one memory scope.
- Enrollment: `sidekick enroll <name> [--owner] [--language]` records utterances from the robot
  mic (VAD segments, 3–5 × ≥ 1.5 s) and 5 camera frames; dashboard Contacts page lists contacts,
  enrolls a voice from recent listening-monitor clips and a face from a camera snapshot; the
  conversational flow ("我是爸爸，記住我的聲音") arrives with the `robot` extension (Phase 5)
  because core modules never register tools (invariant 19).

### Checklist

- [ ] deps: `opencv-python-headless`; models downloaded on demand into `.derived_data/models/`.
- [ ] `contact/`: `schemas.py`, `store.py`, `voice.py`, `face.py`, `contact.py`; tests (store CRUD,
  cosine math with synthetic vectors; slow tests with the real models on two TTS voices).
- [ ] `config`: `contacts` section (thresholds, model names); `interaction.speaker_gate` wired.
- [ ] `interaction`: identification per segment, `self` as echo, gaze trigger, per-contact language.
- [ ] `agent`: speaker names / remote id resolution.
- [ ] CLI `enroll`, dashboard Contacts page + API, `app.py` wiring, `self` enrollment at start
  when missing (3 TTS clips of the configured voice).
- [ ] Live: enroll `self`; verify the two TTS voices separate; presence + gaze on the robot.

---

## [2026-10-26 #17] Progress: Phase 3 landed — channels, perception, event jobs

Checklist from block #16, all done.

- [x] `config`: `ConfigChannels` (`telegram`, `wechat`), `ConfigPerception`; `segno` added for QR.
- [x] `channel/telegram.py` (long polling, allowlist, `/pair <code>`, typing action, back-off),
  `channel/wechat.py` (`WeChatClient` with the iLink headers / `base_info`, `WeChatLogin` QR
  state machine incl. `need_verifycode` and IDC redirect, `WeChatAdapter` poll loop with
  persisted `get_updates_buf` and per-user `context_token`, stale-token pause, one notice to
  unlisted senders). Tests over `httpx.MockTransport` for both.
- [x] `perception/`: event bus with pattern subscriptions, history and `events_v1.db`; camera
  presence watcher (enter 1 s / leave 60 s, frontal gaze), audio speech-onset watcher, `Watcher`
  base for extensions. Tests for the state machines, fan-out isolation and persistence.
- [x] `agent`: `on_event` runs `event` jobs (type + filter), `schedule` accepts `event=`,
  presence-aware `auto` delivery (`body.awake and someone_present`).
- [x] CLI `telegram pair|status`, `wechat login|status` (terminal QR via `segno`); dashboard
  Channels page (status, pairing code, presence, events) and `/api/channels`, `/api/perception*`.
- [x] `app.py` wiring: perception started with the body, remote adapters registered when their
  credentials exist. Suite: 91 fast + 4 slow pass; `ruff`, `mypy --strict` clean.

Live on the Lite: perception started with camera and audio watchers; a test utterance produced
`audio.speech {yaw 0.51}` events and `presence.speech_direction`; no face in front of the robot
during the session, so `presence.enter` was exercised by the unit tests only. Telegram and WeChat
could not be exercised live: no bot token and no phone scan in this session — the owner runs
`sidekick config set credentials.telegram.bot_token …` + `sidekick telegram pair`, and
`sidekick wechat login`, then restarts `sidekick run`.

---

## [2026-10-26 #16] Todo: Phase 3 — channels (Telegram, WeChat iLink), perception, event jobs, delivery

### Research: Tencent `@tencent-weixin/openclaw-weixin` 2.4.10 (npm tarball read on 2026-10-26)

The official OpenClaw plugin is the reference for personal-WeChat bots over **iLink**. What
sidekick needs (text in / text out; media later):

- Base URL `https://ilinkai.weixin.qq.com` (login may redirect to another IDC host via
  `scaned_but_redirect.redirect_host`; the confirmed login returns the account's `baseurl`).
- Headers on every request: `Content-Type: application/json`, `AuthorizationType: ilink_bot_token`,
  `Authorization: Bearer <bot_token>`, `X-WECHAT-UIN: base64(str(random uint32))`,
  `iLink-App-Id: bot`, `iLink-App-ClientVersion: (major<<16|minor<<8|patch)`. Every body carries
  `base_info: {channel_version, bot_agent}` (`bot_agent` is a UA-style observability string).
- **QR login**: `POST ilink/bot/get_bot_qrcode?bot_type=3` body `{"local_token_list": [...]}` →
  `{qrcode, qrcode_img_content}` (the latter is the URL to encode as a QR); then long-poll
  `GET ilink/bot/get_qrcode_status?qrcode=…[&verify_code=…]` (35 s client timeout) → `status` ∈
  `wait | scaned | need_verifycode | verify_code_blocked | expired | scaned_but_redirect |
  binded_redirect | confirmed{bot_token, ilink_bot_id, baseurl, ilink_user_id}`. `need_verifycode`
  asks for the digits shown in the phone's WeChat. QR TTL 5 min, refresh up to 3 times.
- **Receive**: `POST ilink/bot/getupdates` `{get_updates_buf, base_info}` long-poll (server
  suggests `longpolling_timeout_ms`) → `{ret, errcode, errmsg, msgs[], get_updates_buf}`; persist
  `get_updates_buf` and echo it on the next call (`""` on first). `errcode -14` = stale token →
  pause one hour. Message: `from_user_id`, `message_type` (1 user / 2 bot), `item_list[]` with
  `type` 1 text (`text_item.text`), 3 voice (`voice_item.text` is the server transcript), 2/4/5
  image/file/video (CDN, AES-128-ECB — deferred), `context_token` (**must be echoed per user in
  every send**), `message_id` as uint64 string (parse losslessly).
- **Send**: `POST ilink/bot/sendmessage` `{msg: {from_user_id: "", to_user_id, client_id,
  message_type: 2, message_state: 2, item_list: [{type: 1, text_item: {text}}], context_token},
  base_info}` → `{message_id, ret, errmsg}`. Optional typing: `ilink/bot/getconfig`
  `{ilink_user_id, context_token}` → `typing_ticket`; `ilink/bot/sendtyping`.
- Only direct messages; the plugin keeps an `allowFrom` list of `ilink_user_id`s (the scanner's id
  is returned at login). Credentials: `bot_token`, `ilink_bot_id`, `baseurl`, `user_id`.

Telegram: raw Bot API (`getUpdates` long polling with `offset` and `timeout=30`, `sendMessage`,
`sendChatAction typing`), allowlist of chat ids, pairing by code: `sidekick telegram pair`
prints a one-time code, the owner sends `/pair <code>` to the bot, the chat id is stored.

### Decisions

- `channel/telegram.py` and `channel/wechat.py` implement `ChannelAdapter` over `httpx`; both
  loops run as asyncio tasks inside `ChannelSession.start_all()`. Secrets (`telegram.bot_token`,
  `wechat.bot_token`) live in `credentials`, everything else in `channels.telegram` /
  `channels.wechat` (typed `ConfigChannels`). WeChat state (`get_updates_buf`, context tokens) is
  a JSON file under the home. Inbound text (and voice transcripts) go to the agent as
  `ChannelMessage(channel="telegram"|"wechat", speaker="tg:<chat id>"|"wx:<user id>")`; the agent
  replies to the originating channel (invariant 14). Unknown senders get a short "not paired"
  reply once and are otherwise ignored.
- **QR rendering** without a browser: add `segno` (pure Python, no dependencies, MIT) to print
  the QR in the terminal for `sidekick wechat login` and to serve a PNG on the dashboard
  (owner sign-off requested here; the alternative was a CDN JS library in the dashboard only).
- `perception`: `EventBus` (typed `PerceptionEvent{type, severity, data, ts}`, async subscribers,
  short history, `events_v1.db` for `severity >= notice`), `camera.py` presence from the body's
  face tracker (`presence.enter` after 1 s of a face, `presence.leave` after 60 s without one,
  `face.seen`, `gaze.frontal`), `audio.py` (`audio.speech` from DoA), `watcher.py` base for
  extension watchers (periodic async poll). `PerceptionSession.presence()` is the snapshot the
  delivery policy uses; `auto` delivery now means "speak if someone is present and the body is
  awake, else remote".
- Event jobs: `PerceptionSession` fans events into `AgentSession.on_event()`, which runs active
  `event` jobs whose type (and optional `event_filter`) match; the job prompt sees the event data.
- Dashboard: Channels page (Telegram status + allowlist + pairing code; WeChat login with QR, status,
  allowlist) and Events page.

### Checklist

- [ ] `config`: `ConfigChannels` (`telegram {enabled, allow_chat_ids, pairing_code}`, `wechat
  {enabled, bot_id, base_url, allow_user_ids, user_id}`), `perception {presence_leave_s, …}`.
- [ ] `channel/telegram.py`, `channel/wechat.py` (+ `ilink` login helper), `ChannelSession`
  running adapter loops; tests with `httpx.MockTransport` (pairing, allowlist, inbound → reply,
  WeChat login state machine, getupdates buf persistence, stale-token pause, send body).
- [ ] `perception/`: `schemas.py`, `perception.py`, `camera.py`, `audio.py`, `watcher.py`; tests
  with the null body (face injected → presence events; DoA speech → audio event).
- [ ] `agent`: `on_event`, event jobs, presence-aware `auto` delivery; tests.
- [ ] CLI `telegram pair`, `wechat login`; dashboard Channels + Events pages; `app.py` wiring.
- [ ] Live: Telegram needs a bot token from the owner (not available in this session → unit tests
  only, documented); WeChat login needs the owner's phone to scan (same). Presence events verified
  on the robot with the camera.

---

## [2026-10-26 #15] Progress: Phase 2 landed — agent core

Checklist from block #14, all done.

- [x] `agent/schemas.py`, `tools.py` (registry, confirm gate, built-in tools), `dialogue.py`
  (timeline + visibility-filtered context view with tool-pair integrity), `memory.py`,
  `skills.py`, `mcp.py` (registry + client pool over the official SDK), `automation.py`
  (cron matcher, `at`, scheduler, heartbeat, quiet hours), `loop.py` (streamed ReAct),
  `agent.py` (swarm, delegation sync/async, confirmation flow, delivery policy).
- [x] `config`: `agents` (main knobs + subagent profiles) and `automation` (tick, heartbeat,
  quiet hours) sections. `pyproject.toml`: `mcp 1.30.0`.
- [x] `app.py` wiring: stores under `.derived_data/`, scheduler started, voice `say` as the
  in-person delivery, `body.awake` as the `auto` delivery hint.
- [x] Dashboard: Timeline (+ text chat into the main agent), Agent (swarm state, memory, jobs,
  skills editor, MCP servers) pages and `/api/agent/*`.
- [x] Tests: 12 store/session tests with a scripted LLM (tool call → reply, confirm gate yes/no,
  delegation sync + async follow-up, scheduler delivery in person and to a text channel,
  heartbeat `NO_REPLY`), MCP live test against a toy `FastMCP` stdio server (slow), dashboard
  agent routes. Suite: 83 fast + 3 slow pass; `ruff`, `mypy --strict` clean.

### Live (dashboard chat → main agent, MiniMax-M3 fast slot)

| Turn | Result |
|---|---|
| "明朝八點提我食藥" | `schedule(prompt="提你食藥", when="2026-10-27T08:00")` → job created, reply "好，聽日朝早八點提你食藥。"; tool round 6.1 s + reply round 5.3 s |
| "你而家有咩提醒？" | `jobs_list` → "而家有一個提醒：聽日朝早八點提你食藥。" |
| "記住我鍾意飲奶茶" (first prompt) | model *claimed* to remember without calling `remember` → prompt now states it has no memory unless it calls the tool (re-verified below) |
| Replies | carry `[express:happy]` tags, stripped and performed by the pipeline |

### Findings

1. **Two LLM rounds per tool turn** cost ~5–6 s each on MiniMax-M3; a reminder confirmation takes
   ~11 s end to end. Options for later: speak the model's acknowledgement before the tool result
   (already streamed when present), let simple tools return a canned Cantonese sentence the agent
   relays verbatim, or a faster `fast` slot provider.
2. **Tool adherence** needs explicit prompt rules for MiniMax-M3 (memory claims without a call).
3. The heartbeat runs every 30 min outside 23:00–07:30 and answers `NO_REPLY` unless internal
   notes (async delegation results, due jobs) need relaying.

---

## [2026-10-26 #14] Todo: Phase 2 — agent core (swarm, tools, timeline, memory, skills, MCP, automations)

Design is fixed in AGENTS.md "Agent swarm", "Dialogue and memory", "Automations, heartbeat,
delivery". This block lists the concrete pieces and the decisions that were still open.

### Decisions

- **One `Agent` class, profiles decide behaviour.** `AgentSession` keeps its Phase 1 surface
  (`respond(message)` for the voice pipeline, `handle(message)` for text channels) and becomes the
  swarm: a `main` agent on `fast` plus subagents registered by extensions or config (`agents`
  section of the spec). `delegate(agent, task, mode)` is a tool of the main agent only.
- **ReAct loop streams.** Text deltas reach the voice pipeline as they arrive; tool calls are
  executed when the model's stream ends with `tool_calls`, results are appended and the loop
  re-prompts (max `profile.max_steps`). A step that produces both text and tool calls speaks the
  text first (acknowledgement) and continues.
- **Confirm-gated tools** (invariant 13): a tool with `confirm=True` is not executed on first
  call; the agent gets a tool result asking it to confirm with the user, the request is stored per
  conversation (channel + speaker) and the next user message is checked for an affirmative
  (好 / 係 / 確認 / 可以 / yes / ok). The main agent then re-issues the call with
  `confirmed=true`.
- **Timeline** `dialogue_v1.db`: every message from every channel (user, assistant, tool,
  internal) with `visibility`; the per-turn context view is filtered (`private` only for the same
  speaker, `internal` only for the producing agent) and bounded by a character budget. Phase 1's
  in-memory history is replaced by the view.
- **Memory** `memory_v1.db`: `facts(scope, text, source_id)` with `scope` a contact id or
  `household`; `episodes` (compaction summaries, written by the heartbeat when the timeline view
  overflows). Tools `remember`, `forget`, `recall`; the system prompt gets a memory block scoped to
  the speaker + household.
- **Skills** `skills_v1.db`: Markdown with `name` / `description` header; descriptions injected,
  body on demand (`skill_read`); CRUD tools. Bundled defaults: `conversation style`.
- **MCP** `mcp_v1.db`: server configs (`stdio` command/args/env or `http` url/headers) with
  `origin`; official `mcp` SDK client; tools surfaced as `mcp.<server>.<tool>`; CRUD tools; lazy
  connect, cached tool lists, reconnect on failure.
- **Automations** `automation_v1.db`: jobs with `cron` (5-field matcher implemented in-tree,
  minute resolution), `at` (ISO local time), `event` (wired to `perception` in Phase 3); actions
  run a main-agent turn with the job prompt; delivery `in_person` (voice channel `say`), `remote`
  (Phase 3 channels), `both`, `auto` (presence from `perception` in Phase 3; until then `in_person`
  when the body is awake). The `schedule` tool creates jobs; `jobs_list` / `job_cancel` manage them.
  **Heartbeat** = a built-in cron job (default every 30 min, configurable, off during quiet hours)
  whose prompt reviews new internal messages (finished async delegations, due reminders) and
  answers `NO_REPLY` or a message to deliver.
- **Dashboard**: Timeline, Memory, Automations, Skills & MCP pages (read + simple CRUD) on top of
  `/api/agent/*`.

### Checklist

- [ ] `agent/schemas.py`: `Tool`, `ToolContext`, `ToolResult`, `DialogueMessage`, `MemoryFact`,
  `Skill`, `MCPServer`, `Job`, `AgentEvent`.
- [ ] `agent/tools.py` registry + confirm gating; built-in tools (`reply` is implicit; `recall`,
  `remember`, `forget`, `schedule`, `jobs_list`, `job_cancel`, `skill_*`, `mcp_*`, `delegate`,
  `time_now`).
- [ ] `agent/dialogue.py` timeline + context view; `agent/memory.py`; `agent/skills.py`;
  `agent/mcp.py`; `agent/automation.py` (store, cron matcher, scheduler, delivery);
  `agent/loop.py` ReAct; `agent/agent.py` swarm façade.
- [ ] `app.py` wiring (stores under the home, scheduler task, heartbeat), `config` `agents`
  section (subagent profiles) and `automation` section (heartbeat interval, quiet hours).
- [ ] Dashboard pages + API; tests for every store, the loop with a fake LLM emitting tool calls,
  confirm gating, delegation sync/async, cron matcher, scheduler firing, MCP registry (+ a slow
  live test against a tiny stdio server written with the SDK's `FastMCP`).
- [ ] Live: "八點提我食藥" → job; "記住我鍾意飲奶茶" → fact; "我鍾意飲咩" → recall; a delegated
  task; dashboard timeline shows the turn.

---

## [2026-10-26 #13] Progress: Phase 1 landed — body, daemon via CLI, voice MVP, dashboard

Checklist from block #12, all done; live-verified on the Lite over USB on this Mac.

- [x] `pyproject.toml`: `reachy-mini 1.12.0`, gstreamer plugin pins, `fastapi`, `uvicorn`.
- [x] `config`: `ConfigBody` (`manage_daemon`, `sim`, `wake_on_start`, `sleep_on_stop`,
  `preload_datasets`, `stop_daemon_on_exit`, `volume`), `ConfigInteraction` (triggers, gate,
  timeouts, barge-in, fillers, level gate, echo similarity, pre-roll, `asr_slot`, `shadow_asr`),
  `ConfigDashboard`, `ConfigRobot.keywords`; presets gained `slot_api` / `slot_params` so one
  provider can serve two ASR apis (`sherpa_sensevoice` for `local`, `sherpa_kws` for `kws`).
- [x] `body`: `reachy.py`, `null.py`, `motion.py`, `touch.py`, `media.py`, `daemon.py`, `dsp.py`,
  `body.py`; 13 offline tests incl. a real `--mockup-sim` daemon lifecycle (up in ~9 s).
- [x] `cli`: `daemon start|stop|restart|status|log`, `say`, `run` supervising the daemon; `doctor`
  reports daemon, keyword model and audio-DSP health.
- [x] `channel` (protocol + registry), `agent` (fast-slot streaming reply, `NO_REPLY`).
- [x] `interaction`: all submodules; 7 offline tests with fakes (wake name → turn → follow-up →
  timeout, duck → stop → next turn, touch, robot-initiated `say`).
- [x] `dashboard`: Health / Listening / Settings / Traces / Logs at `127.0.0.1:8787`; API test.
- [x] `app.py` wiring; live turns on the robot (below). AGENTS.md yellow pages and READMEs updated.

Suite: 76 offline tests pass (slow ones download the keyword model and spawn a mockup daemon);
`ruff`, `ruff format --check`, `mypy --strict` clean.

### Live measurements (Lite, MiniMax domestic, test utterances played from the Mac speakers)

| Stage | Result |
|---|---|
| `sidekick daemon start` → daemon `running`, robot awake | 6 s (first start: +30 s GStreamer registry scan) |
| SDK connect + media pipelines | 3 s |
| Wake name "Bobby，今日天氣點呀？" (padded test file, 3 replays) | 3/3 engaged: streaming keyword hit (`寶比`) + segment "BOBBY 今日天气点呀" |
| Turn ASR, local SenseVoice (`interaction.asr_slot = local`) | 99–160 ms per 2–3 s clip |
| Shadow ASR, MiniMax `asr-1.0` | 2.4–2.8 s, same text |
| LLM `fast` (MiniMax-M3, thinking off) time to first token | 2.1–3.0 s (bench: `service_tier: priority` 2.0–2.1 s; M3.1-Flash ≥ 2.6 s and cannot disable thinking) |
| First audible word after speech end | 3.0–4.8 s (was 8.0 s before the sentence splitter cut at the first comma) |
| Whole turn until the speaker is quiet | 8–12 s (replies of 20–30 chars) |
| Story request ("講個關於小狗嘅故事") | first audio 3.2–3.6 s, 16–26 s of speech, paragraph fragments streamed |
| Barge-in | duck at onset and hard stop at 0.75–0.95 s verified live (triggered by the robot's own residual echo at volume 100 → guards below); a test "等一下" played over the robot's voice reached SenseVoice as "Y"/"O", i.e. a quiet interrupter is masked at volume 100 → `body.volume` 70 |
| TTS bidi session | connect 2.1 s once at start, reused across turns |

### Findings and fixes (within AGENTS.md constraints)

1. **Silent microphone = hung XVF3800.** All CoreAudio clients received zeros and every DSP
   parameter read answered "retry"; a vendor `REBOOT` over USB restored both. `body/dsp.py`
   probes the chip before `sidekick daemon start` and reboots it when busy; `doctor` shows it.
   Likely cause: several processes using the USB control interface at once (daemon + SDK DoA);
   sidekick therefore reads DoA only through the daemon's REST endpoint.
2. **GStreamer 1.28.8 plugin wheels** were published for Windows only on 2026-10-26 →
   `gstreamer-plugins* < 1.28.8` pins (remove when macOS wheels exist).
3. **Wake name through a speaker**: SenseVoice alone heard "Bobby" 1/3 ("BOBY", "BOB", "BOBE",
   "咦"); Silero VAD starts segments ~0.2–0.4 s into the name. Fixes: 1 s pre-roll from a ring
   buffer, VAD hangover 0.8 s / threshold 0.35, merge of a short content-less segment just before,
   heard variants as aliases, and the sherpa-onnx keyword spotter (`asr.kws`) both on the segment
   and **streaming on the raw mic feed** (a hit opens the session; the following segment is the
   first turn). Result 3/3 on the padded test file. A human voice at 1 m is expected to do
   better than Mac speakers across a desk; the listening monitor keeps every clip for tuning.
4. **Latency budget**: cloud ASR (2.6 s) + LLM first token (2.4 s) + TTS (0.8 s) cannot meet the
   2.5 s target, so the turn ASR slot defaults to local SenseVoice (0.1 s) with MiniMax as a
   shadow shown on the dashboard. The LLM is now the whole budget; `service_tier: priority` on
   MiniMax-M3 gains ~0.3 s (pricing to confirm with the owner before enabling). The sentence
   splitter sends the first fragment at the first comma after 4 characters because MiniMax M3
   generates Cantonese at only ~5 chars/s in the agent's context.
5. **Robot hears itself**: hardware AEC leaves a residual at volume 100 that VAD + SenseVoice turn
   into "嗯" segments and, twice, into a duration-based hard stop of the robot's own answer.
   Guards added: filler/single-char transcripts never count; a segment whose transcript overlaps
   the text being spoken is `echo`; echo and filler directions feed a learned **self sector** that
   cannot duck or stop; unknown-direction speech never ducks (content-only stop); the addressee
   sector is re-checked while speech continues; before any duration-based stop the speech so far
   is decoded locally and ignored when it is echo or filler; `hard_stop_speech_s` 0.9;
   `body.volume` (set to 70 on this robot) lowers the residual. The remaining weak point is a
   quiet interrupter talking over the robot: with Mac-speaker playback the stop word reached
   SenseVoice as a single letter. A human voice closer to the robot, the `self` voice profile
   (Phase 4) and tuning on the listening monitor are the next steps.
6. **Session timing**: the 8 s silence timeout no longer ticks while a turn is in flight (cloud
   ASR + LLM alone exceeded it once).
7. `AudioPlayer` keeps ≤ 250 ms queued in GStreamer so ducking and stops react within ~300 ms;
   emotions play on the motion thread so the daemon never sees competing `set_target`s.

### Open items carried to Phase 2+

- Decide with the owner: `asr.primary` MiniMax vs local as default (data above), `service_tier`.
- Phase 2: agent core (ReAct, tools, timeline, memory, automations, heartbeat); `[express:]` tags
  are already honoured by the pipeline so the agent can emit expressions.
- Human-voice tuning session on the listening monitor (thresholds, TV sector, self sector).

---

## [2026-10-26 #12] Todo: Phase 1 — body, daemon lifecycle, voice MVP, minimal dashboard

Owner instructions received after Phase 0 (2026-10-26): finish the whole roadmap and commit only
after the owner has accepted the result; the Reachy daemon is started and stopped **through the
sidekick CLI**, never as a standalone command.

### Research: `reachy-mini` 1.12.0 as installed (wheel inspected, env verified)

- Console scripts: `reachy-mini-daemon` (`reachy_mini.daemon.app.main:main`),
  `reachy-mini-app-assistant`, `reachy-mini-reflash-motors`. Daemon flags of interest:
  `--serialport auto`, `--sim` (MuJoCo extra), `--mockup-sim` (no MuJoCo, behaves like a real
  robot for clients — usable for hardware-free integration tests), `--no-media`,
  `--no-wake-up-on-start`, `--no-goto-sleep-on-stop`, `--preload-datasets`, `--fastapi-host`,
  `--fastapi-port`, `--log-level`, `--log-file`, `--robot-name`. Lite binds `127.0.0.1:8000`.
- REST used by sidekick: `GET /api/daemon/status` (`state` not_initialized | starting | running |
  stopping | stopped | error; `backend_status.motor_control_mode` enabled | disabled |
  gravity_compensation; `version`, `face_target`), `GET /api/state/doa` (`angle`,
  `speech_detected`; 0 = left, π/2 = front, π = right), `GET /api/move/running`,
  `POST /api/move/play/recorded-move-dataset/{dataset}/{move}`,
  `GET /api/move/recorded-move-datasets/list/{dataset}`, `POST /api/daemon/stop?goto_sleep=`.
- SDK: `ReachyMini(host, port, connection_mode="localhost_only", media_backend="default")`
  connects over `ws://…/ws/sdk`; `set_target(head 4x4, antennas, body_yaw)` for the 30–50 Hz
  owner loop, `goto_target(…, duration)` blocks until done; the daemon **ignores `set_target`
  while a move is running** (warning per command), so the owner loop must pause during
  emotions and gotos. `start_head_tracking(weight)` / `stop_head_tracking()` run daemon-side;
  `get_tracked_face()` → `FaceTarget(detected, x, y ∈ [-1, 1], roll, ts)`. `enable_wobbling()`
  makes pushed audio wobble the head daemon-side. `media.get_audio_sample()` → float32 `(n, 2)`
  at 16 kHz (hardware AEC), `media.start_playing()` + `media.push_audio_sample(float32 mono)` →
  speaker, `media.audio.clear_player()` flushes queued playback, `media.get_frame()` BGR from
  the daemon's IPC socket. Emotions: `RecordedMoves("pollen-robotics/reachy-mini-emotions-library")`
  (HF cache, shared with the daemon's `--preload-datasets`), `reachy.play_move(move)` drives
  `set_target*` from the caller's thread, `cancel_move()` stops it. `huggingface.co` reachable
  from this network (200 in 0.8 s).
- Constants: `INIT_ANTENNAS_JOINT_POSITIONS = [-0.1745, 0.1745]`, sleep antennas `[-3.05, 3.05]`,
  `INIT_HEAD_POSE = I`. Antenna press detector in the daemon uses hysteresis 0.25 / 0.10 rad.
- Packaging: `gstreamer-bundle 1.28.3` pulls `gstreamer_*~=1.28.3`; on 2026-10-26 the 1.28.8
  release of five plugin packages had Windows-only wheels, so `pyproject.toml` pins
  `gstreamer-plugins*, gstreamer-plugins-libs < 1.28.8` (remove once macOS wheels exist). First
  `Gst.init` builds the plugin registry in ~30 s (cached afterwards in the venv). `libgstpython`
  fails to load (missing `libpython3.12.dylib`) — harmless.

### Decisions

- **Daemon lifecycle lives in `body/daemon.py`** (`BodyDaemon`): spawns `reachy-mini-daemon`
  from the active environment with flags derived from `config.body`, writes
  `.derived_data/reachy_daemon.pid`, logs to `.derived_data/logs/reachy-daemon.log`, waits for
  `state == running`, stops with SIGINT (daemon puts the robot to sleep). CLI:
  `sidekick daemon start|stop|status|restart [--mockup-sim|--sim] [--no-wake]`. `sidekick run`
  supervises the daemon when `body.manage_daemon` is true (default): start if unreachable, stop
  on exit when it started it. Invariant 11 holds: sidekick never wakes or sleeps the robot
  itself; the daemon does on start/stop.
- **`body` API** (body-agnostic, `BodyBackend` protocol implemented by `reachy.py` and
  `null.py`): `connect/close`, `status()`, `set_target`, `goto`, `play_emotion(name)`,
  `emotions()`, `track_face(on, weight)`, `tracked_face()`, `doa()`, `antennas()`, audio in
  (`read_audio()` mono float32 chunks), audio out (`start_playing`, `push_audio`, `clear_audio`,
  `stop_playing`), `frame()`. `BodySession` adds the **motion owner thread** (`motion.py`: base
  look pose + breathing + antenna pose + queued gestures, the only `set_target` caller), the
  **touch detector** (`touch.py`: commanded-vs-present antenna delta with hysteresis), the
  **media pump** (`media.py`: capture thread fan-out to subscriber queues; paced playback with a
  live gain for ducking and a flush for hard stop). Emotions run inside the motion thread via
  `play_move`, so the owner loop is paused exactly for their duration.
- **Config**: `ConfigBody` gains `manage_daemon`, `sim` (`none` | `mockup` | `mujoco`),
  `wake_on_start`, `preload_datasets`, `daemon_log_level`; `ConfigInteraction` becomes a typed
  model (triggers, speaker gate, session timeout, barge-in parameters, TV sector, stop words,
  trace retention).
- **Minimal `channel` and `agent` modules now** so the dependency table holds: `channel`
  defines `ChannelMessage`, `ChannelReply`, `ChannelAdapter` and a registry; `agent` provides
  `AgentSession.respond(message) -> AsyncIterator[str]` on the `fast` slot without tools (the
  "main agent without tools" of the roadmap). Phase 2 grows `agent` into the swarm.
- **`interaction` MVP**: `namespot.py` (fuzzy wake-name match on local SenseVoice text, strip
  the name from the first turn), `engagement.py` (SLEEPING → IDLE → ENGAGED ↔ SPEAKING,
  triggers `wake_name` and `touch`; `gaze` lands with `contact` in Phase 4), `barge_in.py`
  (duck → confirm, stop words), `pipeline.py` (ASR → responder → sentence splitter → one
  long-lived bidi TTS stream → body speaker, latency marks), `attention.py` (DoA turn, face
  tracking while engaged), `expression.py` (listening / thinking / speaking cues, named
  emotions), `voice_channel.py` (`ChannelAdapter` over the pipeline), `trace.py` (engagement
  decisions + clips, 7-day prune).
- **Dashboard** (FastAPI + uvicorn, already pulled by `reachy-mini`, now declared): loopback
  `127.0.0.1:8787`; pages Health, Settings (slots, interaction switches), Listening monitor
  (engagement trace with clip playback), Traces (llm / asr / tts), Logs. Onboarding wizard
  pages land with their modules in later phases.

### Checklist

- [ ] `pyproject.toml`: `reachy-mini`, gstreamer pins, `fastapi`, `uvicorn` with reasons.
- [ ] `config`: `ConfigBody` + `ConfigInteraction` fields; `sidekick config show` prints them.
- [ ] `body`: `schemas.py`, `reachy.py`, `null.py`, `motion.py`, `touch.py`, `media.py`,
  `daemon.py`, `body.py`; tests with the null body and a `--mockup-sim` daemon (`slow`).
- [ ] `cli`: `daemon start|stop|status|restart`, `say "<text>"`, `run` supervising the daemon;
  `doctor` uses `BodyDaemon.status()`.
- [ ] `channel` (protocol + registry), `agent` (fast-slot streaming reply, Cantonese prompt).
- [ ] `interaction`: all submodules above, offline tests with fakes (no network).
- [ ] `dashboard`: app, API, static page; test with FastAPI `TestClient`.
- [ ] `app.py` wiring; live run on the Lite: daemon via CLI, `say`, a full turn with the wake
  name, antenna press, barge-in; record latencies in a `Progress` block.
- [ ] AGENTS.md yellow pages / headers, README diagrams updated.

---

## [2026-10-26 #11] Progress: Phase 0 foundations landed and verified live

Checklist from block #10, all done:

- [x] Python 3.12.15 (Homebrew), Poetry env, `pyproject.toml` (PEP 621, deps with reason
  comments, dev group, ruff / mypy / pytest config), `.gitignore`, `.derived_data/` layout.
  sherpa-onnx 2.0.0 installs cleanly on macOS arm64 cp312.
- [x] `log`, `storage` (`database.py`, `trace.py`), new layer-0 `audio` module.
- [x] `llm` (`v1_chat_completion`: infer + SSE stream + tool-call deltas + `base_resp`), `asr`
  (`minimax_speech_to_text`, `sherpa_sensevoice`), `tts` (`minimax_sync`, `minimax_ws`
  bidirectional session), `vad` (`silero_sherpa`), `config` (presets, pydantic spec, resolve,
  `match api` factories, apply, probe with region resolution), `app.py`, `cli.py`.
- [x] Tests: 53 unit/offline tests pass (fake MiniMax WebSocket server, `httpx.MockTransport`,
  real local models), `tests/test_architecture.py` enforces the allowed-import table,
  façade-only imports, re-export-only `__init__`, no nested directories, docstring headers.
  `ruff check`, `ruff format --check`, `mypy --strict` clean.
- [x] Live self-test (`SIDEKICK_LIVE=1 poetry run pytest -m network tests/test_live_minimax.py`,
  6 passed): all 7 slots probe ok; region auto-resolved to `domestic` (the owner's key is an
  `api.minimaxi.com` key); no plaintext key in logs, traces or repo files.

Measured on this Mac against MiniMax domestic endpoints (single runs, home Wi-Fi):

| Stage | Result |
|---|---|
| LLM `fast` (MiniMax-M3, thinking disabled), short Cantonese answer | 2.7 s total; streaming first token 2.4 s |
| LLM `smart` (MiniMax-M3.1-Flash, reasoning medium) | 3.0 s, 136 chars of reasoning |
| LLM tool call (`schedule`) from "八點提我食藥" | correct call `{"when":"08:00","text":"提我食藥"}` + colloquial Cantonese reply |
| TTS HTTP, 38 chars Cantonese → 2.9 s PCM | 2.3 s |
| TTS WebSocket bidi | connect 2.0 s once; first audio 0.8 s after fragments start; turn 1.8 s |
| ASR MiniMax `asr-1.0` on the 2.9 s clip (`yue` and auto) | 2.6 s, text correct ("今日天气好好，我哋一齊去公園玩呀") |
| ASR SenseVoice local on the same clip | 0.35 s, text correct, language `yue` |
| VAD silero on the padded clip | one segment 0.68–3.44 s |

Findings and refinements (within the AGENTS.md constraints):

1. **Region-bound keys.** The first probe classified a 401 on the overseas endpoint as a
   credentials failure and stopped; TTS, probed later, found the domestic region. Fixed: every
   candidate region is tried on any failure, the first success is persisted, and the most
   actionable failure is reported when none works. MiniMax code `2049` added to the credential
   codes.
2. **`audio` module (layer 0).** `AudioClip` + WAV helpers were needed by asr / tts / vad alike;
   a tiny shared module avoids cross-imports between them. Allowed-import table updated.
3. **`storage/database.py`.** The architecture test caught `trace.py` importing the façade; the
   SQLite pattern moved into its own submodule. Also fixed: `executescript()` auto-commits, so
   each migration now wraps itself in `BEGIN IMMEDIATE … COMMIT`.
4. **Local ASR is ~7× faster than cloud** on this clip with equal accuracy (clean TTS audio;
   real mic audio still to be compared). The owner prefers MiniMax, so `asr.primary` stays
   MiniMax; Phase 1 should run both as a shadow pair and show them side by side on the dashboard
   before deciding. Switching is one slot in config.
5. **`fast` slot time-to-first-token is 2.4 s**, the largest item in the latency budget.
   Phase 1 to-do: compare `MiniMax-M3` (thinking disabled) with `MiniMax-M3.1-Flash`
   (`reasoning_effort: low`), check whether `thinking.type: disabled` is honored in traces, try
   `service_tier: priority`, and shorten the system prompt.
6. **Keep the TTS WebSocket session alive across turns.** Connect costs 2 s; `flush` ends a turn
   without reconnecting. The pipeline must own one long-lived session with reconnect on the
   120 s idle timeout.
7. **SenseVoice hallucinates a filler ("嗯") on pure silence** — VAD gating upstream is
   mandatory before any local transcription, as designed.

Next: Phase 1 (body adapter + interaction MVP). Nothing is committed yet; the owner decides when
to commit.

## [2026-10-26 #10] Todo: Phase 0 — foundations

Owner's go-ahead received with a standing instruction: every module and every technical approach
is self-tested after development, failures are fixed autonomously, and a better approach may be
adopted proactively as long as it stays inside the `AGENTS.md` constraints.

Interface facts verified before coding (MiniMax API reference, sherpa-onnx examples):

- Chat: `POST /v1/chat/completions` (OpenAI-compatible), models `MiniMax-M3.1-Flash` (always
  thinks, `reasoning_effort` tunable) and `MiniMax-M3` (adaptive thinking; `thinking.type:
  disabled` accepted), `max_completion_tokens`, SSE chunks with `delta.content` /
  `delta.reasoning_content`, tool calls via `message.tool_calls` and `role: tool` replies,
  `base_resp` error codes (1004 auth, 1008 balance, 1002/1039 limits). The legacy
  `/v1/text/chatcompletion_v2` used by Scoop still exists; sidekick uses the new path.
- TTS HTTP `POST /v1/t2a_v2`: `audio_setting.format` includes `pcm`, `sample_rate` includes
  `16000`, `language_boost: "Chinese,Yue"` is valid, `output_format: hex`, `voice_setting.emotion`
  available. Streaming over HTTP is a loosely specified chunked JSON array — not used.
- TTS WebSocket `wss://…/ws/v1/t2a_v2_bidi`: `connected_success` → `task_start` (model,
  voice_setting, audio_setting, language_boost) → `task_started` → N × `task_continue{text}` →
  server `sentence_start` / `task_continued{data.audio hex, is_final}` / `sentence_end` →
  `task_flush` (end of turn, keeps the session) / `task_cancel` (barge-in) / `task_finish`.
  Idle timeout ~120 s, client must ping. One session per connection.
- ASR `POST /v1/speech_to_text`: multipart, `model=asr-1.0`, `language` header (`yue`, `zh`,
  `en`, empty = auto), WAV in, JSON `{text, duration}` out.
- sherpa-onnx: `VadModelConfig.silero_vad.{model, threshold, min_silence_duration,
  min_speech_duration, max_speech_duration}`, `VoiceActivityDetector(config,
  buffer_size_in_seconds)`, `accept_waveform` / `empty` / `front.samples` / `pop` /
  `is_speech_detected` / `flush`; `OfflineRecognizer.from_sense_voice(model, tokens,
  num_threads, use_itn, language, debug)`, `create_stream` / `accept_waveform(16000, samples)` /
  `decode_stream` / `stream.result.text|lang`.

Design refinement adopted now: the trace-table base helper moves from `log` to `storage`
(`storage/trace.py`), because `log` is layer 0 and must not depend on SQLite helpers; `log`
stays pure logging. Yellow pages updated.

Checklist (tick in a `Progress` block):

- [ ] Python 3.12 via Homebrew; Poetry env; `pyproject.toml` (PEP 621, deps with reason
  comments, dev group, ruff/mypy/pytest config); `.derived_data/` layout.
- [ ] `log`: façade, `info0`, `mask_secret`, file sink. Tests: masking, format.
- [ ] `storage`: data dir, `Database` (connection per op, `PRAGMA user_version` migrations,
  `transaction()`), JSON spec 0600, `ensure_download`, `TraceTable`. Tests: migrate, rollback,
  prune, 0600.
- [ ] `llm`: schemas, `v1_chat_completion` (infer + SSE stream + tool-call deltas + `base_resp`),
  `LLMSession` slots + trace. Tests with `httpx.MockTransport`.
- [ ] `asr`: schemas, WAV packing, `minimax_speech_to_text`, `sherpa_sensevoice`, `ASRSession`
  slots + trace. Tests: mock transport; local model test marked `slow`.
- [ ] `tts`: schemas, `minimax_sync` (pcm16k hex), `minimax_ws` (bidi session: start / continue /
  flush / cancel / finish, audio chunk async iterator, ping keepalive), `TTSSession` slots + trace.
  Tests: mock transport for HTTP; fake WebSocket server for bidi.
- [ ] `vad`: schemas, `silero_sherpa`, `VADSession`. Test with synthesized speech (`slow`).
- [ ] `config`: pydantic schemas, catalog (`provider_minimax.json`, `provider_local.json`),
  `ConfigSession.load/save/default/apply/probe`, region resolution by probing. Tests: catalog
  validity, apply builds the right backend classes, probe outcome mapping with mocks.
- [ ] `cli`: `init [--preset dev]`, `doctor`, `config show|set|probe`. `app.py`: boot sequence.
- [ ] `tests/test_architecture.py`: allowed-import table, façade-only imports, `__init__`
  re-export only, header docstring present.
- [ ] Live self-test with the owner's MiniMax key stored in `.derived_data/config.json`: probe all
  slots; LLM reply (fast + smart latency); TTS Cantonese → PCM; ASR on that PCM (`yue`); VAD
  segments on that PCM; SenseVoice transcript of the same clip; bidi WebSocket round trip.
- [ ] `ruff`, `mypy --strict`, full `pytest`; update yellow pages to `wip`; `Progress` block.

## [2026-10-26 #9] Decision: fixed wake name "Bobby", per-slot providers, touch input

Owner's answers:

1. The robot is named **Bobby** and the wake name is fixed, to cut complexity.
2. MiniMax has the best Cantonese TTS even if other capabilities lag; later ASR, TTS, LLM and even
   VAD must be bindable to different vendors (e.g. ElevenLabs).
3. Head touch would be nicer than antenna touch, but if it is complex or false-triggers, defer it
   for the prototype.

Decisions (written into `AGENTS.md`):

- **Wake name fixed**: `Bobby`, with built-in aliases for how it is heard in Cantonese, Mandarin
  and English (`bobby`, `bob`, `波比`, `巴比`, `寶比`; tunable in config, removed from the wizard).
  Mechanism unchanged: local SenseVoice transcription of IDLE segments + fuzzy match. A sherpa-onnx
  KWS model for "bobby" is noted as a later CPU/latency optimization, not a second mechanism now.
- **Four services with named slots**: new core module **`vad`** (`VADSession`, `silero_sherpa`
  backend) joins `llm`, `asr`, `tts` in layer 1. Every slot (`llm.fast`, `llm.smart`,
  `asr.primary`, `asr.local`, `tts.primary`, `tts.fallback`, `vad.primary`) binds to a provider +
  model. `provider_local.json` makes on-host models an ordinary provider; `elevenlabs` is a
  planned preset. `sidekick config set provider minimax` remains the one-vendor shortcut.
- **Touch input**: antenna push for the prototype (safe for the hardware, zero false positives).
  Head tap deferred: Lite has no touch sensor or IMU; pose-deviation detection false-triggers during
  motion; Wireless IMU tap detection is the natural later path. `body` exposes a single `touch`
  event so `interaction` is unaffected when the source changes.

## [2026-10-26 #8] Decision: onboarding, guests and TV, iLink, interruption, streaming, languages

Owner's answers:

1. The robot's name (wake name) is configured in a **first-run onboarding wizard** on the
   dashboard, together with provider keys and member enrollment. Debug runs may use presets
   (`sidekick init --preset dev`).
2. "Antenna trigger" explained: the antennas are low-stiffness motors; a push past 0.3 rad is read
   from the joint angle, so a touch is a physical button with zero false positives.
3. Guests **may** converse, but the robot may sit next to a TV, so false-trigger reduction has
   priority.
4. WeChat via personal-WeChat **iLink**.
5. New requirement: users must be able to interrupt the robot without false interruptions.
6. MiniMax LLM / ASR / TTS should be used in **streaming** form; ASR and TTS must support
   **Cantonese (first), English, Mandarin**.

Research results feeding the design (sources: MiniMax API reference `speech-to-text`,
`speech-t2a-websocket-bidi`, `speech-t2a-http`; sherpa-onnx SenseVoice page):

- MiniMax ASR `asr-1.0`: HTTP multipart upload, `language` header supports `zh`, `yue`, `en`
  (+17 others), empty = mixed-language auto-detect; `stream=true` is **SSE output for an uploaded
  file, not real-time audio input**; `verbose_json` gives diarization; max 500 s / 50 MB; WAV,
  MP3, FLAC, Opus … but no raw PCM.
- MiniMax TTS: HTTP `/v1/t2a_v2` with `stream=true`; WebSocket `/ws/v1/t2a_v2` (per-sentence);
  WebSocket `/ws/v1/t2a_v2_bidi` (streaming text in, server buffers sentences, audio out) — ideal
  for piping LLM tokens. Cantonese via `language_boost: "Chinese,Yue"` and Cantonese voices (as
  in the Scoop preset). PCM output at 16 kHz to be verified against the reference.
- MiniMax LLM: SSE streaming with tool calls on `chatcompletion_v2`.
- sherpa-onnx SenseVoice (`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`): one offline
  model for Mandarin, Cantonese, English, Japanese, Korean. The sherpa-onnx keyword-spotting models
  are Mandarin/English only, so Cantonese wake names need the SenseVoice route.

Decisions (written into `AGENTS.md`):

- **Wake name via local name spotting**: SenseVoice transcribes every IDLE speech segment locally
  and fuzzy-matches the robot's name and per-language aliases. Works for Cantonese; one mechanism
  for all three languages; the same model is the local/shadow ASR fallback.
- **Guests and TV**: guests enter by wake name or antenna only; gaze trigger requires an enrolled
  voice; the wizard marks a TV zone (camera) and DoA sector; the robot's own TTS voice is enrolled
  as `self` to reject residual echo.
- **Two-stage interruption** (new invariant 20): qualifying speech ducks playback immediately
  (−12 dB, stop queuing sentences, antennas lift); a hard stop needs ≥ 700 ms of speech, a stop
  word (停 / 等一下 / 等陣 / stop / 收聲), the wake name, or an antenna touch; short backchannels
  resume playback. Long content is paragraph-paced with lower thresholds in the pauses.
- **Streaming pipeline**: LLM tokens → sentence splitter → bidi TTS WebSocket → PCM 16 kHz →
  speaker; target ≤ 2.5 s to first audible word. ASR stays utterance-based (upload + SSE deltas)
  with a `transcribe_stream` protocol slot for a real-time vendor or incremental SenseVoice later.
- **Languages**: household default + per-contact preference; ASR `language` header from the
  speaker's preference else auto; per-language TTS voice and boost; LLM prompted to answer in
  colloquial written Cantonese for speech; wake-name aliases per language.
- **Onboarding wizard** pages and `sidekick init --preset dev` added to dashboard / CLI designs.
- `channel.wechat` targets iLink; protocol details are to be read from Tencent's official
  `@tencent-weixin/openclaw-weixin` npm plugin during a Phase 3 spike.

## [2026-10-26 #7] Discussion: voice interaction quality — engagement model (superseded in part by #8)

The main interaction is voice, so false triggers, missed triggers and latency decide product
quality. Problems and the proposed answers; everything is a config switch with a dashboard
monitor so it can be re-tuned on real household data.

| Problem | Proposal |
|---|---|
| Who may trigger (TV, guests, neighbours) | Speaker gate on enrolled voiceprints (`soft` default: members trigger by voice/gaze, unknown voices only by wake word or antenna). sherpa-onnx speaker-embedding models, cosine threshold tuned on the monitor. Optional `ignore_sectors` for a TV direction. |
| When the robot listens (friction vs false positives) | Engagement state machine `sleeping → idle → engaged → speaking`. In `idle` only local VAD / keyword / speaker-ID / DoA run; nothing goes to cloud ASR. Entering `engaged` opens a session; follow-up turns need no wake word until timeout or a closing phrase. |
| How to enter `engaged` | Four switchable triggers: wake word (sherpa-onnx open-vocabulary KWS, Chinese zipformer model, name as pinyin tokens, no training); gaze (frontal face + DoA match + speaker gate, double-checked by the main agent's `NO_REPLY`); antenna press; robot-initiated speech. Wake word and the utterance are one turn ("小管家，今天天气怎么样"). |
| Every turn needing a wake-up is tiring | Session window: 8 s after the robot stops speaking, extended while the addressee's face stays frontal; closing phrases end it; two `NO_REPLY` in a row end it. |
| Noise, echo, overlap | Hardware AEC on the XVF3800 (always on); Silero VAD 250 ms min speech, 600–800 ms hangover; barge-in only by the addressee (speaker id or DoA match); DoA sector tolerance. No custom DSP. |
| ASR quality for Chinese | MiniMax `asr-1.0` (`POST /v1/speech_to_text`, multipart WAV, streaming + diarization available) as first backend; `openai_transcription` and local `sherpa_sensevoice` as fallbacks selectable in config. Every call traced; a dashboard page compares transcripts with clips. |
| Latency (3–4 s before first word) | Streaming LLM → sentence-chunked TTS; "thinking" expression + short filler sound right after end-of-speech; per-stage latency traced. Streaming ASR later. |
| Tuning without guessing | Invariant 18: every engagement decision is traced with scores and a short clip (7-day prune); the dashboard "Listening monitor" shows live decisions and recent accepted/rejected segments with playback. |
| Enrollment burden | Voice: 3–5 utterances via dashboard or antenna-started conversation; face: a few frames via OpenCV YuNet + SFace. Done once per member; unknown people still work via wake word or antenna. |

Open points for the owner: the robot's wake-word name; default trigger set (proposal: wake word +
antenna on, gaze on but gated `soft`); whether a TV sits in the robot's field of view (sector
ignore); whether unknown guests may converse at all (`off` vs `soft`).

Sources: sherpa-onnx KWS docs (open-vocabulary, `text2token` with `ppinyin`, models
`sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01`, `…-zh-en-3M-2025-12-20`); sherpa-onnx
speaker-identification models (`speaker-recongition-models` release tag); MiniMax Speech to Text
reference (`platform.minimax.io/docs/api-reference/speech-to-text`, model `asr-1.0`, $0.38/h).

## [2026-10-26 #6] Decision: owner answers and consequences

Owner's answers (2026-10-26):

1. The Reachy Mini Lite is connected to the owner's Mac; development starts on this Mac.
2. MiniMax first for LLM / ASR / TTS; no on-device model inference for the agent; privacy is not a
   constraint for the prototype. *(An API key was shared in chat; it is not recorded anywhere and
   should be rotated. Credentials go into `.derived_data/config.json` via CLI or dashboard.)*
3. Channels: Telegram **and** WeChat.
4. Integrations (Jellyfin + qBittorrent, Home Assistant, …) use existing tools; sidekick exposes one
   protocol (tool use, MCP, skills) and these become **extensions**, manageable (CRUD) on the
   dashboard.
5. One interaction mode for everyone — no adult/child distinction.
6. No publishing intent.
7. Runtime cache and sandbox live beside the repository: run the CLI from the repository root,
   state in `./.derived_data/`.

Consequences written into `AGENTS.md`:

- New core module **`extension`** (manifest, loader, registry, lifecycle, registration bridge).
  Former feature modules `news`, `media`, `home` become **bundled extensions** under
  `extensions/`, plus a `robot` extension that is the only bridge from body/perception to agent
  tools (invariant 19). User-installed extensions go to `.derived_data/extensions/`.
- **`contact`** drops roles and child policy; keeps identity (voice + face enrollment, owner flag,
  remote ids). Invariant 13 becomes confirm-gated sensitive tools.
- **`channel`** gains `wechat.py`. Two viable paths found: Tencent's official iLink bot protocol
  for personal WeChat (QR login, HTTP long polling `getupdates` / `sendmessage`, DM + media, no
  groups; endpoint details are community-documented, the official reference is Tencent's npm
  plugin `@tencent-weixin/openclaw-weixin`), or WeCom (企业微信) "智能机器人 API 模式" with an
  official long-connection API and proactive messaging. Recommendation: Telegram first; WeChat via
  iLink after a spike that reads the official plugin for the exact protocol.
- **`asr`** first backend is `minimax_speech_to_text`; ASR input is 16 kHz mono WAV (MiniMax
  rejects raw PCM).
- **`storage`** data dir is `./.derived_data/` (override `SIDEKICK_HOME`); `.gitignore` added.
- Dependencies added to the planned set: `sherpa-onnx` (VAD, KWS, speaker embeddings, local
  ASR), `opencv-python` (face detect/embed). Verify sherpa-onnx 2.x wheels for macOS arm64 cp312
  at scaffolding time.
- Coverage check of the original requirements against the module map: multi-member Q&A →
  `interaction` + `contact` + `agent`; remote monitoring → `channel.telegram/wechat` + `robot`
  extension tools; timed/conditional automations → `agent.automation` + `perception` + extension
  watchers; child companionship → main agent + a `companion` subagent/skills, personalization via
  memory; daily news → `news` extension + cron job + delivery policy; downloads and streaming →
  `media` extension. No further core module identified.

## [2026-10-25 #5] Decision: harness, module map, swarm design, documentation layout

Agreed with the owner in session 1 and written into `AGENTS.md`:

- **Documentation lives in four places only:** `AGENTS.md` (harness + module yellow pages),
  `CLAUDE.md` (`@AGENTS.md`), module file headers (technical design), `PLAN.md` (this file,
  timestamped blocks). `README.md` / `README_CN.md` are developer-facing with ASCII flow diagrams.
  The `docs/` directory is removed; its research content is block #1 below. English everywhere
  except `README_CN.md`.
- **Repository shape:** `src/sidekick/<module>/` flat directories, no nested sub-directories;
  submodules are single `.py` files; `<module>/<module>.py` is the façade that assembles them;
  `src/sidekick/app.py` assembles modules; `src/sidekick/cli.py` is the CLI. Dependency chain
  `app.py → <module>.py → <submodule>.py`; cross-module dependencies one-way, enforced by
  `tests/test_architecture.py`.
  - Interpretation 1: the import root is `src/sidekick/` (not bare `src/`) so module names such as
    `config`, `agent`, `log` cannot collide with PyPI packages. Reversible.
  - Interpretation 2: data files (provider presets, dashboard HTML) sit flat in the module
    directory with a module prefix instead of a `resources/` sub-directory. Reversible.
- **Renames:** `console → dashboard`, `member → contact`. `log` and `storage` are mandatory base
  modules.
- **Agent swarm:** `agent` is a generic runtime. One **main agent** owns every inbound turn, runs
  on a fast LLM slot, does conversation and intent routing with a tiny tool set, and delegates via
  a `delegate(agent, task, mode)` tool. **Subagents** are domain workers with their own tool, MCP
  and skill allowlists and a stronger LLM slot by default; `sync` delegation blocks the turn,
  `async` posts the result back into the timeline for the next turn or the heartbeat.
- **Final module list:** `log`, `storage` · `llm`, `asr`, `tts`, `config`, `body` · `channel`,
  `contact`, `perception`, `interaction` · `agent` · feature modules `news`, `media`, `home` ·
  `dashboard`, `app.py`, `cli.py`. Allowed-import table is in `AGENTS.md` "Architecture".
- **Provider framework** mirrors weij-scoop with three extensions: LLM backend speaks multi-turn
  messages + tool calling + streaming; a new `asr` service block; the paired-provider default may be
  overridden per service and per LLM slot (`fast` / `smart`).

## [2026-10-25 #4] Todo: roadmap

Phases are ordered by dependency and by how early they produce something the owner can touch.
Tick items in `Progress` blocks, not here.

- [ ] **Phase 0 — Foundations.** Poetry project (`requires-python >=3.12,<3.13`), `log`,
  `storage`, `config` + `llm` + `asr` + `tts` with one working provider each and save-time probe,
  `cli.py` (`doctor`, `config`), `tests/test_architecture.py`, yellow pages marked `wip`.
- [ ] **Phase 1 — Body and voice MVP.** `body` (Reachy adapter + null body), `interaction`
  (VAD → ASR → main agent without tools → sentence-chunked TTS → speaker, barge-in, antenna
  press to listen, DoA turn, face tracking, idle breathing), minimal `dashboard` (settings,
  health). Outcome: a single person talks to the robot.
- [ ] **Phase 2 — Agent core.** ReAct loop, tool registry with permission gating, dialogue
  timeline + context views, memory tools, skills and MCP stores with CRUD tools, subagent
  delegation (sync + async), trace pages on the dashboard.
- [ ] **Phase 3 — Channels and automations.** `channel` protocol, Telegram adapter (allowlist,
  `/look`, `/say`, `/status`, media), delivery policy, `automation` jobs (cron / at / event),
  heartbeat, `perception` event bus with presence and basic audio events.
- [ ] **Phase 4 — Household.** `contact` profiles, roles and child policy, face identification,
  speaker attribution in the voice channel, per-contact memory scoping, quiet hours.
- [ ] **Phase 5 — Feature modules.** `news` (feeds ported from Scoop, morning briefing subagent),
  `media` (qBittorrent/aria2 + Jellyfin orchestration, completion notifications), `home` (Home
  Assistant), kids profile + story skill.
- [ ] **Phase 6 — Wireless and hardening.** Config profile for daemon-on-robot (WebRTC media),
  Raspberry Pi degraded profile, launchd/systemd units, backup/restore of `~/.sidekick`.

## [2026-10-25 #3] Discussion: core modules and gaps

Owner's three core modules, with the review outcome:

1. **`agent`** — fully self-built: ReAct, pluggable tool use, MCP and skills (both registered as
   tools so the agent can CRUD them), one dialogue list storing every conversation from every
   channel, memory, automations, heartbeat. *Review:* agreed. The single timeline needs three
   guards to work: per-message `speaker` / `channel` / `visibility` metadata; a filtered
   per-turn context view instead of full replay; replies routed to the originating channel by
   default. Heartbeat is defined as a periodic main-agent review job, implemented as a special
   automation, not a separate mechanism.
2. **`interaction`** — voice pipeline (ASR, TTS, agent) and robot interaction (camera, DoA, face
   tracking, body language). *Review:* agreed; split the Reachy-specific adapter into `body` so
   `interaction` targets an abstract body and simulation / Wireless / other robots change one
   module. The daemon already provides face detection and tracking, DoA, speech wobble and an
   emotions library, so `interaction` is smaller than expected.
3. **`config`** — unified internal API over providers that supply LLM + ASR + TTS, same framework as
   weij-scoop. *Review:* agreed; see block #1 (Scoop conventions) and block #5 (extensions).

Gaps identified and accepted as core modules: `channel`, `contact` (was `member`), `perception`,
`storage`, `log`, runtime (`app.py`), `dashboard` (was `console`).

Complexity trade-offs proposed and accepted in principle: single Poetry project with one package;
no LangChain-style frameworks; Telegram via raw Bot API over `httpx`; Silero VAD through
`onnxruntime` (already a `reachy-mini` dependency); MVP voice path is VAD-segmented batch ASR and
sentence-chunked batch TTS, streaming later; listening policy is antenna press or face-facing,
wake word later; face identification via a small ONNX embedding model, not InsightFace.

## [2026-10-25 #2] Discussion: scope, scenarios, key judgments

Owner's scenarios: multi-member Q&A; remote monitoring via a Telegram bot; automations (timed
reminders; conditional tasks such as home anomaly → remote or in-person notification, TV-show
update → notification); companionship for the child (chat, stories, learning); daily news; remote
download of videos/torrents with NAS-style streaming to phone and TV.

Scenario groups added in discussion:

| Domain | Owner | Added |
|---|---|---|
| Conversation & companionship | Q&A, multi-member, child chat/stories/learning | stories with expressions and sound; show-and-tell object explanations; language practice, dictation, homework timer; antenna mini-games; translation |
| Briefings | daily news | morning briefing with weather, calendar, commute, umbrella; per-member personalization; show updates, scores, parcel arrival |
| Automations & reminders | timed, conditional, remote/in-person notify | medication/water/posture; shared calendar, birthdays; bills, trash day; "tell dad when he gets home" relayed on face sighting |
| Perception & safety | home anomaly | stranger, nobody-for-long, crying, glass break, smoke alarm sound; doorbell/parcel log; pet watch; existing RTSP cameras as extra sources |
| Remote channels | Telegram monitoring | `/look` photo, short clip, `/listen`, `/say`; daily home event log; web console |
| Media center | downloads, NAS streaming | show subscriptions auto-download + notify; completion notice; cast to TV; family album, daily photo recap; music/podcast/white noise/radio |
| Home control | — | lights/AC/vacuum, leave/arrive modes, night window check |
| Household knowledge | — | WiFi password, appliance manuals, warranties, troubleshooting, photo intake |
| Privacy & permissions | — | privacy mode (head down, mic muted); roles admin/member/child/guest; child content filter and time windows; remote camera needs allowlist + confirmation |

Key judgments agreed in principle:

1. sidekick orchestrates existing services (qBittorrent/aria2, Jellyfin, Home Assistant, the
   Reachy daemon) rather than reimplementing them. Its core value is agent orchestration, embodied
   interaction, automations and channels.
2. sidekick is an independent always-on service; the robot is a node connected through the
   daemon. A thin `ReachyMiniApp` shell may be added later for antenna wake-up and store listing.
3. Mac mini is the primary target; Raspberry Pi is a degraded configuration, not a second
   implementation.
4. The speech path is an abstraction with multiple implementations (cloud realtime, local cascade,
   domestic cloud ASR/TTS), never bound to OpenAI Realtime.
5. Multi-member identification is face-first, voice later; MVP is turn-taking with speaker switch,
   not overlapped speech separation.
6. "Home anomaly" means the room the robot sits in plus events from Home Assistant or external
   cameras; the robot cannot move.
7. Automations are "LLM translates, rule engine executes": natural language becomes a stored job;
   execution is deterministic and auditable.
8. Security from day one: daemon is unauthenticated and LAN-only; remote camera access needs
   allowlist and confirmation; children's data may need a local-only option; secrets stay out of
   the repository.

## [2026-10-25 #1] Research: Reachy Mini platform, weij-scoop conventions, OpenClaw

Snapshot: `reachy-mini` PyPI 1.12.0 (2026-10-15), GitHub `main` 1.13.0.dev0;
`reachy_mini_conversation_app` 1.1.1; Poetry 2.5.1 on the dev machine. Verify against installed
versions when implementing.

### Sources

| Topic | Link |
|---|---|
| Docs index / Python SDK / core concepts / media architecture / apps / lifecycle contract / REST | https://huggingface.co/docs/reachy_mini/ (`index`, `SDK/python-sdk`, `SDK/core-concept`, `SDK/media-architecture`, `SDK/apps`, `SDK/lifecycle-contract`, `API/rest-api`, `API/*`) |
| Hardware datasheets | `platforms/reachy_mini_lite/hardware`, `platforms/reachy_mini/hardware` |
| Wireless dev workflow, GStreamer install, troubleshooting | `platforms/reachy_mini/development_workflow`, `SDK/gstreamer-installation`, `troubleshooting` |
| Source repo (AGENTS.md, `skills/*.md`, `examples/*.py`, `docs/source/integrations/home_assistant.md`) | https://github.com/pollen-robotics/reachy_mini |
| Official conversation app | https://github.com/pollen-robotics/reachy_mini_conversation_app |
| Motion datasets | HF datasets `pollen-robotics/reachy-mini-emotions-library`, `pollen-robotics/reachy-mini-dances-library` |
| Media stack blog | https://huggingface.co/blog/pollen-robotics/reachy-mini-media-stack |
| OpenClaw docs | https://docs.openclaw.ai/ (`index`, `concepts/architecture`, `concepts/features`, `tools/skills`, `automation`) |

### Hardware

| Item | Reachy Mini Lite | Reachy Mini (Wireless) |
|---|---|---|
| Compute | none; USB-C to host (macOS/Linux/Windows) | Raspberry Pi CM4 (CM4104016: WiFi, 4 GB RAM, 16 GB eMMC) |
| Power | wall supply 6.8–7.6 V (7 V / 5 A); USB does not power it | wall + LiFePO4 2000 mAh / 6.4 V / 12.8 Wh with BMS |
| Link | USB-C (internally: USB serial for motors + UVC camera + USB audio) | WiFi 2.4/5 GHz, Bluetooth; USB-C is an output port; no USB tethering |
| IMU | no | yes (BMI088: accel, gyro, quaternion, temperature) |
| Mass | 1.350 kg | 1.475 kg |
| Daemon location | host | onboard, systemd `reachy-mini-daemon` |
| REST bind | `127.0.0.1:8000` | `0.0.0.0:8000`, mDNS `reachy-mini.local` |
| Price | $299 | $449 |

Shared parts: head 6 DoF (Stewart platform), body yaw, two antennas; 9 Dynamixel servos on TTL
at 1 Mbaud, IDs 10–18 (`body_rotation`, `stewart_1..6`, `right_antenna`, `left_antenna`;
XC330-M288-PG body, XL330-M288-T ×6 head, XL330-M077-T ×2 antennas). Camera: Pi Camera v3 Wide
(IMX708, 12 MP, 120°, autofocus, calibrated); Lite exposes it as UVC MJPEG, macOS caps at 30 fps.
Audio: reSpeaker XVF3800 four-mic PDM array, 16 kHz, hardware AEC always on, stereo mix, DoA with
VAD flag; 5 W / 4 Ω speaker with daemon-side EQ. Safety limits (SDK clamps): head pitch/roll
±40°, head yaw ±180°, body yaw ±160°, head–body yaw delta ≤ 65°.

Known quirks: antennas shake at exactly 0°, default offset ~10°; sleep pose points the camera into
the shell (dark image, not a fault); Lite camera may be dark → enable auto-exposure; Linux XVF3800
playback is quiet until `PCM1` is 100 %; battery level is not readable (LED only).

### Software architecture

- Client–server. The daemon (`reachy-mini-daemon`, FastAPI/Uvicorn) owns serial, camera and
  audio, runs the ~50 Hz motor loop, face detection/tracking, the app manager, and mDNS
  `_reachy-mini._tcp`. Backends: `robot`, `mujoco` (`--sim`), `mockup_sim`. Kinematics:
  `AnalyticalKinematics` (default), `NN`, `Placo` (needed for gravity compensation).
- Daemon CLI of note: `--sim`, `--wireless-version`, `--no-media`, `--serialport auto`,
  `--fastapi-host/--fastapi-port`, `--no-wake-up-on-start`, `--goto-sleep-on-stop`,
  `--preload-datasets`, `--kinematics-engine`, `--log-level/--log-file`. Docs mention
  `--startup-app`; source stores it via `startup_app_config` / `PUT /api/apps/startup-app`.
- REST/WS at `http://<host>:8000` (`/docs`, `/openapi.json`): `/api/apps`, `/api/daemon`,
  `/api/state`, `/api/move`, `/api/motors`, `/api/kinematics`, `/api/volume`, `/api/hf-auth`;
  `ws://…/api/state/ws/full`. **No authentication; LAN-only trust.**
- Deployment topologies: Lite + host (daemon and agent same machine, LOCAL media: IPC frames
  capped at 10 fps + direct GStreamer audio); Wireless with code on CM4 (`/venvs/apps_venv`,
  Python 3.12, limited CPU); Wireless with code on the Mac (WEBRTC media: H.264 + Opus, client
  needs GStreamer); cloud consumer via `central-consumer` extra (aiortc).
- Raspberry Pi as Lite host is plausible: the Wireless CM4 already runs the same daemon on
  aarch64 Linux. Caveats: Reachy Mini Control desktop app has no ARM64 build (use the CLI daemon);
  udev rules for `1a86:55d3` and `38fb:1001`; Linux needs GStreamer ≥ 1.22 from apt plus the
  Rust `gst-plugin-webrtc` (gst-plugins-rs 0.14.5) built with `cargo cinstall`,
  `GST_PLUGIN_PATH=/opt/gst-plugins-rs/lib/aarch64-linux-gnu`.
- Wireless ops: `ssh pollen@reachy-mini.local` (password `root`), `reachyminios_check`,
  `journalctl -u reachy-mini-daemon -f`, venvs `/venvs/mini_daemon` and `/venvs/apps_venv`,
  offline install via `scp` + `/venvs/apps_venv/bin/pip install`, proxy via `systemctl edit`,
  HF mirror `HF_ENDPOINT=https://hf-mirror.com/`.

### Python SDK essentials

```python
ReachyMini(
    robot_name="reachy_mini",
    host="reachy-mini.local",
    port=8000,
    connection_mode="auto",  # auto | localhost_only | network
    media_backend="default",  # default | local | webrtc | no_media
    automatic_body_yaw=True,
    timeout=5.0,
    log_level="INFO",
)
```

| Area | Methods |
|---|---|
| Motion | `goto_target(head, antennas, body_yaw, duration=0.5, method="minjerk")` (methods `linear`/`minjerk`/`ease_in_out`/`cartoon`); `set_target(...)` for 50–100 Hz loops; `cancel_move()`; `play_move(move, play_frequency=100, initial_goto_duration=0, sound=True)`; `look_at_world(x,y,z)`; `look_at_image(u,v)`; `get_current_head_pose()`; `get_current_joint_positions()`; `get_present_antenna_joint_positions()` |
| Motors | `enable_motors()`, `disable_motors()`, `enable/disable_gravity_compensation()` (Placo only); `wake_up()` does **not** enable torque; `goto_sleep()` |
| Perception | `start_head_tracking(weight)`, `stop_head_tracking()`, `get_tracked_face()` → `FaceTarget(detected, x, y ∈ [-1,1], roll)`; `imu` (Wireless) |
| Media | `media.get_frame()` BGR uint8; `get_frame_jpeg()`; `start_recording()/start_playing()`; `get_audio_sample()` float32 (n,2) @16 kHz; `push_audio_sample()` float32 (n,1|2) @16 kHz non-blocking; `get_DoA()` → (rad: 0 left, π/2 front/back, π right; speech bool); `play_sound(file)`; `release_media()/acquire_media()`; `enable_wobbling()/disable_wobbling()` |
| Recording | `start_recording()/stop_recording()` → list[dict] |
| Utils | `reachy_mini.utils.create_head_pose(x,y,z,roll,pitch,yaw, mm=False, degrees=True)` → 4×4; `reachy_mini.utils.discovery.find_robots()` |
| Motion lib | `reachy_mini.motion.recorded_move.RecordedMoves(hf_dataset_name).list_moves()/get(name)`; `Move.evaluate(t)`; `motion/head_wobbler.py`, `motion/speech_tapper.py`; `vision/face_detector.py`, `vision/face_tracking.py`, `vision/look_at.py` |

### App framework and lifecycle

- `ReachyMiniApp.run(reachy_mini, stop_event)`; entry point group `reachy_mini_apps`; daemon runs
  `python -u -m <pkg>.main` as a subprocess, stops with `SIGINT`, resets the robot afterwards.
  **One app at a time**; apps inherit the daemon's environment; optional `custom_app_url` starts a
  FastAPI UI serving `static/`. Scaffold only with `reachy-mini-app-assistant create`.
- Lifecycle contract: apps never wake/sleep; states `enabled` (awake), `gravity_compensation`
  (not awake), `disabled` (asleep at sleep pose, crash elsewhere); daemon idle-reset after 1.5 s
  (15 s on handoff); wake budget 5 s, sleep 6 s. Safe torque: goto sleep pose then disable; read
  pose then goto it in 0.05 s then enable.
- Motion patterns from `skills/`: `goto_target` for gestures, `set_target` only from one 50–100 Hz
  loop; layered moves (primary exclusive, secondary additive offsets); breathing ≈ 2° pitch at
  0.2 Hz; LLM never drives motors directly (tool → queue → loop); antennas as buttons (|angle| >
  0.3 rad, debounce); head as joystick.

### Official conversation app (reference)

Hugging Face realtime backend proxying OpenAI gpt-realtime by default (`openai==2.28.0`), switchable
to a local `speech-to-speech` server; local Silero VAD with barge-in; vision via gpt-realtime or
SmolVLM2; tools `dance`, `play_emotion`, `camera`, `move_head`, `head_tracking`, `sweep_look`,
`go_to_sleep`, `remember`/`forget`, `volume_control`, `robot_status`, plus MCP Space tools; profiles
as Markdown with `+++` TOML header; `.env` keys `REALTIME_TRANSCRIPTION_LANGUAGE`,
`REACHY_MINI_MEMORY_ENABLED`, `REACHY_MINI_CAMERA_ENABLED`, …; `--ui` on 7860. From China the
OpenAI path needs a VPN (FAQ gives split-routing advice).

### Home Assistant

Official HACS integration `reachy_mini_homeassistant`: mDNS discovery, 30 s polling of
`/api/daemon/status`, `/api/daemon/robot-app-lock-status`, `/api/state/doa`, `/api/volume/*`;
sensors + six blueprints. Direction is HA monitoring the robot; sidekick controlling the home is
sidekick acting as an HA client.

### Dependencies and packaging

- `reachy-mini` 1.12.0: `requires-python >= 3.11`, docs recommend 3.12. Core: `fastapi`,
  `uvicorn[standard]`, `pydantic>=2.12.5,<3`, `websockets>=12,<16`, `aiohttp>=3.14`,
  `numpy>=2.2.5`, `onnxruntime==1.27.0` (wheels cp311–cp314, macOS arm64, manylinux
  x86_64/aarch64, Windows), `huggingface-hub>=1.20.1,<2`, `zeroconf`, `pyserial`, `pyusb`,
  `rustypot`, `reachy-mini-rust-kinematics`, `reachy_mini_motor_controller`, `pip>=26.1`.
  Platform: non-Linux `gstreamer-bundle==1.28.3` (pip-delivered GStreamer); Linux
  `PyGObject>=3.42.2,<=3.46.0` + system GStreamer. Extras: `mujoco`, `placo_kinematics`,
  `rerun`, `wireless-version`, `opencv`, `examples`, `central-consumer`.
- Poetry notes: use `[project]` (PEP 621); pin `python = ">=3.12,<3.13"`; do not re-pin
  `onnxruntime` or `gstreamer-bundle`; on Raspberry Pi install `libgirepository1.0-dev
  libcairo2-dev python3-gi` before resolving `PyGObject`.

### Dev machine (2026-10-25)

macOS 27.0.1 arm64; only system Python 3.9.6 (**below the 3.11 minimum**); Poetry 2.5.1 at
`~/.local/bin`; no `uv`, no Homebrew Python, no GStreamer CLI (not needed on macOS), no Node, no
Docker. Install Python 3.12 before scaffolding.

### weij-scoop conventions (to mirror)

Four-layer provider abstraction: declarative preset JSON per provider (`id`, `name`,
`console_url`, `credentials`, `regions`, `languages`, `capabilities`, `llm{api,url{region},model,
params,extra_body,credential_map}`, `tts{…,default_speed,per_language}`, `default_voice`,
`voices`); thin user spec (`provider`, `credentials`, `region`, `voice`, `speed`, `language`);
`apply()` merges preset + spec + probed region into `ProviderSpec{api, params, credentials}` and
builds backends in one `switch api`; fixed backend shape (`*Configuration` + `*Backend` whose
`infer` returns a complete `*Result` with `apiCode`); one `*Session.shared` per service that traces
every call to SQLite; save-time probe through the real backend. Twelve invariants (dependency
direction, no third-party deps, never log secrets, declarative config, SQLite pattern, versioned DB
names, English logs, trace all calls, dev surfaces always shipped, …). File naming
`<Area>Session` / `<Area>Schemas` / `<Area>Utils` / `<Area><Component>`. Five TTS backends
(`minimax_sync`, `volcengine`, `qwen`, `openai`, `gemini`) and the RSS / Hacker News / Telegram
feed parsers are portable to Python.

### OpenClaw (shape to emulate)

MIT, Node.js, self-hosted. One long-lived **Gateway** (WebSocket `127.0.0.1:18789`, typed
protocol) is the source of truth for sessions, routing and channel connections. **Channels** as
plugins (Telegram, WhatsApp, Discord, Slack, Signal, iMessage, Matrix, Teams, Feishu, WeChat …);
DMs share a main session, groups isolated. Embedded **agent runtime** with tools; multi-agent
routing. **Skills** are `SKILL.md` files (frontmatter `name`/`description`, body instructions)
discovered from layered directories with gating metadata; ClawHub registry. **Automation**: cron,
one-shot, webhook triggers, hooks, heartbeat as a job, `AGENTS.md` as standing orders. **Nodes**
(iOS/Android/macOS) join the same socket exposing `camera.*`, `screen.record`, `location.get` —
in sidekick the Reachy Mini is the embodied node. Pairing + tokens for non-loopback access.
