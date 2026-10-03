/* Saathi call screen.
 * Flow: greet -> speak -> listen -> think -> speak -> listen ... until "कॉल खत्म".
 * Replies stream in from Gemma; each finished sentence is turned into speech right away,
 * so Saathi starts talking before the whole answer is written.
 */
"use strict";
const $ = (id) => document.getElementById(id);

const NO_SPEECH_MS = 10000;   // stop listening if she says nothing for this long
const END_SILENCE_MS = 1600;  // a pause this long means she has finished speaking
const MIN_SPEECH_MS = 250;    // ignore shorter blips (a cough, a door)
const MAX_LISTEN_MS = 30000;   // Gemma hears clips of up to about 30 seconds
const KEEP_WARM_MS = 10 * 60 * 1000;   // while this window is open, keep Gemma loaded

const S = {
  settings: null, status: null, phase: "precall",
  audioCtx: null, outAnalyser: null,
  mic: null, micAnalyser: null, micAvailable: false, sttAvailable: true,
  queue: [], playing: false, streamDone: true, currentSource: null, browserSpeaking: false,
  abort: null, generation: 0, lastSentences: [], noAutoListen: false,
  ttsMode: "piper",             // piper -> browser -> none (falls back automatically)
  rec: null, recInfo: null, vadTimer: null, missedHeard: 0,
  callStart: 0, timer: null,
};

const female = () => (S.settings?.profile?.avatar || "bhaiya") === "didi";
const myVerb = (m, f) => (female() ? f : m);   // Saathi's own verb endings follow its face

// ------------------------------------------------------------------ setup ----
async function loadSettings() {
  S.settings = await (await fetch("/api/settings")).json();
  const { profile, config } = S.settings;
  document.body.className = `size-${config.text_size}` + (document.body.classList.contains("in-call") ? " in-call" : "");
  $("avatar").classList.remove("didi", "bhaiya");
  $("avatar").classList.add(profile.avatar || "bhaiya");
  const name = profile.companion_name || "साथी";
  $("companionName").textContent = name;
  document.title = name;
  $("helloText").textContent = `नमस्ते ${S.settings.address}!`.replace("नमस्ते आप!", "नमस्ते!");
  $("helloSub").textContent = `${name} आपसे बात करने के लिए तैयार है।`;
}

async function checkSetup() {
  try {
    S.status = await (await fetch("/api/status")).json();
  } catch { return; }
  const st = S.status, notes = [];
  if (!st.ollama.reachable) notes.push("Ollama is not running. Open the Ollama app, then reload this page.");
  else if (!st.ollama.model_present) notes.push(`Gemma model "${st.ollama.model}" is not downloaded. Run: python scripts/setup.py`);
  if (!st.stt.available) { S.sttAvailable = false; notes.push("Listening is off (Whisper model missing), so she can only type. Run: python scripts/setup.py"); }
  if (!st.tts.available) notes.push("Hindi voice not installed; using the browser's voice if there is one. Run: python scripts/setup.py");
  if (notes.length) {
    $("setupWarning").hidden = false;
    $("setupWarning").textContent = "For family: " + notes.join(" ");
  }
}

/** Gemma takes a while to load into memory. Show it on the start screen, but never block the button. */
async function watchReady() {
  const note = $("readyNote");
  const t0 = Date.now();
  while (S.phase === "precall") {
    try { S.status = await (await fetch("/api/status")).json(); } catch { /* server starting */ }
    const o = S.status?.ollama;
    if (o?.loaded) { note.className = "ready ok"; note.textContent = `${S.settings?.profile?.companion_name || "साथी"} तैयार है`; return; }
    if (o && (!o.reachable || !o.model_present)) { note.textContent = ""; return; }   // the setup warning explains
    if (Date.now() - t0 > 180000) { note.textContent = ""; return; }
    note.className = "ready warming";
    note.textContent = "तैयार हो रहे हैं…";
    await new Promise((r) => setTimeout(r, 2000));
  }
}

function keepWarm() {
  fetch("/api/warmup", { method: "POST" }).catch(() => {});
}

function initAudio() {
  if (S.audioCtx) return S.audioCtx.resume();
  S.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  S.outAnalyser = S.audioCtx.createAnalyser();
  S.outAnalyser.fftSize = 1024;
  S.outAnalyser.connect(S.audioCtx.destination);
  return S.audioCtx.resume();
}

async function initMic() {
  if (S.mic || !S.sttAvailable) { S.micAvailable = !!S.mic && S.sttAvailable; return; }
  try {
    S.mic = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const src = S.audioCtx.createMediaStreamSource(S.mic);
    S.micAnalyser = S.audioCtx.createAnalyser();
    S.micAnalyser.fftSize = 1024;
    src.connect(S.micAnalyser);           // analysed only, never played back
    S.micAvailable = true;
  } catch {
    S.micAvailable = false;
  }
}

// ------------------------------------------------------------------ phase ----
const STATUS_TEXT = {
  thinking: '<span class="dots">सोच रहे हैं</span>',
  transcribing: '<span class="dots">समझ रहे हैं</span>',
  listening: "सुन रहे हैं… आराम से बोलिए",
  speaking: "&nbsp;",
  idle: "बोलने के लिए हरा बटन दबाइए",
  error: "&nbsp;",
};

function setPhase(phase, statusHtml) {
  S.phase = phase;
  $("avatarWrap").dataset.phase = phase === "transcribing" ? "thinking" : phase;
  $("status").innerHTML = statusHtml ?? STATUS_TEXT[phase] ?? "&nbsp;";
  const mic = $("micBtn");
  mic.classList.toggle("active", phase === "listening");
  $("micLabel").textContent = phase === "listening" ? "बस, हो गया" : (phase === "speaking" || phase === "thinking") ? "रोकिए, मैं बोलूँ" : "बोलिए";
  const inCall = phase !== "precall" && phase !== "ended";
  mic.disabled = !inCall || !S.micAvailable;
  $("typeBtn").disabled = !inCall;
  $("endBtn").disabled = !inCall;
  $("repeatBtn").disabled = !inCall || S.lastSentences.length === 0;
}

// -------------------------------------------------------------- sentences ----
function cleanText(t) {
  return t.replace(/[*_#`>|~]/g, "").replace(/\s+/g, " ").trim();
}

/** Split finished sentences off the front of the buffer. Returns [sentences, rest]. */
function takeSentences(buf) {
  const out = [];
  let last = 0, m;
  const re = /[।॥!?.\n]+["'”’)]*\s*/g;
  while ((m = re.exec(buf))) {
    const end = m.index + m[0].length;
    const piece = cleanText(buf.slice(last, end));
    if (piece.replace(/[।॥!?.\s]/g, "").length >= 3) { out.push(piece); last = end; }
  }
  let rest = buf.slice(last);
  if (rest.length > 220) {                 // a very long sentence: break at a comma so speech starts
    const cut = Math.max(rest.lastIndexOf(","), rest.lastIndexOf("،"));
    if (cut > 60) { out.push(cleanText(rest.slice(0, cut + 1))); rest = rest.slice(cut + 1); }
  }
  return [out, rest];
}

// ----------------------------------------------------------------- speech ----
function hindiVoice() {
  if (!("speechSynthesis" in window)) return null;
  return speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith("hi")) || null;
}

async function fetchSpeech(text) {
  if (S.ttsMode !== "piper") return null;
  try {
    const r = await fetch("/api/speak", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    if (r.status === 503) { S.ttsMode = hindiVoice() ? "browser" : "none"; return null; }
    if (!r.ok || r.status === 204) return null;
    return await S.audioCtx.decodeAudioData(await r.arrayBuffer());
  } catch {
    return null;
  }
}

function enqueue(text) {
  if (!text) return;
  S.queue.push({ text, gen: S.generation, audio: fetchSpeech(text) });   // start synthesis immediately
  if (!S.playing) playNext();
}

async function playNext() {
  if (S.playing) return;
  const item = S.queue.shift();
  if (!item) {
    if (S.streamDone) finishedSpeaking();
    else if (S.phase === "speaking") setPhase("thinking");   // said the first bit; Gemma is still writing
    return;
  }
  S.playing = true;
  if (item.gen === S.generation) {
    setPhase("speaking");
    $("saathiCaption").textContent = item.text;
    const buf = await item.audio;
    if (item.gen === S.generation) {
      if (buf) await playBuffer(buf);
      else await speakWithoutPiper(item.text);
    }
  }
  S.playing = false;
  playNext();
}

function playBuffer(buf) {
  return new Promise((resolve) => {
    const src = S.audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(S.outAnalyser);
    src.onended = () => { if (S.currentSource === src) S.currentSource = null; resolve(); };
    S.currentSource = src;
    src.start();
  });
}

function speakWithoutPiper(text) {
  if (S.ttsMode === "browser" && "speechSynthesis" in window) {
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "hi-IN";
      const v = hindiVoice();
      if (v) u.voice = v;
      u.rate = S.settings.config.speech_speed;
      S.browserSpeaking = true;
      u.onend = u.onerror = () => { S.browserSpeaking = false; resolve(); };
      speechSynthesis.speak(u);
    });
  }
  // No voice at all: leave the words on screen long enough to read them.
  return new Promise((resolve) => setTimeout(resolve, Math.min(9000, 1500 + text.length * 70)));
}

function stopSpeaking() {
  S.generation += 1;                       // anything queued or in flight is now stale
  S.queue = [];
  if (S.abort) { S.abort.abort(); S.abort = null; }
  if (S.currentSource) { try { S.currentSource.stop(); } catch { /* already stopped */ } }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  S.streamDone = true;
}

function finishedSpeaking() {
  if (S.phase === "ended" || S.phase === "precall" || S.phase === "listening") return;
  if (S.noAutoListen) { S.noAutoListen = false; setPhase("idle", S.errorStatus || undefined); S.errorStatus = ""; return; }
  if (S.settings.config.auto_listen && S.micAvailable) setTimeout(() => {
    if (S.phase !== "ended" && !S.playing && S.queue.length === 0) startListening();
  }, 300);
  else setPhase("idle");
}

/** Say a fixed line without asking Gemma (used for "I didn't hear you" and errors). */
function sayLocal(text, { listenAfter = true } = {}) {
  stopSpeaking();
  S.noAutoListen = !listenAfter;
  S.streamDone = true;
  enqueue(text);
}

// --------------------------------------------------------- talking to Gemma ----
async function talk(url, payload, { prelude = "" } = {}) {
  stopSpeaking();
  stopListening(true);
  const gen = ++S.generation;
  const ctrl = new AbortController();
  S.abort = ctrl;
  S.streamDone = false;
  S.lastSentences = [];
  setPhase("thinking");
  if (prelude) enqueue(prelude);           // something to say while Gemma loads
  let buf = "", failed = false;
  try {
    const r = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}), signal: ctrl.signal,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, nl).trim();
        pending = pending.slice(nl + 1);
        if (!line || gen !== S.generation) continue;
        const ev = JSON.parse(line);
        if (ev.type === "delta") {
          buf += ev.text;
          const [sentences, rest] = takeSentences(buf);
          buf = rest;
          for (const s of sentences) { S.lastSentences.push(s); enqueue(s); }
        } else if (ev.type === "alert") {
          showAlert(ev);
        } else if (ev.type === "error") {
          failed = true;
          showError(ev);
        }
      }
    }
    if (!failed && gen === S.generation && cleanText(buf)) {
      const s = cleanText(buf);
      S.lastSentences.push(s);
      enqueue(s);
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    failed = true;
    showError({ code: "network", detail: String(err) });
  } finally {
    if (gen === S.generation && !failed) {
      S.streamDone = true;
      S.abort = null;
      if (!S.playing && S.queue.length === 0) finishedSpeaking();
    }
  }
}

function showError(ev) {
  const forFamily = {
    ollama_offline: "परिवार के लिए: Ollama ऐप चालू नहीं है। उसे खोलकर फिर से कोशिश करें।",
    model_missing: "परिवार के लिए: Gemma मॉडल डाउनलोड नहीं है। scripts/setup.py चलाएँ।",
    network: "परिवार के लिए: Saathi का सर्वर बंद हो गया है। start वाली फ़ाइल फिर से चलाएँ।",
  }[ev.code] || "परिवार के लिए: " + (ev.detail || ev.code || "unknown error").slice(0, 160);
  S.errorStatus = forFamily;
  sayLocal(`माफ़ कीजिए, अभी मैं जवाब नहीं दे पा ${myVerb("रहा", "रही")} हूँ। किसी घर वाले को बुला लीजिए।`, { listenAfter: false });
  setPhase("error", forFamily);
}

// -------------------------------------------------------------- listening ----
function rms(analyser) {
  const data = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
  return Math.sqrt(sum / data.length);
}

function startListening() {
  if (!S.micAvailable) { setPhase("idle", "लिखकर बात करने के लिए 'लिखिए' दबाइए"); return; }
  stopSpeaking();
  stopListening(true);
  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
    .find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
  const rec = new MediaRecorder(S.mic, mime ? { mimeType: mime } : undefined);
  const chunks = [];
  const info = { heard: 0, forced: false, cancelled: false };
  S.rec = rec;
  S.recInfo = info;
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = () => onRecorded(new Blob(chunks, { type: rec.mimeType || "audio/webm" }), info);
  rec.start(200);
  setPhase("listening");

  const t0 = performance.now();
  let floor = null, speechStart = null, lastLoud = 0;
  S.vadTimer = setInterval(() => {
    const now = performance.now();
    const level = rms(S.micAnalyser);
    floor = floor === null ? level : level < floor ? level : floor * 0.995 + level * 0.005;
    const loud = level > Math.max(0.012, floor * 2.8);
    if (loud) { if (speechStart === null) speechStart = now; lastLoud = now; }
    info.heard = speechStart === null ? 0 : lastLoud - speechStart;

    if (speechStart === null && now - t0 > NO_SPEECH_MS) {
      stopListening(true);
      setPhase("idle");
    } else if (speechStart !== null && now - lastLoud > END_SILENCE_MS) {
      if (info.heard >= MIN_SPEECH_MS) stopListening(false);
      else speechStart = null;               // just a blip: keep waiting
    } else if (now - t0 > MAX_LISTEN_MS) {
      stopListening(false);
    }
  }, 50);
}

function stopListening(cancel) {
  if (S.vadTimer) { clearInterval(S.vadTimer); S.vadTimer = null; }
  if (S.rec && S.rec.state !== "inactive") {
    S.recInfo.cancelled = cancel;
    S.rec.stop();
  }
  S.rec = null;
}

async function onRecorded(blob, info) {
  if (info.cancelled || S.phase === "ended") return;
  if (info.heard < MIN_SPEECH_MS && !info.forced) { setPhase("idle"); return; }
  setPhase("transcribing");
  const form = new FormData();
  form.append("audio", blob, blob.type.includes("ogg") ? "speech.ogg" : "speech.webm");
  let text = "";
  try {
    const r = await fetch("/api/listen", { method: "POST", body: form });
    const body = await r.json();
    if (body.error === "stt_unavailable") {
      S.micAvailable = false;
      setPhase("idle", "सुनने वाला हिस्सा चालू नहीं है। 'लिखिए' दबाकर लिखिए।");
      return;
    }
    text = (body.text || "").trim();          // a one-off failure counts as "didn't hear" below
  } catch {
    showError({ code: "network" });
    return;
  }
  if (S.phase === "ended") return;
  if (!text) {
    S.missedHeard += 1;
    if (S.missedHeard <= 2) sayLocal("माफ़ कीजिए, मुझे ठीक से सुनाई नहीं दिया। एक बार फिर बोलिए?");
    else { S.missedHeard = 0; setPhase("idle"); }
    return;
  }
  S.missedHeard = 0;
  $("youCaption").textContent = text;
  talk("/api/chat", { text });
}

// ------------------------------------------------------------------ alerts ----
function showAlert(ev) {
  const card = $("alertCard");
  const lines = [];
  if (ev.kind === "emergency") {
    card.classList.remove("scam");
    $("alertTitle").textContent = "🚨 अभी मदद लीजिए";
    $("alertBody").textContent = "अगर तबीयत ठीक नहीं लग रही, तो देर मत कीजिए। अभी फ़ोन कीजिए:";
    if (ev.phone) lines.push(`${ev.contact || "परिवार"}: ${ev.phone}`);
    lines.push(`आपातकालीन नंबर: ${ev.number}`);
  } else {
    card.classList.add("scam");
    $("alertTitle").textContent = "⚠️ सावधान रहिए";
    $("alertBody").textContent = "किसी को भी OTP, PIN, पासवर्ड या बैंक की जानकारी मत दीजिए। कोई पैसे माँगे या डराए, तो पहले परिवार से बात कीजिए।";
    if (ev.phone) lines.push(`${ev.contact || "परिवार"}: ${ev.phone}`);
  }
  $("alertPhone").textContent = lines.join("\n");
  $("alertPhone").style.whiteSpace = "pre-line";
  $("alert").hidden = false;
  $("alertClose").focus();
}

// ------------------------------------------------------------- the call ----
function tickTimer() {
  const s = Math.floor((Date.now() - S.callStart) / 1000);
  $("timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

async function startCall() {
  $("precall").hidden = true;
  $("ended").hidden = true;
  await initAudio();
  await initMic();
  document.body.classList.add("in-call");
  S.callStart = Date.now();
  tickTimer();
  clearInterval(S.timer);
  S.timer = setInterval(tickTimer, 1000);
  $("youCaption").textContent = "";
  $("saathiCaption").textContent = "";
  setPhase("thinking");
  const cold = S.status && S.status.ollama?.reachable && !S.status.ollama.loaded;
  const hello = `नमस्ते ${S.settings?.address || ""}! बस एक मिनट, मैं आ ${myVerb("रहा", "रही")} हूँ।`.replace("नमस्ते आप!", "नमस्ते!");
  talk("/api/greet", {}, { prelude: cold ? hello : "" });
}

function endCall() {
  stopSpeaking();
  stopListening(true);
  setPhase("ended");
  document.body.classList.remove("in-call");
  clearInterval(S.timer);
  fetch("/api/session/end", { method: "POST" }).catch(() => {});
  $("ended").hidden = false;
  $("againBtn").focus();
}

function onMicButton() {
  if (S.phase === "listening") {
    if (S.recInfo) S.recInfo.forced = true;   // she pressed "done": send it even if it was quiet
    stopListening(false);
  } else {
    startListening();                           // also interrupts Saathi if it is speaking
  }
}

function openTyping() {
  stopListening(true);
  if (S.phase === "listening") setPhase("idle");
  $("typeInput").value = "";
  $("typeDialog").showModal();
  $("typeInput").focus();
}

// --------------------------------------------------------------- animation ----
function animate() {
  let target = 0;
  if (S.currentSource) target = rms(S.outAnalyser) * 7;
  else if (S.browserSpeaking) {
    const t = performance.now();
    target = 0.3 + 0.35 * Math.abs(Math.sin(t / 95) * Math.sin(t / 41));
  }
  target = Math.min(1, Math.max(0, target));
  animate.level = (animate.level || 0) + (target - (animate.level || 0)) * 0.35;
  $("mouthOpen").setAttribute("ry", (animate.level * 13).toFixed(1));
  $("smile").style.opacity = animate.level > 0.08 ? "0" : "1";
  const ring = $("ring");
  if (S.phase === "listening" && S.micAnalyser) {
    ring.style.transform = `scale(${1 + Math.min(1, rms(S.micAnalyser) * 9) * 0.09})`;
  } else if (ring.style.transform) {
    ring.style.transform = "";
  }
  requestAnimationFrame(animate);
}

// ------------------------------------------------------------------- wire ----
window.addEventListener("DOMContentLoaded", async () => {
  if ("speechSynthesis" in window) { speechSynthesis.getVoices(); speechSynthesis.onvoiceschanged = () => speechSynthesis.getVoices(); }
  keepWarm();                                   // start loading Gemma now, not when she presses the button
  setInterval(keepWarm, KEEP_WARM_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) keepWarm(); });
  try { await loadSettings(); } catch { $("helloSub").textContent = "Saathi का सर्वर नहीं मिल रहा।"; }
  await checkSetup();
  setPhase("precall");
  watchReady();
  requestAnimationFrame(animate);

  $("startBtn").addEventListener("click", startCall);
  $("againBtn").addEventListener("click", startCall);
  $("endBtn").addEventListener("click", endCall);
  $("micBtn").addEventListener("click", onMicButton);
  $("typeBtn").addEventListener("click", openTyping);
  $("repeatBtn").addEventListener("click", () => {
    const lines = [...S.lastSentences];
    stopListening(true);
    stopSpeaking();
    lines.forEach(enqueue);
  });
  $("typeCancel").addEventListener("click", () => { $("typeDialog").close(); finishedSpeaking(); });
  $("typeForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("typeInput").value.trim();
    $("typeDialog").close();
    if (!text) return;
    $("youCaption").textContent = text;
    talk("/api/chat", { text });
  });
  $("alertClose").addEventListener("click", () => { $("alert").hidden = true; });
  $("familyLink").addEventListener("click", (e) => {
    if (!confirm("यह पेज परिवार वालों के लिए है। खोलें?")) e.preventDefault();
  });
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !$("typeDialog").open && !$("micBtn").disabled && document.activeElement.tagName !== "TEXTAREA") {
      e.preventDefault();
      onMicButton();
    }
  });
  $("startBtn").focus();
});
