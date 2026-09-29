const $ = (id) => document.getElementById(id);
const state = { file: null, html: "", key: sessionStorage.getItem("groq_key") || "" };

function showError(m) { const e = $("errorBox"); e.hidden = !m; e.textContent = m || ""; }
function setLoading(on, t) { $("loading").hidden = !on; if (t) $("loadingText").textContent = t; }
async function refreshStatus() {
  try {
    const headers = state.key ? { "X-Groq-Key": state.key } : {};
    const r = await fetch("/api/status", { headers });
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
  state.file = f;
  if (f) {
    const url = URL.createObjectURL(f);
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
fi.addEventListener("change", () => { if (fi.files[0]) setFile(fi.files[0]); });
["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) setFile(f); });
dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") fi.click(); });

$("clearBtn").addEventListener("click", () => {
  setFile(null); fi.value = ""; $("styleHint").value = ""; $("refineInput").value = "";
  state.html = ""; $("previewFrame").removeAttribute("srcdoc");
  $("emptyState").style.display = "flex"; $("codeEl").textContent = "";
  $("copyBtn").disabled = true; $("downloadBtn").disabled = true; showError("");
});

$("generateBtn").addEventListener("click", async () => {
  showError("");
  if (!state.file) { showError("Upload a screenshot first (JPG/PNG/WEBP/GIF)."); return; }
  setLoading(true, "Generating site from screenshot…");
  try {
    const fd = new FormData();
    fd.append("image", state.file);
    fd.append("style_hint", $("styleHint").value || "");
    if (state.key) fd.append("api_key", state.key);
    const r = await fetch("/api/generate", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
    setHtml(j.html);
    activateTab("preview");
  } catch (e) { showError(e.message); }
  finally { setLoading(false); }
});

$("refineBtn").addEventListener("click", async () => {
  showError("");
  const ins = $("refineInput").value.trim();
  if (!state.html) { showError("Generate a site first, then refine it."); return; }
  if (!ins) { showError("Describe the change first."); return; }
  setLoading(true, "Refining…");
  try {
    const r = await fetch("/api/refine", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html: state.html, instruction: ins, api_key: state.key || undefined }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
    setHtml(j.html);
  } catch (e) { showError(e.message); }
  finally { setLoading(false); }
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
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "shot-to-site.html"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
});

// settings modal
$("settingsBtn").addEventListener("click", () => { $("settingsModal").hidden = false; $("keyInput").value = state.key; $("keyMsg").textContent = state.key ? "Key loaded from session memory." : ""; });
$("closeSettingsBtn").addEventListener("click", () => $("settingsModal").hidden = true);
$("removeKeyBtn").addEventListener("click", () => { state.key = ""; sessionStorage.removeItem("groq_key"); $("keyInput").value = ""; $("keyMsg").textContent = "Key removed from session."; refreshStatus(); });
$("saveKeyBtn").addEventListener("click", async () => {
  const k = $("keyInput").value.trim();
  if (!k) { $("keyMsg").textContent = "Paste a key first."; return; }
  $("keyMsg").textContent = "Verifying…";
  try {
    const r = await fetch("/api/verify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: k }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) throw new Error(j.error || `Verify failed (${r.status})`);
    state.key = k; sessionStorage.setItem("groq_key", k);
    $("keyMsg").textContent = "✓ Key verified & saved (session only).";
    refreshStatus();
  } catch (e) { $("keyMsg").textContent = e.message; }
});

refreshStatus();
