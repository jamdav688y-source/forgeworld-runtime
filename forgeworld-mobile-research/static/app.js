// ForgeWorld Mobile Research Companion -- single-shell client.
// All navigation happens inside this one page (tabs/modals). No new windows.

const view = document.getElementById("view");
const modalRoot = document.getElementById("modal-root");
const tabs = document.querySelectorAll(".tab");

let selectedIds = new Set();

function escapeHtml(s) {
  return (s === undefined || s === null ? "" : String(s)).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  if (!res.ok) {
    let message = `${res.status}`;
    try {
      const body = await res.json();
      message = body.error ? `${res.status}: ${body.error}` : `${res.status}: ${await res.text()}`;
    } catch (_) {
      message = `${res.status}: ${await res.text().catch(() => res.statusText)}`;
    }
    throw new Error(message);
  }
  return res.json();
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function closeModal() { modalRoot.innerHTML = ""; }

function openModal(innerHtml) {
  modalRoot.innerHTML = "";
  const overlay = el(`<div class="modal-overlay"><div class="modal-box">${innerHtml}</div></div>`);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeModal(); });
  modalRoot.appendChild(overlay);
}

// Wrap a click handler so a failed request always surfaces a visible
// message instead of failing silently -- alert() is intentionally blunt
// here (no toast system in this MVP shell) but every guarded action now
// reports something to the operator.
function guarded(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (err) {
      console.error(err);
      alert(`Action failed: ${err.message}`);
    }
  };
}

// ---------------------------------------------------------------- router --

const routes = {
  dashboard: renderDashboard,
  library: renderLibrary,
  search: renderSearch,
  collections: renderCollections,
  promptlab: renderPromptLab,
  ingestion: renderIngestion,
  settings: renderSettings,
  status: renderStatus,
};

function activateTab(name) {
  tabs.forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  view.innerHTML = "<p class='muted'>Loading...</p>";
  routes[name]().catch((err) => {
    view.innerHTML = `<div class="card error-text">Failed to load: ${escapeHtml(err.message)}</div>`;
  });
}

tabs.forEach((t) => t.addEventListener("click", () => activateTab(t.dataset.tab)));

// ------------------------------------------------------------- dashboard --

async function renderDashboard() {
  const d = await api("/api/dashboard");
  view.innerHTML = `
    <div class="card">
      <h2>Dashboard</h2>
      <div class="grid-stats">
        ${stat(d.total_screenshots, "Total")}
        ${stat(d.processed_screenshots, "Processed")}
        ${stat(d.pending_screenshots, "Pending")}
        ${stat(d.ocr_failures, "OCR Failures")}
        ${stat(d.new_today, "New Today")}
        ${stat(fmtBytes(d.database_size_bytes), "DB Size")}
        ${stat(fmtBytes(d.free_storage_bytes), "Free Storage")}
      </div>
    </div>
    <div class="card">
      <h3>Top Topics</h3>
      ${d.top_topics.map((t) => `<span class="badge">${escapeHtml(t.name)} (${t.c})</span>`).join("") || "<span class='muted'>none yet</span>"}
      <h3>Top Entities</h3>
      ${d.top_entities.map((t) => `<span class="badge">${escapeHtml(t.name)} (${escapeHtml(t.entity_type)})</span>`).join("") || "<span class='muted'>none yet</span>"}
      <h3>Recent Collections</h3>
      ${d.recent_collections.map((c) => `<div>${escapeHtml(c.name)}</div>`).join("") || "<span class='muted'>none yet</span>"}
      <h3>Last Scan</h3>
      <div class="muted">${d.last_scan ? escapeHtml(d.last_scan.message) + " -- " + escapeHtml(d.last_scan.created_at) : "no scans yet"}</div>
    </div>
  `;
}

function stat(num, label) {
  return `<div class="stat"><div class="num">${escapeHtml(num)}</div><div class="label">${escapeHtml(label)}</div></div>`;
}

function fmtBytes(n) {
  if (n === undefined || n === null) return "?";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)}${units[i]}`;
}

// --------------------------------------------------------------- library --

async function renderLibrary() {
  const data = await api("/api/library?limit=60");
  view.innerHTML = `
    <div class="card">
      <h2>Library</h2>
      <div class="muted">${data.total} screenshot(s)</div>
      <div class="grid-library" id="lib-grid"></div>
    </div>
  `;
  const grid = document.getElementById("lib-grid");
  data.items.forEach((item) => {
    const card = el(`
      <div class="thumb" data-id="${item.id}">
        <img loading="lazy" src="${escapeHtml(item.preview_path)}" onerror="this.style.opacity=0.15" />
        <div class="meta">
          <div class="title">${escapeHtml(item.title || item.filename)}</div>
          <span class="badge">${escapeHtml(item.content_type)}</span>
          <span class="badge ${item.processing_status === "PROCESSED" ? "ok" : "warn"}">${escapeHtml(item.processing_status)}</span>
        </div>
      </div>
    `);
    card.addEventListener("click", guarded(() => openScreenshotDetail(item.id)));
    grid.appendChild(card);
  });
}

async function openScreenshotDetail(id) {
  const d = await api(`/api/screenshots/${id}`);
  openModal(`
    <h2>${escapeHtml(d.title || d.filename)}</h2>
    <img class="detail-image" src="${escapeHtml(d.preview_path)}" onerror="this.style.display='none'" />
    <div class="section-label">Source</div>
    <div class="muted">path: ${escapeHtml(d.original_path)}<br>sha256: ${escapeHtml(d.sha256)}<br>status: ${escapeHtml(d.processing_status)}</div>

    <div class="section-label">Raw OCR</div>
    <pre class="prompt-output">${escapeHtml(d.raw_ocr_text || "(none)")}</pre>

    <div class="section-label">Corrected OCR</div>
    <textarea id="ocr-correction" rows="4">${escapeHtml(d.corrected_ocr_text || "")}</textarea>
    <div class="row" style="margin-top:0.4rem;">
      <button class="btn secondary" id="save-correction">Save Correction</button>
      <button class="btn secondary" id="rerun-ocr">Rerun OCR</button>
      <button class="btn secondary" id="mark-unusable">Mark Unusable</button>
    </div>

    <div class="section-label">Tags</div>
    ${d.tags.map((t) => `<span class="badge" title="${escapeHtml(t.rationale || "")}">${escapeHtml(t.name)} (${(t.confidence*1).toFixed(2)})</span>`).join("") || "<span class='muted'>none</span>"}

    <div class="section-label">Entities</div>
    ${d.entities.map((e) => `<span class="badge">${escapeHtml(e.name)} (${escapeHtml(e.entity_type)})</span>`).join("") || "<span class='muted'>none</span>"}

    <div class="section-label">System Summary</div>
    <div class="muted">${escapeHtml(d.summary || "(none)")}</div>

    <div class="section-label">Notes</div>
    <div id="notes-list">${d.notes.map((n) => `<div class="card">${escapeHtml(n.body)}<div class="muted">${escapeHtml(n.created_at)}</div></div>`).join("") || "<span class='muted'>no notes</span>"}</div>
    <textarea id="new-note" rows="2" placeholder="Add a note..."></textarea>
    <button class="btn secondary" id="add-note">Add Note</button>

    <div class="row" style="margin-top:0.6rem;">
      <button class="btn" id="select-for-prompt">Add to Prompt/Export Selection</button>
      <button class="btn secondary" id="close-modal">Close</button>
    </div>
  `);

  document.getElementById("close-modal").addEventListener("click", closeModal);
  document.getElementById("save-correction").addEventListener("click", guarded(async () => {
    const text = document.getElementById("ocr-correction").value;
    await api(`/api/screenshots/${id}/ocr/correct`, { method: "POST", body: JSON.stringify({ corrected_text: text }) });
    openScreenshotDetail(id);
  }));
  document.getElementById("rerun-ocr").addEventListener("click", guarded(async () => {
    await api(`/api/screenshots/${id}/ocr/rerun`, { method: "POST" });
    openScreenshotDetail(id);
  }));
  document.getElementById("mark-unusable").addEventListener("click", guarded(async () => {
    await api(`/api/screenshots/${id}/ocr/unusable`, { method: "POST" });
    openScreenshotDetail(id);
  }));
  document.getElementById("add-note").addEventListener("click", guarded(async () => {
    const body = document.getElementById("new-note").value.trim();
    if (!body) return;
    await api(`/api/screenshots/${id}/notes`, { method: "POST", body: JSON.stringify({ body }) });
    openScreenshotDetail(id);
  }));
  document.getElementById("select-for-prompt").addEventListener("click", () => {
    selectedIds.add(id);
    alert(`Added source ${id} to selection (${selectedIds.size} selected). Open Prompt Lab to generate.`);
  });
}

// ---------------------------------------------------------------- search --

async function renderSearch() {
  view.innerHTML = `
    <div class="card">
      <h2>Search</h2>
      <div class="row">
        <input id="search-q" placeholder="keywords or &quot;phrase&quot;" style="flex:1;" />
        <select id="search-sort">
          <option value="relevance">Relevance</option>
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
        </select>
        <button class="btn" id="search-go">Search</button>
      </div>
      <div class="row" style="margin-top:0.4rem;">
        <input id="search-tags" placeholder="tags (comma separated)" />
        <input id="search-content-types" placeholder="content types (comma separated)" />
        <input id="search-min-conf" placeholder="min confidence" style="width:110px;" />
      </div>
    </div>
    <div id="search-results"></div>
  `;
  document.getElementById("search-go").addEventListener("click", guarded(runSearch));
  document.getElementById("search-q").addEventListener("keydown", (e) => { if (e.key === "Enter") guarded(runSearch)(); });
}

async function runSearch() {
  const q = document.getElementById("search-q").value;
  const sort = document.getElementById("search-sort").value;
  const tags = document.getElementById("search-tags").value;
  const contentTypes = document.getElementById("search-content-types").value;
  const minConf = document.getElementById("search-min-conf").value;
  const params = new URLSearchParams({ q, sort, tags, content_types: contentTypes });
  if (minConf) params.set("min_confidence", minConf);
  const results = document.getElementById("search-results");
  results.innerHTML = "<p class='muted'>Searching...</p>";
  let data;
  try {
    data = await api(`/api/search?${params.toString()}`);
  } catch (err) {
    results.innerHTML = `<div class="card error-text">Search failed: ${escapeHtml(err.message)}</div>`;
    return;
  }
  results.innerHTML = data.results.map((r) => `
    <div class="card result-card" data-id="${r.id}">
      <img src="${escapeHtml(r.preview_path)}" onerror="this.style.opacity=0.15" />
      <div>
        <div><strong>${escapeHtml(r.title || r.filename)}</strong></div>
        <div class="muted">${escapeHtml(r.source_platform || "")} ${escapeHtml(r.discovered_at || "")}</div>
        <div>${(r.top_tags || []).map((t) => `<span class="badge">${escapeHtml(t.name)}</span>`).join("")}</div>
        <div class="excerpt">${escapeHtml(r.excerpt || "")}</div>
        <span class="badge ${r.processing_status === "PROCESSED" ? "ok" : "warn"}">${escapeHtml(r.processing_status)}</span>
      </div>
    </div>
  `).join("") || "<p class='muted'>No results.</p>";
  results.querySelectorAll(".result-card").forEach((c) => {
    c.addEventListener("click", guarded(() => openScreenshotDetail(parseInt(c.dataset.id, 10))));
  });
}

// ------------------------------------------------------------ collections -

async function renderCollections() {
  const cols = await api("/api/collections");
  view.innerHTML = `
    <div class="card">
      <h2>Collections</h2>
      <div class="row">
        <input id="new-collection-name" placeholder="new collection name" />
        <button class="btn" id="create-collection">Create</button>
      </div>
    </div>
    <div id="collections-list"></div>
  `;
  document.getElementById("create-collection").addEventListener("click", guarded(async () => {
    const name = document.getElementById("new-collection-name").value.trim();
    if (!name) return;
    await api("/api/collections", { method: "POST", body: JSON.stringify({ name }) });
    renderCollections();
  }));
  const list = document.getElementById("collections-list");
  list.innerHTML = cols.map((c) => `
    <div class="card">
      <div class="row" style="justify-content:space-between;">
        <strong>${escapeHtml(c.name)}</strong>
        <span class="muted">${c.item_count} item(s)</span>
      </div>
      <div class="row" style="margin-top:0.4rem;">
        <button class="btn secondary" data-view="${c.id}">View</button>
        <button class="btn secondary" data-add="${c.id}">Add Selection (${selectedIds.size})</button>
        <button class="btn secondary" data-export="${c.id}">Export Markdown</button>
      </div>
    </div>
  `).join("") || "<p class='muted'>No collections yet.</p>";

  list.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", guarded(() => viewCollection(b.dataset.view))));
  list.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", guarded(async () => {
    await api(`/api/collections/${b.dataset.add}/items`, {
      method: "POST",
      body: JSON.stringify({ action: "add", screenshot_ids: Array.from(selectedIds) }),
    });
    renderCollections();
  })));
  list.querySelectorAll("[data-export]").forEach((b) => b.addEventListener("click", guarded(async () => {
    const data = await api(`/api/exports/markdown?collection_id=${b.dataset.export}`);
    openModal(`<h2>Export</h2><pre class="prompt-output">${escapeHtml(data.content)}</pre><div class="muted">saved to ${escapeHtml(data.path)}</div><button class="btn secondary" id="close-modal">Close</button>`);
    document.getElementById("close-modal").addEventListener("click", closeModal);
  })));
}

async function viewCollection(id) {
  const c = await api(`/api/collections/${id}`);
  openModal(`
    <h2>${escapeHtml(c.name)}</h2>
    ${c.items.map((i) => `<div class="card">${escapeHtml(i.title || i.filename)} <span class="badge">${escapeHtml(i.content_type)}</span></div>`).join("") || "<p class='muted'>empty</p>"}
    <button class="btn secondary" id="close-modal">Close</button>
  `);
  document.getElementById("close-modal").addEventListener("click", closeModal);
}

// ------------------------------------------------------------- prompt lab -

async function renderPromptLab() {
  const modes = await api("/api/prompt_modes");
  const options = Object.entries(modes).map(([key, m]) => `<option value="${escapeHtml(key)}">${escapeHtml(m.label)}</option>`).join("");
  view.innerHTML = `
    <div class="card">
      <h2>Prompt Lab</h2>
      <div class="muted">Selected source IDs: ${escapeHtml(Array.from(selectedIds).join(", ")) || "(none -- open items in Library/Search and click 'Add to Prompt/Export Selection')"}</div>
      <div class="row" style="margin-top:0.4rem;">
        <input id="manual-ids" placeholder="or type comma-separated screenshot IDs" style="flex:1;" />
      </div>
      <select id="prompt-mode" style="margin-top:0.4rem;width:100%;">${options}</select>
      <textarea id="prompt-objective" rows="2" placeholder="Operator objective" style="margin-top:0.4rem;width:100%;"></textarea>
      <textarea id="prompt-instruction" rows="2" placeholder="Additional operator instruction (optional)" style="margin-top:0.4rem;width:100%;"></textarea>
      <button class="btn" id="generate-prompt" style="margin-top:0.4rem;">Generate Prompt</button>
      <button class="btn secondary" id="clear-selection">Clear Selection</button>
    </div>
    <div id="prompt-output-wrap"></div>
  `;
  document.getElementById("clear-selection").addEventListener("click", () => { selectedIds.clear(); renderPromptLab(); });
  document.getElementById("generate-prompt").addEventListener("click", async () => {
    const manual = document.getElementById("manual-ids").value;
    const ids = manual ? manual.split(",").map((s) => parseInt(s.trim(), 10)).filter(Boolean) : Array.from(selectedIds);
    const mode = document.getElementById("prompt-mode").value;
    const objective = document.getElementById("prompt-objective").value;
    const operator_instruction = document.getElementById("prompt-instruction").value;
    const outputWrap = document.getElementById("prompt-output-wrap");
    if (ids.length === 0) {
      outputWrap.innerHTML = `<div class="card error-text">No sources selected. Add IDs manually or select some from Library/Search first.</div>`;
      return;
    }
    try {
      const result = await api("/api/prompts/generate", {
        method: "POST",
        body: JSON.stringify({ mode, objective, operator_instruction, screenshot_ids: ids }),
      });
      outputWrap.innerHTML = `
        <div class="card">
          <h3>Generated Prompt</h3>
          <pre class="prompt-output" id="prompt-text">${escapeHtml(result.content)}</pre>
          <div class="row">
            <button class="btn secondary" id="copy-prompt">Copy Prompt</button>
            <button class="btn secondary" id="download-prompt">Download Markdown</button>
            <button class="btn secondary" id="save-template">Save as Template</button>
          </div>
        </div>
      `;
      document.getElementById("copy-prompt").addEventListener("click", () => {
        navigator.clipboard.writeText(result.content).then(
          () => alert("Copied to clipboard."),
          (err) => alert(`Copy failed: ${err.message}`)
        );
      });
      document.getElementById("download-prompt").addEventListener("click", () => {
        const blob = new Blob([result.content], { type: "text/markdown" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `prompt_${result.id}.md`;
        a.click();
      });
      document.getElementById("save-template").addEventListener("click", guarded(async () => {
        const name = prompt("Template name:");
        if (!name) return;
        await api(`/api/prompts/${result.id}/save_template`, { method: "POST", body: JSON.stringify({ name }) });
        alert("Saved as template.");
      }));
    } catch (err) {
      outputWrap.innerHTML = `<div class="card error-text">${escapeHtml(err.message)}</div>`;
    }
  });
}

// -------------------------------------------------------------- ingestion -

async function renderIngestion() {
  const sources = await api("/api/sources");
  const lastScan = await api("/api/scan/last");
  const scanStatus = await api("/api/scan/status");
  view.innerHTML = `
    <div class="card">
      <h2>Ingestion</h2>
      <div class="row">
        <button class="btn secondary" id="probe-sources">Probe Sources</button>
        <button class="btn" id="start-scan" ${scanStatus.scan_in_progress ? "disabled" : ""}>
          ${scanStatus.scan_in_progress ? "Scan running..." : "Start Scan"}
        </button>
      </div>
      <div id="sources-list" style="margin-top:0.6rem;"></div>
      <div class="row" style="margin-top:0.6rem;">
        <input id="new-source-path" placeholder="add a source path" style="flex:1;" />
        <button class="btn secondary" id="add-source">Add</button>
      </div>
    </div>
    <div class="card">
      <h3>Last Scan Result</h3>
      <div id="last-scan">${lastScan ? formatScan(lastScan) : "<span class='muted'>no scans yet</span>"}</div>
    </div>
  `;
  renderSourcesList(sources);

  document.getElementById("probe-sources").addEventListener("click", guarded(async () => {
    const updated = await api("/api/sources/probe", { method: "POST" });
    renderSourcesList(updated);
  }));
  document.getElementById("start-scan").addEventListener("click", async () => {
    const lastScanEl = document.getElementById("last-scan");
    lastScanEl.innerHTML = "<span class='muted'>scanning...</span>";
    try {
      const summary = await api("/api/scan", { method: "POST", body: JSON.stringify({}) });
      lastScanEl.innerHTML = formatScan(summary);
    } catch (err) {
      lastScanEl.innerHTML = `<span class="error-text">${escapeHtml(err.message)}</span>`;
    }
  });
  document.getElementById("add-source").addEventListener("click", guarded(async () => {
    const path = document.getElementById("new-source-path").value.trim();
    if (!path) return;
    await api("/api/sources", { method: "POST", body: JSON.stringify({ path }) });
    renderSourcesList(await api("/api/sources"));
  }));
}

function renderSourcesList(sources) {
  const container = document.getElementById("sources-list");
  container.innerHTML = sources.map((s) => `
    <div class="row" style="justify-content:space-between; padding:0.3rem 0; border-bottom:1px solid var(--border);">
      <div>
        <div>${escapeHtml(s.label)}</div>
        <div class="muted">${escapeHtml(s.path)}</div>
      </div>
      <div>
        <span class="badge ${s.exists ? "ok" : "err"}">${s.exists ? "found" : "not found"}</span>
        <label class="muted"><input type="checkbox" data-toggle="${escapeHtml(s.path)}" ${s.enabled ? "checked" : ""} /> enabled</label>
      </div>
    </div>
  `).join("");
  container.querySelectorAll("[data-toggle]").forEach((cb) => {
    cb.addEventListener("change", guarded(async () => {
      await api("/api/sources/update", { method: "POST", body: JSON.stringify({ path: cb.dataset.toggle, enabled: cb.checked }) });
    }));
  });
}

function formatScan(s) {
  const resumed = s.resumed_count ? ` resumed=${s.resumed_count}` : "";
  return `scanned=${s.scanned} new=${s.new_count}${resumed} duplicate=${s.duplicate_count} skipped=${s.skipped_count} errors=${s.error_count}<br><span class="muted">${escapeHtml(s.started_at)} -> ${escapeHtml(s.finished_at)}</span>`;
}

// --------------------------------------------------------------- settings -

async function renderSettings() {
  const s = await api("/api/settings");
  view.innerHTML = `
    <div class="card">
      <h2>Settings</h2>
      <div class="muted">Local-only. Cloud uploads and semantic search stay off until explicitly enabled here.</div>
      <div id="settings-form"></div>
      <div id="settings-error" class="error-text"></div>
      <button class="btn" id="save-settings" style="margin-top:0.6rem;">Save</button>
    </div>
  `;
  const boolKeys = ["debug", "manual_scan_default", "preserve_originals", "skip_existing_hashes",
    "cloud_uploads_enabled", "execute_ocr_text", "semantic_search_enabled", "bounded_polling_enabled",
    "scheduled_scan_enabled", "sqlite_wal"];
  const form = document.getElementById("settings-form");
  form.innerHTML = Object.entries(s).map(([k, v]) => {
    if (boolKeys.includes(k)) {
      return `<div class="row"><label style="flex:1;">${escapeHtml(k)}</label><input type="checkbox" data-key="${escapeHtml(k)}" ${v ? "checked" : ""} /></div>`;
    }
    return `<div class="row"><label style="flex:1;">${escapeHtml(k)}</label><input data-key="${escapeHtml(k)}" value="${escapeHtml(v)}" /></div>`;
  }).join("");
  document.getElementById("save-settings").addEventListener("click", async () => {
    const payload = {};
    form.querySelectorAll("[data-key]").forEach((input) => {
      const key = input.dataset.key;
      if (input.type === "checkbox") payload[key] = input.checked;
      else payload[key] = input.value;
    });
    const errorEl = document.getElementById("settings-error");
    errorEl.textContent = "";
    try {
      await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
      alert("Settings saved.");
    } catch (err) {
      errorEl.textContent = `Save failed: ${err.message}`;
    }
  });
}

// ----------------------------------------------------------------- status -

async function renderStatus() {
  const s = await api("/api/system_status");
  const rs = s.mobile_resource_state || {};
  view.innerHTML = `
    <div class="card">
      <h2>System Status</h2>
      <div>application: ${escapeHtml(s.application_name)}</div>
      <div>bound to: ${escapeHtml(s.host)}:${s.port}</div>
      <div>database: ${escapeHtml(s.database_path)}</div>
      <div>database size: ${fmtBytes(s.database_size_bytes)}</div>
      <div>free storage: ${fmtBytes(s.free_storage_bytes)}</div>
      <div>scan in progress: ${s.scan_in_progress}</div>
      <div>semantic search enabled: ${s.semantic_search_enabled}</div>
      <div>bounded polling enabled: ${s.bounded_polling_enabled} (running: ${s.bounded_polling_running})</div>
      <div>cloud uploads enabled: ${s.cloud_uploads_enabled}</div>
    </div>
    <div class="card">
      <h3>Mobile Substrate</h3>
      <div class="muted">Per FORGEWORLD-MOBILE-SUBSTRATE-001: this device's actual platform, resource state, and pending handoffs -- not a reduced Windows workstation.</div>
      <div class="row" style="justify-content:space-between; padding:0.2rem 0;">
        <span>Keel state</span><span class="badge ${s.mobile_keel_state === 'MOBILE_KEEL_IDLE' ? 'ok' : ''}">${escapeHtml(s.mobile_keel_state || "unknown")}</span>
      </div>
      <div class="row" style="justify-content:space-between; padding:0.2rem 0;">
        <span>Platform class</span><span class="badge">${escapeHtml(s.mobile_platform_class || "unknown")}</span>
      </div>
      <div class="row" style="justify-content:space-between; padding:0.2rem 0;">
        <span>Resource state</span><span class="badge ${rs.state === 'GREEN' ? 'ok' : rs.state === 'RED' ? 'err' : rs.state ? 'warn' : ''}">${escapeHtml(rs.state || "unknown")}</span>
      </div>
      <div class="row" style="justify-content:space-between; padding:0.2rem 0;">
        <span>Pending mission handoffs</span><span>${s.pending_mission_handoffs ?? 0}</span>
      </div>
      <div class="row" style="justify-content:space-between; padding:0.2rem 0;">
        <span>Pending Cinema reviews</span><span>${s.pending_cinema_reviews ?? 0}</span>
      </div>
      <div class="row" style="margin-top:0.5rem;">
        <button class="btn secondary" id="btn-capability-state">Capability State</button>
        <button class="btn secondary" id="btn-mission-list">Mission Handoffs</button>
        <button class="btn secondary" id="btn-cinema-review">Cinema Review</button>
        <button class="btn secondary" id="btn-device-profile">Device Profile</button>
      </div>
    </div>
    <div class="card">
      <h3>ForgeWorld Integrations</h3>
      <div class="muted">Extension points for a later cycle -- all disabled, app is fully functional without them.</div>
      ${Object.values(s.forgeworld_integrations || {}).map((i) => `
        <div class="row" style="justify-content:space-between; padding:0.2rem 0;">
          <span>${escapeHtml(i.name)}</span>
          <span class="badge">${escapeHtml(i.status)}</span>
        </div>
      `).join("")}
    </div>
  `;

  document.getElementById("btn-capability-state").addEventListener("click", async () => {
    const cap = await api("/api/capability_state");
    const rows = cap.requirements.map((r) => `
      <div class="row" style="justify-content:space-between; padding:0.2rem 0; border-bottom:1px solid var(--border, #333);">
        <span>${escapeHtml(r.capability_id)}</span>
        <span class="badge ${r.state === 'AVAILABLE' ? 'ok' : ''}">${escapeHtml(r.state)}</span>
      </div>
      <div class="muted" style="font-size:0.8rem;">${escapeHtml(r.evidence)}</div>
    `).join("");
    openModal(`<h2>Capability State -- android_mobile_deployment</h2><div class="muted">can_proceed: ${cap.can_proceed}</div>${rows}`);
  });

  document.getElementById("btn-mission-list").addEventListener("click", async () => {
    const missions = await api("/api/missions");
    const rows = missions.map((m) => `
      <div class="card">
        <strong>${escapeHtml(m.mission_id)}</strong> (${escapeHtml(m.priority)})<br>
        <span class="muted">${escapeHtml(m.requested_outcome)}</span><br>
        mobile_available: ${m.mobile_available.length}, windows_required: ${m.windows_required.length}, operator_required: ${m.operator_required.length}
      </div>
    `).join("") || "<div class='muted'>No mission handoffs yet.</div>";
    openModal(`<h2>Mission Handoffs</h2>${rows}`);
  });

  document.getElementById("btn-cinema-review").addEventListener("click", async () => {
    const data = await api("/api/cinema/reviews");
    const artifacts = await api("/api/cinema/artifacts");
    const summary = data.summary;
    const rows = data.reviews.map((r) => `
      <div class="card">
        <strong>${escapeHtml(r.artifact)}</strong> (${escapeHtml(r.version)})<br>
        <span class="badge ${r.approval_state === 'approved' ? 'ok' : ''}">${escapeHtml(r.approval_state)}</span>
        <span class="muted">${escapeHtml(r.review_type)}</span>
      </div>
    `).join("") || "<div class='muted'>No reviews yet.</div>";
    openModal(`
      <h2>Cinema Review</h2>
      <div class="muted">${artifacts.length} artifact(s) available to review (real Cinema Player release data). Queue: ${JSON.stringify(summary)}</div>
      ${rows}
    `);
  });

  document.getElementById("btn-device-profile").addEventListener("click", async () => {
    const profile = await api("/api/device_profile");
    openModal(`<h2>Device Profile</h2><pre class="prompt-output">${escapeHtml(JSON.stringify(profile, null, 2))}</pre>`);
  });
}

activateTab("dashboard");
