/* sidekick dashboard — the Live page (PLAN.md blocks #67 / #69: Live = now, a module's page =
   depth) and the live feed every page uses: /api/live WebSocket frames — 10 Hz meters with peak
   hold, pose readout, the engagement state, the Telemetry card on Body, the live line of the
   dialogue card (which reads the timeline while Live is open), the camera overlay; once a second
   `modules` (every core module's live() vital signs → the Now card, the Turn card, one card per
   module) and `activity` (what the modules did → the activity stream). The feed runs from page
   load on every page; the camera stream and the 3D view run only while Live or Body is open
   (their cards move between those pages; the 3D view is dashboard_robot3d.js,
   window.SidekickRobot3D). Other scripts subscribe to frames with SidekickLive.subscribe(cb). */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, d = 0) => (v === null || v === undefined ? "–" : typeof v === "number" ? v.toFixed(d) : String(v));
  const deg = (r) => (r === null || r === undefined ? "–" : `${(r * 180 / Math.PI).toFixed(0)}°`);
  const clock = (ts) => new Date((ts || Date.now() / 1000) * 1000).toLocaleTimeString([], { hour12: false });
  const token = (name, fallback) => (getComputedStyle(document.documentElement).getPropertyValue(name) || fallback).trim();

  // ---------------------------------------------------------------- level bars (dBFS, peak hold)
  function bar(fillId, peakId, dbId) {
    const fill = $(fillId), peak = $(peakId), db = $(dbId);
    let hold = -100, holdAt = 0;
    const pct = (dbfs) => Math.max(0, Math.min(100, (dbfs + 60) / 60 * 100));
    return {
      set(dbfs, text) {
        const v = typeof dbfs === "number" ? dbfs : -100;
        fill.style.width = `${pct(v)}%`;
        fill.className = v > -1 ? "clip" : v > -12 ? "hot" : "";
        const now = Date.now();
        if (v >= hold || now - holdAt > 1500) { hold = v; holdAt = now; }
        peak.style.left = `calc(${pct(hold)}% - 1px)`;
        db.textContent = text;
      },
    };
  }
  const mic = bar("bar-mic", "peak-mic", "db-mic");
  const spk = bar("bar-spk", "peak-spk", "db-spk");
  const micLive = bar("bar-mic-live", "peak-mic-live", "db-mic-live");  // the Now card's pair
  const spkLive = bar("bar-spk-live", "peak-spk-live", "db-spk-live");

  // ---------------------------------------------------------------- camera overlay (faces)
  const facesEl = $("cam-faces");
  const guestName = (id) => (typeof id !== "string" ? id : id.startsWith("guest:") ? `訪客 ${id.slice(6)}` : id.startsWith("person:") ? `訪客 ${id.slice(7)}` : id);
  function faces(list) {
    if (!facesEl) return;
    facesEl.innerHTML = (list || []).map((f) => `<div class="face${f.contact ? "" : " unknown"}" style="left:${(f.x * 100).toFixed(1)}%;top:${(f.y * 100).toFixed(1)}%;width:${(f.w * 100).toFixed(1)}%;height:${(f.h * 100).toFixed(1)}%"><span>${esc(f.name || "?")}${f.id_score != null ? ` ${f.id_score}` : ""}</span></div>`).join("");
  }

  // ---------------------------------------------------------------- dialogue (the Live card): what the timeline holds of the
  // conversation — every channel's user and assistant rows (invariant 12) —, oldest at the top; scrolled to the top it loads
  // earlier rows, new rows arrive while Live is open, and the live line (listening / thinking / the sentence being spoken)
  // stays below them; a reader who scrolled up is not pulled down. Watching only: turns are typed on Agent → Test.
  const scroller = $("chat-scroll");
  const rowsEl = $("tl-rows"), liveEl = $("tl-live"), latest = $("chat-latest");
  const PAGE = 60;
  const CHANNEL = { voice: "語音", telegram: "Telegram", wechat: "微信", dashboard: "控制台" };
  const CUE = /\[\s*(express|style)\s*:\s*([^\]]*)\]\s*/gi;  // performance cues stay on the timeline; shown as notes here
  const rows = new Map();  // timeline id → row
  const notes = [];  // the agent's errors, in time order with the rows
  let liveLine = null, liveHtml = "", shown = "", oldest = null, exhausted = false, loading = false, open = false, poller = null, autoPages = 0;
  let names = {};
  const nearBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 60;
  const dayOf = (ts) => { const d = new Date(ts * 1000); return `${d.getMonth() + 1}月${d.getDate()}日 星期${"日一二三四五六"[d.getDay()]}`; };
  const stamp = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit" });
  const nameOf = (id) => names[id] || guestName(id);
  const msg = (kind, avatar, text, meta, bubbleCls = "") => `<div class="msg ${kind}"><div class="avatar">${esc(avatar)}</div><div class="body"><div class="bubble${bubbleCls}">${esc(text)}</div><div class="meta">${meta.filter(Boolean).map(esc).join(" · ")}</div></div></div>`;
  function rowHtml(r) {
    const channel = CHANNEL[r.channel] || r.channel;
    if (r.note) return `<div class="msg note"><div class="body"><div class="bubble ${r.cls || ""}">${esc(r.text)}</div><div class="meta">agent · ${esc(stamp(r.ts))}</div></div></div>`;
    if (r.role === "user") { const name = nameOf(r.speaker); return msg("user", String(name).slice(0, 1).toUpperCase(), r.content, [name, channel, stamp(r.ts), r.visibility === "private" ? "private" : ""]); }
    const cues = [...r.content.matchAll(CUE)].map((m) => `${m[1]}: ${m[2].trim()}`);
    const own = r.meta && r.meta.delivery ? `主動${r.delivered_to ? " → " + (CHANNEL[r.delivered_to] || r.delivered_to) : ""}` : "";
    return msg("bot", "B", r.content.replace(CUE, "").trim() || r.content, ["Bobby", channel, own, stamp(r.ts), cues.join(", ")]);
  }
  const liveMessage = (l) => (l.who === "hearing"
    ? msg("user live", "…", l.text, ["聽緊講"], " pulse")
    : msg("bot live", "B", l.text, ["Bobby", l.pulse ? "" : "講緊"], l.pulse ? " pulse" : ""));
  // the empty state: an invitation when Bobby is ready, the readiness verdict when it is not
  function emptyState() {
    const r = window.SidekickApp && window.SidekickApp.readiness ? window.SidekickApp.readiness() : null;
    if (r && r.ready === false) {
      const blocking = (r.items || []).filter((i) => i.level === "bad").map((i) => esc(i.title));
      return `<div class="empty"><h1>Bobby 未準備好</h1><p>${esc(r.summary)}${blocking.length ? "：" + blocking.join("、") : ""}。System 頁列出差咩、去邊度補。</p><div class="ready-call"><button class="primary" data-readiness-run>檢查就緒</button> <button data-go="system">睇 System</button></div></div>`;
    }
    return '<div class="empty"><h1>Bobby 在聽</h1><p>講一聲「Bobby」開始對話。聽到同講出嘅嘢、Telegram 同微信嘅訊息都會顯示喺呢度。</p></div>';
  }
  function renderRows(keepTop) {
    const before = { height: scroller.scrollHeight, top: scroller.scrollTop, bottom: nearBottom() };
    const items = [...rows.values(), ...notes].sort((x, y) => x.ts - y.ts);
    const out = items.length ? [`<div class="day dim">${exhausted ? "對話由呢度開始" : loading ? "載入緊更早嘅對話…" : "向上捲睇更早嘅對話"}</div>`] : [];
    let day = "";
    for (const it of items) {
      const d = dayOf(it.ts);
      if (d !== day) { day = d; out.push(`<div class="day">${esc(d)}</div>`); }
      out.push(rowHtml(it));
    }
    const html = out.join("") || (liveLine ? "" : emptyState());
    if (html === shown) return;
    shown = html;
    rowsEl.innerHTML = html;
    if (keepTop) scroller.scrollTop = before.top + (scroller.scrollHeight - before.height);  // earlier rows went in above
    else if (before.bottom) scroller.scrollTop = scroller.scrollHeight;
    latest.hidden = nearBottom();
  }
  function renderLive() {
    const html = liveLine ? liveMessage(liveLine) : "";
    if (html === liveHtml) return;
    const bottom = nearBottom();
    liveHtml = html;
    liveEl.innerHTML = html;
    if (bottom) scroller.scrollTop = scroller.scrollHeight;
    if (!rows.size) renderRows();  // the empty state gives way to the live line
  }
  const take = (got) => { got.forEach((r) => rows.set(r.id, r)); if (got.length) oldest = Math.min(oldest ?? Infinity, ...got.map((r) => r.ts)); };
  async function refresh() {
    try {
      const got = await (await fetch(`/api/agent/timeline?conversation=true&limit=${PAGE}`)).json();
      if (!Array.isArray(got)) return;
      if (oldest === null) exhausted = got.length < PAGE;
      take(got);
      renderRows();
      if (!exhausted && autoPages < 3 && scroller.scrollHeight <= scroller.clientHeight) { autoPages += 1; earlier(); }  // too few to scroll: the page before
    } catch (e) { /* the next tick tries again */ }
  }
  async function earlier() {
    if (loading || exhausted || oldest === null) return;
    loading = true;
    renderRows(true);
    try {
      const got = await (await fetch(`/api/agent/timeline?conversation=true&limit=${PAGE}&before=${oldest}`)).json();
      take(got);
      exhausted = got.length < PAGE;
    } catch (e) { /* scroll up again to retry */ }
    loading = false;
    renderRows(true);
  }
  async function loadNames() {
    try {
      const snap = await (await fetch("/api/contacts")).json();
      names = {};
      (snap.contacts || []).forEach((c) => { names[c.id] = c.name; if (c.is_owner && !names.owner) names.owner = c.name; });
    } catch (e) { names = {}; }
  }
  scroller.addEventListener("scroll", () => { if (scroller.scrollTop < 40) earlier(); latest.hidden = nearBottom(); });
  latest.addEventListener("click", () => { scroller.scrollTop = scroller.scrollHeight; latest.hidden = true; });
  rowsEl.addEventListener("click", (e) => { if (e.target.closest("[data-readiness-run]") && window.SidekickApp && window.SidekickApp.runReadiness) window.SidekickApp.runReadiness(); });
  function addLine(who, text, cls) { notes.push({ note: true, ts: Date.now() / 1000, who, text, cls }); renderRows(); }
  let lastHeardAt = null, wasRunning = false;
  function captions(c, inter) {
    if (!c) return;
    const running = !!c.turn_running || !!(inter && inter.speaking);
    if (c.said && running) liveLine = { who: "bobby", text: c.said };
    else if (c.listening) liveLine = { who: "hearing", text: "聆聽中…" };
    else if (running) liveLine = { who: "bobby", text: "思考中…", pulse: true };
    else liveLine = null;
    const heard = !!c.heard_at && c.heard_at !== lastHeardAt;
    if (heard) lastHeardAt = c.heard_at;
    if (open && (heard || (wasRunning && !running))) refresh();  // a turn began or ended: its rows are on the timeline
    wasRunning = running;
    renderLive();
  }

  // ---------------------------------------------------------------- small formatters
  const dur = (ms) => (ms === null || ms === undefined ? "–" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`);
  const ago = (s) => (s === null || s === undefined ? "–" : s < 60 ? `${Math.round(s)} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${(s / 3600).toFixed(1)} h ago`);
  const inS = (s) => (s === null || s === undefined ? "–" : s <= 0 ? "now" : s < 90 ? `in ${Math.round(s)} s` : s < 5400 ? `in ${Math.round(s / 60)} min` : `in ${(s / 3600).toFixed(1)} h`);
  const span = (text, cls) => `<span class="${cls || ""}">${esc(text)}</span>`;
  const RANK = { "": 0, acc: 0, ok: 1, warn: 2, bad: 3 };
  const worst = (...levels) => levels.reduce((a, b) => (RANK[b || ""] > RANK[a || ""] ? b : a), "");
  const tabLevel = (tab) => { const h = window.SidekickApp && window.SidekickApp.health ? window.SidekickApp.health() : null; return (h && h.doctor && h.doctor.tabs && h.doctor.tabs[tab]) || ""; };
  const setHtml = (el, html) => { if (el && el.__html !== html) { el.__html = html; el.innerHTML = html; } };

  // ---------------------------------------------------------------- Now (10 Hz state, 1 Hz session time and decisions)
  const MODES = { idle: "idle", scan: "glancing around", sound: "looking at a sound", face: "on a face", engaged: "engaged" };
  const CAP = { quiet: 0, normal: 6, chatty: 12 };
  let mods = {};
  function attention(a, ini) {
    if (!a) return "–";
    let s = esc(MODES[a.mode] || a.mode);
    if (a.mode === "idle" && a.next_scan_s != null) s += ` <span class="dim">· next glance ${a.next_scan_s.toFixed(0)} s</span>`;
    if ((a.mode === "scan" || a.mode === "sound") && a.glance_s != null) s += ` <span class="dim">· ${a.glance_s.toFixed(0)} s</span>`;
    if (ini) s += ` <span class="dim">· ${esc(ini.sociability)} · greeted ${ini.offered_today || 0}/${CAP[ini.sociability] ?? "?"}</span>`;
    return s;
  }
  function renderNow(f) {
    const inter = f.interaction || {};
    const slow = mods.interaction || {};
    const s = inter.session, state = inter.state || "off";
    const badges = [inter.held ? "held" : "", inter.ducked ? "ducked" : ""].filter(Boolean).map((b) => `<span class="badge">${b}</span>`).join("");
    const who = s ? guestName((slow.session && slow.session.addressee) || s.addressee) : "";
    const left = slow.session && slow.session.left_s != null ? ` · ${Math.ceil(slow.session.left_s)} s left` : "";
    const session = s ? `${who} · ${s.trigger} · ${s.turns} turn(s)${left}` : "no session";
    setHtml($("now-line"), `<span class="state ${esc(state)}">${esc(state)}</span>${badges}<span class="dim">${esc(session)}</span>`);
    const c = f.captions || {};
    const tts = slow.tts;
    const rows = [
      ["listening", c.speech_open ? `<span class="${c.listening ? "ok" : "dim"}">speech open${c.listening ? "" : " · idle"}</span>` : "quiet"],
      ["attention", attention(inter.attention, inter.initiative)],
      ["turn", inter.turn_running ? '<span class="ok">running</span>' : inter.reason ? `<span class="dim">${esc(inter.reason)}</span>` : "–"],
      ["tts link", tts ? (tts.connected ? `<span class="ok">connected</span> <span class="dim">· ${tts.connects} connect(s)</span>` : `<span class="dim">closed</span>${tts.error ? ` <span class="warn">· ${esc(tts.error.slice(0, 60))}</span>` : ""}`) : (inter.tts_connected ? '<span class="ok">connected</span>' : '<span class="dim">closed</span>')],
    ];
    setHtml($("live-status"), rows.map(([k, v]) => `<div>${k}</div><div>${v}</div>`).join(""));
    const level = inter.held ? "warn" : { engaged: "ok", speaking: "ok", idle: "acc" }[state] || "";
    const st = $("now-st"); if (st) st.className = `st ${worst(level, tabLevel("voice"))}`;
  }
  function renderDecisions(inter) {
    const rows = (inter.decisions || []).map((d) => `<div><span class="dim">${esc(clock(d.ts))}</span><span class="${d.decision}">${esc(d.decision)}</span><span>${esc(d.event)} · ${esc(d.reason)}${d.speaker ? " · " + esc(guestName(d.speaker)) : ""}${d.text ? " · " + esc(d.text) : ""}</span></div>`);
    setHtml($("now-decisions"), rows.join("") || '<div><span class="dim">–</span><span></span><span class="dim">no decision yet</span></div>');
  }

  // ---------------------------------------------------------------- Turn: the turn in progress, else the last (voice or text)
  function waterfall(m, running) {
    const end = m.end ?? Math.max(m.first_audio ?? 0, m.first_sentence ?? 0, m.first_token ?? 0, m.asr ?? 0, 1);
    const seg = (a, b, cls) => (a == null || b == null || b <= a ? "" : `<i class="${cls}" style="width:${((b - a) / end * 100).toFixed(1)}%"></i>`);
    const asr = m.asr ?? 0;
    const bars = seg(0, m.asr, "asr") + seg(asr, m.first_token, "llm") + seg(m.first_token, m.first_audio, "tts") + seg(m.first_audio, m.end, "say");
    const keys = [
      m.asr != null ? `<span class="key"><i style="background:#8d7bd6"></i>ASR <b>${dur(m.asr)}</b></span>` : "",
      m.first_token != null ? `<span class="key"><i style="background:var(--acc)"></i>first token <b>${dur(m.first_token - asr)}</b></span>` : running ? '<span class="key"><i style="background:var(--acc)"></i>thinking…</span>' : "",
      m.first_audio != null && m.first_token != null ? `<span class="key"><i style="background:var(--warn)"></i>TTS <b>${dur(m.first_audio - m.first_token)}</b></span>` : "",
      m.end != null && m.first_audio != null ? `<span class="key"><i style="background:var(--ok)"></i>speaking <b>${dur(m.end - m.first_audio)}</b></span>` : "",
    ];
    return `<div class="waterfall">${bars}</div><div class="marks">${keys.filter(Boolean).join("")}</div>`;
  }
  function chips(tools) {
    if (!tools || !tools.length) return "";
    return `<div class="tool-chips">${tools.map((t) => `<span class="${t.ok === null || t.ok === undefined ? "run" : t.ok ? "ok" : "bad"}">${esc(t.tool)}${t.ok === null || t.ok === undefined ? " …" : t.ok ? " ✓" : " ✗"}${t.ms != null ? " " + dur(t.ms) : ""}</span>`).join("")}</div>`;
  }
  const level = (ms, good, poor) => (ms == null ? "" : ms <= good ? "ok" : ms <= poor ? "warn" : "bad");
  function renderTurn() {
    const vt = (mods.interaction || {}).turn;
    const agent = mods.agent || {};
    const inflight = agent.inflight || [];
    const mainNow = inflight.find((t) => t.agent === "main" && t.channel === "voice");
    const textNow = inflight.find((t) => t.agent === "main" && (t.channel !== "voice" || t.kind !== "turn"));
    const last = agent.last_turn || agent.last;  // a job (the heartbeat) shows only while it runs
    let html = "", sub = "", lvl = "";
    if (vt && vt.running) {
      const m = vt.marks || {};
      const first = m.first_audio;
      sub = `voice · ${guestName(vt.speaker || "") || "someone"} · in progress`;
      html = `<div class="turn-big"><b class="${level(first, 2500, 4000)}">${first != null ? dur(first) : "…"}</b><span>to the first word${first == null ? " (waiting)" : ""}</span></div>`
        + `<div class="turn-text"><div>heard</div><div>${esc(vt.text_in || "…")}</div><div>saying</div><div>${esc(vt.said || "…")}</div></div>`
        + waterfall(m, true) + chips(mainNow && mainNow.tools);
      lvl = "acc";
    } else if (textNow) {
      sub = `${textNow.channel} · ${guestName(textNow.speaker)} · ${textNow.kind} in progress`;
      html = `<div class="turn-big"><b class="${level(textNow.first_token_ms, 1500, 3000)}">${textNow.first_token_ms != null ? dur(textNow.first_token_ms) : "…"}</b><span>to the first token · step ${textNow.step}${textNow.tool ? " · " + esc(textNow.tool) : ""}</span></div>`
        + `<div class="turn-text"><div>${textNow.kind === "job" ? "job" : "heard"}</div><div>${esc(textNow.text)}</div><div>saying</div><div>${esc(textNow.said || "…")}</div></div>` + chips(textNow.tools);
      lvl = "acc";
    } else {
      const voiceAt = vt && vt.at ? vt.at : 0;
      const lastAt = last ? last.ts : 0;
      if (vt && voiceAt >= lastAt - 30) {
        const m = vt.marks || {};
        const first = m.first_audio;
        const outcome = vt.interrupted ? "interrupted" : vt.error ? vt.error : vt.no_reply ? "NO_REPLY" : "ok";
        sub = `voice · ${clock(vt.at)} · ${outcome}`;
        const tools = last && last.channel === "voice" && Math.abs(lastAt - voiceAt) < 60 ? last.tools : null;
        html = `<div class="turn-big"><b class="${level(first, 2500, 4000)}">${first != null ? dur(first) : "–"}</b><span>end of speech → first word</span></div>`
          + `<div class="turn-text"><div>heard</div><div>${esc(vt.text_in || "–")}</div><div>said</div><div>${esc(vt.text_out || (vt.no_reply ? "NO_REPLY" : "–"))}</div></div>`
          + waterfall(m, false) + chips(tools);
        lvl = vt.error ? "bad" : level(first, 2500, 4000);
      } else if (last) {
        sub = `${last.channel} · ${guestName(last.speaker)} · ${clock(last.ts)} · ${last.outcome}`;
        html = `<div class="turn-big"><b class="${level(last.first_token_ms, 1500, 3000)}">${last.first_token_ms != null ? dur(last.first_token_ms) : "–"}</b><span>to the first token · ${dur(last.total_ms)} in all · ${last.steps} step(s)</span></div>`
          + `<div class="turn-text"><div>${last.kind === "job" ? "job" : "heard"}</div><div>${esc(last.text || "–")}</div><div>said</div><div>${esc(last.said || (last.outcome === "no_reply" ? "NO_REPLY" : "–"))}</div></div>` + chips(last.tools);
        lvl = last.outcome === "error" ? "bad" : level(last.first_token_ms, 1500, 3000);
      } else {
        html = '<span class="dim">no turn yet — say “Bobby”</span>';
      }
    }
    $("turn-sub").textContent = sub || "the turn in progress, else the last";
    setHtml($("turn-body"), html);
    $("turn-st").className = `st ${lvl}`;
  }

  // ---------------------------------------------------------------- one card per core module
  // while Bobby's service is stopped the runtime modules are off on purpose: no red dots for them
  const RUNTIME_CARDS = new Set(["body", "perception", "channel", "record", "extension", "agent", "automation", "services"]);
  let serviceState = null;
  function card(key, lvl, sub, rows) {
    const el = $(`mod-${key}`);
    if (!el) return;
    if (serviceState && serviceState !== "running" && RUNTIME_CARDS.has(key)) lvl = "";
    el.querySelector(".st").className = `st ${lvl || ""}`;
    el.querySelector("h3 small").textContent = sub || "";
    setHtml(el.querySelector(".kv"), rows.filter(Boolean).map(([k, v]) => `<div>${esc(k)}</div><div>${v}</div>`).join(""));
  }
  const deg0 = (r) => (r === null || r === undefined ? "–" : `${Math.round(r * 180 / Math.PI)}°`);
  let cameraFps = null;
  const SLOT_NAMES = { "llm.fast": "llm fast", "llm.smart": "llm smart", "asr.local": "asr local", "asr.primary": "asr cloud", "asr.kws": "kws", "tts.primary": "tts stream", "tts.fallback": "tts http" };
  const RENDER = {
    agent(a) {
      const busy = (a.inflight || []).map((t) => `${esc(t.agent)} ${t.state === "tool" ? "→ " + esc(t.tool) : esc(t.state)} · step ${t.step} · ${esc(t.channel)} ${dur(t.age_ms)}`);
      const today = a.today || {};
      const bg = (a.background || []).map((b) => `${esc(b.agent)}: ${esc(b.task)} · ${ago(b.age_s).replace(" ago", "")}`);
      const parked = (a.parked || []).map((p) => `${esc(p.tool)} waiting ${Math.round(p.age_s)} s`);
      card("agent", worst(a.last_error ? "warn" : busy.length ? "acc" : "ok", tabLevel("agent")), `${a.agents} agents · ${a.tools} tools`, [
        ["now", busy.length ? busy.join("<br>") : '<span class="dim">idle</span>'],
        ["today", `${today.turns || 0} turn(s) · ${today.tools || 0} tool call(s)${today.tool_errors ? ` · <span class="warn">${today.tool_errors} failed</span>` : ""}`],
        ["first token", a.first_token_median_ms != null ? `<b>${dur(a.first_token_median_ms)}</b> <span class="sub">median of the last turns</span>` : '<span class="dim">no turn yet</span>'],
        bg.length ? ["background", bg.join("<br>")] : null,
        parked.length ? ["asks first", parked.join("<br>")] : null,
        a.last_error ? ["last error", span(a.last_error.slice(0, 120), "warn")] : null,
      ]);
    },
    services(sv) {
      const rows = [];
      let lvl = "ok";
      for (const kind of ["llm", "asr", "tts"]) {
        const slots = ((sv[kind] || {}).slots) || {};
        const bound = ((sv[kind] || {}).bound) || [];
        for (const name of bound) {
          const s = slots[name];
          const key = `${kind}.${name}`;
          if (key === "asr.kws") continue;
          if (!s || !s.last) { rows.push([SLOT_NAMES[key] || key, '<span class="dim">no call yet</span>']); continue; }
          const last = s.last;
          if (s.errors_1h) lvl = worst(lvl, "warn");
          const first = s.median_first_ms != null ? ` · first <b>${dur(s.median_first_ms)}</b>` : "";
          const hedged = s.hedged ? ` <span class="sub">· asked twice ${s.hedged}× (the second first ${s.hedge_won || 0}×)</span>` : "";
          rows.push([SLOT_NAMES[key] || key, `${s.inflight ? '<span class="ok">● </span>' : ""}<b>${dur(s.median_ms)}</b>${first} <span class="sub">· ${ago(last.age_s)}${last.ok || last.cancelled ? "" : " · failed"}</span>${s.errors_1h ? ` <span class="warn">· ${s.errors_1h} error(s)/h</span>` : ""}${hedged}`]);
        }
      }
      card("services", lvl, "median of the last calls", rows.length ? rows : [["slots", '<span class="dim">none bound</span>']]);
    },
    memory(m) {
      if (!m || m.error) { card("memory", "", "", [["memory", span(m && m.error ? m.error : "–", "dim")]]); return; }
      const w = m.writer || null;
      const last = m.last_fact ? `${esc(m.last_fact.text)} <span class="sub">· ${esc(guestName(m.last_fact.scope))} · ${ago(m.last_fact.ago_s)}</span>` : '<span class="dim">nothing yet</span>';
      card("memory", worst(w && w.error ? "warn" : w && w.state === "writing" ? "acc" : "ok", tabLevel("agent")), `${m.facts ?? 0} fact(s) · ${m.episodes ?? 0} episode(s)`, [
        ["profiles", m.scopes != null ? `${m.scopes} scope(s)${m.digests ? ` · ${m.digests} digest(s)` : ""}` : "–"],
        ["last fact", last],
        m.last_episode ? ["last episode", `${esc(m.last_episode.title)} <span class="sub">· ${ago(m.last_episode.ago_s)}</span>`] : null,
        w ? ["writer", `${w.state === "writing" ? '<span class="ok">writing</span>' : esc(w.state || "idle")}${w.waiting ? ` <span class="sub">· ${w.waiting} conversation(s) waiting</span>` : ""}${w.last_s != null ? ` <span class="sub">· last ${ago(w.last_s)}</span>` : ""}${w.error ? `<br>${span(w.error.slice(0, 100), "warn")}` : ""}`] : null,
      ]);
    },
    automation(a) {
      const next = (a.next || []).map((j) => `${esc(j.name)} <span class="sub">${inS(j.in_s)}</span>`);
      const hb = a.heartbeat;
      const lastBeat = hb && hb.last ? ` <span class="sub">· last ${hb.last.error ? "failed" : hb.last.said ? "spoke" : "nothing to say"} ${ago(Date.now() / 1000 - hb.last.ts)}</span>` : "";
      card("automation", worst(!a.enabled ? "warn" : a.job ? "acc" : "ok", tabLevel("automation")), a.enabled ? (a.quiet ? "quiet hours" : "on") : "switched off", [
        ["running", a.job ? `${esc(a.job.name)} <span class="sub">${Math.round(a.job.age_s)} s</span>` : '<span class="dim">nothing</span>'],
        ["next", next.length ? next.join("<br>") : '<span class="dim">no timed job</span>'],
        ["heartbeat", hb ? `${hb.in_s != null ? inS(hb.in_s) : "–"}${lastBeat}` : '<span class="dim">–</span>'],
        ["today", `${a.runs_today} run(s)`],
      ]);
    },
    channel(c) {
      const rows = [];
      let lvl = "ok";
      for (const [name, ch] of Object.entries(c || {})) {
        if (name === "voice") continue;
        const state = ch.paused_s ? `<span class="warn">paused ${Math.round(ch.paused_s / 60)} min</span>` : ch.alive === false ? '<span class="bad">stopped</span>' : '<span class="ok">polling</span>';
        if (ch.error || ch.alive === false) lvl = worst(lvl, ch.alive === false ? "bad" : "warn");
        const last = ch.last_in_s != null ? `last message ${ago(ch.last_in_s)}` : "no message yet";
        rows.push([CHANNEL[name] || name, `${state} <span class="sub">· ${last} · ${ch.received ?? 0} in / ${ch.sent ?? 0} out</span>${ch.error ? `<br>${span(ch.error.slice(0, 100), "warn")}` : ""}`]);
      }
      card("channel", worst(rows.length ? lvl : "", tabLevel("channel")), rows.length ? "remote chats" : "", rows.length ? rows : [["remote", '<span class="dim">no Telegram / WeChat running</span>']]);
    },
    system(sys) {
      const d = sys.doctor || {}, h = sys.host || {}, log = sys.log || {};
      const lag = h.loop_lag_ms;
      const lvl = worst(d.ready === false ? "bad" : d.warn ? "warn" : "ok", lag > 500 ? "bad" : lag > 100 ? "warn" : "", log.error ? "warn" : "");
      const failing = (d.failing || []).map((i) => `<a data-go="${esc(i.tab)}" class="${i.level}">${esc(i.title)}</a>`);
      card("system", lvl, `up ${ago(sys.uptime_s).replace(" ago", "")}`, [
        ["readiness", `<span class="${d.ready === false ? "bad" : d.warn ? "warn" : "ok"}">${esc(d.summary || "–")}</span>${failing.length ? "<br>" + failing.join(" · ") : ""}`],
        ["host", `load ${h.load ? h.load[0].toFixed(1) : "–"} / ${h.cores ?? "–"} cores · CPU ${h.cpu_pct ?? "–"}% · ${h.rss_mb ?? "–"} MB${h.rss_current === false ? " peak" : ""}`],
        ["event loop", lag == null ? "–" : `<span class="${lag > 500 ? "bad" : lag > 100 ? "warn" : "ok"}">${dur(lag)}</span> <span class="sub">worst wake-up delay, 10 s</span>`],
        h.temp_c != null ? ["temperature", `${h.temp_c.toFixed(0)} °C`] : null,
        ["log, 10 min", `${log.warning || 0} warning(s) · <span class="${log.error ? "bad" : ""}">${log.error || 0} error(s)</span>`],
      ]);
    },
    body(b) {
      const layers = Object.entries(b.layers || {}).map(([layer, name]) => `${esc(layer)}: <b>${esc(name)}</b>`);
      const lvl = worst(!b.connected ? "bad" : b.state !== "awake" ? "warn" : b.manual ? "warn" : "ok", tabLevel("body"));
      card("body", lvl, `daemon ${b.daemon || "–"}`, [
        ["state", `<span class="${b.state === "awake" ? "ok" : "warn"}">${esc(b.state)}</span>${b.error ? ` · ${span(b.error.slice(0, 80), "bad")}` : ""}`],
        ["control", b.manual ? `<span class="warn">manual · ${esc(b.holder || "?")}</span>${b.dropped ? ` <span class="sub">· ${b.dropped} dropped</span>` : ""}` : "auto"],
        ["motion", `${layers.length ? layers.join(" · ") : '<span class="dim">no expression</span>'}${b.moving ? ' <span class="sub">· moving</span>' : ""}`],
        ["look", b.look ? `yaw ${deg0(b.look.yaw)} · pitch ${deg0(b.look.pitch)}` : "–"],
        ["voice", `${b.speaking ? '<span class="ok">speaking</span>' : "quiet"} <span class="sub">· sway ${b.sway ? "on" : "off"} · style ${esc(b.style)}${b.volume != null ? ` · volume ${b.volume}` : ""}</span>`],
        ["touch", b.touch ? `${esc(b.touch.side)} antenna ${ago(b.touch.ago_s)}` : '<span class="dim">none yet</span>'],
        ["camera", cameraFps != null ? `${cameraFps.toFixed(0)} fps <span class="sub">· daemon cap 10</span>` : "–"],
      ]);
    },
    perception(p) {
      const pr = p.presence || {};
      const faces = (p.faces || []).map((f) => `${esc(guestName(f.name || "?"))}${f.score != null ? ` <span class="sub">${Number(f.score).toFixed(2)}</span>` : ""}`);
      const t = p.today || {};
      const watchers = (p.watchers || []).map((w) => `${esc(w.name)}${w.errors ? ` <span class="warn">${w.errors} err</span>` : ""}`);
      card("perception", worst((p.watchers || []).some((w) => w.errors) ? "warn" : "ok"), `${p.published} event(s)`, [
        ["presence", pr.someone_present ? `<span class="ok">someone here</span>${pr.since_ts ? ` <span class="sub">since ${clock(pr.since_ts)}</span>` : ""}` : `nobody${pr.last_seen_ts ? ` <span class="sub">· last seen ${ago(Date.now() / 1000 - pr.last_seen_ts)}</span>` : ""}`],
        ["faces", faces.length ? faces.join(" · ") : '<span class="dim">none</span>'],
        ["speech", pr.speech_direction != null ? `from ${deg0(pr.speech_direction)}` : '<span class="dim">–</span>'],
        ["today", `${t["gaze.mutual"] || 0} mutual gaze · ${t["presence.enter"] || 0} arrival(s) · ${t["greet.due"] || 0} greeting(s)`],
        ["watchers", watchers.join(" · ") || "–"],
      ]);
    },
    contact(c) {
      const id = (x) => (x ? `${esc(guestName(x.name || x.contact || "?"))} <span class="sub">${x.score.toFixed(2)} · ${ago(x.ago_s)}</span>` : '<span class="dim">–</span>');
      card("contact", worst(c.members ? "ok" : "warn", tabLevel("contact")), `${c.members ?? 0} member(s)`, [
        ["voice", id(c.voice)],
        ["face", id(c.face)],
        ["members", c.members ? `${c.members}${c.owner ? ` <span class="sub">· owner ${esc(c.owner)}</span>` : ' <span class="warn">· no owner</span>'}` : '<span class="warn">nobody enrolled</span>'],
        ["people seen", `${c.people ?? 0}${c.ready ? ` <span class="ok">· ${c.ready} ready to befriend</span>` : ""}`],
        ["own voice", c.self_enrolled ? '<span class="ok">enrolled</span>' : '<span class="warn">missing</span>'],
      ]);
    },
    record(r) {
      const lvl = worst(r.state === "recording" ? "ok" : r.state === "off" ? "" : "warn", r.error ? "warn" : "", tabLevel("record"));
      const chunk = r.chunk ? `${esc(r.chunk)} <span class="sub">· ${Math.floor((r.chunk_age_s || 0) / 60)}:${String((r.chunk_age_s || 0) % 60).padStart(2, "0")}</span>` : "–";
      card("record", lvl, r.retention_hours ? `${r.retention_hours} h ring` : "", [
        ["state", `<span class="${r.state === "recording" ? "ok" : "warn"}">${esc(r.state)}</span>`],
        ["chunk", chunk],
        ["ring", r.hours != null ? `${r.hours.toFixed(1)} h · ${r.size_gb.toFixed(1)} GB` : "–"],
        ["disk", r.free_gb != null ? `<span class="${r.free_gb < (r.min_free_gb || 0) * 1.2 ? "warn" : ""}">${r.free_gb.toFixed(0)} GB free</span> <span class="sub">· floor ${r.min_free_gb} GB</span>` : "–"],
        r.error ? ["error", span(r.error.slice(0, 100), "warn")] : null,
      ]);
    },
    extension(x) {
      const watchers = (x.watchers || []).map((w) => `${esc(String(w.name).startsWith(w.extension + ".") ? w.name : `${w.extension}.${w.name}`)} <span class="sub">${w.ago_s != null ? ago(w.ago_s) : "not yet"}</span>${w.errors ? ` <span class="warn">· ${w.errors} err</span>` : ""}`);
      card("extension", worst((x.watchers || []).some((w) => w.errors) ? "warn" : "ok", tabLevel("extension")), `${(x.active || []).length} of ${x.installed} on`, [
        ["active", (x.active || []).map(esc).join(" · ") || '<span class="dim">none</span>'],
        ["tools", String(x.tools ?? 0)],
        ["watchers", watchers.join("<br>") || '<span class="dim">none</span>'],
      ]);
    },
  };
  function renderModules(m) {
    mods = m;
    for (const [key, render] of Object.entries(RENDER)) {
      const data = key === "services" ? m.services : m[key];
      if (data === undefined && key !== "memory") continue;
      try { render(data || {}); } catch (e) { console.warn(key, e); }
    }
    renderDecisions(m.interaction || {});
    renderTurn();
    const a = m.agent || {};
    if (a.last_error && a.last_error !== renderModules.lastError) { renderModules.lastError = a.last_error; addLine("agent", `error: ${a.last_error}`, "bad"); }
  }

  // ---------------------------------------------------------------- activity: what every module did, newest first
  const activity = [];
  const seen = new Set();
  let filter = "all";
  const MODULE_NAMES = { interaction: "voice", perception: "perception", agent: "agent", automation: "automation", channel: "channel", memory: "memory", system: "system" };
  function addActivity(rows) {
    let added = false;
    for (const r of rows.slice().reverse()) {
      const key = `${r.ts}|${r.module}|${r.text}`;
      if (seen.has(key)) continue;
      seen.add(key);
      activity.unshift(r);
      added = true;
    }
    if (activity.length > 300) activity.splice(300).forEach((r) => seen.delete(`${r.ts}|${r.module}|${r.text}`));
    if (added) renderActivity();
  }
  function renderActivity() {
    const counts = {};
    activity.forEach((r) => { counts[r.module] = (counts[r.module] || 0) + 1; });
    const chipsHtml = [["all", activity.length], ...Object.keys(MODULE_NAMES).filter((k) => counts[k]).map((k) => [k, counts[k]])]
      .map(([k, n]) => `<button data-act="${k}" class="${filter === k ? "active" : ""}">${esc(k === "all" ? "all" : MODULE_NAMES[k])}<small>${n}</small></button>`).join("");
    setHtml($("activity-chips"), chipsHtml);
    const shown = activity.filter((r) => filter === "all" || r.module === filter).slice(0, 150);
    setHtml($("activity"), shown.map((r) => `<div class="act ${esc(r.level || "")}"><time>${esc(clock(r.ts))}</time><span class="m">${esc(MODULE_NAMES[r.module] || r.module)}</span><span class="t">${esc(r.text)}</span></div>`).join("") || '<span class="dim">nothing yet</span>');
  }
  $("activity-chips").addEventListener("click", (e) => { const b = e.target.closest("[data-act]"); if (b) { filter = b.dataset.act; renderActivity(); } });

  // ---------------------------------------------------------------- frame handling
  function onFrame(f) {
    if (f.service !== undefined && f.service !== serviceState) {
      const was = serviceState;
      serviceState = f.service;
      if (serviceState === "stopped") $("live-cam").removeAttribute("src");  // the stream ended with the robot
      else if (serviceState === "running" && was && railShown) $("live-cam").src = `/api/body/stream.mjpg?width=800&fps=10&t=${Date.now()}`;
    }
    const b = f.body;
    if (b) {
      const micText = `${fmt(b.mic_dbfs, 1)} dBFS`;
      const spkText = b.speaking ? `${fmt(b.speaker_dbfs, 1)}${b.gain_db < -1 ? " ducked" : ""}` : "quiet";
      mic.set(b.mic_dbfs, micText);
      spk.set(b.speaking ? b.speaker_dbfs : -100, spkText);
      micLive.set(b.mic_dbfs, micText);
      spkLive.set(b.speaking ? b.speaker_dbfs : -100, spkText);
      const h = b.head;
      if (b.camera_fps != null) { cameraFps = b.camera_fps; $("cam-info").textContent = `camera ${b.camera_fps.toFixed(0)} fps · daemon cap 10`; }
      $("pose-info").textContent = `yaw ${deg(h[0])} · pitch ${deg(h[1])} · roll ${deg(h[2])} · antennas ${deg((b.antennas_measured || b.antennas)[0])} / ${deg((b.antennas_measured || b.antennas)[1])}${b.emotion ? " · " + b.emotion : b.gesture ? " · " + b.gesture : ""}${b.joints_measured ? " · measured" : " · commanded"}`;
    }
    faces(f.faces);
    if (f.modules) renderModules(f.modules);
    renderNow(f);
    if (window.SidekickApp && window.SidekickApp.telemetry) window.SidekickApp.telemetry($("live-telemetry"), f);
    captions(f.captions, f.interaction || {});
    if (f.activity && f.activity.length) addActivity(f.activity);
    if (window.SidekickRobot3D && liveView) liveView.setPose(b);
    for (const cb of subscribers) { try { cb(f); } catch (e) { console.warn(e); } }
  }
  const subscribers = [];

  // ---------------------------------------------------------------- lifecycle (feed always on)
  let ws = null, active = true, timer = null, liveView = null, visible = true;
  function connect() {
    if (!active) return;
    try { ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live?hz=10`); } catch (e) { timer = setTimeout(connect, 2000); return; }
    ws.onmessage = (e) => { try { onFrame(JSON.parse(e.data)); } catch (err) { console.warn(err); } };
    ws.onclose = () => { ws = null; if (active) timer = setTimeout(connect, 1500); };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  }
  // the heavy parts (camera stream, WebGL) run only on the pages that show them; the feed itself stays up
  let railShown = false;
  function railVisible(camera, body3d = camera) {
    visible = body3d;
    railShown = camera;
    if (camera) { if (!$("live-cam").getAttribute("src") && serviceState !== "stopped") $("live-cam").src = `/api/body/stream.mjpg?width=800&fps=10&t=${Date.now()}`; }  // the daemon's IPC feed is capped at 10 fps
    else $("live-cam").removeAttribute("src");
    if (body3d) {
      if (window.SidekickRobot3D) { if (!liveView) liveView = window.SidekickRobot3D.create($("robot3d")); liveView.resume(); }
      else window.addEventListener("robot3d-ready", () => { if (visible && !liveView) { liveView = window.SidekickRobot3D.create($("robot3d")); liveView.resume(); } }, { once: true });
    } else if (liveView) liveView.pause();
  }
  // the dialogue card polls the timeline only while Live is open (a turn's start and end also refresh it at once)
  function start() {
    open = true;
    loadNames().then(refresh);
    clearInterval(poller);
    poller = setInterval(refresh, 2000);
  }
  function stop() { open = false; clearInterval(poller); poller = null; }
  const rerender = () => { shown = ""; renderRows(); };
  // after a start of the service: the old MJPEG stream ended with the robot, open a new one
  function reloadCamera() { if (railShown) $("live-cam").src = `/api/body/stream.mjpg?width=800&fps=10&t=${Date.now()}`; }
  window.SidekickLive = { start, stop, addLine, railVisible, refresh: rerender, subscribe: (cb) => subscribers.push(cb), guestName, reloadCamera };
  connect();
  const openAt = window.SidekickApp && window.SidekickApp.currentTab ? window.SidekickApp.currentTab() : "live";
  railVisible(openAt === "live" || openAt === "body");
  renderRows();
  if (openAt === "live") start();
})();
