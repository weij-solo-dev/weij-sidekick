/* sidekick dashboard — plain JS, polls /api/* (AGENTS.md "Dashboard and CLI"); the shell (module
   list on the left, one page per core module on the right), tab routing (and a page's views,
   #agent/tools), the 1 Hz health poll (feeds System's status card, the sidebar dots and the
   readiness card), the two renderers every tab shares — parameter cards built from
   /api/config/schema and service cards (one per LLM / ASR / TTS / VAD slot) — the readiness run,
   and every plain page. dashboard_live.js owns the rail's live feed and the Live transcript,
   dashboard_robot.js the Robot controller, dashboard_robot3d.js the 3D body, dashboard_replay.js
   the Replay tab. */
(function () {
  const $ = (id) => document.getElementById(id);
  const api = async (path, opts) => {
    const r = await fetch(path, opts);
    if (!r.ok) {
      const text = await r.text();
      if (r.status === 409 && text.includes("Bobby is stopped") && window.SidekickService) window.SidekickService.toast("Bobby is stopped — start the service first", "warn", "system");
      throw new Error(`${r.status} ${text}`);
    }
    return r.json();
  };
  const post = (path, body) => api(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const put = (path, body) => api(path, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const del = (path) => api(path, { method: "DELETE" });
  const fmt = (v, d = 0) => (v === null || v === undefined ? "–" : typeof v === "number" ? v.toFixed(d) : String(v));
  const kv = (el, pairs) => { el.innerHTML = pairs.map(([k, v, cls]) => `<div>${k}</div><div class="${cls || ""}">${v}</div>`).join(""); };
  const strip = (el, pairs) => { el.innerHTML = pairs.map(([k, v, cls]) => `<span>${k}<b class="${cls || ""}">${v}</b></span>`).join(""); };  // label · value pairs in one line
  const time = (ts) => new Date(ts * 1000).toLocaleTimeString();
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---------------------------------------------------------------- tabs: one per module directory (Live and Voice share `interaction`;
  // perception rides with Live; System = config · doctor · storage · log); every tab aggregates its own monitoring, parameters and debugging
  const TITLES = { live: "Live", voice: "Voice", body: "Body", agent: "Agent", automation: "Automation", contact: "Contact", channel: "Channel", record: "Record", extension: "Extension", system: "System" };
  const ALIASES = { robot: "body", listen: "voice/decisions", listening: "voice/decisions", timeline: "agent/timeline", memory: "agent/memory", tools: "agent/tools", subagents: "agent/swarm", agents: "agent/swarm", mcp: "agent/mcp", skills: "agent/skills", traces: "agent/swarm", automations: "automation", jobs: "automation", channels: "channel", contacts: "contact", extensions: "extension", replay: "record", settings: "system", setup: "system", logs: "system/logs" };  // old deep links
  const LOADERS = {
    body: () => { if (window.SidekickRobot) window.SidekickRobot.start(); return renderPage("body"); },
    voice: () => Promise.all([renderPage("voice"), loadDecisions(), loadContacts().catch(() => {})]),
    agent: () => Promise.all([loadAgent(), loadTimeline(), loadMemory(), loadTestSpeakers(), renderPage("agent")]),
    automation: () => Promise.all([loadAutomation(), renderPage("automation")]),
    channel: () => loadChannels(),
    contact: () => Promise.all([loadContacts(), renderPage("contact"), initTvZone()]),
    extension: () => loadExtensions(),
    record: () => { if (window.SidekickReplay) window.SidekickReplay.open(); return renderPage("record"); },
    system: () => Promise.all([loadSystem(), renderPage("system")]),
  };
  let currentTab = "live";
  // views (PLAN.md block #59): a page with a view bar shows one view at a time; the route is
  // "tab/view" (#agent/tools); a page keeps its last view for the session
  const lastView = {};
  function showView(tab, view) {
    const section = $(`tab-${tab}`);
    const views = section ? [...section.querySelectorAll(":scope > .view")] : [];
    if (!views.length) return null;
    const pick = views.find((v) => v.dataset.view === view) || views.find((v) => v.dataset.view === lastView[tab]) || views[0];
    views.forEach((v) => v.classList.toggle("active", v === pick));
    section.querySelectorAll(".viewbar [data-view]").forEach((b) => {
      const on = b.dataset.view === pick.dataset.view;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    lastView[tab] = pick.dataset.view;
    return pick.dataset.view;
  }
  const routeOf = (tab, view) => (view ? `${tab}/${view}` : tab);
  function selectView(tab, view) {
    const shown = showView(tab, view);
    const route = routeOf(tab, shown);
    if (location.hash.slice(1) !== route) history.replaceState(null, "", `#${route}`);
    const content = document.querySelector(".content");
    if (content) content.scrollTop = 0;
    if (window.innerWidth <= 900) window.scrollTo(0, 0);
  }
  document.querySelectorAll(".viewbar [data-view]").forEach((b) => b.addEventListener("click", () => selectView(b.closest("section").id.slice(4), b.dataset.view)));
  function openTab(route) {
    route = ALIASES[route] || route;
    const [name, view] = route.split("/");
    const b = document.querySelector(`nav button[data-tab="${name}"]`);
    if (!b) return;
    document.querySelectorAll("nav button[data-tab]").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll("section").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
    // the camera and 3D body cards are single views shared by Live and Body: move them into the open page's slots
    [["cam-card", "camera"], ["robot3d-card", "body3d"]].forEach(([id, slotName]) => {
      const card = $(id), slot = document.querySelector(`#tab-${name} [data-slot="${slotName}"]`);
      if (card && slot && card.parentElement !== slot) slot.appendChild(card);
    });
    document.title = `Sidekick · ${TITLES[name] || name}`;
    $("menu-current").textContent = TITLES[name] || name;
    shell.classList.remove("menu-open");
    $("menu-btn").setAttribute("aria-expanded", "false");
    if (currentTab === "live" && name !== "live" && window.SidekickLive) window.SidekickLive.stop();
    if (currentTab === "body" && name !== "body" && window.SidekickRobot) window.SidekickRobot.stop();
    if (currentTab === "record" && name !== "record" && window.SidekickReplay) window.SidekickReplay.close();
    currentTab = name;
    if (name === "live" && window.SidekickLive) window.SidekickLive.start();
    if (LOADERS[name]) Promise.resolve().then(LOADERS[name]).catch((e) => console.warn(e));
    // the camera stream and the 3D view run only while Live or Body is open
    if (window.SidekickLive && window.SidekickLive.railVisible) window.SidekickLive.railVisible(name === "live" || name === "body");
    window.dispatchEvent(new Event("resize"));
    const shown = routeOf(name, showView(name, view));
    if (location.hash.slice(1) !== shown) history.replaceState(null, "", `#${shown}`);
    const content = document.querySelector(".content");
    if (content) content.scrollTop = 0;  // the hash also names a table body (#timeline, #memory): undo the anchor scroll
  }
  document.querySelectorAll("nav button[data-tab]").forEach((b) => b.addEventListener("click", () => openTab(b.dataset.tab)));
  window.addEventListener("hashchange", () => {
    const route = ALIASES[location.hash.slice(1)] || location.hash.slice(1);
    const [name, view] = route.split("/");
    if (name && name !== currentTab) openTab(route);
    else if (name) selectView(name, view);
  });
  document.addEventListener("click", (e) => { const a = e.target.closest("[data-go]"); if (a) { e.preventDefault(); openTab(a.dataset.go); } });
  const shell = $("shell");
  // phones: the module list folds into a menu button that names the current module
  const setMenu = (open) => { shell.classList.toggle("menu-open", open); $("menu-btn").setAttribute("aria-expanded", open ? "true" : "false"); };
  $("menu-btn").addEventListener("click", () => setMenu(!shell.classList.contains("menu-open")));
  $("menu-backdrop").addEventListener("click", () => setMenu(false));
  const DOT_RANK = { "": 0, acc: 1, ok: 1, warn: 2, bad: 3 };
  const dot = (id, cls) => { const el = $(id); if (el) el.className = `dot${cls ? " " + cls : ""}`; };
  const worst = (...levels) => levels.reduce((a, b) => (DOT_RANK[b || ""] > DOT_RANK[a || ""] ? b : a), "");
  // theme follows the system (no switch)
  document.documentElement.removeAttribute("data-theme");
  window.SidekickApp = window.SidekickApp || {};
  window.SidekickApp.currentTab = () => currentTab;
  let lastHealth = null;
  Object.assign(window.SidekickApp, { openTab, loadTimeline: () => loadTimeline(), esc: (v) => esc(v), time: (ts) => time(ts), health: () => lastHealth, telemetry: (el, f) => telemetry(el, f), readiness: () => readiness, runReadiness: () => runReadiness() });

  // ---------------------------------------------------------------- config: cache, schema, catalog
  let cfg = null, schema = null, providers = null;
  const loadConfig = async (force) => { if (!cfg || force) cfg = await api("/api/config"); return cfg; };
  const loadSchema = async () => { if (!schema) schema = await api("/api/config/schema"); return schema; };
  const loadProviders = async (force) => { if (!providers || force) providers = await api("/api/config/providers"); return providers; };
  const getPath = (obj, path) => path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
  const findField = (section, path) => {
    let fields = (schema && schema[section]) || [];
    let f = null;
    for (const key of path.split(".")) { f = fields.find((x) => x.name === key) || null; if (!f) return null; fields = f.fields || []; }
    return f;
  };

  // which parameters each card shows (section.path); the card's HTML is in dashboard_index.html
  const SWAY_DETAIL = ["pitch_deg", "yaw_deg", "roll_deg", "x_mm", "y_mm", "z_mm", "pitch_hz", "yaw_hz", "roll_hz", "x_hz", "y_hz", "z_hz", "loud_low_db", "loud_high_db", "loud_offset_db", "loud_gamma", "vad_on_db", "vad_off_db", "vad_attack_ms", "vad_release_ms", "attack_ms", "release_ms", "follow", "latency_ms"].map((k) => `body.sway.${k}`);
  const PARAMS = {
    "robot.motion": { fields: ["body.expressiveness", "body.sway.enabled", "body.sway.master", "body.sdk_wobble", "body.volume"], sliders: ["body.expressiveness", "body.sway.master"] },
    "robot.attention": { fields: ["interaction.face_tracker", "interaction.face_servo_gain", "interaction.idle_face_tracking_weight", "interaction.engaged_face_tracking_weight", "interaction.idle_scan", "interaction.idle_scan_min_s", "interaction.idle_scan_max_s", "interaction.idle_scan_yaw_rad", "interaction.idle_scan_hold_s", "interaction.sound_glance", "interaction.sound_glance_min_dbfs", "interaction.sound_glance_min_s", "interaction.sound_glance_hold_s", "perception.poll_hz", "perception.mutual_gaze_s", "perception.mutual_gaze_min_height"], sliders: ["interaction.face_servo_gain"] },
    "robot.sway": { fields: SWAY_DETAIL },
    "robot.daemon": { fields: ["body.mode", "body.host", "body.port", "body.media_backend", "body.manage_daemon", "body.sim", "body.wake_on_start", "body.sleep_on_stop", "body.daemon_log_level", "body.daemon_start_timeout_s", "body.preload_datasets"] },
    "voice.wake": { fields: ["robot.aliases", "robot.keywords"] },
    "voice.triggers": { fields: ["interaction.triggers", "interaction.speaker_gate", "interaction.asr_slot", "interaction.shadow_asr", "interaction.session_timeout_s", "interaction.answer_timeout_s", "interaction.no_reply_limit", "interaction.language"] },
    "voice.thresholds": { fields: ["interaction.name_match_threshold", "interaction.min_segment_dbfs", "interaction.echo_similarity", "interaction.self_sector_tolerance_rad", "interaction.doa_sector_tolerance_rad", "interaction.pre_roll_s", "interaction.duck_db", "interaction.hard_stop_speech_s", "interaction.clip_max_s", "interaction.trace_retention_days"] },
    "voice.words": { fields: ["interaction.closing_phrases", "interaction.stop_words", "interaction.backchannels", "interaction.fillers", "interaction.tv_sector", "interaction.tv_sector_tolerance_rad"] },
    "voice.language": { fields: ["languages.default", "languages.order"] },
    "voice.pacing": { fields: ["interaction.sentence_pause_ms"] },
    "agent.main": { fields: ["agents.main_llm_slot", "agents.main_max_steps", "agents.main_max_tokens", "agents.context_chars", "agents.main_hedge_s"] },
    "automations.initiative": { fields: ["interaction.sociability", "automation.quiet_hours"] },
    "automations.scheduler": { fields: ["automation.enabled", "automation.tick_s", "automation.heartbeat_minutes"] },
    "contacts.recognition": { fields: ["contacts.voice_threshold", "contacts.face_threshold", "contacts.enroll_self", "perception.presence_enter_s", "perception.presence_leave_s"] },
    "replay.recording": { fields: ["recording.enabled", "recording.root", "recording.chunk_minutes", "recording.retention_hours", "recording.min_free_gb", "recording.width", "recording.height", "recording.fps", "recording.bitrate_kbps", "recording.audio_codec", "recording.telemetry_hz"] },
    "system.dashboard": { fields: ["dashboard.host", "dashboard.port"] },
  };
  const LANG_NAMES = { yue: "廣東話 Cantonese", zh: "普通話 Mandarin", en: "English" };

  function control(section, path, f, value, opts) {
    const ref = `${section}|${path}`;
    const label = `<span class="p-name">${esc(path.split(".").slice(-1)[0])}${f.description ? `<small>${esc(f.description)}</small>` : ""}</span>`;
    const num = (step) => `<input type="number" step="${step}" data-p="${ref}" data-type="${f.type}" ${f.min != null ? `min="${f.min}"` : ""} ${f.max != null ? `max="${f.max}"` : ""} value="${value ?? ""}" ${f.nullable ? 'placeholder="empty"' : ""}>`;
    switch (f.type) {
      case "boolean": return `<label class="p-row">${label}<input type="checkbox" data-p="${ref}" data-type="boolean" ${value ? "checked" : ""}></label>`;
      case "enum": return `<label class="p-row">${label}<select data-p="${ref}" data-type="enum">${f.choices.map((c) => `<option ${c === value ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>`;
      case "integer": return `<label class="p-row">${label}${num(1)}</label>`;
      case "number":
        if (opts.sliders && opts.sliders.includes(`${section}.${path}`) && f.min != null && f.max != null) {
          const step = (f.max - f.min) / 30;
          return `<label class="p-row">${label}<span class="p-range"><input type="range" data-p="${ref}" data-type="number" min="${f.min}" max="${f.max}" step="${step.toFixed(3)}" value="${value ?? f.min}"><output>${Number(value ?? f.min).toFixed(2)}</output></span></label>`;
        }
        return `<label class="p-row">${label}${num("any")}</label>`;
      case "list": return `<label class="p-row wide">${label}<input type="text" data-p="${ref}" data-type="list" data-items="${f.items}" value="${esc((value || []).join(" "))}" placeholder="${f.nullable ? "empty = none" : "space separated"}"></label>`;
      case "flags": return `<div class="p-row wide">${label}<div class="flags">${Object.entries(value || {}).map(([k, v]) => `<label><input type="checkbox" data-p="${ref}.${k}" data-type="boolean" ${v ? "checked" : ""}> ${esc(k)}</label>`).join("")}</div></div>`;
      default: return `<label class="p-row">${label}<input type="text" data-p="${ref}" data-type="string" value="${esc(value ?? "")}" ${f.nullable ? 'placeholder="empty"' : ""}></label>`;
    }
  }
  async function renderParams(container) {
    const spec = PARAMS[container.dataset.params];
    if (!spec) return;
    await Promise.all([loadConfig(), loadSchema()]);
    const rows = spec.fields.map((ref) => {
      const [section, ...rest] = ref.split(".");
      const path = rest.join(".");
      const f = findField(section, path);
      if (!f) return `<div class="p-row dim">${esc(ref)} <small>not in schema</small></div>`;
      return control(section, path, f, getPath(cfg[section], path), spec);
    }).join("");
    const body = container.dataset.fold ? `<details class="p-fold"><summary>${esc(container.dataset.fold)}</summary>${rows}</details>` : rows;
    container.innerHTML = `${body}<div class="p-status"></div>`;
    container.querySelectorAll("input[type=range]").forEach((el) => el.addEventListener("input", () => { el.nextElementSibling.textContent = Number(el.value).toFixed(2); }));
    container.querySelectorAll("[data-p]").forEach((el) => el.addEventListener("change", () => saveParam(el, container.querySelector(".p-status"))));
  }
  function readControl(el) {
    const type = el.dataset.type;
    const [section, path] = el.dataset.p.split("|");
    const f = type === "boolean" ? null : findField(section, path);
    const nullable = !!(f && f.nullable);
    if (type === "boolean") return el.checked;
    if (type === "integer") return el.value === "" ? (nullable ? null : 0) : parseInt(el.value, 10);
    if (type === "number") return el.value === "" ? (nullable ? null : 0) : Number(el.value);
    if (type === "list") { const parts = el.value.split(/\s+/).filter(Boolean); if (!parts.length && nullable) return null; return el.dataset.items === "number" ? parts.map(Number) : parts; }
    return el.value === "" && nullable ? null : el.value;
  }
  async function saveParam(el, statusEl) {
    const [section, path] = el.dataset.p.split("|");
    const value = readControl(el);
    const values = {}; let cur = values;
    const parts = path.split(".");
    parts.forEach((k, i) => { if (i === parts.length - 1) cur[k] = value; else cur = cur[k] = {}; });
    statusEl.className = "p-status"; statusEl.textContent = "saving…";
    try {
      let note;
      if (section === "languages") { await post("/api/config/languages", { ...cfg.languages, ...values }); cfg.languages = { ...cfg.languages, ...values }; note = "applied"; }
      else { const r = await post(`/api/config/${section}`, { values }); note = r.note; delete r.note; delete r.applied; cfg[section] = r; }
      statusEl.textContent = `${parts[parts.length - 1]}: ${note}`;
      if (/next start/.test(note || "") && window.SidekickService && window.SidekickService.running()) statusEl.insertAdjacentHTML("beforeend", ' · <a href="#" data-service-restart>Restart now</a>');
      if (section === "contacts" && path === "tv_zone") initTvZone();
    } catch (e) { statusEl.className = "p-status bad"; statusEl.textContent = e.message.slice(0, 300); }
  }

  // service cards: one per slot — provider, model / voice, the provider's key (write-only), probe
  const svcDraft = {};
  function serviceCard(slotKey) {
    const [kind, name] = slotKey.split(".");
    const slot = providers.slots[slotKey] || {};
    const options = providers.providers.filter((p) => p.services.includes(kind));
    const chosen = svcDraft[slotKey] || slot.provider;
    const p = options.find((x) => x.id === chosen) || options[0];
    if (!p) return `<div class="card svc"><h3>${esc(slotKey)}</h3><p class="dim">no provider offers ${esc(kind)}</p></div>`;
    const models = p.models[kind] || { default: "", slots: {} };
    const modelDefault = (models.slots && models.slots[name]) || models.default || "";
    const lang = (providers.languages && providers.languages.default) || "yue";
    const voices = kind === "tts" ? (p.voices[lang] || []) : [];
    const sharedWith = (p.slots || []).filter((s) => s !== slotKey);
    const keyState = p.credentials.length ? (p.configured ? `<span class="ok">key set</span>` : `<span class="bad">key missing</span>`) : `<span class="dim">no key needed</span>`;
    return `<div class="card svc" data-slot="${esc(slotKey)}"><h3>${esc(slotKey)} <small class="key">${keyState}${p.console_url ? ` · <a href="${esc(p.console_url)}" target="_blank" rel="noopener">console ↗</a>` : ""}</small></h3>
      <div class="svc-grid">
        <label class="f">provider<select data-k="provider">${options.map((o) => `<option value="${esc(o.id)}" ${o.id === p.id ? "selected" : ""}>${esc(o.name)}</option>`).join("")}</select></label>
        <label class="f">model<input data-k="model" value="${esc(slot.provider === p.id ? slot.model || "" : "")}" placeholder="${esc(modelDefault || "provider default")}"></label>
        ${kind === "tts" ? `<label class="f">voice (${esc(lang)})<select data-k="voice"><option value="">provider default${p.default_voice && p.default_voice[lang] ? ` (${esc(p.default_voice[lang])})` : ""}</option>${voices.map((v) => `<option value="${esc(v.id)}" ${slot.voice === v.id ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></label><label class="f">speed<input type="number" step="0.1" min="0.5" max="2" data-k="speed" value="${slot.speed ?? ""}" placeholder="1.0"></label>` : ""}
        ${p.credentials.map((f) => `<label class="f">${esc(f)}<input type="password" data-k="cred:${esc(f)}" placeholder="${p.configured ? "set · leave blank to keep" : "required"}" autocomplete="off"></label>`).join("")}
      </div>
      <div class="row" style="margin-bottom:0"><button class="primary" data-svc-save>Save</button><button data-svc-probe>Probe</button><span class="dim" data-svc-result>${sharedWith.length ? `${p.credentials.length ? "key shared with" : "also used by"} ${esc(sharedWith.join(", "))}` : ""}</span></div>
    </div>`;
  }
  async function renderServices(container) {
    await loadProviders();
    const keys = container.dataset.services.split(/\s+/).filter(Boolean);
    container.innerHTML = keys.map(serviceCard).join("");
    container.querySelectorAll(".svc").forEach((card) => {
      const slotKey = card.dataset.slot;
      const [kind, name] = slotKey.split(".");
      const out = card.querySelector("[data-svc-result]");
      card.querySelector('[data-k="provider"]').addEventListener("change", (e) => { svcDraft[slotKey] = e.target.value; card.outerHTML = serviceCard(slotKey); renderServices(container); });
      card.querySelector("[data-svc-save]").addEventListener("click", async () => {
        const v = (k) => { const el = card.querySelector(`[data-k="${k}"]`); return el ? el.value : ""; };
        const provider = v("provider");
        out.textContent = "saving…";
        try {
          await post("/api/config/slot", { kind, name, provider, model: v("model") || null, voice: v("voice") || null, speed: v("speed") === "" ? null : Number(v("speed")) });
          const creds = {};
          card.querySelectorAll('[data-k^="cred:"]').forEach((el) => { if (el.value) creds[el.dataset.k.slice(5)] = el.value; });
          if (Object.keys(creds).length) await post("/api/config/credentials", { provider, values: creds });
          delete svcDraft[slotKey];
          await loadProviders(true); await loadConfig(true);
          await renderServices(container);
          const fresh = container.querySelector(`.svc[data-slot="${slotKey}"] [data-svc-result]`);
          if (fresh) fresh.textContent = "saved and applied";
        } catch (e) { out.textContent = e.message.slice(0, 200); }
      });
      card.querySelector("[data-svc-probe]").addEventListener("click", async () => {
        out.textContent = "probing…";
        try {
          const rows = await post(`/api/config/probe?slot=${encodeURIComponent(slotKey)}`, {});
          const r = rows.find((x) => x.slot === slotKey) || rows[0];
          out.innerHTML = r ? (r.ok ? `<span class="ok">ok</span> · ${esc(r.model || "")} ${r.region ? "· " + esc(r.region) : ""} · ${Math.round(r.latency_ms || 0)} ms` : `<span class="bad">${esc(r.kind)}</span> · ${esc(r.message)}`) : "no result";
        } catch (e) { out.textContent = e.message.slice(0, 200); }
      });
    });
  }

  // traces (LLM on Agent, ASR / TTS on Voice)
  async function loadTrace(tbody) {
    const service = tbody.dataset.trace;
    const clamp = "clamp" in tbody.dataset;
    const rows = await api(`/api/traces/${service}?limit=${tbody.dataset.limit || 20}`);
    // the LLM trace stores the whole message list as `query`; show the last user turn, not the prompt
    // a message with parts (a camera frame and its question) shows its text and [image]
    const said = (c) => Array.isArray(c) ? c.map((p) => (p && p.type === "text" ? p.text : "[image]")).join(" ") : String(c);
    const lastUser = (q) => { try { const msgs = JSON.parse(q); const u = [...msgs].reverse().find((m) => m.role === "user"); return u ? said(u.content) : q; } catch (e) { return q; } };
    const text = (r) => service === "llm" ? `${lastUser(r.query || "")}${r.answer ? " → " + r.answer : ""}` : r.text || "";
    tbody.innerHTML = rows.map((r) => {
      const ok = r.success ? "" : ` <span class="bad">${esc(r.error || "failed")}</span>`;
      const model = service === "tts" ? `${esc(r.model || "")}${r.voice ? " · " + esc(r.voice) : ""}` : esc(r.model || "");
      const extra = service === "llm" ? `<td>${r.total_tokens ?? "–"}</td>` : "";
      const body = `${esc(text(r)).slice(0, clamp ? 480 : 240)}${ok}`;
      return `<tr><td>${r.ts ? time(r.ts) : "–"}</td><td>${esc(r.slot || "")}<br><small>${esc(r.provider || "")}</small></td><td>${model}</td><td>${fmt(r.duration_ms)}</td>${extra}<td class="wrap">${clamp ? `<div class="clamp">${body}</div>` : body}</td></tr>`;
    }).join("") || `<tr><td colspan="6" class="dim">no ${esc(service)} calls yet</td></tr>`;
  }

  async function renderPage(tab) {
    const section = $(`tab-${tab}`);
    if (!section) return;
    await Promise.all([
      ...[...section.querySelectorAll("[data-params]")].map(renderParams),
      ...[...section.querySelectorAll("[data-services]")].map(renderServices),
      ...[...section.querySelectorAll("[data-trace]")].map((t) => loadTrace(t).catch((e) => { t.innerHTML = `<tr><td colspan="6" class="bad">${esc(e.message)}</td></tr>`; })),
    ]);
  }

  // ---------------------------------------------------------------- readiness (rail card, dots, Live empty state, System page)
  let readiness = null, readinessRunning = false;
  function renderReadiness(snap) {
    readiness = snap;
    const card = $("rail-system-card"), verdict = $("rail-verdict"), rows = $("rail-ready-rows");
    if (!snap) { verdict.textContent = "no readiness data"; verdict.className = "verdict"; rows.innerHTML = ""; return; }
    verdict.textContent = snap.summary;
    verdict.className = `verdict ${snap.running ? "" : snap.bad ? "bad" : snap.warn ? "warn" : "ok"}`;
    const failing = (snap.items || []).filter((it) => it.level !== "ok");
    rows.innerHTML = failing.slice(0, 8).map((it) => `<div class="r ${it.level}"><i></i><span>${esc(it.title)}<span class="d" title="${esc(it.detail)}">${esc(it.detail)}</span></span><a data-go="${esc(it.tab)}">${esc(it.tab)} →</a></div>`).join("") + (failing.length > 8 ? `<div class="r"><i style="background:transparent"></i><a data-go="system">${failing.length - 8} more on System →</a></div>` : "");
    card.classList.toggle("pinned", snap.bad > 0);
    $("rail-system-when").textContent = snap.ts ? `checked ${time(snap.ts)}` : "";
    $("rail-check").disabled = !!snap.running || readinessRunning;
    $("rail-check").textContent = snap.running || readinessRunning ? "checking…" : "Check";
  }
  function renderSystemItems(rep) {
    if (!rep) return;
    $("sys-verdict").textContent = rep.summary;
    $("sys-verdict").className = rep.bad ? "bad" : rep.warn ? "warn" : "ok";
    $("sys-ready-when").textContent = rep.ts ? `checked ${time(rep.ts)} · layers ${(rep.layers || []).join(", ")}` : "";
    $("sys-items").innerHTML = (rep.items || []).map((it) => `<tr><td class="dim">${esc(it.layer)}</td><td>${esc(it.title)}</td><td><span class="lvl ${it.level}">${esc(it.level)}</span></td><td class="wrap">${esc(it.detail)}</td><td>${it.latency_ms != null ? Math.round(it.latency_ms) : ""}</td><td>${it.level === "ok" ? "" : `<a data-go="${esc(it.tab)}" style="color:var(--acc);cursor:pointer">${esc(it.tab)} →</a>`}</td></tr>`).join("") || '<tr><td colspan="6" class="dim">not checked yet</td></tr>';
  }
  async function runReadiness(layers) {
    if (readinessRunning) return;
    readinessRunning = true;
    layers = layers || ["local", "probe", "loopback"];
    $("rail-verdict").textContent = "checking…";
    try {
      for (const layer of layers) {
        $("rail-verdict").textContent = `checking ${layer}…`;
        const rep = await post(`/api/doctor/run?layers=${layer}`, {});
        renderReadiness(rep);
        renderSystemItems(rep);
      }
    } catch (e) { $("rail-verdict").textContent = e.message.slice(0, 120); }
    readinessRunning = false;
    renderReadiness(readiness);
    if (window.SidekickLive && window.SidekickLive.refresh) window.SidekickLive.refresh();
  }
  $("rail-check").addEventListener("click", () => runReadiness());
  $("sys-check").addEventListener("click", () => runReadiness());
  $("sys-check-local").addEventListener("click", () => runReadiness(["local"]));
  $("sys-backup").addEventListener("click", async () => {
    $("sys-backup-result").textContent = "writing…";
    try { const r = await post("/api/system/backup", {}); $("sys-backup-result").textContent = `${r.path} · ${r.size_mb} MB`; } catch (e) { $("sys-backup-result").textContent = e.message; }
  });
  async function loadSystem() {
    const [rep, logs, config] = await Promise.all([api("/api/doctor"), api(`/api/logs?lines=200&source=${$("logs-source").value}`), loadConfig(true)]);
    renderSystemItems(rep);
    $("logs").textContent = logs.join("\n");
    $("config-json").textContent = JSON.stringify(config, null, 2);
  }
  const loadLogs = async () => {
    const source = $("logs-source").value;
    $("logs-what").textContent = `last 200 lines of .derived_data/logs/${source === "daemon" ? "reachy-daemon.log" : "sidekick.log"}`;
    const lines = await api(`/api/logs?lines=200&source=${source}`);
    $("logs").textContent = lines.join("\n");
  };
  $("logs-refresh").addEventListener("click", loadLogs);
  $("logs-source").addEventListener("change", loadLogs);

  // ---------------------------------------------------------------- health poll (1 Hz)
  const uptime = (s) => (s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min` : s >= 60 ? `${Math.floor(s / 60)} min` : `${fmt(s)} s`);
  const slotSummary = (slots) => { const by = {}; Object.entries(slots || {}).forEach(([k, v]) => { (by[v] = by[v] || []).push(k.replace(/\.primary$/, "")); }); return Object.entries(by).map(([p, ks]) => `${p}: ${ks.join(", ")}`).join(" · ") || "–"; };
  let lastSummary = null;
  async function poll() {
    try {
      const h = await api("/api/health");
      lastHealth = h;
      const inter = h.interaction || {};
      const state = inter.state || "off";
      const tabs = (h.doctor && h.doctor.tabs) || {};
      const r = h.recording;
      dot("dot-live", { idle: "acc", engaged: "ok", speaking: "warn" }[state] || "");
      dot("dot-agent", worst(tabs.agent, h.agent && h.agent.last_error ? "bad" : ""));
      dot("dot-automation", worst(tabs.automation, h.automation && !h.automation.enabled ? "warn" : ""));
      dot("dot-body", worst(tabs.body, inter.held ? "warn" : h.body && h.body.state !== "awake" ? "warn" : h.daemon && !h.daemon.running ? "bad" : ""));
      dot("dot-record", worst(tabs.record, r && (r.state === "paused" || r.errors) ? "warn" : ""));
      ["voice", "contact", "channel", "extension", "system"].forEach((t) => dot(`dot-${t}`, tabs[t] || ""));
      if (window.SidekickService) window.SidekickService.update(h.service);
      if (h.service && h.service.state !== "running") {  // Bobby is stopped: the runtime tabs are grey, a blocking prerequisite stays red
        ["live", "voice", "body", "agent", "automation", "channel", "record", "extension"].forEach((t) => dot(`dot-${t}`, tabs[t] === "bad" ? "bad" : "off"));
      }
      const recordingLine = !r ? ["recording", "off", "dim"] : r.state === "recording" ? ["recording", `${fmt(r.hours, 1)} h · ${fmt(r.size_gb, 2)} GB · ${fmt(r.free_gb, 0)} GB free`, "ok"] : ["recording", `${r.state}${r.errors ? " · " + r.errors : ""} · ${fmt(r.free_gb, 0)} GB free`, "warn"];
      kv($("rail-system"), [recordingLine, ["providers", slotSummary(h.slots)], ["agent", h.agent ? `${h.agent.turns} turn(s)${h.agent.last_error ? " · error" : ""}` : "–", h.agent && h.agent.last_error ? "bad" : ""], ["sidekick", `${h.version} · up ${uptime(h.uptime_s)}`]]);
      if (!readinessRunning) renderReadiness(h.doctor || null);
      const summary = h.doctor ? `${h.doctor.ready}|${h.doctor.summary}` : null;
      if (summary !== lastSummary) { lastSummary = summary; if (window.SidekickLive && window.SidekickLive.refresh) window.SidekickLive.refresh(); }
      const s = inter.session;
      strip($("listen-state"), [["state", state], ["reason", fmt(inter.reason)], ["addressee", s ? s.addressee : "–"], ["trigger", s ? s.trigger : "–"], ["turns", s ? s.turns : "–"], ["doa yaw", s && s.doa_yaw != null ? `${(s.doa_yaw * 180 / Math.PI).toFixed(0)}°` : "–"], ["segments", inter.frontend ? inter.frontend.segments : "–"], ["turn running", inter.turn_running ? "yes" : "no"], ["playback", inter.ducked ? "ducked" : "normal", inter.ducked ? "warn" : ""]]);
      if ($("tab-voice").classList.contains("active") && lastView.voice === "decisions") { loadDecisions(); if (!$("enroll-contact").options.length) loadContacts().catch(() => {}); }
    } catch (e) {
      dot("dot-live", "bad");
      kv($("rail-system"), [["sidekick", "offline", "bad"]]);
    }
  }

  let decisionsLimit = 25;  // "show more" → 120
  $("decisions-more").addEventListener("click", () => {
    decisionsLimit = decisionsLimit === 25 ? 120 : 25;
    $("decisions-more").textContent = decisionsLimit === 25 ? "show more" : "show fewer";
    loadDecisions().catch((e) => console.warn(e));
  });
  async function loadDecisions() {
    const rows = await api(`/api/interaction/decisions?limit=${decisionsLimit}`);
    $("decisions").innerHTML = rows.map((r) => {
      const timing = r.timing && typeof r.timing === "object" ? `${fmt(r.timing.first_audio_ms)} / ${fmt(r.timing.total_ms)} ms` : "";
      const clip = r.clip ? `<audio controls preload="none" src="/api/interaction/clip/${r.id}"></audio>` : "";
      const text = [r.text, r.reply].filter(Boolean).join(" → ");
      const pick = r.clip ? `<input type="checkbox" data-clip="${r.id}">` : "";
      return `<tr class="${r.decision}"><td>${pick}</td><td>${time(r.ts)}</td><td>${r.state}</td><td>${r.event}</td><td>${r.decision}</td><td>${r.reason}</td><td>${fmt(r.name_score, 2)}</td><td>${r.doa != null ? (r.doa * 180 / Math.PI).toFixed(0) + "°" : "–"}</td><td>${fmt(r.duration_s, 1)}</td><td class="wrap">${text}</td><td>${timing}</td><td>${clip}</td></tr>`;
    }).join("");
  }

  $("say-btn").addEventListener("click", async () => {
    $("say-result").textContent = "speaking…";
    try {
      const r = await post("/api/say", { text: $("say-text").value, expression: $("say-expr").value || null });
      $("say-result").textContent = r.ok ? `ok · first audio ${fmt(r.timing.first_audio_ms)} ms` : `failed: ${r.error}`;
    } catch (e) { $("say-result").textContent = e.message; }
  });

  // the Telemetry card (rail): one /api/live frame + the last health poll → rows
  const deg = (r) => (r === null || r === undefined ? "–" : `${(r * 180 / Math.PI).toFixed(1)}°`);
  const mm = (m) => (m === null || m === undefined ? "–" : `${(m * 1000).toFixed(1)} mm`);
  // the measured head pose arrives as a row-major 4×4 relative to the rest pose (Rz·Ry·Rx)
  const euler = (m) => (!m || m.length !== 16 ? null : { yaw: Math.atan2(m[4], m[0]), pitch: -Math.asin(Math.max(-1, Math.min(1, m[8]))), roll: Math.atan2(m[9], m[10]), z: m[11] });
  function telemetry(el, f) {
    const b = f.body, h = lastHealth || {};
    if (!b) { kv(el, [["body", "none", "warn"]]); return; }
    const me = euler(b.head_measured);
    const rows = [
      ["body", `${esc(b.state)}${b.manual ? ' · <span class="warn">manual</span>' : ""}${b.emotion ? " · " + esc(b.emotion) : b.gesture ? " · " + esc(b.gesture) : ""}${b.moving ? ' · <span class="dim">moving</span>' : ""}${b.swaying ? ' · <span class="dim">swaying</span>' : ""}`, b.state === "awake" ? "ok" : "warn"],
      ["daemon", h.daemon ? esc(h.daemon.line) : "–", h.daemon && h.daemon.running ? "ok" : "bad"],
      ["motors · firmware", h.body ? `${esc(fmt(h.body.motor_mode))} · ${esc(fmt(h.body.version))}` : "–"],
      ["head commanded", `yaw ${deg(b.head[0])} · pitch ${deg(b.head[1])} · roll ${deg(b.head[2])} · z ${mm(b.head[3])}`],
      ["head measured", me ? `yaw ${deg(me.yaw)} · pitch ${deg(me.pitch)} · roll ${deg(me.roll)} · z ${mm(me.z)}` : "–"],
      ["body yaw", `${deg(b.body_yaw)}${b.joints_measured ? ` · measured ${deg(b.joints_measured[0])}` : ""}`],
      ["stewart motors", b.joints_measured ? b.joints_measured.slice(1).map((j) => `${(j * 180 / Math.PI).toFixed(0)}°`).join(" ") : '<span class="dim">no joint stream</span>'],
      ["antennas", `cmd ${deg(b.antennas[0])} / ${deg(b.antennas[1])}${b.antennas_measured ? ` · measured ${deg(b.antennas_measured[0])} / ${deg(b.antennas_measured[1])}` : ""}`],
      ["mic", `${fmt(b.mic_dbfs, 1)} dBFS`],
      ["speaker", b.speaking ? `${fmt(b.speaker_dbfs, 1)} dBFS · gain ${fmt(b.gain_db, 1)} dB` : "quiet"],
      ["sound from", b.doa_yaw != null ? deg(b.doa_yaw) : "–"],
      ["face", f.faces && f.faces.length ? `ours · ${f.faces.length} face(s) · x ${fmt((f.faces[0].x + f.faces[0].w / 2) * 2 - 1, 2)}${f.faces[0].facing === true ? " · facing" : ""}${f.faces[0].name ? " · " + esc(f.faces[0].name) : ""}` : b.face ? `daemon x ${fmt(b.face.x, 2)} · y ${fmt(b.face.y, 2)}` : "none"],
    ];
    kv(el, rows);
  }

  async function loadTimeline() {
    const rows = await api("/api/agent/timeline?limit=80");
    $("timeline").innerHTML = rows.map((r) => `<tr class="${r.role === "user" ? "accept" : "reject"}"><td>${time(r.ts)}</td><td>${esc(r.channel)}</td><td>${esc(r.speaker)}</td><td>${esc(r.role)}</td><td>${esc(r.visibility)}</td><td class="wrap">${esc(r.content).slice(0, 400)}${r.meta && r.meta.tool ? ` <small>(${esc(r.meta.tool)})</small>` : ""}</td><td>${esc(r.delivered_to || "")}</td></tr>`).join("");
  }
  // the Agent page's test card: a turn typed as one of the household; the reply, NO_REPLY or the error, the tools the turn
  // called (a click shows arguments and result) and its timings. Turns are real: they reach the timeline, memory and tools.
  const testLog = [];
  let testSpeakers = [];
  const CUE = /\[\s*(express|style)\s*:\s*([^\]]*)\]\s*/gi;
  async function loadTestSpeakers() {
    const snap = await api("/api/contacts").catch(() => ({ contacts: [] }));
    const people = (snap.contacts || []).filter((c) => c.id !== "self");
    const owner = people.find((c) => c.is_owner);
    testSpeakers = [{ id: "owner", label: owner ? `${owner.name} (owner)` : "owner" }, ...people.filter((c) => !c.is_owner).map((c) => ({ id: c.id, label: c.name }))];
    const sel = $("test-speaker"), keep = sel.value;
    sel.innerHTML = testSpeakers.map((p) => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("");
    if (keep && testSpeakers.some((p) => p.id === keep)) sel.value = keep;
  }
  const secs = (ms) => (ms == null ? "" : ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);
  function testReply(t, i) {
    if (t.pending) return '<div class="msg bot live"><div class="avatar">B</div><div class="body"><div class="bubble pulse">thinking…</div></div></div>';
    const raw = t.reply || "";
    const cues = [...raw.matchAll(CUE)].map((m) => `${m[1]}: ${m[2].trim()}`);
    const text = t.error ? `error: ${t.error}` : t.no_reply ? "NO_REPLY — the agent chose not to answer" : raw.replace(CUE, "").trim() || raw;
    const meta = ["Bobby", t.ms != null ? `${secs(t.ms)}${t.first_ms != null ? ` · first words ${secs(t.first_ms)}` : ""}` : "", cues.join(", ")].filter(Boolean).map(esc).join(" · ");
    const tools = (t.tools || []).map((x, j) => `<button class="tag" data-test="${i}" data-call="${j}">${esc(x.agent !== "main" ? `${x.agent} · ${x.name}` : x.name)}</button>`).join("");
    return `<div class="msg bot"><div class="avatar">B</div><div class="body"><div class="bubble${t.error ? " bad" : t.no_reply ? " dim" : ""}">${esc(text)}</div><div class="meta">${meta}</div>${tools ? `<div class="tags">${tools}</div>` : ""}</div></div>`;
  }
  function renderTest() {
    $("test-log").innerHTML = testLog.map((t, i) => `<div class="msg user"><div class="avatar">${esc(String(t.who).slice(0, 1).toUpperCase())}</div><div class="body"><div class="bubble">${esc(t.text)}</div><div class="meta">${esc(t.who)} · ${esc(time(t.ts))}</div></div></div>${testReply(t, i)}`).join("")
      || '<div class="empty"><h1>Try the agent</h1><p>Type a turn for the main agent as one of the household. Every turn is real: it lands in the timeline (channel <code>dashboard</code>) and its tools run — remember, schedule and the rest.</p></div>';
    const sc = $("test-scroll");
    sc.scrollTop = sc.scrollHeight;
  }
  const growTest = () => { const t = $("test-text"); t.style.height = "auto"; t.style.height = `${Math.min(160, t.scrollHeight)}px`; };
  async function sendTest() {
    const text = $("test-text").value.trim();
    if (!text) return;
    const speaker = $("test-speaker").value || "owner";
    const entry = { who: (testSpeakers.find((p) => p.id === speaker) || { label: speaker }).label, text, ts: Date.now() / 1000, pending: true };
    testLog.push(entry);
    $("test-text").value = "";
    growTest();
    renderTest();
    try { Object.assign(entry, await post("/api/agent/chat", { text, speaker })); } catch (e) { entry.error = e.message; }
    entry.pending = false;
    renderTest();
    loadTimeline().catch(() => {});
  }
  $("test-send").addEventListener("click", sendTest);
  $("test-text").addEventListener("input", growTest);
  $("test-text").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendTest(); } });
  $("test-clear").addEventListener("click", () => { testLog.length = 0; renderTest(); });
  $("test-log").addEventListener("click", (e) => {
    const b = e.target.closest("[data-call]");
    if (!b) return;
    const call = testLog[+b.dataset.test].tools[+b.dataset.call];
    let args = call.arguments;
    try { args = JSON.stringify(typeof args === "string" ? JSON.parse(args) : args, null, 2); } catch (err) { args = String(args); }
    openSheet({ title: call.name, sub: `called by ${call.agent === "main" ? "the main agent" : call.agent}`, body: `<div><h4>Arguments</h4><pre>${esc(args)}</pre></div><div><h4>Result</h4><p>${esc(call.result)}</p></div>` });
  });
  renderTest();

  // memory (PLAN.md block #70): the pyramid — one card per profile (L2 facts by category, their provenance as tags,
  // superseded ones folded away), the writer and the episodes by day (L1); an episode opens its conversation (L0)
  const CATEGORIES = ["identity", "style", "preference", "routine", "date", "health", "money", "relationship", "other"];
  let memoryData = { facts: [], episodes: [], digests: {}, writer: null }, memoryNames = {};
  const who = (id) => memoryNames[id] || (window.SidekickLive ? window.SidekickLive.guestName(id) : id);
  const dayLabel = (ts) => { const d = new Date(ts * 1000); return `${d.getMonth() + 1}月${d.getDate()}日 星期${"日一二三四五六"[d.getDay()]}`; };
  const hm = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit" });
  const md = (ts) => { const d = new Date(ts * 1000); return `${d.getMonth() + 1}-${d.getDate()} ${hm(ts)}`; };
  function factRow(f, episodes) {
    const tags = [
      f.origin === "inferred" ? '<span class="tag">inferred</span>' : '<span class="tag acc">asked</span>',
      f.visibility === "private" ? '<span class="tag warn">private</span>' : "",
      f.valid_until ? `<span class="tag">until ${esc(f.valid_until)}</span>` : "",
    ].join("");
    const ep = f.episode ? episodes[f.episode] : null;
    const meta = [
      f.teller && f.teller !== f.scope ? `told by ${esc(who(f.teller))}` : f.teller ? "" : "",
      f.subject && f.subject !== f.scope && f.subject !== "household" ? `about ${esc(who(f.subject))}` : "",
      f.channel ? esc(f.channel) : "",
      md(f.ts),
      ep ? `<a data-episode="${esc(ep.id)}">from “${esc(ep.title)}”</a>` : "",
      f.retired_ts ? `retired ${md(f.retired_ts)}` : "",
    ].filter(Boolean).join(" · ");
    return `<div class="fact${f.retired_ts ? " retired" : ""}"><span class="cat">${esc(f.category)}</span><span class="t">${esc(f.text)}</span>${f.retired_ts ? "<span></span>" : `<button data-forget="${esc(f.id)}" title="forget this fact">forget</button>`}<span class="meta">${tags}${meta ? `<span>${meta}</span>` : ""}</span></div>`;
  }
  function renderMemory() {
    const q = $("mem-search").value.trim().toLowerCase();
    const hit = (text) => !q || String(text || "").toLowerCase().includes(q);
    const episodes = Object.fromEntries(memoryData.episodes.map((e) => [e.id, e]));
    const facts = memoryData.facts.filter((f) => hit(f.text) || hit(who(f.scope)));
    const active = memoryData.facts.filter((f) => !f.retired_ts);
    count("memory", active.length);
    // profiles: household first, then people by name
    const scopes = [...new Set(facts.map((f) => f.scope))].sort((a, b) => (a === "household" ? -1 : b === "household" ? 1 : who(a).localeCompare(who(b))));
    $("mem-profiles").innerHTML = scopes.map((scope) => {
      const mine = facts.filter((f) => f.scope === scope);
      const live = mine.filter((f) => !f.retired_ts).sort((a, b) => CATEGORIES.indexOf(a.category) - CATEGORIES.indexOf(b.category) || b.ts - a.ts);
      const gone = mine.filter((f) => f.retired_ts);
      const priv = live.filter((f) => f.visibility === "private").length;
      const digest = memoryData.digests[scope];
      return `<div class="card"><h3>${esc(scope === "household" ? "Household" : who(scope))} <small>${live.length} fact(s)${priv ? ` · ${priv} private` : ""}${digest ? " · digest" : ""}</small></h3>`
        + (digest ? `<p class="digest">${esc(digest)}</p>` : "")
        + `<div class="facts">${live.map((f) => factRow(f, episodes)).join("") || '<div class="dim" style="font-size:13px">no current fact</div>'}</div>`
        + (gone.length ? `<details class="retired-list"><summary>superseded or expired (${gone.length})</summary><div class="facts">${gone.map((f) => factRow(f, episodes)).join("")}</div></details>` : "")
        + "</div>";
    }).join("") || `<div class="card"><div class="blank"><b>Nothing remembered yet.</b><p>Bobby writes each conversation into memory a few minutes after it ends (the room after ${memoryGap.voice} min of quiet, a chat after ${memoryGap.text} min): who said what about themselves and the household. Facts come only from named people — enroll the family on Contact.</p></div></div>`;
    // episodes by day
    const eps = memoryData.episodes.filter((e) => hit(e.title) || hit(e.summary) || e.participants.some((p) => hit(who(p))));
    let day = "";
    $("mem-episodes").innerHTML = eps.map((e) => {
      const d = dayLabel(e.ts_start);
      const sep = d !== day ? `<span class="day">${esc(d)}</span>` : "";
      day = d;
      const people = e.participants.map(who).join("、");
      const tags = [
        e.status === "failed" ? `<span class="tag bad">failed ×${e.attempts}</span>` : "",
        e.visibility === "private" ? `<span class="tag warn">private · ${esc(who(e.private_to))}</span>` : "",
        ...e.followups.map((f) => `<span class="tag acc">${esc(f.due)} ${esc(f.text)}</span>`),
      ].join("");
      return `${sep}<button class="ep" data-episode="${esc(e.id)}"><div class="top"><b>${esc(e.title || "(not written)")}</b><span>${hm(e.ts_start)}–${hm(e.ts_end)} · ${esc(CHANNEL_NAMES[e.channel] || e.channel)} · ${esc(people)} · ${e.user_turns} turn(s)</span></div>${e.summary ? `<div class="sum">${esc(e.summary)}</div>` : e.error ? `<div class="sum bad">${esc(e.error)}</div>` : ""}${tags ? `<div class="tags">${tags}</div>` : ""}</button>`;
    }).join("") || '<div class="blank"><b>No episode yet.</b><p>One appears for each conversation a few minutes after it ends; “write now” writes them at once, the open ones too.</p></div>';
    $("mem-episodes-count").textContent = `${memoryData.episodes.length} in the last two weeks · click for the conversation`;
    $("mem-count").textContent = q ? `${facts.length} fact(s), ${eps.length} episode(s) match` : `${active.length} current fact(s)`;
    const w = memoryData.writer;
    $("mem-writer-sub").textContent = w ? (w.state === "off" ? "switched off (Settings)" : "writes each conversation after it ends") : "";
    kv($("mem-writer"), w ? [
      ["state", w.state === "writing" ? '<span class="ok">writing</span>' : esc(w.state)],
      ["waiting", `${w.waiting} conversation(s)`],
      ["written", `${w.written} since start${w.last_s != null ? ` · last ${w.last_s < 60 ? w.last_s + " s" : Math.round(w.last_s / 60) + " min"} ago` : ""}`],
      w.error ? ["last error", esc(w.error), "bad"] : null,
    ].filter(Boolean) : [["writer", "–"]]);
  }
  const CHANNEL_NAMES = { voice: "voice", telegram: "Telegram", wechat: "WeChat", dashboard: "test card" };
  let memoryGap = { voice: 5, text: 15 };
  async function loadMemory() {
    const [memory, contacts, cfg] = await Promise.all([api("/api/agent/memory?limit=1000"), api("/api/contacts").catch(() => ({ contacts: [] })), api("/api/config").catch(() => null)]);
    memoryData = memory;
    if (cfg && cfg.agents) memoryGap = { voice: cfg.agents.memory_voice_gap_min, text: cfg.agents.memory_text_gap_min };
    memoryNames = { household: "household" };
    (contacts.contacts || []).forEach((c) => { memoryNames[c.id] = c.name; if (c.is_owner) memoryNames.owner = memoryNames.owner || `${c.name} (owner)`; });
    memoryNames.owner = memoryNames.owner || "owner";
    const people = (contacts.contacts || []).filter((c) => c.id !== "self").map((c) => c.id);
    const scopes = ["household", ...new Set([...people, ...memory.facts.map((f) => f.scope).filter((s) => s !== "household")])];
    const pick = $("mem-scope").value;
    $("mem-scope").innerHTML = scopes.map((x) => `<option value="${esc(x)}">${esc(who(x))}</option>`).join("");
    if (scopes.includes(pick)) $("mem-scope").value = pick;
    if (!$("mem-category").options.length) $("mem-category").innerHTML = CATEGORIES.map((c) => `<option value="${c}"${c === "other" ? " selected" : ""}>${c}</option>`).join("");
    renderMemory();
  }
  async function openEpisode(id) {
    const e = await api(`/api/agent/episodes/${encodeURIComponent(id)}`);
    const rows = (e.rows || []).map((r) => r.role === "tool"
      ? `<div><time>${hm(r.ts)}</time><span class="who">tool</span><span class="tool">${esc(r.tool || "")} ${r.ok ? "ok" : "failed"} · ${esc(String(r.content || "").slice(0, 120))}</span></div>`
      : `<div><time>${hm(r.ts)}</time><span class="who">${esc(r.role === "user" ? who(r.speaker) : "Bobby")}</span><span>${esc(r.role === "user" ? r.content : r.content.replace(/\[\s*(express|style)\s*:[^\]]*\]\s*/gi, ""))}</span></div>`).join("");
    const facts = (e.facts || []).map((f) => `<div>· ${esc(f.text)} <span class="dim">(${esc(who(f.scope))}, ${esc(f.category)}${f.visibility === "private" ? ", private" : ""}${f.retired_ts ? ", superseded" : ""})</span></div>`).join("");
    openSheet({
      title: e.title || "(not written)",
      sub: `${dayLabel(e.ts_start)} ${hm(e.ts_start)}–${hm(e.ts_end)} · ${CHANNEL_NAMES[e.channel] || e.channel} · ${e.participants.map(who).join("、")}`,
      tags: [e.visibility === "private" ? `<span class="tag warn">private · ${esc(who(e.private_to))}</span>` : "", e.status === "failed" ? `<span class="tag bad">failed</span>` : ""].join(""),
      body: `<div><h4>Summary</h4><p>${esc(e.summary || e.error || "–")}</p></div>`
        + (e.followups.length ? `<div><h4>Follow-ups</h4><p>${e.followups.map((f) => `${esc(f.due)} · ${esc(f.text)} (${esc(who(f.who))})`).join("<br>")}</p></div>` : "")
        + `<div><h4>Facts from this conversation</h4>${facts || '<p class="dim">none</p>'}</div>`
        + `<div><h4>Conversation <small>(L0, the timeline)</small></h4><div class="transcript">${rows || '<span class="dim">no rows</span>'}</div></div>`,
      actions: [{ label: "Delete episode", danger: true, left: true, onClick: async () => { await del(`/api/agent/episodes/${encodeURIComponent(id)}`); sheet.close(); loadMemory(); } }],
    });
  }
  $("mem-search").addEventListener("input", renderMemory);
  $("tab-agent").addEventListener("click", async (e) => {
    const f = e.target.closest("[data-forget]");
    if (f) { await del(`/api/agent/memory/${f.dataset.forget}`); loadMemory(); return; }
    const ep = e.target.closest("[data-episode]");
    if (ep && ep.closest('[data-view="memory"]')) { e.preventDefault(); openEpisode(ep.dataset.episode).catch((err) => console.warn(err)); }
  });
  $("mem-add").addEventListener("click", async () => {
    const text = $("mem-text").value.trim();
    if (!text) return;
    try { await post("/api/agent/memory", { scope: $("mem-scope").value, text, category: $("mem-category").value, private: $("mem-private").checked }); $("mem-text").value = ""; $("mem-result").textContent = "remembered"; loadMemory(); } catch (e) { $("mem-result").textContent = e.message; }
  });
  $("mem-text").addEventListener("keydown", (e) => { if (e.key === "Enter") $("mem-add").click(); });
  $("mem-write").addEventListener("click", async () => {
    $("mem-write").disabled = true;
    $("mem-writer-sub").textContent = "writing every conversation now…";
    try { const r = await post("/api/agent/memory/write", {}); $("mem-writer-sub").textContent = `${r.written} conversation(s) written`; } catch (e) { $("mem-writer-sub").textContent = e.message; }
    $("mem-write").disabled = false;
    loadMemory();
  });

  // ---------------------------------------------------------------- details window: one per card on the item boards
  const sheet = $("sheet");
  sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.close(); });  // a click on the backdrop
  $("sheet-close").addEventListener("click", () => sheet.close());
  function openSheet({ title, sub, tags, body, actions }) {
    $("sheet-title").textContent = title;
    $("sheet-sub").textContent = sub || "";
    $("sheet-tags").innerHTML = tags || "";
    $("sheet-body").innerHTML = body;
    const foot = $("sheet-foot");
    foot.innerHTML = "";
    (actions || []).forEach((a) => {
      const b = document.createElement("button");
      b.textContent = a.label;
      if (a.primary) b.className = "primary";
      if (a.danger) b.className = "danger";
      if (a.left) b.style.marginRight = "auto";
      b.addEventListener("click", a.onClick);
      foot.appendChild(b);
    });
    foot.style.display = actions && actions.length ? "" : "none";
    if (!sheet.open) sheet.showModal();
  }
  const tag = (text, cls) => `<span class="tag${cls ? " " + cls : ""}">${esc(text)}</span>`;
  const count = (key, n) => document.querySelectorAll(`.viewbar [data-count="${key}"]`).forEach((el) => (el.textContent = n == null ? "" : String(n)));
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const ORIGIN_RANK = (o) => (o === "core" ? 0 : o === "automation" ? 1 : o.startsWith("extension:") ? 2 : o.startsWith("mcp:") ? 3 : 4);
  const originLabel = (o) => (o === "core" ? "Agent core" : o === "automation" ? "Automation" : o === "user" ? "Yours" : o.startsWith("extension:") ? `Extension · ${o.slice(10)}` : o.startsWith("mcp:") ? `MCP · ${o.slice(4)}` : o);
  const originShort = (o) => (o === "core" ? "core" : o.startsWith("extension:") ? o.slice(10) : o.startsWith("mcp:") ? `mcp · ${o.slice(4)}` : o);
  const byOrigin = (a, b) => ORIGIN_RANK(a) - ORIGIN_RANK(b) || a.localeCompare(b);

  // tools: every registered tool in one grid, sorted by where it comes from; the origin chips filter it
  let toolsData = [], mcpData = [], skillsData = [], agentsData = [], llmSlots = ["fast", "smart"], toolsOrigin = "";
  const toolFlags = (t) => (t.confirm ? tag("asks first", "warn") : "") + (t.main_only ? tag("main agent only", "acc") : "");
  const paramsOf = (t) => Object.entries((t.parameters && t.parameters.properties) || {});
  function renderTools() {
    const q = $("tools-filter").value.trim().toLowerCase();
    const matches = toolsData.filter((t) => !q || `${t.name} ${t.description} ${t.origin}`.toLowerCase().includes(q));
    const origins = [...new Set(toolsData.map((t) => t.origin))].sort(byOrigin);
    if (toolsOrigin && !origins.includes(toolsOrigin)) toolsOrigin = "";
    const shown = matches.filter((t) => !toolsOrigin || t.origin === toolsOrigin).sort((a, b) => byOrigin(a.origin, b.origin) || a.name.localeCompare(b.name));
    $("tools-count").textContent = shown.length === toolsData.length ? `${toolsData.length}` : `${shown.length} of ${toolsData.length}`;
    count("tools", toolsData.length);
    const chip = (o, label, n) => `<button data-origin="${esc(o)}" class="${o === toolsOrigin ? "active" : ""}">${esc(label)}<small>${n}</small></button>`;
    $("tools-origins").innerHTML = chip("", "All", matches.length) + origins.map((o) => chip(o, originLabel(o), matches.filter((t) => t.origin === o).length)).join("");
    $("tools-origins").querySelectorAll("[data-origin]").forEach((el) => el.addEventListener("click", () => { toolsOrigin = el.dataset.origin; renderTools(); }));
    $("tools-board").innerHTML = shown.map((t) => `<button class="item" data-tool="${esc(t.name)}"><span class="top"><span class="name">${esc(t.name)}</span>${toolsOrigin ? "" : `<span class="origin">${esc(originShort(t.origin))}</span>`}</span><span class="desc">${esc(t.description)}</span><span class="tags">${toolFlags(t)}${tag(plural(paramsOf(t).length, "param"))}</span></button>`).join("") || '<p class="dim">no tool matches</p>';
    $("tools-board").querySelectorAll("[data-tool]").forEach((el) => el.addEventListener("click", () => openTool(el.dataset.tool)));
  }
  function openTool(name) {
    const t = toolsData.find((x) => x.name === name);
    if (!t) return;
    const required = new Set((t.parameters && t.parameters.required) || []);
    const rows = paramsOf(t).map(([k, v]) => `<tr><td><code>${esc(k)}</code>${required.has(k) ? " " + tag("required") : ""}</td><td>${esc(v.type || "")}</td><td class="wrap">${v.description ? esc(v.description) : v.enum ? "" : '<span class="dim">–</span>'}${v.enum ? `<div class="dim">${v.enum.map(esc).join(" · ")}</div>` : ""}</td></tr>`).join("");
    openSheet({
      title: t.name,
      sub: originLabel(t.origin),
      tags: toolFlags(t),
      body: `<div><h4>What it does</h4><p>${esc(t.description)}</p></div>
        <div><h4>Parameters</h4>${rows ? `<table><thead><tr><th>name</th><th>type</th><th>meaning</th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="dim">none</p>'}</div>
        <div><h4>Who may call it</h4><div class="tags">${t.agents.length ? t.agents.map((a) => tag(a === "main" ? "main agent" : a)).join("") : '<span class="dim">no agent: it is in no allowlist</span>'}</div></div>`,
    });
  }
  $("tools-filter").addEventListener("input", renderTools);
  $("mcp-new").addEventListener("click", newMcp);
  $("skill-new").addEventListener("click", () => openSkill(null));
  $("subagent-new").addEventListener("click", () => openAgent(null));
  // "show more" on a capped trace: the table in the same card grows to 40 rows, and back
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-more]");
    if (!b) return;
    const tbody = b.closest(".card").querySelector("[data-trace]");
    const base = b.dataset.base || (b.dataset.base = tbody.dataset.limit);
    const more = tbody.dataset.limit === base;
    tbody.dataset.limit = more ? "40" : base;
    b.textContent = more ? "show fewer" : "show more";
    loadTrace(tbody).catch((err) => console.warn(err));
  });

  // MCP servers: one card each plus the add card
  function renderMcp() {
    $("mcp-count").textContent = `${mcpData.length}`;
    count("mcp", mcpData.length);
    const cards = mcpData.map((m) => {
      const state = m.error ? "bad" : !m.enabled ? "" : m.tools.length ? "ok" : "warn";
      const target = m.command ? [m.command, ...m.args].join(" ") : m.url;
      return `<button class="item" data-mcp="${esc(m.name)}"><span class="top"><i class="st ${state}"></i><span class="name">${esc(m.name)}</span></span><span class="desc">${esc(m.error || target)}</span><span class="tags">${tag(m.transport)}${tag(plural(m.tools.length, "tool"))}${m.origin !== "user" ? tag(originLabel(m.origin)) : ""}${m.enabled ? "" : tag("off")}</span></button>`;
    });
    $("mcp-board").innerHTML = cards.join("") || `<div class="blank"><b>No MCP server yet</b><p>An MCP server is another program whose tools Bobby can call — started here as a stdio command (<code>npx …</code>, <code>uvx …</code>) or reached at an HTTP URL. Bobby can also add one when asked (<code>mcp_add</code>, which asks first).</p><button class="primary" data-new-mcp>Add an MCP server</button></div>`;
    $("mcp-board").querySelectorAll("[data-mcp]").forEach((el) => el.addEventListener("click", () => openMcp(el.dataset.mcp)));
    $("mcp-board").querySelectorAll("[data-new-mcp]").forEach((el) => el.addEventListener("click", newMcp));
    $("mcp-new").hidden = !mcpData.length;  // the empty board carries its own button
  }
  function openMcp(name) {
    const m = mcpData.find((x) => x.name === name);
    if (!m) return;
    const tools = m.tools.map((n) => toolsData.find((t) => t.name === n) || { name: n, description: "" });
    const keys = [...m.env_keys.map((k) => `env ${k}`), ...m.header_keys.map((k) => `header ${k}`)];
    openSheet({
      title: m.name,
      sub: `${m.transport} · ${originLabel(m.origin)}`,
      tags: (m.error ? tag("error", "bad") : m.enabled ? tag(m.tools.length ? "connected" : "no tools", m.tools.length ? "" : "warn") : tag("off")),
      body: `${m.error ? `<div><h4>Last error</h4><p class="bad">${esc(m.error)}</p></div>` : ""}
        <div><h4>${m.command ? "Command" : "URL"}</h4><p><code>${esc(m.command ? [m.command, ...m.args].join(" ") : m.url)}</code></p></div>
        ${keys.length ? `<div><h4>Secrets it gets</h4><div class="tags">${keys.map((k) => tag(k)).join("")}</div><small>names only; the values never leave the config file</small></div>` : ""}
        <div><h4>${plural(tools.length, "tool")}</h4>${tools.length ? `<table><tbody>${tools.map((t) => `<tr><td><code>${esc(t.name)}</code></td><td class="wrap">${esc(t.description)}</td></tr>`).join("")}</tbody></table>` : '<p class="dim">none yet</p>'}</div>
        ${m.origin !== "user" ? `<small>Provided by ${esc(originLabel(m.origin))}: disable that extension to remove it.</small>` : ""}`,
      actions: m.origin === "user" ? [{ label: "Remove", danger: true, left: true, onClick: async () => { await del(`/api/agent/mcp/${encodeURIComponent(m.name)}`); sheet.close(); loadAgent(); } }] : [],
    });
  }
  function newMcp() {
    openSheet({
      title: "New MCP server",
      sub: "a stdio command, or an http URL",
      body: `<div class="fields"><label class="f">name<input id="mcp-name" placeholder="e.g. files"></label><label class="f">http URL<input id="mcp-url" placeholder="or leave empty for stdio"></label></div>
        <div class="fields"><label class="f">stdio command<input id="mcp-command" placeholder="e.g. npx"></label><label class="f">arguments (space separated)<input id="mcp-args"></label></div>
        <div class="p-status" id="mcp-status"></div>`,
      actions: [{ label: "Add", primary: true, onClick: async () => {
        try {
          const r = await post("/api/agent/mcp", { name: $("mcp-name").value, command: $("mcp-command").value, args: $("mcp-args").value.split(/\s+/).filter(Boolean), url: $("mcp-url").value });
          if (r.error) { $("mcp-status").textContent = r.error; $("mcp-status").className = "p-status bad"; }
          else sheet.close();
          loadAgent();
        } catch (e) { $("mcp-status").textContent = e.message; $("mcp-status").className = "p-status bad"; }
      } }],
    });
  }

  // the swarm: the main agent's card first, then each subagent — yours are edited in the window, an
  // extension's are shown with their origin (blocks #76 / #78)
  function renderAgents() {
    const subs = agentsData.filter((a) => !a.main);
    $("agents-count").textContent = `${agentsData.length}`;
    count("agents", agentsData.length);
    const card = (a) => a.main
      ? `<button class="item" data-agent="${esc(a.name)}"><span class="top"><span class="name">${esc(a.name)}</span><span class="origin">core</span></span><span class="desc">answers every turn — ${esc(a.description)}; hands longer work to a subagent</span><span class="tags">${tag("main agent", "acc")}${tag(`${a.llm_slot} slot`)}${tag(plural(a.resolved_tools.length, "tool"))}${tag(plural(a.turns, "turn"))}${a.hedge_after_s > 0 ? tag(`asks again after ${a.hedge_after_s} s`) : ""}</span></button>`
      : `<button class="item" data-agent="${esc(a.name)}"><span class="top"><span class="name">${esc(a.name)}</span><span class="origin">${esc(a.origin === "user" ? "yours" : originShort(a.origin))}</span></span><span class="desc">${esc(a.description || a.role)}</span><span class="tags">${tag(`${a.llm_slot} slot`)}${tag(plural(a.resolved_tools.length, "tool"))}${a.skills.includes("*") ? "" : tag(plural(a.skills.length, "skill"))}${tag(plural(a.turns, "task"))}</span></button>`;
    const add = subs.length ? "" : `<button class="item add" data-new-subagent><span class="name">+ New subagent</span><span class="desc">an expert the main agent hands a task to with <code>delegate</code> — its own role, LLM slot, tools and skills; extensions bring theirs</span></button>`;
    $("agents-board").innerHTML = agentsData.map(card).join("") + add;
    $("agents-board").querySelectorAll("[data-agent]").forEach((el) => el.addEventListener("click", () => openAgent(el.dataset.agent)));
    $("agents-board").querySelectorAll("[data-new-subagent]").forEach((el) => el.addEventListener("click", () => openAgent(null)));
    $("subagent-new").hidden = !subs.length;  // the add card carries it while there is none
  }
  function openAgent(name) {
    const a = name ? agentsData.find((x) => x.name === name) : null;
    if (name && !a) return;
    const words = (v) => (v || []).join(" ");
    const mainOnly = new Set(toolsData.filter((t) => t.main_only).map((t) => t.name));
    const gets = a ? `<div><h4>Tools it gets now · ${a.resolved_tools.length}</h4><div class="tags">${a.resolved_tools.map((t) => tag(t, mainOnly.has(t) ? "acc" : "")).join("") || '<span class="dim">none</span>'}</div><small>${a.main ? "highlighted: the main agent's alone (delegation and scheduling)" : "never <code>delegate</code> or the scheduling tools: those are the main agent's alone"}</small></div>` : "";
    if (a && a.main) {
      openSheet({
        title: a.name,
        sub: `Agent core · answers every turn · ${plural(a.turns, "turn")} since start`,
        tags: tag("main agent", "acc") + tag(`${a.llm_slot} slot`) + (a.hedge_after_s > 0 ? tag(`asks again after ${a.hedge_after_s} s`) : tag("no second request")),
        body: `<div><h4>What it does</h4><p>Every message from the room and the chats comes to it: it answers in a sentence or two, uses its tools, and hands longer or specialised work to a subagent with <code>delegate</code>. Only it schedules reminders and runs jobs.</p></div>
          <div><h4>Its rules</h4><p class="prompt">${esc(a.role)}</p><small>written in the code; each turn adds the skills, the subagents and what Bobby remembers about the speaker</small></div>
          ${gets}
          <div><h4>Settings · applied at once</h4><div data-params="agent.main"></div></div>`,
      });
      renderParams($("sheet-body").querySelector("[data-params]")).then(() => {
        // a change applies at once; the card and the tags follow
        $("sheet-body").querySelectorAll("[data-p]").forEach((el) => el.addEventListener("change", () => setTimeout(loadAgent, 400)));
      });
      return;
    }
    if (a && a.origin !== "user") {
      openSheet({
        title: a.name,
        sub: `${originLabel(a.origin)} · ${a.llm_slot} slot`,
        tags: tag(plural(a.turns, "task")) + tag(`up to ${a.max_steps} steps`) + tag(`${a.timeout_s} s timeout`),
        body: `<div><h4>What it does</h4><p>${esc(a.description) || '<span class="dim">–</span>'}</p></div>
          <div><h4>Role</h4><p>${esc(a.role)}</p></div>${gets}
          <div><h4>Skills · MCP servers</h4><div class="tags">${[...a.skills.map((s) => tag(s === "*" ? "all skills" : s)), ...a.mcp_servers.map((m) => tag(m === "*" ? "all MCP servers" : `mcp · ${m}`))].join("")}</div></div>
          <small>Provided by ${esc(originLabel(a.origin))}: disable that extension on the Extension page to remove it.</small>`,
      });
      return;
    }
    const picks = (id, names) => (names.length ? `<div class="picks" data-for="${id}">${names.map((n) => `<button type="button" data-name="${esc(n)}">${esc(n)}</button>`).join("")}</div>` : "");
    const slots = llmSlots.includes(a ? a.llm_slot : "smart") ? llmSlots : [...llmSlots, a ? a.llm_slot : "smart"];
    const save = async () => {
      const nm = a ? a.name : $("sub-name").value.trim();
      const list = (id) => $(id).value.split(/\s+/).filter(Boolean);
      try {
        await put(`/api/agent/subagents/${encodeURIComponent(nm)}`, { description: $("sub-desc").value.trim(), role: $("sub-role").value.trim(), llm_slot: $("sub-slot").value, tools: list("sub-tools"), skills: list("sub-skills"), mcp_servers: list("sub-mcp"), max_steps: parseInt($("sub-steps").value, 10), timeout_s: Number($("sub-timeout").value) });
        sheet.close(); loadAgent();
      } catch (e) { $("sub-status").textContent = e.message.slice(0, 300); $("sub-status").className = "p-status bad"; }
    };
    const actions = [{ label: "Save", primary: true, onClick: save }];
    if (a) actions.unshift({ label: "Delete", danger: true, left: true, onClick: async () => { await del(`/api/agent/subagents/${encodeURIComponent(a.name)}`); sheet.close(); loadAgent(); } });
    openSheet({
      title: a ? a.name : "New subagent",
      sub: a ? `yours · ${plural(a.turns, "task")} since start` : "saved in config.json (agents.subagents), live at once",
      tags: "",
      body: `<div class="fields"><label class="f"><span>name <small>· what delegate(agent=…) takes</small></span><input id="sub-name" value="${esc(a ? a.name : "")}" ${a ? "disabled" : ""} placeholder="e.g. weather" autocomplete="off"></label><label class="f">LLM slot<select id="sub-slot">${slots.map((s) => `<option ${s === (a ? a.llm_slot : "smart") ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label></div>
        <label class="f"><span>what it does <small>· the main agent reads this to choose it</small></span><input id="sub-desc" value="${esc(a ? a.description : "")}" placeholder="e.g. weather forecasts for Hong Kong"></label>
        <label class="f"><span>role <small>· its instructions</small></span><textarea id="sub-role" class="role" spellcheck="false" placeholder="You look up the weather for the household and answer in one or two sentences.">${esc(a ? a.role : "")}</textarea></label>
        <label class="f"><span>tools <small>· space separated · * = every tool a subagent may have</small></span><input id="sub-tools" value="${esc(words(a ? a.tools : ["*"]))}" autocomplete="off"></label>${picks("sub-tools", toolsData.filter((t) => !t.main_only).map((t) => t.name))}
        <label class="f"><span>skills <small>· * = all</small></span><input id="sub-skills" value="${esc(words(a ? a.skills : ["*"]))}" autocomplete="off"></label>${picks("sub-skills", skillsData.map((s) => s.name))}
        <label class="f"><span>MCP servers <small>· * = all</small></span><input id="sub-mcp" value="${esc(words(a ? a.mcp_servers : ["*"]))}" autocomplete="off"></label>${picks("sub-mcp", mcpData.map((m) => m.name))}
        <div class="fields"><label class="f">max steps<input id="sub-steps" type="number" min="1" max="30" value="${a ? a.max_steps : 8}"></label><label class="f">timeout (s)<input id="sub-timeout" type="number" min="5" max="900" value="${a ? a.timeout_s : 120}"></label></div>
        ${gets}<div class="p-status" id="sub-status"></div>`,
      actions,
    });
    // a name under a list toggles it in the field above (choosing one replaces *)
    $("sheet-body").querySelectorAll(".picks").forEach((box) => {
      const input = $(box.dataset.for);
      const sync = () => { const have = input.value.split(/\s+/); box.querySelectorAll("button").forEach((b) => b.classList.toggle("on", have.includes(b.dataset.name))); };
      box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
        const parts = input.value.split(/\s+/).filter((p) => p && p !== "*");
        input.value = (parts.includes(b.dataset.name) ? parts.filter((p) => p !== b.dataset.name) : [...parts, b.dataset.name]).join(" ");
        sync();
      }));
      input.addEventListener("input", sync);
      sync();
    });
  }

  // skills: one card each plus the new card; the window edits the Markdown
  const SKILL_TEMPLATE = "---\nname: example\ndescription: When to use this skill\n---\nInstructions for the agent.";
  function renderSkills() {
    $("skills-count").textContent = `${skillsData.length}`;
    count("skills", skillsData.length);
    const cards = skillsData.map((s) => `<button class="item" data-skill="${esc(s.name)}"><span class="top"><span class="name">${esc(s.name)}</span></span><span class="desc">${esc(s.description)}</span><span class="tags">${tag(originLabel(s.origin))}${s.enabled ? "" : tag("off")}${tag(`${s.body.length} chars`)}</span></button>`);
    $("skills-board").innerHTML = cards.join("") || `<div class="blank"><b>No skill yet</b><p>A skill is a Markdown note that tells Bobby how to do one thing: its description goes into the prompt, and Bobby reads the rest with <code>skill_read</code> when it needs it.</p><button class="primary" data-new-skill>New skill</button></div>`;
    $("skills-board").querySelectorAll("[data-skill]").forEach((el) => el.addEventListener("click", () => openSkill(el.dataset.skill)));
    $("skills-board").querySelectorAll("[data-new-skill]").forEach((el) => el.addEventListener("click", () => openSkill(null)));
    $("skill-new").hidden = !skillsData.length;
  }
  function openSkill(name) {
    const s = name ? skillsData.find((x) => x.name === name) : null;
    if (name && !s) return;
    const markdown = s ? `---\nname: ${s.name}\ndescription: ${s.description}\n---\n${s.body}` : SKILL_TEMPLATE;
    const save = async () => {
      try { const r = await put("/api/agent/skills", { markdown: $("skill-md").value }); $("skill-status").textContent = `saved ${r.name}`; $("skill-status").className = "p-status"; loadAgent(); }
      catch (e) { $("skill-status").textContent = e.message; $("skill-status").className = "p-status bad"; }
    };
    const actions = [{ label: "Save", primary: true, onClick: save }];
    if (s) actions.unshift({ label: "Delete", danger: true, left: true, onClick: async () => { await del(`/api/agent/skills/${encodeURIComponent(s.name)}`); sheet.close(); loadAgent(); } });
    openSheet({
      title: s ? s.name : "New skill",
      sub: s ? `${originLabel(s.origin)} · updated ${new Date(s.updated_ts * 1000).toLocaleString()}` : "Markdown with a name / description header",
      tags: s && !s.enabled ? tag("off") : "",
      body: `${s && s.origin.startsWith("extension:") ? `<small>Provided by ${esc(originLabel(s.origin))}: an edit is kept as your own copy until that extension is enabled again.</small>` : ""}
        <textarea id="skill-md" spellcheck="false">${esc(markdown)}</textarea><div class="p-status" id="skill-status"></div>`,
      actions,
    });
  }

  async function loadAgent() {
    const [state, tools, skills, mcp, agents] = await Promise.all([api("/api/agent"), api("/api/agent/tools"), api("/api/agent/skills"), api("/api/agent/mcp"), api("/api/agent/agents")]);
    $("agent-state").innerHTML = `<span>background tasks<b>${esc(state.pending_async.join(", ")) || "–"}</b></span><span>last error<b class="${state.last_error ? "bad" : ""}">${esc(state.last_error) || "–"}</b></span>`;
    toolsData = tools; skillsData = skills; mcpData = mcp; agentsData = agents; llmSlots = state.llm_slots || ["fast", "smart"];
    renderTools(); renderMcp(); renderSkills(); renderAgents();
  }

  // automation: the switch and the scheduler's state, the jobs table
  async function loadAutomation() {
    const [st, jobs] = await Promise.all([api("/api/automation"), api("/api/automation/jobs")]);
    kv($("automation-state"), [["switch", st.enabled ? "on" : "off — nothing runs", st.enabled ? "ok" : "warn"], ["scheduler", st.running ? "ticking" : "stopped", st.running ? "ok" : "dim"], ["runs since start", st.runs], ["last tick", st.last_tick ? time(st.last_tick) : "–"], ["quiet hours", st.quiet ? "now (the heartbeat waits)" : "not now"], ["jobs", st.jobs], ["main agent's tools", st.tools.length ? st.tools.map((t) => `<code>${esc(t)}</code>`).join(" ") : "– (switched off)"]]);
    $("jobs").innerHTML = jobs.map((j) => `<tr><td>${esc(j.name)}${j.builtin ? " <small>(built-in)</small>" : ""}</td><td>${esc(j.trigger_kind)} ${esc(j.trigger)}</td><td>${j.next_run_ts ? new Date(j.next_run_ts * 1000).toLocaleString() : "–"}</td><td>${j.last_run_ts ? time(j.last_run_ts) : "–"}</td><td>${j.runs}</td><td>${esc(j.delivery)}</td><td>${esc(j.state)}</td><td class="wrap">${esc(j.prompt).slice(0, 80)}</td><td><button data-job="${j.id}" data-action="${j.state === "paused" ? "resume" : "pause"}">${j.state === "paused" ? "resume" : "pause"}</button> ${j.builtin ? "" : `<button data-job="${j.id}" data-action="delete">delete</button>`}</td></tr>`).join("");
    document.querySelectorAll("[data-job]").forEach((b) => b.addEventListener("click", async () => { await post(`/api/automation/jobs/${b.dataset.job}/${b.dataset.action}`, {}); loadAutomation(); }));
  }
  $("job-add").addEventListener("click", async () => {
    try { await post("/api/automation/jobs", { name: $("job-name").value, prompt: $("job-prompt").value, cron: $("job-cron").value, when: $("job-when").value, delivery: $("job-delivery").value }); loadAutomation(); } catch (e) { alert(e.message); }
  });

  async function loadChannels() {
    const [ch, per, events] = await Promise.all([api("/api/channels"), api("/api/perception"), api("/api/perception/events?limit=60")]);
    const running = Object.fromEntries((ch.running || []).map((r) => [r.name, r]));
    const tg = ch.telegram, wx = ch.wechat;
    kv($("telegram-state"), [["enabled", tg.enabled], ["token", tg.token ? "set" : "missing", tg.token ? "ok" : "warn"], ["paired chats", tg.paired.join(", ") || "–"], ["owner chat", tg.owner || "–"], ["pending code", tg.pairing_code || "–"], ["running", running.telegram ? `received ${running.telegram.received} · sent ${running.telegram.sent}${running.telegram.last_error ? " · " + running.telegram.last_error : ""}` : "no", running.telegram ? (running.telegram.last_error ? "bad" : "ok") : "dim"]]);
    kv($("wechat-state"), [["enabled", wx.enabled], ["token", wx.token ? "set" : "missing", wx.token ? "ok" : "warn"], ["bot id", wx.bot_id || "–"], ["user id", wx.user_id || "–"], ["allowed users", wx.allow.join(", ") || "–"], ["running", running.wechat ? `received ${running.wechat.received} · sent ${running.wechat.sent}${running.wechat.last_error ? " · " + running.wechat.last_error : ""}` : "no", running.wechat ? (running.wechat.last_error ? "bad" : "ok") : "dim"]]);
    const p = per.presence || {};
    kv($("presence"), [["someone present", p.someone_present ? "yes" : "no", p.someone_present ? "ok" : "dim"], ["face visible", p.face_visible ? "yes" : "no"], ["frontal", p.frontal ? "yes" : "no"], ["since", p.since_ts ? time(p.since_ts) : "–"], ["last seen", p.last_seen_ts ? time(p.last_seen_ts) : "–"], ["speech yaw", p.speech_direction != null ? `${(p.speech_direction * 180 / Math.PI).toFixed(0)}°` : "–"], ["watchers", Object.entries(per.watchers || {}).map(([n, w]) => `${n}:${w.polls}${w.errors ? "!" : ""}`).join(" ") || "–"]]);
    $("events").innerHTML = events.map((e) => `<tr><td>${time(e.ts)}</td><td>${esc(e.type)}</td><td>${esc(e.severity)}</td><td class="wrap">${esc(JSON.stringify(e.data))}</td></tr>`).join("") || "<tr><td colspan=4 class=dim>no events yet</td></tr>";
  }
  $("telegram-pair").addEventListener("click", async () => {
    try { const r = await post("/api/channels/telegram/pair", {}); $("telegram-code").textContent = `send /pair ${r.code} to the bot`; loadChannels(); } catch (e) { $("telegram-code").textContent = e.message; }
  });
  $("tg-token-save").addEventListener("click", async () => {
    const token = $("tg-token").value.trim();
    if (!token) return;
    try { await post("/api/config/credentials", { provider: "telegram", values: { bot_token: token } }); $("tg-token").value = ""; $("telegram-code").innerHTML = 'token saved · runs from Bobby\'s next start · <a href="#" data-service-restart>Restart now</a>'; loadChannels(); } catch (e) { $("telegram-code").textContent = e.message; }
  });
  // WeChat: the iLink QR login on the page (the CLI no longer has one, block #87)
  let wxTimer = null;
  const WX_STATUS = { wait: "scan the code with WeChat", scaned: "scanned · confirm on the phone", scaned_but_redirect: "scanned · confirm on the phone", need_verifycode: "WeChat asks for the digits it shows", expired: "the code expired · a new one is coming", verify_code_blocked: "too many wrong codes · try later", binded_redirect: "already bound · the saved login stays valid", timeout: "timed out", idle: "" };
  function wxShow(r) {
    const done = ["confirmed", "verify_code_blocked", "binded_redirect", "timeout", "error", "idle"].includes(r.status);
    $("wx-qr").hidden = done || !r.qr;
    if (r.qr && !done) { const src = `/api/channels/wechat/qr.png?url=${encodeURIComponent(r.qr)}`; if ($("wx-qr").getAttribute("src") !== src) $("wx-qr").src = src; }
    $("wx-code-row").hidden = r.status !== "need_verifycode";
    $("wx-cancel").hidden = done;
    $("wx-login").disabled = !done;
    $("wx-status").textContent = r.status === "confirmed" ? r.note || "logged in" : r.status === "error" ? r.error || "error" : WX_STATUS[r.status] || r.status;
    $("wx-status").className = r.status === "confirmed" ? "ok" : r.status === "error" || r.status === "verify_code_blocked" ? "bad" : "dim";
    if (done) { clearTimeout(wxTimer); wxTimer = null; if (r.status === "confirmed") loadChannels(); }
    else wxTimer = setTimeout(wxPoll, 1500);
  }
  async function wxPoll() { try { wxShow(await api("/api/channels/wechat/login")); } catch (e) { wxShow({ status: "error", error: e.message }); } }
  $("wx-login").addEventListener("click", async () => {
    $("wx-status").textContent = "asking WeChat for a code…";
    try { wxShow(await post("/api/channels/wechat/login", {})); } catch (e) { wxShow({ status: "error", error: e.message.slice(0, 200) }); }
  });
  $("wx-cancel").addEventListener("click", async () => { clearTimeout(wxTimer); try { await api("/api/channels/wechat/login", { method: "DELETE" }); } catch (e) {} wxShow({ status: "idle" }); });
  $("wx-code-send").addEventListener("click", async () => { try { await post("/api/channels/wechat/login/code", { values: { code: $("wx-code").value } }); $("wx-code").value = ""; } catch (e) { $("wx-status").textContent = e.message; } });

  // contacts: the household table, one guided enrollment flow (details → voice → face), the TV zone
  let contactsSnap = null;
  async function loadContacts() {
    const snap = await api("/api/contacts");
    contactsSnap = snap;
    const guestName = (window.SidekickLive && window.SidekickLive.guestName) || ((x) => x);
    $("contacts").innerHTML = snap.contacts.filter((c) => c.id !== "self").map((c) => `<tr><td><b>${esc(c.name)}</b><br><small>${esc(c.id)}</small></td><td>${esc(c.aliases.join(" "))}</td><td>${esc(c.language || "household")}</td><td>${c.is_owner ? "yes" : ""}</td><td>${esc(Object.entries(c.remote_ids).map(([k, v]) => `${k}:${v}`).join(" ")) || "–"}</td><td class="${c.voice_samples ? "ok" : "warn"}">${c.voice_samples} clip(s)</td><td class="${c.face_samples ? "ok" : "warn"}">${c.face_samples} frame(s)</td><td><button data-enroll="${esc(c.id)}" data-estep="voice">Enroll voice</button> <button data-enroll="${esc(c.id)}" data-estep="face">Enroll face</button> <button data-clear="${esc(c.id)}" data-kind="voice" title="forget the voice samples">clear voice</button> <button data-del="${esc(c.id)}">delete</button></td></tr>`).join("") || "<tr><td colspan=8 class=dim>no members yet — click New member</td></tr>";
    $("contacts-last").textContent = `self voice ${snap.self_enrolled ? "enrolled" : "missing"} · last voice ${snap.last_voice ? `${guestName(snap.last_voice.contact) || "unknown"} (${snap.last_voice.score})` : "–"} · last face ${snap.last_face ? `${snap.last_face.contact || "unknown"} (${snap.last_face.score})` : "–"}`;
    $("enroll-contact").innerHTML = snap.contacts.filter((c) => c.id !== "self").map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");
    const people = snap.people || [];
    const ago = (ts) => { const s = Date.now() / 1000 - ts; return s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${(s / 3600).toFixed(1)} h ago` : `${(s / 86400).toFixed(1)} d ago`; };
    $("people").innerHTML = people.map((p) => `<tr><td><b>${esc(guestName(p.id))}</b><br><small>${esc(p.id)}</small></td><td>${p.utterances} over ${p.sessions} session(s)</td><td>${p.face_samples}</td><td>${ago(p.last_seen_ts)}</td><td>${p.declined_ts ? '<span class="warn">declined</span>' : p.ready_ts ? '<span class="ok">ready</span>' : p.asked_ts ? "asked" : "collecting"}</td><td><input data-pname="${esc(p.id)}" placeholder="name" style="width:120px"> <button data-promote="${esc(p.id)}">Befriend</button> <button data-forget-person="${esc(p.id)}">Forget</button></td></tr>`).join("") || "<tr><td colspan=6 class=dim>nobody unnamed yet — Bobby collects voices and faces while people talk to it</td></tr>";
    document.querySelectorAll("[data-promote]").forEach((b) => b.addEventListener("click", async () => { const name = document.querySelector(`[data-pname="${b.dataset.promote}"]`).value.trim(); if (!name) return; try { await post(`/api/contacts/people/${encodeURIComponent(b.dataset.promote)}/promote`, { name }); loadContacts(); } catch (e) { alert(e.message); } }));
    document.querySelectorAll("[data-forget-person]").forEach((b) => b.addEventListener("click", async () => { await del(`/api/contacts/people/${encodeURIComponent(b.dataset.forgetPerson)}`); loadContacts(); }));
    document.querySelectorAll("[data-enroll]").forEach((b) => b.addEventListener("click", () => openEnroll(b.dataset.enroll, b.dataset.estep)));
    document.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", async () => { await del(`/api/contacts/${encodeURIComponent(b.dataset.clear)}/embeddings/${b.dataset.kind}`); loadContacts(); }));
    document.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => { if (confirm(`delete ${b.dataset.del}?`)) { await del(`/api/contacts/${encodeURIComponent(b.dataset.del)}`); loadContacts(); } }));
  }
  const LANG_OPTS = { "": "household default", yue: "廣東話 Cantonese", zh: "普通話 Mandarin", en: "English" };
  const PROMPTS = { yue: ["我係屋企人，Bobby 你記住我把聲。", "今日天氣幾好，我哋出去行下啦。", "聽日朝早八點提我食藥，唔該。"], zh: ["我是家里人，Bobby 请记住我的声音。", "今天天气不错，我们出去走走吧。", "明天早上八点提醒我吃药，谢谢。"], en: ["I'm part of the household, Bobby, remember my voice.", "The weather is nice today, let's go for a walk.", "Remind me to take my pills at eight tomorrow morning."] };
  let enroll = { id: null, step: "details", takes: [], faces: null };
  function openEnroll(id, step) {
    enroll = { id, step: step || (id ? "voice" : "details"), takes: [], faces: null };
    $("enroll-panel").style.display = "block";
    renderEnroll();
    $("enroll-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function closeEnroll() { enroll = { id: null, step: "details", takes: [], faces: null }; $("enroll-panel").style.display = "none"; const img = $("enroll-cam"); if (img) img.removeAttribute("src"); }
  $("c-new").addEventListener("click", () => openEnroll(null, "details"));
  document.querySelectorAll("#enroll-steps button").forEach((b) => b.addEventListener("click", () => { if (b.dataset.estep !== "details" && !enroll.id) return; enroll.step = b.dataset.estep; renderEnroll(); }));
  const contactOf = (id) => (contactsSnap && contactsSnap.contacts.find((c) => c.id === id)) || null;
  function renderEnroll() {
    const c = contactOf(enroll.id);
    $("enroll-title").textContent = c ? `${c.name}${c.is_owner ? " (owner)" : ""}` : "new member";
    document.querySelectorAll("#enroll-steps button").forEach((b) => { b.classList.toggle("active", b.dataset.estep === enroll.step); b.classList.toggle("done", (b.dataset.estep === "details" && !!c) || (b.dataset.estep === "voice" && !!(c && c.voice_samples)) || (b.dataset.estep === "face" && !!(c && c.face_samples))); });
    const body = $("enroll-body");
    if (enroll.step === "details") {
      body.innerHTML = `<div class="fields">
        <label class="f">name<input id="e-name" placeholder="e.g. 爸爸" value="${esc(c ? c.name : "")}"></label>
        <label class="f">aliases (space separated)<input id="e-aliases" placeholder="daddy 老豆" value="${esc(c ? c.aliases.join(" ") : "")}"></label>
        <label class="f">language<select id="e-lang">${Object.entries(LANG_OPTS).map(([k, v]) => `<option value="${k}" ${c && (c.language || "") === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
        <label class="f">owner<select id="e-owner"><option value="">no</option><option value="1" ${c && c.is_owner ? "selected" : ""}>yes — the household owner</option></select></label>
        <label class="f">telegram chat id (optional)<input id="e-tg" value="${esc(c ? c.remote_ids.telegram || "" : "")}"></label>
        <label class="f">wechat user id (optional)<input id="e-wx" value="${esc(c ? c.remote_ids.wechat || "" : "")}"></label>
        </div><div class="row"><button class="primary" id="e-save">${c ? "Save" : "Create"} &amp; record voice →</button><button id="e-cancel">Cancel</button><span id="e-result" class="dim"></span></div>`;
      $("e-save").addEventListener("click", async () => {
        const payload = { name: $("e-name").value.trim(), aliases: $("e-aliases").value.split(/\s+/).filter(Boolean), language: $("e-lang").value || null, is_owner: $("e-owner").value === "1", telegram: $("e-tg").value || null, wechat: $("e-wx").value || null };
        if (!payload.name) { $("e-result").textContent = "a name is needed"; return; }
        try {
          const made = c ? await put(`/api/contacts/${encodeURIComponent(c.id)}`, payload) : await post("/api/contacts", payload); // an edit keeps the prints and the facts
          await loadContacts();
          enroll.id = made.id || made.contact_id || (contactsSnap.contacts.find((x) => x.name === payload.name) || {}).id;
          enroll.step = "voice"; enroll.takes = [];
          renderEnroll();
        } catch (e) { $("e-result").textContent = e.message; }
      });
      $("e-cancel").addEventListener("click", closeEnroll);
    } else if (enroll.step === "voice") {
      const lang = (c && c.language) || "yue";
      const prompts = PROMPTS[lang] || PROMPTS.yue;
      const n = enroll.takes.length;
      body.innerHTML = `<p class="dim" style="margin:0">Stand within two metres, speak at normal volume. Each take records 4 seconds straight from Bobby's microphone; three takes make a good voice print.</p>
        <div class="prompt" id="e-prompt">${esc(prompts[Math.min(n, prompts.length - 1)])}</div>
        <div class="row"><span class="count" id="e-count">${n}/3</span><button class="primary" id="e-rec">Record take ${n + 1}</button><button id="e-skip">Skip to face →</button><button id="e-done">Done</button><span id="e-vres" class="dim"></span></div>
        <div class="takes" id="e-takes">${enroll.takes.map((tk, i) => `<span class="${tk.used ? "ok" : ""}">take ${i + 1}: ${tk.used ? `peak ${tk.peak_dbfs} dBFS` : "too short / quiet"}</span>`).join("")}</div>`;
      $("e-rec").addEventListener("click", async () => {
        const btn = $("e-rec"); btn.disabled = true;
        let left = 4; $("e-count").textContent = `${left}s`;
        const tick = setInterval(() => { left -= 1; $("e-count").textContent = `${Math.max(0, left)}s`; }, 1000);
        try {
          const r = await post("/api/contacts/enroll/voice/record", { contact_id: enroll.id, seconds: 4 });
          enroll.takes.push({ used: r.used > 0, peak_dbfs: r.peak_dbfs });
          clearInterval(tick);
          await loadContacts();
          if (enroll.takes.filter((x) => x.used).length >= 3) { enroll.step = "face"; }
          renderEnroll();
        } catch (e) { clearInterval(tick); $("e-vres").textContent = e.message; btn.disabled = false; }
      });
      $("e-skip").addEventListener("click", () => { enroll.step = "face"; renderEnroll(); });
      $("e-done").addEventListener("click", closeEnroll);
    } else {
      body.innerHTML = `<p class="dim" style="margin:0">Look at Bobby; the box shows what the detector sees (the image is brightened in a dark room). Capture takes five frames over two seconds.</p>
        <div class="row" style="align-items:flex-start"><div class="preview"><img id="enroll-cam" src="/api/body/stream.mjpg?width=640&fps=6&t=${Date.now()}" alt="camera"><div class="cam-faces" id="enroll-faces"></div></div>
        <div><div class="row"><button class="primary" id="e-face">Capture 5 frames</button></div><div id="e-fres" class="dim"></div><div class="row"><button id="e-finish">Finish</button></div></div></div>`;
      $("e-face").addEventListener("click", async () => {
        $("e-fres").textContent = "capturing…";
        try { const r = await post(`/api/contacts/enroll/face/${encodeURIComponent(enroll.id)}`, {}); $("e-fres").innerHTML = r.used ? `<span class="ok">used ${r.used} of ${r.frames} frames</span>` : `<span class="warn">no face found in ${r.frames} frames — move closer or add light</span>`; await loadContacts(); renderEnroll(); } catch (e) { $("e-fres").textContent = e.message; }
      });
      $("e-finish").addEventListener("click", closeEnroll);
    }
  }
  if (window.SidekickLive && window.SidekickLive.subscribe) window.SidekickLive.subscribe((f) => {
    const el = $("enroll-faces");
    if (!el || enroll.step !== "face") return;
    el.innerHTML = (f.faces || []).map((x) => `<div class="face${x.contact ? "" : " unknown"}" style="left:${(x.x * 100).toFixed(1)}%;top:${(x.y * 100).toFixed(1)}%;width:${(x.w * 100).toFixed(1)}%;height:${(x.h * 100).toFixed(1)}%"><span>${esc(x.name || "?")}</span></div>`).join("");
  });
  $("enroll-voice").addEventListener("click", async () => {
    const ids = [...document.querySelectorAll("[data-clip]:checked")].map((el) => el.dataset.clip);
    if (!ids.length) { $("enroll-result").textContent = "select clips first"; return; }
    try { const r = await post("/api/contacts/enroll/voice", { contact_id: $("enroll-contact").value, clip_ids: ids }); $("enroll-result").textContent = `enrolled ${r.used} clip(s)`; } catch (e) { $("enroll-result").textContent = e.message; }
  });
  // the TV zone: drag a rectangle on a camera frame; faces inside are ignored (contacts.tv_zone)
  let tvZone = null, tvDrag = null, tvBound = false;
  function drawTvZone() {
    const rect = $("tv-rect");
    if (!tvZone) { rect.style.display = "none"; return; }
    rect.style.display = "block"; rect.style.left = `${tvZone[0] * 100}%`; rect.style.top = `${tvZone[1] * 100}%`; rect.style.width = `${tvZone[2] * 100}%`; rect.style.height = `${tvZone[3] * 100}%`;
  }
  async function initTvZone() {
    await loadConfig(true);
    tvZone = cfg.contacts.tv_zone || null;
    $("tv-cam").src = `/api/body/frame.jpg?t=${Date.now()}`;
    drawTvZone();
    if (tvBound) return;
    tvBound = true;
    const img = $("tv-cam");
    const pos = (e) => { const r = img.getBoundingClientRect(); return [Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), Math.max(0, Math.min(1, (e.clientY - r.top) / r.height))]; };
    img.addEventListener("mousedown", (e) => { tvDrag = pos(e); e.preventDefault(); });
    img.addEventListener("mousemove", (e) => { if (!tvDrag) return; const p = pos(e); tvZone = [Math.min(tvDrag[0], p[0]), Math.min(tvDrag[1], p[1]), Math.abs(p[0] - tvDrag[0]), Math.abs(p[1] - tvDrag[1])]; drawTvZone(); });
    window.addEventListener("mouseup", () => { tvDrag = null; });
    $("tv-refresh").addEventListener("click", () => { img.src = `/api/body/frame.jpg?t=${Date.now()}`; });
    $("tv-clear").addEventListener("click", () => { tvZone = null; drawTvZone(); });
    $("tv-save").addEventListener("click", async () => {
      try { const r = await post("/api/config/tv", { values: { tv_zone: tvZone && tvZone[2] > 0.01 ? tvZone : null } }); tvZone = r.tv_zone; drawTvZone(); $("tv-result").textContent = tvZone ? "zone saved and applied" : "no zone · every face counts"; cfg.contacts.tv_zone = tvZone; } catch (e) { $("tv-result").textContent = e.message; }
    });
  }

  async function loadExtensions() {
    const rows = await api("/api/extensions");
    $("extensions").innerHTML = rows.map((x) => {
      const props = (x.settings_schema && x.settings_schema.properties) || {};
      const fields = Object.entries(props).map(([k, s]) => {
        const v = x.settings[k];
        if (s.type === "boolean") return `<label class="toggle"><input type="checkbox" data-ext="${esc(x.name)}" data-key="${k}" data-type="boolean" ${v ? "checked" : ""}> ${k}</label>`;
        const val = Array.isArray(v) ? v.join(" ") : (v ?? "");
        return `<label class="toggle" style="flex-direction:column;align-items:stretch"><span>${k}${s.description ? ` <small>${esc(s.description)}</small>` : ""}</span><input data-ext="${esc(x.name)}" data-key="${k}" data-type="${s.type}" ${s.secret ? 'type="password"' : ""} value="${esc(val)}"></label>`;
      }).join("");
      return `<div class="card"><h3>${esc(x.name)} <small>${esc(x.version)} · ${esc(x.source)}</small> <span class="${x.active ? "ok" : x.enabled ? "warn" : "dim"}" style="float:right">${x.active ? "active" : x.enabled ? "enabled (restart)" : "disabled"}</span></h3>
        <p class="dim">${esc(x.description)}</p>
        ${x.error ? `<p class="bad">${esc(x.error)}</p>` : ""}
        <div class="kv"><div>tools</div><div>${esc(x.tools.join(", ")) || "–"}</div><div>skills</div><div>${esc(x.skills.join(", ")) || "–"}</div><div>subagent</div><div>${esc(x.subagent || "–")}</div><div>watchers</div><div>${esc(x.watchers.join(", ")) || "–"}</div></div>
        ${fields ? `<div style="margin-top:8px">${fields}</div><div class="row"><button class="primary" data-save-ext="${esc(x.name)}">Save settings</button></div>` : ""}
        <div class="row"><button data-ext-action="${x.enabled ? "disable" : "enable"}" data-name="${esc(x.name)}">${x.enabled ? "disable" : "enable"}</button>${x.source === "user" ? `<button data-ext-action="update" data-name="${esc(x.name)}">update</button><button data-ext-action="remove" data-name="${esc(x.name)}">remove</button>` : ""}</div></div>`;
    }).join("");
    document.querySelectorAll("[data-ext-action]").forEach((b) => b.addEventListener("click", async () => { try { await post(`/api/extensions/${encodeURIComponent(b.dataset.name)}/${b.dataset.extAction}`, {}); } catch (e) { alert(e.message); } loadExtensions(); }));
    document.querySelectorAll("[data-save-ext]").forEach((b) => b.addEventListener("click", async () => {
      const values = {};
      document.querySelectorAll(`[data-ext="${b.dataset.saveExt}"][data-key]`).forEach((el) => {
        const type = el.dataset.type;
        if (type === "boolean") values[el.dataset.key] = el.checked;
        else if (type === "integer" || type === "number") values[el.dataset.key] = el.value === "" ? null : Number(el.value);
        else if (type === "array") values[el.dataset.key] = el.value.split(/\s+/).filter(Boolean);
        else values[el.dataset.key] = el.value;
      });
      try { await put(`/api/extensions/${encodeURIComponent(b.dataset.saveExt)}/settings`, { values }); $("ext-result").textContent = `${b.dataset.saveExt}: settings saved`; } catch (e) { $("ext-result").textContent = e.message; }
      loadExtensions();
    }));
  }
  $("ext-install").addEventListener("click", async () => {
    try { const r = await post("/api/extensions/install", { values: { source: $("ext-source").value } }); $("ext-result").textContent = `installed ${r.name} ${r.version}`; loadExtensions(); } catch (e) { $("ext-result").textContent = e.message; }
  });

  api("/api/body/expressions").then((list) => { $("say-expr").innerHTML += list.filter((x) => x.kind !== "state").map((x) => `<option value="${x.name}">${x.name} · ${x.kind}</option>`).join(""); }).catch(() => {});
  // first tab: the deep link if any, else Live (the readiness card in the rail says what is missing)
  const first = ALIASES[location.hash.slice(1)] || location.hash.slice(1);
  openTab(TITLES[first.split("/")[0]] ? first : "live");
  window.addEventListener("load", () => { const c = document.querySelector(".content"); if (c) c.scrollTop = 0; });
  poll();
  setInterval(poll, 1000);
})();
