/* sidekick dashboard — Banana's service (PLAN.md blocks #82–#87): the state pill by the name and
   its panel (Start, or Restart and Stop), the blocking start dialog that ticks every step and the
   module checks under it, toasts for what happens with no dialog open (a start at boot that
   failed), and the stopped look of the pages (Live's "Banana is stopped", runtime-only controls
   disabled). The state arrives with the 1 Hz health poll (dashboard_app.js calls `update`);
   while a start runs the dialog polls /api/service four times a second. A stop shows no dialog
   (the owner): the pill says stopping, then stopped. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const clock = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "–");
  const BY = { dashboard: "from the dashboard", boot: "when sidekick started", exit: "when sidekick closed", cli: "from the CLI" };
  const LABEL = { running: "Running", starting: "Starting…", stopping: "Stopping…", stopped: "Stopped" };
  const ICON = { pending: "○", running: "", ok: "✓", warn: "!", bad: "✗", skipped: "—" };
  let status = null, fast = null, dismissed = null, toasted = null, wasState = null, openedAt = 0;

  // ------------------------------------------------------------------ toasts
  function toast(text, level = "", link = null) {
    const box = $("toasts");
    const el = document.createElement("div");
    el.className = `toast ${level}`;
    el.innerHTML = `<span>${esc(text)}</span>${link ? `<a data-go="${esc(link)}">${esc(link)} →</a>` : ""}<button aria-label="dismiss">✕</button>`;
    el.querySelector("button").addEventListener("click", () => el.remove());
    el.addEventListener("click", (e) => { if (e.target.closest("a")) el.remove(); });
    box.appendChild(el);
    while (box.children.length > 4) box.firstElementChild.remove();
    if (level !== "bad") setTimeout(() => el.remove(), 8000);
  }

  // ------------------------------------------------------------------ requests
  async function act(action) {
    closePanel();
    try {
      const r = await fetch("/api/service", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action }) });
      const data = await r.json();
      if (!r.ok) { toast(data.detail || `${r.status}`, "warn"); return; }
      if (action !== "stop") openDialog(action === "restart" ? Date.now() / 1000 : 0);
      update(data);
    } catch (e) { toast(e.message, "bad"); }
  }
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-service-start]")) { e.preventDefault(); act("start"); }
    else if (e.target.closest("[data-service-restart]")) { e.preventDefault(); act("restart"); }
    else if (e.target.closest("[data-service-stop]")) { e.preventDefault(); act("stop"); }
  });

  // ------------------------------------------------------------------ the pill and its panel
  const tone = (s) => {
    if (!s) return "";
    if (s.state === "running") return "ok";
    if (s.state === "starting" || s.state === "stopping") return "warn";
    return s.transition && s.transition.action === "start" && s.transition.ok === false ? "bad" : "";
  };
  function sinceLine(s) {
    const t = s.transition;
    if (s.state === "starting" || s.state === "stopping") return `${s.state}… since ${clock(s.since)}`;
    const by = t ? BY[t.by] || t.by : "";
    if (s.state === "running") return `since ${clock(s.since)}${by ? " · started " + by : ""}`;
    if (s.state === "stopped") return t && t.action === "start" && t.ok === false ? `the start at ${clock(t.started_at)} failed` : `since ${clock(s.since)}${t && t.action === "stop" ? " · stopped " + (BY[t.by] || t.by) : ""}`;
    return t ? `${s.state} ${by}` : s.state;
  }
  function renderPanel() {
    const s = status, panel = $("power-panel");
    if (!s || panel.hidden) return;
    const t = s.transition, busy = s.busy || s.state === "starting" || s.state === "stopping";
    const failed = s.state === "stopped" && t && t.action === "start" && t.ok === false;
    panel.innerHTML = `<div class="ps"><i class="svc-dot ${tone(s)}"></i>${esc(LABEL[s.state] || s.state)}</div>
      <div class="pm">${esc(sinceLine(s))}${s.wanted === "stopped" && s.state === "stopped" ? "<br>Stays stopped when sidekick restarts." : ""}</div>
      ${failed ? `<div class="pe">${esc(t.error)}</div>` : ""}
      <div class="row">${s.state === "running" ? '<button data-service-restart>Restart</button><button data-service-stop>Stop</button>' : `<button class="primary" data-service-start ${busy ? "disabled" : ""}>${failed ? "Try again" : "Start"}</button>`}</div>`;
  }
  function placePanel() {  // above the control at the bottom of the module list (below it when there is no room)
    const btn = $("power-btn").getBoundingClientRect(), panel = $("power-panel");
    const above = btn.top - panel.offsetHeight - 8;
    panel.style.top = `${Math.round(above >= 8 ? above : btn.bottom + 8)}px`;
    panel.style.left = `${Math.round(Math.max(8, Math.min(btn.left, window.innerWidth - panel.offsetWidth - 16)))}px`;
  }
  function openPanel() { const panel = $("power-panel"); panel.hidden = false; $("power-btn").setAttribute("aria-expanded", "true"); renderPanel(); placePanel(); }
  function closePanel() { $("power-panel").hidden = true; $("power-btn").setAttribute("aria-expanded", "false"); }
  $("power-btn").addEventListener("click", (e) => { e.stopPropagation(); if ($("power-panel").hidden) openPanel(); else closePanel(); });
  document.addEventListener("click", (e) => { if (!e.target.closest("#power-panel") && !e.target.closest("#power-btn")) closePanel(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePanel(); });
  window.addEventListener("resize", () => { if (!$("power-panel").hidden) placePanel(); });

  // ------------------------------------------------------------------ the start dialog
  function stepRow(step) {
    const items = (step.items || []).map((it) => `<div class="it"><span class="s-${esc(it.level === "off" ? "skipped" : it.level)}">${ICON[it.level === "off" ? "skipped" : it.level] || "·"}</span><b>${esc(it.title)}</b><span>${esc(it.detail)}</span>${it.level === "bad" || it.level === "warn" ? `<a data-go="${esc(it.tab || step.tab)}">${esc(it.tab || step.tab)} →</a>` : ""}</div>`).join("");
    const ms = step.ms != null ? `${(step.ms / 1000).toFixed(1)} s` : "";
    return `<div class="step"><span class="si s-${esc(step.state)}">${ICON[step.state] ?? ""}</span><span><span class="st">${esc(step.title)}</span>${step.detail ? `<span class="sd">${esc(step.detail)}</span>` : ""}</span><span class="sm">${ms}</span>${items ? `<div class="items">${items}</div>` : ""}</div>`;
  }
  function renderDialog() {
    const s = status, t = s && s.transition;
    if (!t || t.action !== "start" || t.started_at < openedAt - 2) {  // a restart: stopping first
      $("start-title").textContent = "Restarting Banana";
      $("start-sub").textContent = "stopping first…";
      $("start-steps").innerHTML = "";
      $("start-error").hidden = true;
      $("start-ok").disabled = true;
      return;
    }
    const done = t.finished_at != null && !s.busy;
    const took = ((t.finished_at || Date.now() / 1000) - t.started_at).toFixed(1);
    $("start-title").textContent = !done ? "Starting Banana" : t.ok ? "Banana is running" : "Banana did not start";
    $("start-sub").textContent = `started ${clock(t.started_at)} ${BY[t.by] || t.by} · ${took} s`;
    $("start-steps").innerHTML = (t.steps || []).map(stepRow).join("");
    const err = $("start-error");
    err.hidden = !(done && !t.ok);
    err.textContent = done && !t.ok ? t.error : "";
    const ok = $("start-ok");
    ok.disabled = !done;
    ok.textContent = done && !t.ok ? "Close" : "OK";
  }
  async function pollFast() {
    try {
      const r = await fetch("/api/service");
      if (r.ok) update(await r.json());
    } catch (e) { /* the 1 Hz health poll carries on */ }
    const t = status && status.transition;
    if ($("start-sheet").open && t && (status.busy || t.finished_at == null)) fast = setTimeout(pollFast, 250);
    else fast = null;
  }
  function openDialog(since = 0) {
    const sheet = $("start-sheet");
    if (!sheet.open) { openedAt = since; sheet.showModal(); }
    renderDialog();
    clearTimeout(fast);
    fast = setTimeout(pollFast, 150);
  }
  $("start-sheet").addEventListener("cancel", (e) => { if ($("start-ok").disabled) e.preventDefault(); });  // blocking while it runs
  $("start-ok").addEventListener("click", () => { const t = status && status.transition; dismissed = t ? t.started_at : null; toasted = dismissed; $("start-sheet").close(); });
  $("start-sheet").addEventListener("click", (e) => { if (e.target.closest("[data-go]") && !$("start-ok").disabled) { const t = status && status.transition; dismissed = t ? t.started_at : null; toasted = dismissed; $("start-sheet").close(); } });

  // ------------------------------------------------------------------ the pages
  function renderPages(s) {
    const t = s.transition, stopped = s.state === "stopped" || s.state === "stopping";
    const failed = s.state === "stopped" && t && t.action === "start" && t.ok === false;
    $("power-dot").className = `pd ${tone(s)}`;
    $("menu-power-dot").className = `pd ${tone(s)}`;
    $("power-label").textContent = failed ? "Stopped · failed" : LABEL[s.state] || s.state;
    $("power-sub").textContent = s.state === "running" || s.state === "stopped" ? (failed ? "the last start failed" : `since ${clock(s.since)}`) : "";
    const card = $("live-stopped");
    card.hidden = !stopped;
    if (stopped) {
      card.querySelector("b").textContent = s.state === "stopping" ? "Banana is stopping…" : "Banana is stopped";
      card.querySelector("[data-service-start]").disabled = s.state === "stopping";
      $("live-stopped-dot").className = `svc-dot ${tone(s)}`;
      $("live-stopped-sub").textContent = sinceLine(s);
      $("live-stopped-err").hidden = !failed;
      $("live-stopped-err").textContent = failed ? t.error : "";
    }
    $("service-dot").className = `svc-dot ${tone(s)}`;
    $("service-line").textContent = failed ? "Stopped · the last start failed" : LABEL[s.state] || s.state;
    $("service-when").textContent = sinceLine(s);
    const kv = [["remembered", s.wanted === "running" ? "running (starts with sidekick)" : "stopped (stays stopped)"]];
    if (t) kv.push([`last ${t.action}`, `${clock(t.started_at)} · ${t.finished_at ? ((t.finished_at - t.started_at).toFixed(1) + " s") : "running"}${t.ok === false ? " · " + esc(t.error) : ""}`]);
    $("service-kv").innerHTML = kv.map(([k, v]) => `<div>${k}</div><div class="${k.startsWith("last") && t && t.ok === false ? "bad" : ""}">${v}</div>`).join("");
    const busy = s.busy || s.state === "starting" || s.state === "stopping";
    document.querySelectorAll("#service-card [data-service-start]").forEach((b) => { b.hidden = s.state === "running"; b.disabled = busy; });
    document.querySelectorAll("#service-card [data-service-restart], #service-card [data-service-stop]").forEach((b) => { b.hidden = s.state !== "running"; b.disabled = busy; });
    // runtime-only controls: off while Banana is stopped; given back exactly as found
    document.querySelectorAll("[data-needs-service]").forEach((el) => {
      if (s.state !== "running") { if (!el.disabled) { el.disabled = true; el.dataset.svcOff = "1"; el.title = "Banana is stopped"; } }
      else if (el.dataset.svcOff) { el.disabled = false; delete el.dataset.svcOff; el.removeAttribute("title"); }
    });
  }

  function update(s) {
    if (!s) return;
    const before = status;
    status = s;
    renderPages(s);
    renderPanel();
    const t = s.transition;
    // a start running that this page did not ask for (sidekick starting, another page): show it
    if (s.state === "starting" && t && t.action === "start" && t.started_at !== dismissed && !$("start-sheet").open) openDialog();
    if ($("start-sheet").open) renderDialog();
    // a start that failed while no dialog was open: say so once
    if (t && t.action === "start" && t.ok === false && t.finished_at && !$("start-sheet").open && toasted !== t.started_at) {
      toasted = t.started_at;
      const bad = (t.steps || []).flatMap((x) => (x.items || []).map((it) => ({ ...it, tab: it.tab || x.tab }))).find((it) => it.level === "bad");
      toast(`Banana did not start: ${t.error}`, "bad", bad ? bad.tab : "system");
    }
    if (s.state === "running" && before && wasState !== "running" && window.SidekickLive && window.SidekickLive.reloadCamera) window.SidekickLive.reloadCamera();
    wasState = s.state;
  }

  window.SidekickService = { update, toast, state: () => (status ? status.state : null), running: () => !!status && status.state === "running" };
  fetch("/api/service").then((r) => (r.ok ? r.json() : null)).then((s) => { if (s) update(s); }).catch(() => {});
})();
