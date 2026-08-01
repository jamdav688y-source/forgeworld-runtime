// ForgeWorld Mobile Research Companion -- single-shell client.
// All navigation happens inside this one page (tabs/modals). No new windows.

const view = document.getElementById("view");
const modalRoot = document.getElementById("modal-root");
const tabs = document.querySelectorAll(".tab");

let selectedIds = new Set();

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
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
    view.innerHTML = `<div class="card error-text">Failed to load: ${err.message}</div>`;
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
      ${d.top_topics.map((t) => `<span class="badge">${t.name} (${t.c})</span>`).join("") || "<span class='muted'>none yet</span>"}
      <h3>Top Entities</h3>
      ${d.top_entities.map((t) => `<span class="badge">${t.name} (${t.entity_type})</span>`).join("") || "<span class='muted'>none yet</span>"}
      <h3>Recent Collections</h3>
      ${d.recent_collections.map((c) => `<div>${c.name}</div>`).join("") || "<span class='muted'>none yet</span>"}
      <h3>Last Scan</h3>
      <div class="muted">${d.last_scan ? d.last_scan.message + " -- " + d.last_scan.created_at : "no scans yet"}</div>
    </div>
  `;
}

function stat(num, label) {
  return `<div class="stat"><div class="num">${num}</div><div class="label">${label}</div></div>`;
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
        <img loading="lazy" src="${item.preview_path}" onerror="this.style.opacity=0.15" />
        <div class="meta">
          <div class="title">${item.title || item.filename}</div>
          <span class="badge">${item.content_type}</span>
          <span class="badge ${item.processing_status === "PROCESSED" ? "ok" : "warn"}">${item.processing_status}</span>
        </div>
      </div>
    `);
    card.addEventListener("click", () => openScreenshotDetail(item.id));
    grid.appendChild(card);
  });
}

async function openScreenshotDetail(id) {
  const d = await api(`/api/screenshots/${id}`);
  openModal(`
    <h2>${d.title || d.filename}</h2>
    <img class="detail-image" src="${d.preview_path}" onerror="this.style.display='none'" />
    <div class="section-label">Source</div>
    <div class="muted">path: ${d.original_path}<br>sha256: ${d.sha256}<br>status: ${d.processing_status}</div>

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
    ${d.tags.map((t) => `<span class="badge" title="${escapeHtml(t.rationale || "")}">${t.name} (${(t.confidence*1).toFixed(2)})</span>`).join("") || "<span class='muted'>none</span>"}

    <div class="section-label">Entities</div>
    ${d.entities.map((e) => `<span class="badge">${e.name} (${e.entity_type})</span>`).join("") || "<span class='muted'>none</span>"}

    <div class="section-label">System Summary</div>
    <div class="muted">${escapeHtml(d.summary || "(none)")}</div>

    <div class="section-label">Notes</div>
    <div id="notes-list">${d.notes.map((n) => `<div class="card">${escapeHtml(n.body)}<div class="muted">${n.created_at}</div></div>`).join("") || "<span class='muted'>no notes</span>"}</div>
    <textarea id="new-note" rows="2" placeholder="Add a note..."></textarea>
    <button class="btn secondary" id="add-note">Add Note</button>

    <div class="row" style="margin-top:0.6rem;">
      <button class="btn" id="select-for-prompt">Add to Prompt/Export Selection</button>
      <button class="btn secondary" id="close-modal">Close</button>
    </div>
  `);

  document.getElementById("close-modal").addEventListener("click", closeModal);
  document.getElementById("save-correction").addEventListener("click", async () => {
    const text = document.getElementById("ocr-correction").value;
    await api(`/api/screenshots/${id}/ocr/correct`, { method: "POST", body: JSON.stringify({ corrected_text: text }) });
    openScreenshotDetail(id);
  });
  document.getElementById("rerun-ocr").addEventListener("click", async () => {
    await api(`/api/screenshots/${id}/ocr/rerun`, { method: "POST" });
    openScreenshotDetail(id);
  });
  document.getElementById("mark-unusable").addEventListener("click", async () => {
    await api(`/api/screenshots/${id}/ocr/unusable`, { method: "POST" });
    openScreenshotDetail(id);
  });
  document.getElementById("add-note").addEventListener("click", async () => {
    const body = document.getElementById("new-note").value.trim();
    if (!body) return;
    await api(`/api/screenshots/${id}/notes`, { method: "POST", body: JSON.stringify({ body }) });
    openScreenshotDetail(id);
  });
  document.getElementById("select-for-prompt").addEventListener("click", () => {
    selectedIds.add(id);
    alert(`Added source ${id} to selection (${selectedIds.size} selected). Open Prompt Lab to generate.`);
  });
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
  document.getElementById("search-go").addEventListener("click", runSearch);
  document.getElementById("search-q").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });
}

async function runSearch() {
  const q = document.getElementById("search-q").value;
  const sort = document.getElementById("search-sort").value;
  const tags = document.getElementById("search-tags").value;
  const contentTypes = document.getElementById("search-content-types").value;
  const minConf = document.getElementById("search-min-conf").value;
  const params = new URLSearchParams({ q, sort, tags, content_types: contentTypes });
  if (minConf) params.set("min_confidence", minConf);
  const data = await api(`/api/search?${params.toString()}`);
  const results = document.getElementById("search-results");
  results.innerHTML = data.results.map((r) => `
    <div class="card result-card" data-id="${r.id}">
      <img src="${r.preview_path}" onerror="this.style.opacity=0.15" />
      <div>
        <div><strong>${r.title || r.filename}</strong></div>
        <div class="muted">${r.source_platform || ""} ${r.discovered_at || ""}</div>
        <div>${(r.top_tags || []).map((t) => `<span class="badge">${t.name}</span>`).join("")}</div>
        <div class="excerpt">${r.excerpt || ""}</div>
        <span class="badge ${r.processing_status === "PROCESSED" ? "ok" : "warn"}">${r.processing_status}</span>
      </div>
    </div>
  `).join("") || "<p class='muted'>No results.</p>";
  results.querySelectorAll(".result-card").forEach((c) => {
    c.addEventListener("click", () => openScreenshotDetail(parseInt(c.dataset.id, 10)));
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
  document.getElementById("create-collection").addEventListener("click", async () => {
    const name = document.getElementById("new-collection-name").value.trim();
    if (!name) return;
    await api("/api/collections", { method: "POST", body: JSON.stringify({ name }) });
    renderCollections();
  });
  const list = document.getElementById("collections-list");
  list.innerHTML = cols.map((c) => `
    <div class="card">
      <div class="row" style="justify-content:space-between;">
        <strong>${c.name}</strong>
        <span class="muted">${c.item_count} item(s)</span>
      </div>
      <div class="row" style="margin-top:0.4rem;">
        <button class="btn secondary" data-view="${c.id}">View</button>
        <button class="btn secondary" data-add="${c.id}">Add Selection (${selectedIds.size})</button>
        <button class="btn secondary" data-export="${c.id}">Export Markdown</button>
      </div>
    </div>
  `).join("") || "<p class='muted'>No collections yet.</p>";

  list.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => viewCollection(b.dataset.view)));
  list.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/collections/${b.dataset.add}/items`, {
      method: "POST",
      body: JSON.stringify({ action: "add", screenshot_ids: Array.from(selectedIds) }),
    });
    renderCollections();
  }));
  list.querySelectorAll("[data-export]").forEach((b) => b.addEventListener("click", async () => {
    const data = await api(`/api/exports/markdown?collection_id=${b.dataset.export}`);
    openModal(`<h2>Export</h2><pre class="prompt-output">${escapeHtml(data.content)}</pre><div class="muted">saved to ${data.path}</div><button class="btn secondary" id="close-modal">Close</button>`);
    document.getElementById("close-modal").addEventListener("click", closeModal);
  }));
}

async function viewCollection(id) {
  const c = await api(`/api/collections/${id}`);
  openModal(`
    <h2>${c.name}</h2>
    ${c.items.map((i) => `<div class="card">${i.title || i.filename} <span class="badge">${i.content_type}</span></div>`).join("") || "<p class='muted'>empty</p>"}
    <button class="btn secondary" id="close-modal">Close</button>
  `);
  document.getElementById("close-modal").addEventListener("click", closeModal);
}

// ------------------------------------------------------------- prompt lab -

async function renderPromptLab() {
  const modes = await api("/api/prompt_modes");
  const options = Object.entries(modes).map(([key, m]) => `<option value="${key}">${m.label}</option>`).join("");
  view.innerHTML = `
    <div class="card">
      <h2>Prompt Lab</h2>
      <div class="muted">Selected source IDs: ${Array.from(selectedIds).join(", ") || "(none -- open items in Library/Search and click 'Add to Prompt/Export Selection')"}</div>
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
    try {
      const result = await api("/api/prompts/generate", {
        method: "POST",
        body: JSON.stringify({ mode, objective, operator_instruction, screenshot_ids: ids }),
      });
      document.getElementById("prompt-output-wrap").innerHTML = `
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
        navigator.clipboard.writeText(result.content).catch(() => {});
      });
      document.getElementById("download-prompt").addEventListener("click", () => {
        const blob = new Blob([result.content], { type: "text/markdown" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `prompt_${result.id}.md`;
        a.click();
      });
      document.getElementById("save-template").addEventListener("click", async () => {
        const name = prompt("Template name:");
        if (!name) return;
        await api(`/api/prompts/${result.id}/save_template`, { method: "POST", body: JSON.stringify({ name }) });
        alert("Saved as template.");
      });
    } catch (err) {
      document.getElementById("prompt-output-wrap").innerHTML = `<div class="card error-text">${err.message}</div>`;
    }
  });
}

// -------------------------------------------------------------- ingestion -

async function renderIngestion() {
  const sources = await api("/api/sources");
  const lastScan = await api("/api/scan/last");
  view.innerHTML = `
    <div class="card">
      <h2>Ingestion</h2>
      <div class="row">
        <button class="btn secondary" id="probe-sources">Probe Sources</button>
        <button class="btn" id="start-scan">Start Scan</button>
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

  document.getElementById("probe-sources").addEventListener("click", async () => {
    const updated = await api("/api/sources/probe", { method: "POST" });
    renderSourcesList(updated);
  });
  document.getElementById("start-scan").addEventListener("click", async () => {
    document.getElementById("last-scan").innerHTML = "<span class='muted'>scanning...</span>";
    try {
      const summary = await api("/api/scan", { method: "POST", body: JSON.stringify({}) });
      document.getElementById("last-scan").innerHTML = formatScan(summary);
    } catch (err) {
      document.getElementById("last-scan").innerHTML = `<span class="error-text">${err.message}</span>`;
    }
  });
  document.getElementById("add-source").addEventListener("click", async () => {
    const path = document.getElementById("new-source-path").value.trim();
    if (!path) return;
    await api("/api/sources", { method: "POST", body: JSON.stringify({ path }) });
    renderSourcesList(await api("/api/sources"));
  });
}

function renderSourcesList(sources) {
  const container = document.getElementById("sources-list");
  container.innerHTML = sources.map((s) => `
    <div class="row" style="justify-content:space-between; padding:0.3rem 0; border-bottom:1px solid var(--border);">
      <div>
        <div>${s.label}</div>
        <div class="muted">${s.path}</div>
      </div>
      <div>
        <span class="badge ${s.exists ? "ok" : "err"}">${s.exists ? "found" : "not found"}</span>
        <label class="muted"><input type="checkbox" data-toggle="${s.path}" ${s.enabled ? "checked" : ""} /> enabled</label>
      </div>
    </div>
  `).join("");
  container.querySelectorAll("[data-toggle]").forEach((cb) => {
    cb.addEventListener("change", async () => {
      await api("/api/sources/update", { method: "POST", body: JSON.stringify({ path: cb.dataset.toggle, enabled: cb.checked }) });
    });
  });
}

function formatScan(s) {
  return `scanned=${s.scanned} new=${s.new_count} duplicate=${s.duplicate_count} skipped=${s.skipped_count} errors=${s.error_count}<br><span class="muted">${s.started_at} -> ${s.finished_at}</span>`;
}

// --------------------------------------------------------------- settings -

async function renderSettings() {
  const s = await api("/api/settings");
  view.innerHTML = `
    <div class="card">
      <h2>Settings</h2>
      <div class="muted">Local-only. Cloud uploads and semantic search stay off until explicitly enabled here.</div>
      <div id="settings-form"></div>
      <button class="btn" id="save-settings" style="margin-top:0.6rem;">Save</button>
    </div>
  `;
  const boolKeys = ["debug", "manual_scan_default", "preserve_originals", "skip_existing_hashes",
    "cloud_uploads_enabled", "execute_ocr_text", "semantic_search_enabled", "bounded_polling_enabled",
    "scheduled_scan_enabled", "sqlite_wal"];
  const form = document.getElementById("settings-form");
  form.innerHTML = Object.entries(s).map(([k, v]) => {
    if (boolKeys.includes(k)) {
      return `<div class="row"><label style="flex:1;">${k}</label><input type="checkbox" data-key="${k}" ${v ? "checked" : ""} /></div>`;
    }
    return `<div class="row"><label style="flex:1;">${k}</label><input data-key="${k}" value="${v}" /></div>`;
  }).join("");
  document.getElementById("save-settings").addEventListener("click", async () => {
    const payload = {};
    form.querySelectorAll("[data-key]").forEach((input) => {
      const key = input.dataset.key;
      if (input.type === "checkbox") payload[key] = input.checked;
      else if (!isNaN(input.value) && input.value.trim() !== "") payload[key] = Number(input.value);
      else payload[key] = input.value;
    });
    await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    alert("Settings saved.");
  });
}

// ----------------------------------------------------------------- status -

async function renderStatus() {
  const s = await api("/api/system_status");
  view.innerHTML = `
    <div class="card">
      <h2>System Status</h2>
      <div>application: ${s.application_name}</div>
      <div>bound to: ${s.host}:${s.port}</div>
      <div>database: ${s.database_path}</div>
      <div>database size: ${fmtBytes(s.database_size_bytes)}</div>
      <div>free storage: ${fmtBytes(s.free_storage_bytes)}</div>
      <div>semantic search enabled: ${s.semantic_search_enabled}</div>
      <div>bounded polling enabled: ${s.bounded_polling_enabled}</div>
      <div>cloud uploads enabled: ${s.cloud_uploads_enabled}</div>
    </div>
  `;
}

activateTab("dashboard");
