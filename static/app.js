const $ = (id) => document.getElementById(id);
const state = { file: null, html: "", stack: "html", previewUrl: null, versionId: null };
const ACCEPTED = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);
const MAX_BYTES = 10 * 1024 * 1024;

function showError(m) { const e = $("errorBox"); e.hidden = !m; e.textContent = m || ""; }
function setLoading(on, t) { $("loading").hidden = !on; if (t) $("loadingText").textContent = t; }
async function refreshStatus() {
  try {
    const r = await fetch("/api/status");
    const j = await r.json();
    const pill = $("statusPill");
    if (j.has_key) { pill.textContent = "key ✓"; pill.className = "pill on"; }
    else { pill.textContent = "no key"; pill.className = "pill off"; }
  } catch { /* offline */ }
}
function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function reactPreviewShell(jsx) {
  return "<!doctype html><html><body style=\"font-family:monospace;padding:24px;background:#f4f7ff;color:#0b2a5c\">"
    + "<h2>React+Tailwind component (preview not rendered offline)</h2>"
    + "<p>JSX cannot render without a React/Babel toolchain, and no external CDN is used so the app works offline. "
    + "The component source is shown below and in the Code tab — paste it into a React + Tailwind project.</p>"
    + "<pre style=\"white-space:pre-wrap;word-break:break-word;background:#0b2a5c;color:#f4f7ff;padding:14px\">"
    + escHtml(jsx) + "</pre></body></html>";
}
function setHtml(html, stack) {
  state.html = html;
  state.stack = stack || state.stack || "html";
  if (state.stack === "react") {
    $("previewFrame").srcdoc = reactPreviewShell(html);
  } else {
    $("previewFrame").srcdoc = html;
  }
  $("emptyState").style.display = "none";
  $("codeEl").textContent = html;
  $("copyBtn").disabled = false;
  $("downloadBtn").disabled = false;
}
function setFile(f) {
  if (f) {
    // client-side guard mirrors server limits so bad drops fail fast
    if (f.type && !ACCEPTED.has(f.type)) { showError(`Unsupported file “${f.type}”. Use JPG, PNG, WEBP or GIF.`); return; }
    if (f.size > MAX_BYTES) { showError(`Image too large (${(f.size / 1048576).toFixed(1)} MB). Max is 10 MB.`); return; }
    showError("");
  }
  // revoke previous object URL (fixes leak on repeated uploads)
  if (state.previewUrl) { URL.revokeObjectURL(state.previewUrl); state.previewUrl = null; }
  state.file = f;
  if (f) {
    const url = URL.createObjectURL(f);
    state.previewUrl = url;
    const img = $("previewImg"); img.src = url; img.hidden = false;
    $("uploadMeta").textContent = `${f.name} · ${(f.size / 1024).toFixed(1)} KB`;
  } else {
    $("previewImg").hidden = true; $("previewImg").removeAttribute("src");
    $("uploadMeta").textContent = "";
  }
}

const dz = $("dropzone"), fi = $("fileInput");
$("browseBtn").addEventListener("click", (e) => { e.stopPropagation(); fi.click(); });
dz.addEventListener("click", () => fi.click());
fi.addEventListener("change", () => { if (fi.files[0]) setFile(fi.files[0]); fi.value = ""; });
["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) setFile(f); });
dz.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fi.click(); }
  if (e.key === "Escape") { dz.blur(); }
});

$("clearBtn").addEventListener("click", () => {
  setFile(null); fi.value = ""; $("styleHint").value = ""; $("refineInput").value = "";
  state.html = ""; state.stack = $("stackSelect").value || "html"; state.versionId = null;
  $("previewFrame").removeAttribute("srcdoc");
  $("emptyState").style.display = "flex"; $("codeEl").textContent = "";
  $("copyBtn").disabled = true; $("downloadBtn").disabled = true; showError("");
});

async function fetchVersions() {
  const sel = $("versionSelect"), meta = $("versionMeta");
  try {
    const r = await fetch("/api/versions");
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Versions failed (${r.status})`);
    const list = j.versions || [];
    sel.innerHTML = "";
    if (!list.length) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = "No versions yet — generate first";
      sel.appendChild(o);
      $("restoreBtn").disabled = true;
      meta.textContent = "";
      return;
    }
    for (const v of list.slice().reverse()) {
      const o = document.createElement("option");
      const when = (v.timestamp || "").slice(0, 19).replace("T", " ");
      o.value = v.id;
      o.textContent = `${v.label} · ${v.stack || "html"} · ${when}${v.current ? " ●" : ""}`;
      if (v.id === state.versionId || v.current) o.selected = true;
      sel.appendChild(o);
    }
    if (!sel.value && sel.options.length) sel.selectedIndex = 0;
    $("restoreBtn").disabled = !sel.value;
    const cur = list.find((v) => v.id === sel.value);
    meta.textContent = cur ? `${cur.id} · prompt: ${(cur.prompt || "—").slice(0, 120)}` : "";
  } catch (e) { meta.textContent = e.message; }
}
$("versionSelect").addEventListener("change", () => {
  $("restoreBtn").disabled = !$("versionSelect").value;
  fetchVersionsMetaOnly();
});
async function fetchVersionsMetaOnly() {
  try {
    const r = await fetch("/api/versions");
    const j = await r.json().catch(() => ({}));
    const cur = (j.versions || []).find((v) => v.id === $("versionSelect").value);
    if (cur) $("versionMeta").textContent = `${cur.id} · ${cur.label} · ${cur.stack} · prompt: ${(cur.prompt || "—").slice(0, 120)}`;
  } catch { /* ignore */ }
}
$("refreshVersionsBtn").addEventListener("click", fetchVersions);
$("restoreBtn").addEventListener("click", async () => {
  showError("");
  const vid = $("versionSelect").value;
  if (!vid) { showError("Pick a version first."); return; }
  $("restoreBtn").disabled = true;
  setLoading(true, "Restoring version…");
  try {
    const r = await fetch(`/api/versions/${encodeURIComponent(vid)}/restore`, { method: "POST" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Restore failed (${r.status})`);
    setHtml(j.html, j.stack || "html");
    state.versionId = j.version_id || vid;
    if ($("stackSelect") && j.stack) $("stackSelect").value = j.stack;
    activateTab("preview");
    await fetchVersions();
  } catch (e) { showError(e.message); }
  finally { setLoading(false); $("restoreBtn").disabled = !$("versionSelect").value; }
});

$("generateBtn").addEventListener("click", async () => {
  showError("");
  if (!state.file) { showError("Upload a screenshot first (JPG/PNG/WEBP/GIF)."); dz.focus(); return; }
  $("generateBtn").disabled = true;
  setLoading(true, "Generating site from screenshot…");
  try {
    const fd = new FormData();
    fd.append("image", state.file);
    fd.append("style_hint", $("styleHint").value || "");
    fd.append("stack", $("stackSelect").value || "html");
    const r = await fetch("/api/generate", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
    setHtml(j.html, j.stack || $("stackSelect").value || "html");
    state.versionId = j.version_id || null;
    activateTab("preview");
    await fetchVersions();
  } catch (e) { showError(e.message); }
  finally { setLoading(false); $("generateBtn").disabled = false; }
});

$("refineBtn").addEventListener("click", async () => {
  showError("");
  const ins = $("refineInput").value.trim();
  if (!state.html) { showError("Generate a site first, then refine it."); return; }
  if (!ins) { showError("Describe the change first."); $("refineInput").focus(); return; }
  $("refineBtn").disabled = true;
  setLoading(true, "Refining…");
  try {
    const r = await fetch("/api/refine", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html: state.html, instruction: ins, stack: state.stack || "html" }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
    setHtml(j.html, j.stack || state.stack || "html");
    state.versionId = j.version_id || null;
    await fetchVersions();
  } catch (e) { showError(e.message); }
  finally { setLoading(false); $("refineBtn").disabled = false; }
});

function activateTab(which) {
  const isPrev = which === "preview";
  $("tabPreview").classList.toggle("active", isPrev);
  $("tabCode").classList.toggle("active", !isPrev);
  $("panePreview").hidden = !isPrev;
  $("paneCode").hidden = isPrev;
}
$("tabPreview").addEventListener("click", () => activateTab("preview"));
$("tabCode").addEventListener("click", () => activateTab("code"));

$("copyBtn").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(state.html); $("copyBtn").textContent = "✓ Copied"; setTimeout(() => $("copyBtn").textContent = "⧉ Copy", 1500); }
  catch { showError("Copy blocked by browser — select the code manually."); }
});
$("downloadBtn").addEventListener("click", () => {
  const ext = state.stack === "react" ? "jsx" : "html";
  const mime = state.stack === "react" ? "text/jsx" : "text/html";
  const blob = new Blob([state.html], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `shot-to-site.${ext}`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
});

// settings modal — key lives only in server memory, never in browser storage
$("settingsBtn").addEventListener("click", () => { $("settingsModal").hidden = false; $("keyInput").value = ""; $("keyMsg").textContent = ""; $("keyInput").focus(); });
$("closeSettingsBtn").addEventListener("click", () => $("settingsModal").hidden = true);
$("settingsModal").addEventListener("keydown", (e) => { if (e.key === "Escape") $("settingsModal").hidden = true; });
$("removeKeyBtn").addEventListener("click", async () => {
  try {
    await fetch("/api/key", { method: "DELETE" });
  } catch { /* offline */ }
  $("keyInput").value = ""; $("keyMsg").textContent = "Key removed from server memory."; refreshStatus();
});
$("saveKeyBtn").addEventListener("click", async () => {
  const k = $("keyInput").value.trim();
  if (!k) { $("keyMsg").textContent = "Paste a key first."; return; }
  $("keyMsg").textContent = "Verifying…";
  $("saveKeyBtn").disabled = true;
  try {
    const r = await fetch("/api/key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: k }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) throw new Error(j.error || `Verify failed (${r.status})`);
    $("keyInput").value = "";
    $("keyMsg").textContent = "✓ Key verified & saved in server memory.";
refreshStatus();
fetchVersions();
  } catch (e) { $("keyMsg").textContent = e.message; }
  finally { $("saveKeyBtn").disabled = false; }
});

refreshStatus();
