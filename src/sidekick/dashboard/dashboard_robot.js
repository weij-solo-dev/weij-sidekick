/* sidekick dashboard — Body page: the controller that takes the body over through /api/robot/*
   (sliders for head / height / body yaw / antennas, gestures), the Expressions card
   (Banana's own library by kind, with an intensity and a thinking preview; /api/body/express
   plays by hand while the controller holds the body) plus the capability tests: microphone
   capture, speaker tone / sweep / replay, say text, camera snapshot, video clip. The live data
   comes from dashboard_live.js; this script subscribes to it for the level labels. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, d = 0) => (v === null || v === undefined ? "–" : typeof v === "number" ? v.toFixed(d) : String(v));
  const rad = (d) => d * Math.PI / 180;
  const api = async (path, opts) => {
    const r = await fetch(path, opts);
    if (!r.ok) { let msg = `${r.status}`; try { msg = (await r.json()).detail || msg; } catch (e) {} throw new Error(msg); }
    return r.json();
  };
  const post = (path, body) => api(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) });
  const kv = (el, pairs) => { el.innerHTML = pairs.map(([k, v, cls]) => `<div>${k}</div><div class="${cls || ""}">${v}</div>`).join(""); };

  // ---------------------------------------------------------------- levels from the rail's feed
  function render(f) {
    const b = f.body;
    if (!b) return;
    $("rb-mic-level").textContent = `${fmt(b.mic_dbfs, 1)} dBFS`;
    $("rb-spk-level").textContent = b.speaking ? `${fmt(b.speaker_dbfs, 1)} dBFS` : "quiet";
  }
  if (window.SidekickLive && window.SidekickLive.subscribe) window.SidekickLive.subscribe(render);

  // ---------------------------------------------------------------- controller
  let status = null;
  const sliders = [...document.querySelectorAll("#rb-sliders input[type=range]")];
  const controls = [$("rb-release"), $("rb-centre"), ...document.querySelectorAll("[data-gesture]")];
  function setHeld(held) {
    $("rb-hold").textContent = held ? "held" : "released";
    $("rb-hold").className = `pill ${held ? "held" : "free"}`;
    $("rb-sliders").classList.toggle("off", !held);
    $("rb-take").disabled = held;
    controls.forEach((el) => { el.disabled = !held; });
  }
  function applyStatus(s) {
    status = s;
    setHeld(!!s.held);
    $("rb-control-result").textContent = s.held ? `${s.dropped || 0} agent command(s) dropped` : s.video_encoder ? `video: ${s.video_encoder}` : "";
  }
  async function refresh() { try { applyStatus(await api("/api/robot")); } catch (e) { $("rb-control-result").textContent = e.message; } }
  $("rb-take").addEventListener("click", async () => {
    $("rb-control-result").textContent = "taking…";
    try { applyStatus(await post("/api/robot/control", { held: true })); resetSliders(); sendPose(true); } catch (e) { $("rb-control-result").textContent = e.message; }
  });
  $("rb-release").addEventListener("click", async () => {
    try { applyStatus(await post("/api/robot/control", { held: false })); resetSliders(); } catch (e) { $("rb-control-result").textContent = e.message; }
  });

  const values = () => Object.fromEntries(sliders.map((s) => [s.dataset.pose, Number(s.value)]));
  const label = (s) => { const v = Number(s.value); s.nextElementSibling.textContent = s.dataset.pose === "z" ? `${v} mm` : `${v}°`; };
  function resetSliders() { sliders.forEach((s) => { s.value = s.dataset.pose === "ant_r" ? -10 : s.dataset.pose === "ant_l" ? 10 : 0; label(s); }); }
  let poseTimer = null, poseDirty = false;
  async function sendPose(now) {
    poseDirty = true;
    if (poseTimer && !now) return;
    const flush = async () => {
      poseTimer = null;
      if (!poseDirty || !status || !status.held) return;
      poseDirty = false;
      const v = values();
      try {
        await post("/api/robot/pose", { yaw: rad(v.yaw), pitch: rad(v.pitch), roll: rad(v.roll), z: v.z / 1000, body_yaw: rad(v.body_yaw), antennas: [rad(v.ant_r), rad(v.ant_l)], duration_s: 0.3 });
        $("rb-motion-result").textContent = "";
      } catch (e) { $("rb-motion-result").textContent = e.message; }
      if (poseDirty) poseTimer = setTimeout(flush, 100);
    };
    if (now) await flush(); else poseTimer = setTimeout(flush, 100);
  }
  sliders.forEach((s) => { label(s); s.addEventListener("input", () => { label(s); sendPose(false); }); });
  $("rb-centre").addEventListener("click", () => { resetSliders(); sendPose(true); });
  document.querySelectorAll("[data-gesture]").forEach((b) => b.addEventListener("click", async () => { try { await post("/api/robot/gesture", { name: b.dataset.gesture }); $("rb-motion-result").textContent = `${b.dataset.gesture}`; } catch (e) { $("rb-motion-result").textContent = e.message; } }));

  // ---------------------------------------------------------------- expressions
  const KINDS = [["beat", "Beats", "small conversational motions"], ["emotion", "Emotions", "only for a real feeling"], ["performance", "Performances", "long, never mid-reply"]];
  const intensity = () => Number($("expr-intensity").value);
  $("expr-intensity").addEventListener("input", () => { $("expr-intensity-out").textContent = intensity().toFixed(1); });
  async function loadExpressions() {
    let list = [];
    try { list = await api("/api/body/expressions"); } catch (e) { $("expr-result").textContent = e.message; return; }
    $("expr-groups").innerHTML = KINDS.map(([kind, title, note]) => {
      const items = list.filter((x) => x.kind === kind);
      if (!items.length) return "";
      return `<div class="expr-group"><h4>${title}<small>${items.length} · ${note}</small></h4><div class="expr-list">${items.map((x) => `<button data-expr="${esc(x.name)}" title="${esc(x.description)} (${x.duration} s${x.aliases.length ? " · " + esc(x.aliases.join(", ")) : ""})">${esc(x.name.replace(/_/g, " "))}</button>`).join("")}</div></div>`;
    }).join("");
    document.querySelectorAll("[data-expr]").forEach((b) => b.addEventListener("click", async () => {
      const name = b.dataset.expr;
      try {
        const r = await post("/api/body/express", { name, intensity: intensity() });
        $("expr-result").textContent = r.ok ? `playing ${name} ×${intensity().toFixed(1)}` : `unknown ${name}`;
        b.classList.add("playing"); setTimeout(() => b.classList.remove("playing"), 1500);
      } catch (e) { $("expr-result").textContent = e.message; }
    }));
  }
  $("expr-think").addEventListener("click", async () => {
    try { await post("/api/body/state", { name: "think", seconds: 6 }); $("expr-result").textContent = "thinking for 6 s…"; } catch (e) { $("expr-result").textContent = e.message; }
  });
  loadExpressions();

  // ---------------------------------------------------------------- tests
  $("rb-mic").addEventListener("click", async () => {
    $("rb-mic").disabled = true; $("rb-mic-result").textContent = `recording ${$("rb-mic-s").value} s…`;
    try {
      const r = await post("/api/robot/test/mic", { seconds: Number($("rb-mic-s").value) });
      if (!r.ok) throw new Error(r.error);
      $("rb-mic-result").innerHTML = `${r.seconds} s · peak <b>${r.peak_dbfs} dBFS</b> · rms ${r.rms_dbfs} dBFS${r.clipped ? ' · <span class="bad">clipped</span>' : ""}`;
      const a = $("rb-mic-audio"); a.src = `${r.url}?t=${Date.now()}`; a.style.display = "block";
    } catch (e) { $("rb-mic-result").textContent = e.message; }
    $("rb-mic").disabled = false;
  });
  document.querySelectorAll("[data-spk]").forEach((b) => b.addEventListener("click", async () => {
    $("rb-spk-result").textContent = "playing…";
    try {
      const r = await post("/api/robot/test/speaker", { kind: b.dataset.spk, seconds: b.dataset.spk === "sweep" ? 3 : 1, freq: 440 });
      if (!r.ok) throw new Error(r.error);
      $("rb-spk-result").textContent = `${r.kind} ${r.seconds} s · first push ${r.first_push_s != null ? (r.first_push_s * 1000).toFixed(0) + " ms" : "–"} · done in ${r.played_in_s} s`;
    } catch (e) { $("rb-spk-result").textContent = e.message; }
  }));
  $("rb-snap").addEventListener("click", async () => {
    $("rb-cam-result").textContent = "capturing…";
    try {
      const r = await post("/api/robot/test/snapshot");
      if (!r.ok) throw new Error(r.error);
      $("rb-cam-result").textContent = `${r.width}×${r.height} · ${(r.bytes / 1024).toFixed(0)} KB`;
      $("rb-media").innerHTML = `<img src="${r.url}?t=${Date.now()}" alt="snapshot"><small>${esc(r.file)}</small>`;
    } catch (e) { $("rb-cam-result").textContent = e.message; }
  });
  $("rb-video").addEventListener("click", async () => {
    const seconds = Number($("rb-video-s").value);
    $("rb-video").disabled = true; $("rb-cam-result").textContent = `recording ${seconds} s…`;
    try {
      const r = await post("/api/robot/test/video", { seconds });
      if (!r.ok) throw new Error(r.error || "video failed");
      $("rb-cam-result").textContent = `${r.frames} frames · ${r.width}×${r.height} @ ${r.fps} fps · ${r.encoder} · ${(r.bytes / 1024).toFixed(0)} KB${r.mic_seconds != null ? ` · mic ${r.mic_seconds} s` : ""}`;
      $("rb-media").innerHTML = `<video src="${r.url}?t=${Date.now()}" controls playsinline></video>${r.mic_url ? `<audio src="${r.mic_url}?t=${Date.now()}" controls preload="none" style="width:100%;margin-top:6px"></audio>` : ""}<small>${esc(r.file)}</small>`;
    } catch (e) { $("rb-cam-result").textContent = e.message; }
    $("rb-video").disabled = false;
  });

  // ---------------------------------------------------------------- lifecycle
  function start() { refresh(); }
  function stop() {}
  window.SidekickRobot = { start, stop, refresh };
  if ($("tab-body").classList.contains("active")) start();
})();
