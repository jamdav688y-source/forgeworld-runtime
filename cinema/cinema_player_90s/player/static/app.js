// ForgeWorld Cinema Player -- vanilla JS, no CDN, no build step, no
// internet dependency. <video controls> provides native play/pause/seek/
// volume/mute/fullscreen; the buttons below add the mission-specific
// controls (aspect select, folder/report access, alerts, render control).

const spec = JSON.parse(document.getElementById("spec-data").textContent);
const video = document.getElementById("video");
const modalRoot = document.getElementById("modal-root");
let currentAspect = "16x9";

function escapeHtml(s) {
  return (s === undefined || s === null ? "" : String(s)).replace(
    /[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

function openModal(html) {
  modalRoot.innerHTML = `<div class="modal-overlay"><div class="modal-box">${html}<div style="margin-top:0.6rem;"><button class="btn secondary" id="modal-close">Close</button></div></div></div>`;
  document.getElementById("modal-close").addEventListener("click", () => { modalRoot.innerHTML = ""; });
}

function loadAspect(aspect, kind = "master") {
  currentAspect = aspect;
  video.src = `/media/${kind}/${aspect}`;
}

document.getElementById("btn-16x9").addEventListener("click", () => loadAspect("16x9"));
document.getElementById("btn-4x5").addEventListener("click", () => loadAspect("4x5"));
document.getElementById("btn-replay").addEventListener("click", () => { video.currentTime = 0; video.play(); });
document.getElementById("btn-fullscreen").addEventListener("click", () => {
  if (video.requestFullscreen) video.requestFullscreen();
});

document.getElementById("btn-folder").addEventListener("click", async () => {
  try {
    const data = await api("/api/release_folder");
    openModal(`<h3>Release Folder</h3><div class="muted">${escapeHtml(data.path)}</div><pre>${data.entries.map(escapeHtml).join("\n") || "(empty)"}</pre>`);
  } catch (err) {
    openModal(`<h3>Release Folder</h3><pre>${escapeHtml(err.message)}</pre>`);
  }
});

document.getElementById("btn-validation").addEventListener("click", async () => {
  try {
    const data = await api("/api/validation_report");
    openModal(`<h3>Validation Report</h3><pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`);
  } catch (err) {
    openModal(`<h3>Validation Report</h3><pre>${escapeHtml(err.message)}</pre>`);
  }
});

document.getElementById("btn-review").addEventListener("click", async () => {
  try {
    const data = await api("/api/artistic_review");
    openModal(`<h3>Artistic Review</h3><pre>${escapeHtml(data.content)}</pre>`);
  } catch (err) {
    openModal(`<h3>Artistic Review</h3><pre>${escapeHtml(err.message)}</pre>`);
  }
});

document.getElementById("btn-alerts").addEventListener("click", async () => {
  const alerts = await api("/api/alerts");
  const rows = alerts.map((a) => `
    <div class="alert-row">
      <span class="badge ${a.alert_class === 'BLOCKING' ? 'err' : a.alert_class === 'ACTIVE_WARNING' ? 'warn' : 'ok'}">${escapeHtml(a.alert_class)}</span>
      <strong>${escapeHtml(a.code)}</strong> (${escapeHtml(a.source)}) -- ${escapeHtml(a.state)}<br>
      <span class="muted">${escapeHtml(a.message)}</span>
      ${a.state === "PRESENTED" ? `<div><button class="btn secondary ack-btn" data-id="${a.id}">Acknowledge</button></div>` : ""}
    </div>
  `).join("") || "<div class='muted'>No active alerts.</div>";
  openModal(`<h3>Alerts (${alerts.length} active)</h3>${rows}`);
  document.querySelectorAll(".ack-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      await api(`/api/alerts/${b.dataset.id}/acknowledge`, { method: "POST", body: JSON.stringify({ by: "operator" }) });
      document.getElementById("btn-alerts").click();
    });
  });
});

document.getElementById("btn-preview").addEventListener("click", () => loadAspect(currentAspect, "preview"));

document.getElementById("btn-resume").addEventListener("click", async () => {
  openModal("<h3>Resume Render</h3><div class='muted'>Rendering... this may take a while.</div>");
  try {
    const result = await api("/api/render/resume", { method: "POST", body: JSON.stringify({ aspect: currentAspect }) });
    openModal(`<h3>Resume Render</h3><pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre>`);
  } catch (err) {
    openModal(`<h3>Resume Render</h3><pre>${escapeHtml(err.message)}</pre>`);
  }
});

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    document.getElementById("status-body").innerHTML = `
      <div class="kv"><span>Active film</span><span>${escapeHtml(s.active_film)}</span></div>
      <div class="kv"><span>Target FPS</span><span>${s.target_fps}</span></div>
      <div class="kv"><span>16:9</span><span>${escapeHtml(s.resolutions["16x9"])} ${s.masters_present["16x9"] ? "✓" : "missing"}</span></div>
      <div class="kv"><span>4:5</span><span>${escapeHtml(s.resolutions["4x5"])} ${s.masters_present["4x5"] ? "✓" : "missing"}</span></div>
      <div class="kv"><span>Render in progress</span><span>${s.render_in_progress}</span></div>
      <div class="kv"><span>Validation</span><span class="badge ${s.validation_status === 'PASS' ? 'ok' : s.validation_status === 'FAIL' ? 'err' : 'warn'}">${escapeHtml(s.validation_status)}</span></div>
      <div class="kv"><span>Free storage</span><span>${(s.free_storage_bytes / 1e9).toFixed(1)} GB</span></div>
      <div class="kv"><span>Active alerts</span><span>${s.active_alerts}</span></div>
      <div class="kv"><span>Blocking alerts</span><span class="badge ${s.blocking_alerts > 0 ? 'err' : 'ok'}">${s.blocking_alerts}</span></div>
      <div class="kv"><span>Release readiness</span><span class="badge ${s.release_readiness ? 'ok' : 'warn'}">${s.release_readiness}</span></div>
      <div class="kv"><span>Playback position</span><span id="pos-readout">0.0s</span></div>
      <div class="kv"><span>Active scene</span><span id="scene-readout">-</span></div>
    `;
  } catch (err) {
    document.getElementById("status-body").innerHTML = `<div class="muted">status unavailable: ${escapeHtml(err.message)}</div>`;
  }
}

video.addEventListener("timeupdate", () => {
  const posEl = document.getElementById("pos-readout");
  const sceneEl = document.getElementById("scene-readout");
  if (!posEl) return;
  posEl.textContent = video.currentTime.toFixed(1) + "s";
  const frame = Math.floor(video.currentTime * spec.fps.num);
  const scene = spec.scenes.find((s) => frame >= s.start_s * spec.fps.num && frame < s.end_s * spec.fps.num);
  if (sceneEl) sceneEl.textContent = scene ? `${scene.index}/9 -- ${scene.name}` : "-";
});

loadAspect("16x9");
refreshStatus();
setInterval(refreshStatus, 5000);
