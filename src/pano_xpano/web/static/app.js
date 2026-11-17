const state = {
  groups: [],
  folders: [],
  folderId: null,
  currentGroup: null,
  browserPath: ".",
  browserLoading: false,
  browserCache: new Map(),
  pollingJob: null,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDate(value) {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function toast(message, isError = false) {
  const element = document.getElementById("toast");
  if (!element) return;
  element.textContent = message;
  element.className = `toast${isError ? " error" : ""}`;
  element.hidden = false;
  clearTimeout(element._timer);
  element._timer = setTimeout(() => { element.hidden = true; }, isError ? 9000 : 4500);
}

function showJobBar(label) {
  const bar = document.getElementById("jobbar");
  if (!bar) return;
  bar.hidden = false;
  document.getElementById("job-label").textContent = label;
  document.getElementById("job-percent").textContent = "0%";
  document.getElementById("job-progress").style.width = "0%";
}

function updateJobBar(job) {
  const percent = Math.round((job.progress || 0) * 100);
  document.getElementById("job-percent").textContent = `${percent}%`;
  document.getElementById("job-progress").style.width = `${percent}%`;
  if (job.message) document.getElementById("job-label").textContent =
    `${job.kind} · ${job.message}`;
}

function hideJobBar() {
  const bar = document.getElementById("jobbar");
  if (bar) bar.hidden = true;
}

async function waitForJob(job) {
  state.pollingJob = job.id;
  showJobBar(`${job.kind} started`);
  updateJobBar(job);
  try {
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      const current = await api(`/api/jobs/${job.id}`);
      updateJobBar(current);
      if (current.status === "completed") {
        hideJobBar();
        return current;
      }
      if (current.status === "failed") {
        hideJobBar();
        throw new Error(current.message || `${job.kind} failed`);
      }
    }
  } finally {
    state.pollingJob = null;
  }
}

async function resumeActiveJob() {
  try {
    const active = await api("/api/jobs?active=true");
    if (!active.length) return;
    const job = active[0];
    if (state.pollingJob === job.id) return;
    const finished = await waitForJob(job);
    toast(`${job.kind} finished`);
    await refreshVisible(finished);
  } catch (error) {
    toast(error.message, true);
  }
}

function statusBadge(status) {
  const value = status || "never";
  return `<span class="badge ${escapeHtml(value)}">${escapeHtml(value)}</span>`;
}

function selectedFolder() {
  return state.folders.find(folder => folder.id === state.folderId) || null;
}

function folderName(folderId) {
  const folder = state.folders.find(item => item.id === folderId);
  return folder ? folder.path : "folder";
}

function setSelectedFolder(folderId, { reload = true } = {}) {
  state.folderId = folderId || null;
  const url = new URL(window.location.href);
  if (state.folderId) url.searchParams.set("folder", state.folderId);
  else url.searchParams.delete("folder");
  window.history.replaceState(null, "", url);
  if (state.folderId) localStorage.setItem("pano.folder", state.folderId);
  else localStorage.removeItem("pano.folder");
  const filter = document.getElementById("folder-filter");
  if (filter) filter.value = state.folderId || "";
  if (reload) loadGroups().catch(error => toast(error.message, true));
}

function initialFolder() {
  const fromUrl = new URL(window.location.href).searchParams.get("folder");
  return fromUrl || localStorage.getItem("pano.folder") || null;
}

// Folders ------------------------------------------------------------------

function folderCard(folder) {
  return `
    <article class="folder-card" data-folder-id="${escapeHtml(folder.id)}">
      <div class="folder-top">
        <div>
          <div class="folder-name">/${escapeHtml(folder.path)}</div>
          <div class="card-meta">last scan ${escapeHtml(formatDate(folder.last_scan_at))}</div>
        </div>
        ${statusBadge(folder.last_scan_status)}
      </div>
      <div class="folder-stats">
        <span>${folder.photo_count || folder.image_count || 0} photos</span>
        <span>${folder.file_count || 0} files</span>
        <span>${folder.group_count} groups</span>
      </div>
      <div class="card-actions">
        <button class="button small primary" data-folder-action="scan" data-id="${escapeHtml(folder.id)}">Scan</button>
        <button class="button small" data-folder-action="show" data-id="${escapeHtml(folder.id)}">Show groups</button>
        <button class="button small danger" data-folder-action="remove" data-id="${escapeHtml(folder.id)}">Remove</button>
      </div>
    </article>`;
}

async function loadFolders() {
  const folders = await api("/api/folders");
  state.folders = folders;
  const container = document.getElementById("folders");
  if (!container) return;
  container.innerHTML = folders.map(folderCard).join("");
  const empty = document.getElementById("folders-empty");
  if (empty) empty.hidden = folders.length !== 0;
  const count = document.getElementById("folder-count");
  if (count) count.textContent = `${folders.length} folder(s)`;

  const filter = document.getElementById("folder-filter");
  if (filter) {
    filter.innerHTML = `<option value="">All folders</option>${folders.map(folder =>
      `<option value="${escapeHtml(folder.id)}">/${escapeHtml(folder.path)}</option>`
    ).join("")}`;
    if (state.folderId && !folders.some(folder => folder.id === state.folderId)) {
      state.folderId = null;
      const url = new URL(window.location.href);
      url.searchParams.delete("folder");
      window.history.replaceState(null, "", url);
      localStorage.removeItem("pano.folder");
    }
    filter.value = state.folderId || "";
  }
}

async function addFolder(path) {
  const value = (path || "").trim();
  if (!value) { toast("Enter a folder path or use Browse", true); return; }
  const folder = await api("/api/folders", {
    method: "POST",
    body: JSON.stringify({ path: value }),
  });
  toast(
    `Folder /${folder.path} added: ${folder.image_count || 0} photos in ${folder.file_count || 0} files`
  );
  await loadFolders();
  setSelectedFolder(folder.id, { reload: false });
  await loadGroups();
  const input = document.getElementById("folder-path");
  if (input) input.value = "";
}

async function removeFolder(folderId) {
  const folder = state.folders.find(item => item.id === folderId);
  if (!folder) return;
  if (!confirm(`Remove /${folder.path} from the scan list? Files are not touched.`)) return;
  await api(`/api/folders/${folderId}`, { method: "DELETE" });
  toast(`Folder /${folder.path} removed from the index`);
  if (state.folderId === folderId) setSelectedFolder(null, { reload: false });
  await loadFolders();
  await loadGroups();
}

async function scanFolder(folderId) {
  const job = await api(`/api/folders/${folderId}/scan`, { method: "POST" });
  await waitForJob(job);
  toast("Folder scan finished");
  await refreshVisible(job);
}

async function scanAll() {
  const job = await api("/api/scan", { method: "POST" });
  await waitForJob(job);
  toast("Scan finished");
  await refreshVisible(job);
}

function openBrowser(path) {
  const dialog = document.getElementById("browser-dialog");
  if (!dialog) return;
  if (!dialog.open) dialog.showModal();
  loadBrowser(path || ".");
}

async function loadBrowser(path) {
  const container = document.getElementById("browser-entries");
  if (!container) return;
  if (state.browserLoading) return;
  const key = path || ".";
  const cached = state.browserCache.get(key);
  if (cached && Date.now() - cached.time < 10000) {
    renderBrowser(cached.result);
    return;
  }
  state.browserLoading = true;
  container.innerHTML = `<p class="browser-loading">Loading ${escapeHtml(key)}…</p>`;
  try {
    const result = await api(`/api/folders/browse?path=${encodeURIComponent(key)}`);
    state.browserCache.set(key, { result, time: Date.now() });
    renderBrowser(result);
  } catch (error) {
    container.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  } finally {
    state.browserLoading = false;
  }
}

function renderBrowser(result) {
  state.browserPath = result.path;
  const pathLabel = document.getElementById("browser-path");
  if (pathLabel) pathLabel.textContent = `/${result.path}`;
  const container = document.getElementById("browser-entries");
  if (!container) return;
  container.innerHTML = result.entries.length
    ? result.entries.map(entry => `
      <button class="browser-entry" data-browser-path="${escapeHtml(entry.path)}">
        <span>▸</span>
        ${escapeHtml(entry.name)}
      </button>`).join("")
    : `<p class="muted">No subfolders. Use this folder.</p>`;
  const up = document.getElementById("browser-up");
  if (up) up.dataset.parent = result.parent === null ? "" : result.parent;
}

// Groups -------------------------------------------------------------------

function groupCovers(group) {
  const photos = group.members.slice(0, 4);
  const single = photos.length === 1 ? " single" : "";
  return `<div class="cover-grid${single}">${photos.map(photo =>
    `<img class="cover" src="${escapeHtml(photo.thumbnail)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
  ).join("")}</div>`;
}

function groupCard(group) {
  const first = group.members[0];
  const last = group.members[group.members.length - 1];
  const span = first && last
    ? `${escapeHtml(formatDate(first.captured_at))} → ${escapeHtml(formatDate(last.captured_at))}`
    : "";
  const stitchReady = group.stitch && group.stitch.status === "completed";
  const replaceDisabled = stitchReady ? "" : "disabled";
  return `
    <article class="group-card" data-group="${escapeHtml(group.id)}">
      ${groupCovers(group)}
      <div class="card-body">
        <div class="card-top">
          <span class="card-title">${group.members.length} photos</span>
          ${statusBadge(group.status)}
        </div>
        <div class="card-meta">/${escapeHtml(folderName(group.folder_id))} · ${span}</div>
        <div class="card-meta">confidence ${(group.confidence * 100).toFixed(0)}% · ${formatBytes(group.members.reduce((sum, photo) => sum + (photo.size || 0), 0))}</div>
        <div class="card-actions">
          <button class="button small primary" data-action="stitch" data-id="${escapeHtml(group.id)}">Make panorama</button>
          <button class="button small" data-action="replace" data-id="${escapeHtml(group.id)}" ${replaceDisabled}>Replace</button>
          <a class="button small ghost" href="/groups/${escapeHtml(group.id)}">Details</a>
        </div>
      </div>
    </article>`;
}

async function loadGroups() {
  const query = state.folderId ? `?folder_id=${encodeURIComponent(state.folderId)}` : "";
  const groups = await api(`/api/groups${query}`);
  state.groups = groups;
  const container = document.getElementById("groups");
  if (!container) return;
  container.innerHTML = groups.map(groupCard).join("");
  const folder = selectedFolder();
  const title = document.getElementById("groups-title");
  if (title) title.textContent = folder ? `/${folder.path}` : "All folders";
  const photos = groups.reduce((sum, group) => sum + group.members.length, 0);
  const ready = groups.filter(group => group.stitch && group.stitch.status === "completed").length;
  const stats = document.getElementById("stats");
  if (stats) {
    stats.hidden = groups.length === 0;
    document.getElementById("stat-groups").textContent = groups.length;
    document.getElementById("stat-photos").textContent = photos;
    document.getElementById("stat-ready").textContent = ready;
  }
  const empty = document.getElementById("empty");
  if (empty) empty.hidden = groups.length !== 0;
}

async function refreshVisible(job) {
  if (!job) return;
  if (document.getElementById("folders")) await loadFolders();
  if (document.getElementById("groups")) await loadGroups();
  if (document.getElementById("operations")) await loadOperations();
  if (state.currentGroup) await loadGroup(state.currentGroup.id);
}

async function stitchGroup(groupId) {
  const job = await api(`/api/groups/${groupId}/stitch`, { method: "POST" });
  await waitForJob(job);
  toast("Panorama is ready");
  await refreshVisible(job);
}

async function replaceGroup(groupId) {
  const confirmation = prompt(
    "This moves the source photos and sidecars into the trash and writes the panorama into the library.\n\nType REPLACE to continue:"
  );
  if (confirmation !== "REPLACE") {
    toast("Replacement cancelled");
    return;
  }
  const job = await api(`/api/groups/${groupId}/replace`, {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  });
  await waitForJob(job);
  toast("Group replaced; originals are in the trash");
  await refreshVisible(job);
}

function bindGroupActions() {
  document.addEventListener("click", async event => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    const groupId = button.dataset.id;
    if (!groupId) return;
    button.disabled = true;
    try {
      if (action === "stitch") await stitchGroup(groupId);
      if (action === "replace") await replaceGroup(groupId);
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}

// Pages --------------------------------------------------------------------

async function initIndex() {
  state.folderId = initialFolder();
  bindGroupActions();

  document.addEventListener("click", async event => {
    const folderButton = event.target.closest("[data-folder-action]");
    if (folderButton) {
      const folderId = folderButton.dataset.id;
      const action = folderButton.dataset.folderAction;
      folderButton.disabled = true;
      try {
        if (action === "scan") await scanFolder(folderId);
        if (action === "show") {
          setSelectedFolder(folderId);
          document.querySelector(".group-section")?.scrollIntoView({ behavior: "smooth" });
        }
        if (action === "remove") await removeFolder(folderId);
      } catch (error) {
        toast(error.message, true);
      } finally {
        folderButton.disabled = false;
      }
      return;
    }
    const browserEntry = event.target.closest("[data-browser-path]");
    if (browserEntry) {
      try { await loadBrowser(browserEntry.dataset.browserPath); }
      catch (error) { toast(error.message, true); }
    }
  });

  const addButton = document.getElementById("add-folder");
  if (addButton) addButton.addEventListener("click", async () => {
    addButton.disabled = true;
    const label = addButton.textContent;
    addButton.textContent = "Counting…";
    try { await addFolder(document.getElementById("folder-path").value); }
    catch (error) { toast(error.message, true); }
    finally {
      addButton.textContent = label;
      addButton.disabled = false;
    }
  });

  const pathInput = document.getElementById("folder-path");
  if (pathInput) pathInput.addEventListener("keydown", event => {
    if (event.key === "Enter") { event.preventDefault(); addButton?.click(); }
  });

  const browseButton = document.getElementById("browse-folder");
  if (browseButton) browseButton.addEventListener("click", () => openBrowser("."));
  const browserClose = document.getElementById("browser-close");
  if (browserClose) browserClose.addEventListener("click", () => document.getElementById("browser-dialog")?.close());
  const browserUse = document.getElementById("browser-use");
  if (browserUse) browserUse.addEventListener("click", async () => {
    try {
      const dialog = document.getElementById("browser-dialog");
      if (dialog) dialog.close();
      await addFolder(state.browserPath);
    } catch (error) { toast(error.message, true); }
  });
  const browserUp = document.getElementById("browser-up");
  if (browserUp) browserUp.addEventListener("click", async () => {
    const parent = browserUp.dataset.parent;
    if (parent === "") return;
    try { await loadBrowser(parent || "."); }
    catch (error) { toast(error.message, true); }
  });

  const scanAllButton = document.getElementById("scan-all");
  if (scanAllButton) scanAllButton.addEventListener("click", async () => {
    scanAllButton.disabled = true;
    try { await scanAll(); }
    catch (error) { toast(error.message, true); }
    finally { scanAllButton.disabled = false; }
  });

  const filter = document.getElementById("folder-filter");
  if (filter) filter.addEventListener("change", () => setSelectedFolder(filter.value || null));

  try {
    await loadFolders();
    await loadGroups();
  } catch (error) {
    toast(error.message, true);
  }
  await resumeActiveJob();
}

function memberCard(photo) {
  const dimensions = photo.width && photo.height ? `${photo.width}×${photo.height}` : null;
  const meta = [photo.camera, dimensions].filter(Boolean).join(" · ");
  const fullMeta = [
    dimensions || "unknown size",
    formatBytes(photo.size),
    formatDate(photo.captured_at),
  ].filter(Boolean).join(" · ");
  return `
    <div class="member">
      <button class="member-image" type="button"
        data-full-image="${escapeHtml(photo.original)}"
        data-full-title="${escapeHtml(photo.name)}"
        data-full-meta="${escapeHtml(fullMeta)}"
        title="View at actual size">
        <img src="${escapeHtml(photo.thumbnail)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
      </button>
      <div>
        <strong title="${escapeHtml(photo.path)}">${escapeHtml(photo.name)}</strong>
        ${escapeHtml(meta || "no camera metadata")}<br>
        ${escapeHtml(formatDate(photo.captured_at))}
      </div>
    </div>`;
}

function operationRow(operation, includeUndo = true) {
  const undo = includeUndo && operation.status === "completed"
    ? `<button class="button small" data-undo="${escapeHtml(operation.id)}">Undo</button>`
    : "";
  return `
    <div class="operation">
      <div class="operation-main">
        <div class="operation-title">${statusBadge(operation.status)} ${escapeHtml(operation.panorama || "no panorama")}</div>
        <div class="operation-sub">${escapeHtml(formatDate(operation.created_at))} · ${operation.sources.length} source file(s)</div>
        ${operation.error ? `<div class="operation-sub" style="color:var(--red)">${escapeHtml(operation.error)}</div>` : ""}
      </div>
      <div class="operation-actions">${undo}</div>
    </div>`;
}

function openImageViewer({ src, title, meta }) {
  const dialog = document.getElementById("image-dialog");
  if (!dialog || !src) return;
  document.getElementById("image-dialog-title").textContent = title || "Photo";
  document.getElementById("image-dialog-meta").textContent =
    meta ? `${meta} · actual size` : "Actual size";
  const image = document.getElementById("image-dialog-image");
  const errorBox = document.getElementById("image-dialog-error");
  image.hidden = false;
  errorBox.hidden = true;
  image.onerror = () => {
    image.hidden = true;
    errorBox.textContent = `The file for ${title || "this image"} is not available.`;
    errorBox.hidden = false;
    document.getElementById("image-dialog-meta").textContent = "file not found";
  };
  image.src = src;
  image.alt = title || "";
  const stage = document.getElementById("image-dialog-stage");
  stage.scrollTop = 0;
  stage.scrollLeft = 0;
  if (!dialog.open) dialog.showModal();
}

function bindImageViewer() {
  const dialog = document.getElementById("image-dialog");
  if (!dialog) return;
  document.addEventListener("click", event => {
    const trigger = event.target.closest("[data-full-image]");
    if (!trigger) return;
    openImageViewer({
      src: trigger.dataset.fullImage,
      title: trigger.dataset.fullTitle,
      meta: trigger.dataset.fullMeta,
    });
  });
  const close = document.getElementById("image-dialog-close");
  if (close) close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    if (event.target === dialog) dialog.close();
  });
}

async function loadGroup(groupId) {
  if (!state.folders.length) {
    try { state.folders = await api("/api/folders"); }
    catch (_) { state.folders = []; }
  }
  const group = await api(`/api/groups/${groupId}`);
  state.currentGroup = group;
  const title = document.getElementById("group-title");
  const status = document.getElementById("group-status");
  const meta = document.getElementById("group-meta");
  if (!title) return;
  title.textContent = `${group.members.length} photo panorama`;
  status.className = `badge ${group.status}`;
  status.textContent = group.status;
  meta.textContent = `/${folderName(group.folder_id)} · confidence ${(group.confidence * 100).toFixed(0)}% · group ${group.id}`;

  const members = document.getElementById("members");
  members.innerHTML = group.members.map(memberCard).join("");
  document.getElementById("member-count").textContent = `${group.members.length} files`;

  const stitchReady = group.stitch && group.stitch.status === "completed";
  const previewPanel = document.getElementById("preview-panel");
  const previewImage = document.getElementById("preview-image");
  const previewError = document.getElementById("preview-error");
  const previewFull = document.getElementById("preview-full");
  const replaceButton = document.getElementById("replace-button");
  if (stitchReady) {
    previewPanel.hidden = false;
    previewError.hidden = true;
    previewImage.hidden = false;
    previewFull.hidden = false;
    previewImage.src = `/api/groups/${group.id}/preview?t=${Date.now()}`;
    const size = `${group.stitch.width || "?"}×${group.stitch.height || "?"}`;
    document.getElementById("preview-size").textContent = size;
    const openPanorama = () => openImageViewer({
      src: previewImage.src,
      title: "Stitched panorama",
      meta: `${size} · ${group.members.length} source photos`,
    });
    previewFull.onclick = openPanorama;
    previewImage.onclick = openPanorama;
    replaceButton.hidden = false;
    replaceButton.disabled = group.status === "replaced";
  } else if (group.stitch && group.stitch.status === "failed") {
    previewPanel.hidden = false;
    previewImage.hidden = true;
    previewFull.hidden = true;
    previewError.hidden = false;
    previewError.textContent = group.stitch.error || "Panorama stitching failed.";
    document.getElementById("preview-size").textContent = "";
    replaceButton.hidden = true;
  } else {
    previewPanel.hidden = true;
    replaceButton.hidden = true;
  }
  const operationsPanel = document.getElementById("operations-panel");
  const operations = group.operations || [];
  operationsPanel.hidden = operations.length === 0;
  document.getElementById("group-operations").innerHTML =
    operations.map(operation => operationRow(operation)).join("");

  const stitchButton = document.getElementById("stitch-button");
  stitchButton.onclick = async () => {
    stitchButton.disabled = true;
    try {
      const job = await api(`/api/groups/${group.id}/stitch`, { method: "POST" });
      await waitForJob(job);
      toast("Panorama is ready");
      await refreshVisible(job);
    } catch (error) {
      toast(error.message, true);
    } finally {
      stitchButton.disabled = false;
    }
  };
  replaceButton.onclick = async () => {
    replaceButton.disabled = true;
    try { await replaceGroup(group.id); }
    catch (error) { toast(error.message, true); }
    finally { replaceButton.disabled = false; }
  };
}

async function initGroup(groupId) {
  bindGroupActions();
  bindImageViewer();
  try { await loadGroup(groupId); }
  catch (error) { toast(error.message, true); }
  await resumeActiveJob();
}

async function loadOperations() {
  const operations = await api("/api/operations");
  const container = document.getElementById("operations");
  if (!container) return;
  container.innerHTML = operations.map(operation => operationRow(operation)).join("");
  const empty = document.getElementById("operations-empty");
  if (empty) empty.hidden = operations.length !== 0;
}

async function initOperations() {
  document.addEventListener("click", async event => {
    const button = event.target.closest("[data-undo]");
    if (!button) return;
    if (!confirm("Restore the original photos and move the panorama out of the library?")) return;
    button.disabled = true;
    try {
      const job = await api(`/api/operations/${button.dataset.undo}/undo`, { method: "POST" });
      await waitForJob(job);
      toast("Originals restored");
      await refreshVisible(job);
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  try { await loadOperations(); }
  catch (error) { toast(error.message, true); }
  await resumeActiveJob();
}

async function initSettings() {
  const form = document.getElementById("settings-form");
  if (!form) return;
  const status = document.getElementById("settings-status");
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const data = {};
    for (const [key, value] of new FormData(form).entries()) {
      data[key] = value === "" ? null : Number(value);
    }
    try {
      await api("/api/settings", { method: "PUT", body: JSON.stringify(data) });
      if (status) status.textContent = "saved";
      toast("Detection settings saved");
    } catch (error) {
      if (status) status.textContent = "";
      toast(error.message, true);
    }
  });
  await resumeActiveJob();
}
