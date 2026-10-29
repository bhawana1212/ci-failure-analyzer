"use strict";

const byId = (id) => document.getElementById(id);
const labels = { test: "Test failure", compilation: "Compilation", timeout: "Timeout", infrastructure: "Infrastructure", build: "Build failure", unknown: "Unclassified", none: "No failure" };
const colors = { test: "#d97869", compilation: "#7892b1", timeout: "#d4b36b", infrastructure: "#8c80a7", build: "#62988b", unknown: "#b3bcb3" };
const state = { offset: 0, limit: 8, total: 0, metrics: null, selected: null, mode: "file", sequence: 0 };
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
const icons = () => { if (window.lucide) window.lucide.createIcons(); };
const statusBadge = (status) => `<span class="status ${escapeHTML(status)}">${escapeHTML(status.charAt(0).toUpperCase() + status.slice(1))}</span>`;
const dateLabel = (value) => new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
let toastTimer;
let searchTimer;

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, signal: AbortSignal.timeout(30000) });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : body.detail?.map((error) => error.msg).join("; ") || message;
    } catch {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function notify(message, error = false) {
  clearTimeout(toastTimer);
  byId("toast").textContent = message;
  byId("toast").classList.toggle("error", error);
  byId("toast").hidden = false;
  toastTimer = setTimeout(() => { byId("toast").hidden = true; }, 5000);
}

function renderMetrics(metrics) {
  state.metrics = metrics;
  byId("metric-total").textContent = metrics.total.toLocaleString();
  byId("nav-count").textContent = metrics.total;
  byId("metric-passed").textContent = metrics.statuses.passed || 0;
  byId("metric-failed").textContent = metrics.statuses.failed || 0;
  byId("metric-other").textContent = `${metrics.statuses.unstable || 0} unstable · ${metrics.statuses.aborted || 0} aborted`;
  byId("metric-rate").innerHTML = `${metrics.pass_rate ?? "--"}<span>%</span>`;
  byId("outcome-strip").innerHTML = metrics.recent.length ? metrics.recent.map((build) => `<button type="button" class="outcome-bar ${escapeHTML(build.status)}" data-build="${build.id}" title="${escapeHTML(build.name)}: ${escapeHTML(build.status)}" aria-label="${escapeHTML(build.name)}: ${escapeHTML(build.status)}"></button>`).join("") : '<div class="outcome-empty"></div>';
  const unknown = metrics.statuses.unknown || 0;
  byId("outcome-caption").textContent = metrics.total ? `${metrics.recent.length} most recent builds · ${unknown} unknown ${unknown === 1 ? "outcome" : "outcomes"} overall` : "No builds analyzed yet.";
  const categories = Object.entries(metrics.categories).filter(([, count]) => count > 0);
  const total = categories.reduce((sum, [, count]) => sum + count, 0);
  byId("category-total").textContent = total;
  byId("category-legend").innerHTML = categories.length ? categories.sort((left, right) => right[1] - left[1]).map(([category, count]) => `<button type="button" class="category-item" data-category="${escapeHTML(category)}" title="Filter ${escapeHTML(labels[category])} builds"><span class="dot" style="background:${colors[category] || colors.unknown}"></span><span>${escapeHTML(labels[category])}</span><strong>${count}</strong></button>`).join("") : '<p class="muted">No failures recorded.</p>';
  drawChart(categories, total);
  byId("top-tests").innerHTML = metrics.top_tests.length ? metrics.top_tests.map((test) => `<div class="test-item"><i data-lucide="flask-conical"></i><span class="test-name">${escapeHTML(test.name)}</span><span class="test-count">${test.count} ${test.count === 1 ? "build" : "builds"}</span></div>`).join("") : '<p class="muted">No test failures recorded.</p>';
  icons();
}

function drawChart(categories, total) {
  const canvas = byId("category-chart");
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, 320, 320);
  context.lineWidth = 28;
  context.strokeStyle = "#e5ece5";
  context.beginPath();
  context.arc(160, 160, 133, 0, Math.PI * 2);
  context.stroke();
  let start = -Math.PI / 2;
  for (const [category, count] of categories) {
    const angle = count / total * Math.PI * 2;
    const gap = Math.min(0.055, angle / 4);
    context.beginPath();
    context.strokeStyle = colors[category] || colors.unknown;
    context.arc(160, 160, 133, start + gap, start + angle - gap);
    context.stroke();
    start += angle;
  }
  canvas.setAttribute("aria-label", categories.length ? categories.map(([category, count]) => `${labels[category]}: ${count}`).join(", ") : "No failure data");
}

async function loadBuilds() {
  const sequence = ++state.sequence;
  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  for (const [id, key] of [["search", "search"], ["status-filter", "status"], ["category-filter", "category"]]) {
    if (byId(id).value.trim()) params.set(key, byId(id).value.trim());
  }
  const data = await request(`/api/builds?${params}`);
  if (sequence !== state.sequence) return;
  state.total = data.total;
  if (state.offset && !data.items.length) { state.offset = 0; return loadBuilds(); }
  byId("build-count").textContent = data.total;
  byId("build-rows").innerHTML = data.items.map((build) => `<tr><td><button type="button" class="build-link" data-build="${build.id}">${escapeHTML(build.name)}</button><span class="build-project">${escapeHTML(build.project)}</span></td><td>${statusBadge(build.status)}</td><td><span class="category-text ${escapeHTML(build.category)}">${escapeHTML(labels[build.category])}</span></td><td class="branch">${escapeHTML(build.branch)}</td><td title="${escapeHTML(build.created_at)}">${escapeHTML(dateLabel(build.created_at))}</td><td><button class="icon-button" type="button" data-build="${build.id}" title="View build details" aria-label="View ${escapeHTML(build.name)}"><i data-lucide="chevron-right"></i></button></td></tr>`).join("");
  byId("empty-state").hidden = data.items.length > 0;
  const filtered = params.has("search") || params.has("status") || params.has("category");
  byId("empty-title").textContent = filtered ? "No matching builds" : "No builds yet";
  byId("empty-copy").textContent = filtered ? "No results for the current filters." : "Your build history starts here.";
  byId("load-demo").hidden = filtered || (state.metrics?.total || 0) > 0;
  byId("page-label").textContent = data.total ? `${state.offset + 1}–${Math.min(state.offset + state.limit, data.total)} of ${data.total} builds` : "0 builds";
  byId("previous").disabled = state.offset === 0;
  byId("next").disabled = state.offset + state.limit >= data.total;
  icons();
}

async function refresh() {
  byId("refresh").disabled = true;
  try {
    renderMetrics(await request("/api/metrics"));
    await loadBuilds();
    byId("connection-error").hidden = true;
    byId("connection-dot").className = "dot green";
    byId("connection-text").textContent = "API connected";
    byId("updated-at").textContent = `Synced ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  } catch (error) {
    byId("connection-error").hidden = false;
    byId("connection-error").querySelector("span").textContent = `Cannot load dashboard. ${error.message}`;
    byId("connection-dot").className = "dot red";
    byId("connection-text").textContent = "API unavailable";
  } finally { byId("refresh").disabled = false; }
}

async function openBuild(id) {
  try {
    const build = await request(`/api/builds/${id}`);
    state.selected = build;
    byId("detail-title").textContent = build.name;
    byId("detail-project").textContent = build.project;
    byId("detail-content").innerHTML = `<dl class="detail-meta"><div><dt>Status</dt><dd>${statusBadge(build.status)}</dd></div><div><dt>Failure category</dt><dd>${escapeHTML(labels[build.category])}</dd></div><div><dt>Failed stage</dt><dd>${escapeHTML(build.failed_stage || "Not identified")}</dd></div><div><dt>Branch</dt><dd>${escapeHTML(build.branch)}</dd></div><div><dt>Analyzed</dt><dd>${escapeHTML(dateLabel(build.created_at))}</dd></div><div><dt>Log lines</dt><dd>${build.line_count.toLocaleString()}</dd></div></dl><section class="detail-section"><h3>Possible cause</h3><p>${escapeHTML(build.summary)}</p></section><section class="detail-section"><h3>Failed tests <span class="count-badge">${build.failed_tests.length}</span></h3>${build.failed_tests.length ? `<ul class="detail-tests">${build.failed_tests.map((test) => `<li>${escapeHTML(test)}</li>`).join("")}</ul>` : '<p>No failed test names extracted.</p>'}</section><section class="detail-section"><h3>Matching log evidence</h3><pre class="evidence">${build.evidence.length ? build.evidence.map((item) => `${String(item.line).padStart(4, " ")}  ${escapeHTML(item.text)}`).join("\n") : "No matching failure evidence."}</pre></section><p class="detail-footer">Heuristic analysis, not a confirmed root cause. Raw log not retained.</p>`;
    if (!byId("detail-dialog").open) byId("detail-dialog").showModal();
  } catch (error) { notify(error.message, true); }
}

function setMode(mode) {
  state.mode = mode;
  byId("file-mode").setAttribute("aria-pressed", mode === "file");
  byId("paste-mode").setAttribute("aria-pressed", mode === "paste");
  byId("file-zone").hidden = mode !== "file";
  byId("paste-zone").hidden = mode !== "paste";
  byId("log-file").disabled = mode !== "file";
  byId("log-file").required = mode === "file";
  const textarea = byId("upload-form").elements.log;
  textarea.disabled = mode !== "paste";
  textarea.required = mode === "paste";
}

async function submitLog(event) {
  event.preventDefault();
  byId("upload-error").hidden = true;
  const form = byId("upload-form");
  const submit = byId("submit-log");
  submit.disabled = true;
  submit.textContent = "Analyzing...";
  try {
    const data = new FormData(form);
    let result;
    if (state.mode === "file") {
      if (byId("log-file").files[0].size > 2 * 1024 * 1024) throw new Error("Logs must be at most 2 MiB.");
      result = await request("/api/builds/upload", { method: "POST", body: data });
    } else {
      const payload = Object.fromEntries(data);
      if (new Blob([payload.log]).size > 2 * 1024 * 1024) throw new Error("Logs must be at most 2 MiB.");
      result = await request("/api/builds", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    }
    byId("upload-dialog").close();
    form.reset();
    byId("file-label").textContent = "Choose console log";
    clearFilters();
    await refresh();
    notify("Build analyzed and saved.");
    await openBuild(result.id);
  } catch (error) {
    byId("upload-error").textContent = error.message;
    byId("upload-error").hidden = false;
  } finally {
    submit.disabled = false;
    submit.innerHTML = '<i data-lucide="scan-line"></i>Analyze build';
    icons();
  }
}

function clearFilters() {
  for (const id of ["search", "status-filter", "category-filter"]) byId(id).value = "";
  state.offset = 0;
}

function filterBuilds() {
  state.offset = 0;
  loadBuilds().catch((error) => notify(error.message, true));
}

document.addEventListener("click", (event) => {
  const buildButton = event.target.closest("[data-build]");
  if (buildButton) openBuild(buildButton.dataset.build);
  const closeButton = event.target.closest("[data-close]");
  if (closeButton) byId(closeButton.dataset.close).close();
  const categoryButton = event.target.closest("[data-category]");
  if (categoryButton) {
    clearFilters();
    byId("category-filter").value = categoryButton.dataset.category;
    filterBuilds();
    byId("builds").scrollIntoView({ behavior: "smooth" });
  }
});

byId("open-upload").addEventListener("click", () => { byId("upload-error").hidden = true; byId("upload-dialog").showModal(); });
byId("file-mode").addEventListener("click", () => setMode("file"));
byId("paste-mode").addEventListener("click", () => setMode("paste"));
byId("log-file").addEventListener("change", () => { byId("file-label").textContent = byId("log-file").files[0]?.name || "Choose console log"; });
byId("upload-form").addEventListener("submit", submitLog);
byId("refresh").addEventListener("click", refresh);
byId("retry").addEventListener("click", refresh);
byId("search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(filterBuilds, 250); });
for (const id of ["status-filter", "category-filter"]) byId(id).addEventListener("change", filterBuilds);
byId("clear-filters").addEventListener("click", () => { clearFilters(); filterBuilds(); });
byId("previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadBuilds().catch((error) => notify(error.message, true)); });
byId("next").addEventListener("click", () => { state.offset += state.limit; loadBuilds().catch((error) => notify(error.message, true)); });
byId("load-demo").addEventListener("click", async () => {
  byId("load-demo").disabled = true;
  byId("load-demo").textContent = "Loading samples...";
  let added = 0;
  try {
    const samples = await request("/static/sample-builds.json");
    for (const sample of samples) {
      await request("/api/builds", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sample) });
      added += 1;
    }
    notify(`${added} synthetic sample builds loaded.`);
  } catch (error) { notify(`${added} samples saved. ${error.message}`, true); }
  finally {
    await refresh();
    byId("load-demo").disabled = false;
    byId("load-demo").innerHTML = '<i data-lucide="database"></i>Load sample builds';
    icons();
  }
});
byId("export-build").addEventListener("click", () => {
  if (!state.selected) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(state.selected, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `build-${state.selected.id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
byId("delete-build").addEventListener("click", () => byId("delete-dialog").showModal());
byId("confirm-delete").addEventListener("click", async () => {
  if (!state.selected) return;
  byId("confirm-delete").disabled = true;
  try {
    await request(`/api/builds/${state.selected.id}`, { method: "DELETE" });
    byId("delete-dialog").close();
    byId("detail-dialog").close();
    state.selected = null;
    await refresh();
    notify("Build deleted.");
  } catch (error) { notify(error.message, true); }
  finally { byId("confirm-delete").disabled = false; }
});
function syncNavigation() {
  const hash = location.hash || "#overview";
  document.querySelectorAll("nav .nav-link").forEach((link) => {
    const active = link.getAttribute("href") === hash;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  });
}
window.addEventListener("hashchange", syncNavigation);
syncNavigation();
icons();
refresh();