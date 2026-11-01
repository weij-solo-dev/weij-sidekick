/* sidekick dashboard — Replay tab: the 24 h recording ring as a control-room view. A day strip of
   5-minute chunks (coloured by activity), the chunk's video with the mic and speaker tracks kept in
   sync as separate <audio> elements, a canvas of tracks (peak envelopes, engagement state band,
   dialogue / decision / event markers) that seeks on click, and the 3D body driven by the telemetry
   row under the cursor (dashboard_robot3d.js). Data: /api/record/* (dashboard/replay.py). */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const api = async (path) => { const r = await fetch(path); if (!r.ok) throw new Error(`${r.status} ${await r.text()}`); return r.json(); };
  const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
  const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const deg = (r) => (r === null || r === undefined ? "–" : `${(r * 180 / Math.PI).toFixed(0)}°`);
  const CHUNK_S = 300;
  const token = (name, fallback) => (getComputedStyle(document.documentElement).getPropertyValue(name) || fallback).trim();

  const video = $("rp-video"), mic = $("rp-mic"), spk = $("rp-spk"), canvas = $("rp-canvas");
  let days = [], day = null, chunks = [], chunk = null, tracks = null, telemetry = [], view = null, opened = false;
  let master = video; // the element whose currentTime is the clock (audio when a chunk has no video)
  let raf = null;

  // ---------------------------------------------------------------- loading
  async function open() {
    opened = true;
    if (window.SidekickRobot3D) { if (!view) view = window.SidekickRobot3D.create($("rp-robot3d")); view.resume(); }
    else window.addEventListener("robot3d-ready", () => { if (opened && !view) { view = window.SidekickRobot3D.create($("rp-robot3d")); view.resume(); } }, { once: true });
    await refresh();
    tick();
  }
  function close() { opened = false; pause(); if (view) view.pause(); if (raf) { cancelAnimationFrame(raf); raf = null; } }
  async function refresh() {
    const overview = await api("/api/record");
    days = overview.days;
    const st = overview.status;
    $("rp-summary").textContent = `${st.state} · ${st.chunks} chunk(s) · ${st.hours.toFixed(1)} h · ${st.size_gb.toFixed(2)} GB · ${st.free_gb.toFixed(0)} GB free`;
    if (!days.length) { $("rp-day").innerHTML = "<option>no recordings yet</option>"; $("rp-strip").innerHTML = ""; return; }
    if (!day || !days.includes(day)) day = days[days.length - 1];
    $("rp-day").innerHTML = days.map((d) => `<option ${d === day ? "selected" : ""}>${d}</option>`).join("");
    await loadDay();
  }
  async function loadDay() {
    chunks = await api(`/api/record/chunks?day=${encodeURIComponent(day)}`);
    const cells = new Array(288).fill(null);
    for (const c of chunks) {
      const d = new Date(c.start_ts * 1000);
      const slot = Math.min(287, Math.floor((d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / CHUNK_S));
      cells[slot] = c;
    }
    $("rp-strip").innerHTML = cells.map((c, i) => {
      if (!c) return `<i data-slot="${i}"></i>`;
      const cls = ["has", c.open ? "open" : c.activity > 0.3 ? "a3" : c.activity > 0.08 ? "a2" : c.activity > 0 ? "a1" : "", c.errors && c.errors.length ? "err" : "", chunk && chunk.id === c.id ? "sel" : ""].filter(Boolean).join(" ");
      return `<i class="${cls}" data-id="${c.id}" title="${clock(c.start_ts)} · ${Math.round(c.duration_s)} s · ${c.frames} frames · activity ${(c.activity * 100).toFixed(0)}%${c.open ? " · recording" : ""}"></i>`;
    }).join("");
    $("rp-strip").querySelectorAll("i[data-id]").forEach((el) => el.addEventListener("click", () => loadChunk(el.dataset.id)));
    if (!chunk && chunks.length) loadChunk(chunks[chunks.length - 1].id);
  }
  async function loadChunk(id) {
    pause();
    const [meta, tr, tel] = await Promise.all([api(`/api/record/${id}`), api(`/api/record/${id}/tracks`), api(`/api/record/${id}/telemetry`)]);
    chunk = meta; tracks = tr; telemetry = tel;
    $("rp-strip").querySelectorAll("i").forEach((el) => el.classList.toggle("sel", el.dataset.id === id));
    $("rp-title").innerHTML = `${esc(id)} <small id="rp-info"></small>`;
    $("rp-info").textContent = `${clock(meta.start_ts)} – ${meta.end_ts ? clock(meta.end_ts) : "recording"} · ${meta.frames} frames · ${(meta.bytes / 1e6).toFixed(1)} MB · ${meta.video || "no video"} · ${tel.length} telemetry rows${meta.errors && meta.errors.length ? " · " + meta.errors.join("; ") : ""}`;
    const base = `/api/record/${id}/file/`;
    video.removeAttribute("src"); mic.removeAttribute("src"); spk.removeAttribute("src");
    if (tr.has_video) { video.src = base + "video.mp4"; video.style.display = ""; master = video; }
    else { video.style.display = "none"; master = mic; }
    if (tr.audio.mic) { mic.src = base + tr.audio.mic.file; if (!tr.has_video) { mic.controls = true; } }
    if (tr.audio.speaker) spk.src = base + tr.audio.speaker.file;
    video.muted = true; // the video file carries no audio; the tracks do
    applyMutes();
    $("rp-list").innerHTML = [...tr.dialogue.map((d) => `${mmss(d.at)} <b>${esc(d.role)}</b> ${esc(d.speaker)}: ${esc(d.content).slice(0, 160)}${d.tool ? ` <i>(${esc(d.tool)})</i>` : ""}`), ...tr.decisions.filter((d) => d.event === "turn" || d.decision === "reject").map((d) => `${mmss(d.at)} <b>${esc(d.event)}</b> ${esc(d.decision)} ${esc(d.reason)} ${esc(d.text || "")}`), ...tr.events.map((e) => `${mmss(e.at)} <b>event</b> ${esc(e.type)} ${esc(JSON.stringify(e.data)).slice(0, 80)}`)].sort().join("<br>") || '<span class="dim">no dialogue, decisions or events in this chunk</span>';
    draw(0);
    setPoseAt(0);
  }

  // ---------------------------------------------------------------- playback sync
  function applyMutes() { mic.muted = $("rp-mute-mic").checked; spk.muted = $("rp-mute-spk").checked; }
  $("rp-mute-mic").addEventListener("change", applyMutes);
  $("rp-mute-spk").addEventListener("change", applyMutes);
  const followers = () => [mic, spk].filter((a) => a !== master && a.getAttribute("src"));
  function syncFollowers(force) {
    for (const a of followers()) {
      if (force || Math.abs(a.currentTime - master.currentTime) > 0.2) { try { a.currentTime = master.currentTime; } catch (e) {} }
      if (!master.paused && a.paused) a.play().catch(() => {});
      if (master.paused && !a.paused) a.pause();
    }
  }
  function pause() { try { video.pause(); mic.pause(); spk.pause(); } catch (e) {} }
  for (const ev of ["play", "pause", "seeked"]) video.addEventListener(ev, () => { if (master === video) syncFollowers(true); });
  for (const ev of ["play", "pause", "seeked"]) mic.addEventListener(ev, () => { if (master === mic) syncFollowers(true); });
  video.addEventListener("ended", () => { if ($("rp-auto").checked) next(1); });
  mic.addEventListener("ended", () => { if (master === mic && $("rp-auto").checked) next(1); });
  function next(delta) {
    if (!chunk) return;
    const i = chunks.findIndex((c) => c.id === chunk.id);
    const target = chunks[i + delta];
    if (target) loadChunk(target.id).then(() => { if (delta > 0) master.play().catch(() => {}); });
  }
  $("rp-prev").addEventListener("click", () => next(-1));
  $("rp-next").addEventListener("click", () => next(1));
  $("rp-refresh").addEventListener("click", () => refresh().catch((e) => console.warn(e)));
  $("rp-day").addEventListener("change", () => { day = $("rp-day").value; chunk = null; loadDay().catch((e) => console.warn(e)); });
  function seek(t) { try { master.currentTime = Math.max(0, Math.min(t, (master.duration || chunk.duration_s) - 0.05)); } catch (e) {} syncFollowers(true); draw(t); setPoseAt(t); }
  canvas.addEventListener("click", (e) => { if (!chunk) return; const r = canvas.getBoundingClientRect(); seek((e.clientX - r.left) / r.width * chunk.duration_s); });

  // ---------------------------------------------------------------- telemetry → 3D
  function rowAt(t) {
    if (!telemetry.length || !chunk) return null;
    const target = chunk.start_ts + t;
    let lo = 0, hi = telemetry.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (telemetry[mid].t < target) lo = mid + 1; else hi = mid; }
    return telemetry[lo];
  }
  function setPoseAt(t) {
    const row = rowAt(t);
    if (!row) return;
    if (view) view.setPose({ head: row.head, head_measured: row.head_measured, joints_measured: row.joints_measured, antennas: row.antennas, antennas_measured: row.antennas_measured });
    const x = row.x || {};
    $("rp-pose").textContent = `yaw ${deg(row.head[0])} · pitch ${deg(row.head[1])} · roll ${deg(row.head[2])}${row.emotion ? " · " + row.emotion : row.gesture ? " · " + row.gesture : ""}`;
    $("rp-status").innerHTML = [`<span class="state ${esc(x.state || row.state)}">${esc(x.state || row.state)}</span>`, x.who ? `<span><b>with</b>${esc(x.who)} · ${esc(x.trigger || "")}</span>` : "", `<span><b>mic</b>${row.mic_dbfs} dBFS</span>`, `<span><b>speaker</b>${row.speaking ? row.speaker_dbfs + " dBFS" : "quiet"}</span>`, x.ducked ? `<span class="warn">ducked</span>` : "", x.listening ? `<span class="ok">hearing</span>` : "", `<span><b>DoA</b>${deg(row.doa_yaw)}</span>`, row.face ? `<span><b>face</b>x ${row.face.x}</span>` : ""].join("");
  }
  function tick() {
    if (!opened) return;
    if (chunk && !master.paused) { const t = master.currentTime; draw(t); setPoseAt(t); syncFollowers(false); }
    raf = requestAnimationFrame(tick);
  }

  // ---------------------------------------------------------------- tracks canvas
  function draw(t) {
    const w = canvas.clientWidth || 600, h = canvas.clientHeight || 170, dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    if (!chunk || !tracks) { g.fillStyle = token("--dim", "#8b93a7"); g.fillText("select a chunk", 10, 20); return; }
    const dur = Math.max(1, chunk.duration_s);
    const x = (s) => (s / dur) * w;
    const lane = (i, n = 5) => [8 + (i * (h - 16)) / n, (h - 16) / n - 4];
    // 1 + 2: peak envelopes
    const env = (name, i, color) => {
      const a = tracks.audio[name]; const [y, lh] = lane(i);
      g.fillStyle = token("--panel", "#171a21"); g.fillRect(0, y, w, lh);
      if (!a || !a.peaks.length) return;
      g.fillStyle = color;
      const bw = Math.max(1, w / a.peaks.length);
      a.peaks.forEach((p, k) => { const bh = Math.max(1, Math.pow(p, 0.6) * lh); g.fillRect(k * bw, y + (lh - bh) / 2, Math.max(0.8, bw - 0.3), bh); });
    };
    env("mic", 0, token("--ok", "#3fb950")); env("speaker", 1, token("--acc", "#58a6ff"));
    // 3: engagement state band from telemetry
    const [sy, sh] = lane(2);
    g.fillStyle = "rgba(139,147,167,.08)"; g.fillRect(0, sy, w, sh);
    const colors = { engaged: "#2f6f3a", speaking: "#8a5a12", sleeping: token("--line-2", "#30343c"), idle: null };
    let segStart = 0, segState = null;
    const flush = (end) => { if (segState && colors[segState]) { g.fillStyle = colors[segState]; g.fillRect(x(segStart), sy, Math.max(1, x(end) - x(segStart)), sh); } };
    for (const row of telemetry) { const s = (row.x && row.x.state) || row.state; const at = row.t - chunk.start_ts; if (s !== segState) { flush(at); segStart = at; segState = s; } }
    flush(dur);
    for (const row of telemetry) { if (row.x && row.x.ducked) { g.fillStyle = "#d29922"; g.fillRect(x(row.t - chunk.start_ts), sy + sh - 3, 1.5, 3); } }
    // 4: dialogue + decisions markers
    const [dy, dh] = lane(3);
    g.fillStyle = "rgba(139,147,167,.08)"; g.fillRect(0, dy, w, dh);
    for (const d of tracks.dialogue) { g.fillStyle = d.role === "user" ? "#d29922" : d.role === "assistant" ? "#58a6ff" : "#8b93a7"; const mh = d.role === "internal" || d.role === "tool" ? dh * 0.5 : dh; g.fillRect(x(d.at) - 1, dy + dh - mh, 2.5, mh); }
    for (const d of tracks.decisions) { if (d.decision === "reject") { g.fillStyle = "#f85149"; g.fillRect(x(d.at) - 0.5, dy, 1, dh * 0.4); } }
    // 5: perception events
    const [ey, eh] = lane(4);
    g.fillStyle = "rgba(139,147,167,.08)"; g.fillRect(0, ey, w, eh);
    for (const e of tracks.events) { g.fillStyle = "#b083f0"; g.beginPath(); g.moveTo(x(e.at), ey); g.lineTo(x(e.at) + 4, ey + eh); g.lineTo(x(e.at) - 4, ey + eh); g.fill(); }
    // minute grid + cursor
    g.strokeStyle = token("--line-2", "#8b93a7"); g.beginPath();
    for (let m = 60; m < dur; m += 60) { g.moveTo(x(m), 0); g.lineTo(x(m), h); }
    g.stroke();
    g.strokeStyle = token("--fg", "#fff"); g.lineWidth = 1.5; g.beginPath(); g.moveTo(x(t), 0); g.lineTo(x(t), h); g.stroke(); g.lineWidth = 1;
    g.fillStyle = token("--fg", "#e6e8ee"); g.font = "11px sans-serif"; g.fillText(`${mmss(t)} / ${mmss(dur)} · ${clock(chunk.start_ts + t)}`, Math.min(w - 150, x(t) + 6), h - 4);
    $("rp-clock").textContent = `${clock(chunk.start_ts + t)} · ${mmss(t)} / ${mmss(dur)}`;
  }
  window.addEventListener("resize", () => { if (opened && chunk) draw(master.currentTime || 0); });
  window.SidekickReplay = { open: () => open().catch((e) => { console.warn(e); $("rp-summary").textContent = e.message; }), close, loadChunk };
  if ($("tab-record").classList.contains("active")) window.SidekickReplay.open();
})();
