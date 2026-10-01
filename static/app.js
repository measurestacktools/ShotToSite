const $ = (id) => document.getElementById(id);
const state = { file: null, html: "", previewUrl: null };
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
function setHtml(html) {
  state.html = html;
  $("previewFrame").srcdoc = html;
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
  state.html = ""; $("previewFrame").removeAttribute("srcdoc");
  $("emptyState").style.display = "flex"; $("codeEl").textContent = "";
  $("copyBtn").disabled = true; $("downloadBtn").disabled = true; showError("");
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
    const r = await fetch("/api/generate", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
    setHtml(j.html);
    activateTab("preview");
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
      body: JSON.stringify({ html: state.html, instruction: ins }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
    setHtml(j.html);
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
  const blob = new Blob([state.html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "shot-to-site.html";
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
  } catch (e) { $("keyMsg").textContent = e.message; }
  finally { $("saveKeyBtn").disabled = false; }
});

refreshStatus();
