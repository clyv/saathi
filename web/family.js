/* Family settings page. */
"use strict";
const $ = (id) => document.getElementById(id);
const form = $("settingsForm");
let current = null;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// --------------------------------------------------------------- status ----
async function refreshStatus() {
  const ul = $("checks");
  ul.innerHTML = "<li>Checking…</li>";
  let st;
  try { st = await (await fetch("/api/status")).json(); }
  catch { ul.innerHTML = '<li class="bad">The Saathi server is not responding. Start it with start.bat / start.sh.</li>'; return; }
  const items = [];
  if (!st.ollama.reachable) items.push(["bad", "Ollama is not running. Install it from ollama.com and open the app (it runs in the background)."]);
  else if (!st.ollama.model_present) items.push(["bad", `Ollama is running, but <code>${esc(st.ollama.model)}</code> is not downloaded. Run <code>ollama pull ${esc(st.ollama.model)}</code> or <code>python scripts/setup.py</code>.` +
      (st.ollama.installed.length ? ` Installed: ${st.ollama.installed.map((n) => `<code>${esc(n)}</code>`).join(" ")}` : "")]);
  else items.push(["ok", `Gemma is ready: <code>${esc(st.ollama.model)}</code> running locally in Ollama` +
      (st.ollama.loaded ? " (loaded in memory)." : " (it loads when the call window opens).")]);
  const note = st.stt.note ? ` <span class="hint">${esc(st.stt.note)}</span>` : "";
  if (st.stt.engine === "gemma") {
    items.push(["ok", `Listening: Gemma hears them directly, offline.` +
      (st.stt.whisper ? ` Whisper <code>${esc(st.stt.model)}</code> is the backup.` : " (No Whisper backup downloaded; that's fine.)") + note]);
  } else if (st.stt.whisper) {
    items.push(["ok", `Listening: Whisper <code>${esc(st.stt.model)}</code> on ${esc(st.stt.device.toUpperCase())}, offline.` +
      (st.stt.chosen === "gemma" && st.ollama.model_present ? ` <code>${esc(st.ollama.model)}</code> has no audio input, so Whisper listens instead.` : "") + note]);
  } else {
    items.push(["bad", `Nothing can listen yet: <code>${esc(st.ollama.model)}</code> can't take audio and Whisper isn't downloaded. Use <code>gemma4:e4b</code> or <code>e2b</code>, or run <code>python scripts/setup.py</code>.`]);
  }
  if (st.ollama.model_present) {
    items.push(st.ollama.sees
      ? ["ok", "Seeing: they can show Saathi things on the laptop camera (the दिखाइए button). Pictures are never saved."]
      : ["warn", `<code>${esc(st.ollama.model)}</code> can't see pictures, so the दिखाइए button is hidden.`]);
  }
  items.push(st.tts.available
    ? ["ok", `Hindi voice installed: <code>${esc(st.tts.voice)}</code>.`]
    : ["warn", `Voice <code>${esc(st.tts.voice)}</code> is not installed. Saathi will try the browser's Hindi voice. Run <code>python scripts/setup.py</code>.`]);
  items.push(["ok", `Conversations and memories are stored in <code>${esc(st.data_dir)}</code>. Nothing is sent anywhere.`]);
  ul.innerHTML = items.map(([cls, html]) => `<li class="${cls}"><span>${html}</span></li>`).join("");
}

// ------------------------------------------------------------- settings ----
function setField(name, value) {
  const el = form.elements[name];
  if (!el) return;
  if (el.type === "checkbox") el.checked = !!value;
  else el.value = value ?? "";
}

function addMember(m = {}) {
  const row = $("memberRow").content.firstElementChild.cloneNode(true);
  row.querySelectorAll("input").forEach((inp) => { inp.value = m[inp.dataset.k] || ""; });
  row.querySelector("button").addEventListener("click", () => row.remove());
  $("members").appendChild(row);
}

function fillVoices(voices, installed) {
  const sel = $("voiceSelect");
  sel.innerHTML = Object.entries(voices).map(([id, label]) =>
    `<option value="${esc(id)}">${esc(label)}${installed.includes(id) ? "" : " (not downloaded)"}</option>`).join("");
  const extra = installed.filter((id) => !(id in voices));
  extra.forEach((id) => sel.insertAdjacentHTML("beforeend", `<option value="${esc(id)}">${esc(id)}</option>`));
}

function render(s) {
  current = s;
  fillVoices(s.voices, s.voices_installed);
  for (const [k, v] of Object.entries(s.profile)) if (k !== "family") setField(`profile.${k}`, v);
  for (const [k, v] of Object.entries(s.config)) setField(`config.${k}`, v);
  $("members").innerHTML = "";
  (s.profile.family.length ? s.profile.family : [{}]).forEach(addMember);
  updateSpeed();
  updateVoiceNote();
}

function collect() {
  const out = { profile: {}, config: {} };
  for (const el of form.elements) {
    if (!el.name || !el.name.includes(".")) continue;
    const [group, key] = el.name.split(".");
    let v = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "range" || el.type === "number") v = Number(v);
    out[group][key] = v;
  }
  out.profile.family = [...$("members").querySelectorAll(".member")].map((row) => {
    const m = {};
    row.querySelectorAll("input").forEach((inp) => { m[inp.dataset.k] = inp.value.trim(); });
    return m;
  }).filter((m) => m.name);
  return out;
}

function updateSpeed() {
  const v = Number(form.elements["config.speech_speed"].value);
  $("speedValue").textContent = v < 0.97 ? `(${v.toFixed(2)}, slower)` : v > 1.03 ? `(${v.toFixed(2)}, faster)` : "(normal)";
}

function updateVoiceNote() {
  const avatar = form.elements["profile.avatar"].value;
  const voice = form.elements["config.voice"].value;
  const female = /priyamvada/.test(voice);
  $("voiceNote").textContent = (avatar === "didi") === female ? "" :
    `Tip: the "${avatar === "didi" ? "Didi" : "Bhaiya"}" face with a ${female ? "female" : "male"} voice may feel odd.`;
}

async function save(e) {
  e.preventDefault();
  $("saveNote").textContent = "Saving…";
  const r = await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collect()) });
  if (!r.ok) { $("saveNote").textContent = "Could not save. Check the values and try again."; return; }
  render(await r.json());
  $("saveNote").textContent = "Saved ✓  The next call will use these settings.";
  refreshStatus();
}

async function testVoice() {
  const name = form.elements["profile.address_as"].value || "जी";
  const text = `नमस्ते ${name}! मैं साथी हूँ। आज आपका दिन कैसा रहा?`;
  $("testNote").textContent = "Generating…";
  const r = await fetch("/api/speak", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice: form.elements["config.voice"].value, speed: Number(form.elements["config.speech_speed"].value) }),
  });
  if (!r.ok) { $("testNote").textContent = "This voice is not downloaded yet. Run python scripts/setup.py."; return; }
  const url = URL.createObjectURL(await r.blob());
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  audio.play();
  $("testNote").textContent = "";
}

// ------------------------------------------------- messages and memories ----
async function loadMessages() {
  const items = await (await fetch("/api/family-messages")).json();
  $("messages").innerHTML = items.length ? items.slice().reverse().map((m) => `
    <li><div><strong>${esc(m.from_name)}</strong>${m.relation ? ` <span class="meta">(${esc(m.relation)})</span>` : ""}
      ${m.delivered ? `<span class="pill done">told on ${esc(m.delivered)}</span>` : '<span class="pill">waiting for next call</span>'}
      <div>${esc(m.text)}</div><div class="meta">added ${esc(m.created)}</div></div>
      <button class="icon-btn" data-del-msg="${esc(m.id)}" title="Delete">✕</button></li>`).join("")
    : '<li class="empty">No messages yet.</li>';
}

async function loadMemories() {
  const items = await (await fetch("/api/memories")).json();
  $("memories").innerHTML = items.length ? items.slice().reverse().map((m) => `
    <li><div><div lang="hi">${esc(m.text)}</div><div class="meta">${esc(m.date)}</div></div>
      <button class="icon-btn" data-del-mem="${esc(m.id)}" title="Forget this">✕</button></li>`).join("")
    : '<li class="empty">Nothing yet. Saathi starts remembering after the first few conversations.</li>';
}

document.addEventListener("click", async (e) => {
  const msg = e.target.closest("[data-del-msg]");
  const mem = e.target.closest("[data-del-mem]");
  if (msg) { await fetch(`/api/family-messages/${msg.dataset.delMsg}`, { method: "DELETE" }); loadMessages(); }
  if (mem) { await fetch(`/api/memories/${mem.dataset.delMem}`, { method: "DELETE" }); loadMemories(); }
});

$("msgForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  const r = await fetch("/api/family-messages", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  if (r.ok) { e.target.reset(); loadMessages(); }
});

$("clearHistory").addEventListener("click", async () => {
  if (!confirm("Forget the recent conversation? Saved memories below are kept; delete them one by one if you want.")) return;
  await fetch("/api/history/clear", { method: "POST" });
  alert("Recent conversation forgotten.");
});

// ------------------------------------------------------------------ init ----
form.addEventListener("submit", save);
form.elements["config.speech_speed"].addEventListener("input", updateSpeed);
form.elements["profile.avatar"].addEventListener("change", updateVoiceNote);
$("voiceSelect").addEventListener("change", updateVoiceNote);
$("addMember").addEventListener("click", () => addMember());
$("testVoice").addEventListener("click", testVoice);
$("refreshStatus").addEventListener("click", refreshStatus);

(async () => {
  render(await (await fetch("/api/settings")).json());
  refreshStatus();
  loadMessages();
  loadMemories();
})();
