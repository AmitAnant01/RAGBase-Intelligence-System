/* ============================================================
   RAGBase PRO — frontend logic
   ============================================================ */

const chatWindow   = document.getElementById("chatWindow");
const chatForm      = document.getElementById("chatForm");
const userInput      = document.getElementById("userInput");
const sessionList     = document.getElementById("sessionList");
const docList          = document.getElementById("docList");
const docCount          = document.getElementById("docCount");
const chatTitle           = document.getElementById("chatTitle");
const newChatBtn           = document.getElementById("newChatBtn");
const dropZone               = document.getElementById("dropZone");
const fileInput                = document.getElementById("fileInput");
const topKSelect                 = document.getElementById("topK");
const personaSelect                = document.getElementById("personaSelect");
const renameBtn                     = document.getElementById("renameBtn");
const exportMdBtn                     = document.getElementById("exportMdBtn");
const exportPdfBtn                     = document.getElementById("exportPdfBtn");
const micBtn                             = document.getElementById("micBtn");
const speakToggle                          = document.getElementById("speakToggle");
const themeToggle                            = document.getElementById("themeToggle");
const sourceModal                              = document.getElementById("sourceModal");
const modalBody                                  = document.getElementById("modalBody");
const closeModal                                   = document.getElementById("closeModal");
const toast                                          = document.getElementById("toast");

let currentSessionId = null;
let speakEnabled = localStorage.getItem("ragbase_speak") === "1";
let recognizing = false;

// ================================================================
// Toast helper
// ================================================================
function showToast(msg, ms = 2600) {
  toast.textContent = msg;
  toast.classList.remove("hidden");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.add("hidden"), ms);
}

// ================================================================
// Theme
// ================================================================
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("ragbase_theme", theme);
}
applyTheme(localStorage.getItem("ragbase_theme") || "dark");
themeToggle.addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  applyTheme(cur === "dark" ? "light" : "dark");
});

// ================================================================
// Tabs
// ================================================================
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "analytics") loadAnalytics();
  });
});

// ================================================================
// Sessions
// ================================================================
async function loadSessions() {
  const res = await fetch("/api/sessions");
  const data = await res.json();
  sessionList.innerHTML = "";
  data.sessions.forEach(s => {
    const div = document.createElement("div");
    div.className = "session-item" + (s.id === currentSessionId ? " active" : "");
    div.innerHTML = `<span>${escapeHtml(s.title)}</span><span class="del" data-id="${s.id}">&times;</span>`;
    div.addEventListener("click", (e) => {
      if (e.target.classList.contains("del")) return;
      openSession(s.id);
    });
    div.querySelector(".del").addEventListener("click", async (e) => {
      e.stopPropagation();
      await fetch(`/api/sessions/${s.id}`, { method: "DELETE" });
      if (s.id === currentSessionId) await createNewSession();
      loadSessions();
    });
    sessionList.appendChild(div);
  });
  if (!currentSessionId && data.sessions.length > 0) {
    openSession(data.sessions[0].id);
  } else if (!currentSessionId) {
    await createNewSession();
  }
}

async function createNewSession() {
  const res = await fetch("/api/sessions", { method: "POST" });
  const data = await res.json();
  currentSessionId = data.id;
  chatTitle.textContent = data.title;
  chatWindow.innerHTML = `<div class="welcome"><h3>Welcome to RAGBase PRO</h3><p>Upload documents on the left, pick a response style above, then ask anything. Answers are grounded in your files with live citations, confidence scores, and streaming replies.</p></div>`;
  loadSessions();
}

async function openSession(id) {
  currentSessionId = id;
  const res = await fetch(`/api/sessions/${id}`);
  const data = await res.json();
  chatTitle.textContent = data.title;
  chatWindow.innerHTML = "";
  if (data.messages.length === 0) {
    chatWindow.innerHTML = `<div class="welcome"><h3>Welcome to RAGBase PRO</h3><p>Ask anything about your uploaded documents.</p></div>`;
  } else {
    data.messages.forEach(m => renderMessage(m.role, m.content, m.sources, m.confidence));
  }
  loadSessions();
}

newChatBtn.addEventListener("click", createNewSession);

renameBtn.addEventListener("click", async () => {
  const title = prompt("Rename this chat:", chatTitle.textContent);
  if (!title) return;
  const res = await fetch(`/api/sessions/${currentSessionId}/rename`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const data = await res.json();
  chatTitle.textContent = data.title;
  loadSessions();
});

exportMdBtn.addEventListener("click", () => {
  window.open(`/api/sessions/${currentSessionId}/export?format=md`, "_blank");
});
exportPdfBtn.addEventListener("click", () => {
  window.open(`/api/sessions/${currentSessionId}/export?format=pdf`, "_blank");
});

// ================================================================
// Documents / Upload
// ================================================================
async function loadDocuments() {
  const res = await fetch("/api/documents");
  const data = await res.json();
  renderDocs(data.documents);
}

function renderDocs(documents) {
  docCount.textContent = documents.length;
  docList.innerHTML = "";
  documents.forEach(doc => {
    const div = document.createElement("div");
    div.className = "doc-item";
    const tagsHtml = (doc.tags || []).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("");
    div.innerHTML = `
      <div class="doc-item-top">
        <span class="doc-item-name" title="${escapeHtml(doc.name)}">${escapeHtml(doc.name)}</span>
        <button class="doc-del" data-name="${escapeHtml(doc.name)}">&times;</button>
      </div>
      <div class="doc-item-meta">${doc.chunks} chunks indexed</div>
      ${doc.summary ? `<div class="doc-item-summary">${escapeHtml(doc.summary)}</div>` : ""}
      ${tagsHtml ? `<div class="tags">${tagsHtml}</div>` : ""}
    `;
    div.querySelector(".doc-del").addEventListener("click", async () => {
      await fetch(`/api/documents/${encodeURIComponent(doc.name)}`, { method: "DELETE" });
      loadDocuments();
      showToast(`Removed ${doc.name}`);
    });
    docList.appendChild(div);
  });
}

async function uploadFiles(files) {
  if (!files.length) return;
  const formData = new FormData();
  [...files].forEach(f => formData.append("files", f));
  showToast(`Uploading ${files.length} file(s)...`);
  try {
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await res.json();
    renderDocs(data.documents);
    const failed = data.results.filter(r => r.status !== "indexed");
    if (failed.length) {
      showToast(`${data.results.length - failed.length} indexed, ${failed.length} skipped/failed`);
    } else {
      showToast(`Indexed ${data.results.length} file(s) successfully`);
    }
  } catch (e) {
    showToast("Upload failed: " + e.message);
  }
}

dropZone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => uploadFiles(fileInput.files));
["dragover", "dragenter"].forEach(evt =>
  dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.add("dragover"); })
);
["dragleave", "drop"].forEach(evt =>
  dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.remove("dragover"); })
);
dropZone.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));

// ================================================================
// Chat — streaming
// ================================================================
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function simpleMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/```([\s\S]*?)```/g, (m, code) => `<pre><code>${code}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\n/g, "<br>");
  return html;
}

function confidenceClass(conf) {
  if (conf >= 0.5) return "confidence-high";
  if (conf >= 0.25) return "confidence-mid";
  return "confidence-low";
}

function renderMessage(role, content, sources = [], confidence = null) {
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;
  const avatar = role === "user" ? "You" : "RB";

  let metaHtml = "";
  if (role === "assistant") {
    const chips = (sources || [])
      .filter(s => s.source)
      .map(s => `<span class="source-chip" data-source="${escapeHtml(s.source)}" data-chunk="${s.chunk_index}">${escapeHtml(s.source)} · ${Math.round((s.relevance || 0) * 100)}%</span>`)
      .join("");
    const confPill = confidence !== null
      ? `<span class="confidence-pill ${confidenceClass(confidence)}">Confidence ${Math.round(confidence * 100)}%</span>`
      : "";
    metaHtml = `<div class="msg-meta">${confPill}<div class="source-chips">${chips}</div></div>`;
  }

  msg.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div>
      <div class="msg-bubble">${simpleMarkdown(content)}</div>
      ${metaHtml}
    </div>
  `;
  chatWindow.appendChild(msg);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  msg.querySelectorAll(".source-chip").forEach(chip => {
    chip.addEventListener("click", () => showSourceModal(chip.dataset.source, chip.dataset.chunk));
  });

  return msg;
}

async function showSourceModal(source, chunkIndex) {
  modalBody.innerHTML = `<p><strong>${escapeHtml(source)}</strong> — chunk ${chunkIndex}</p><p style="margin-top:10px;">Retrieved as one of the passages used to ground this answer. Re-ask a more specific question if you need the exact wording verified against the original file.</p>`;
  sourceModal.classList.remove("hidden");
}
closeModal.addEventListener("click", () => sourceModal.classList.add("hidden"));
sourceModal.addEventListener("click", (e) => { if (e.target === sourceModal) sourceModal.classList.add("hidden"); });

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = userInput.value.trim();
  if (!message || !currentSessionId) return;
  userInput.value = "";

  renderMessage("user", message);

  const typingMsg = document.createElement("div");
  typingMsg.className = "msg assistant";
  typingMsg.innerHTML = `<div class="msg-avatar">RB</div><div><div class="msg-bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div></div>`;
  chatWindow.appendChild(typingMsg);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  const bubble = typingMsg.querySelector(".msg-bubble");
  let accumulated = "";     // full text received so far from the network
  let revealed = "";        // text actually painted to the DOM (typewriter pace)
  let sources = [];
  let confidence = 0;
  let firstChunk = true;
  let streamDone = false;

  // Decoupling the reveal speed from network speed gives a smooth, consistent
  // typing animation even though Groq's stream can arrive in large, uneven bursts.
  const revealTimer = setInterval(() => {
    if (revealed.length < accumulated.length) {
      const nextSpace = accumulated.indexOf(" ", revealed.length + 2);
      const sliceEnd = nextSpace === -1 ? accumulated.length : Math.min(nextSpace + 1, accumulated.length);
      revealed = accumulated.slice(0, sliceEnd);
      bubble.innerHTML = simpleMarkdown(revealed) + `<span class="type-cursor"></span>`;
      chatWindow.scrollTop = chatWindow.scrollHeight;
    } else if (streamDone) {
      clearInterval(revealTimer);
      bubble.innerHTML = simpleMarkdown(accumulated);
    }
  }, 22);

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: currentSessionId,
        message,
        top_k: parseInt(topKSelect.value, 10),
        persona: personaSelect.value,
      }),
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();

      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        const evt = JSON.parse(part.slice(6));

        if (evt.type === "sources") {
          sources = evt.sources;
          confidence = evt.confidence;
        } else if (evt.type === "chunk") {
          if (firstChunk) { bubble.innerHTML = ""; firstChunk = false; }
          accumulated += evt.text;
        } else if (evt.type === "error") {
          clearInterval(revealTimer);
          bubble.innerHTML = `<span style="color:var(--danger)">Error: ${escapeHtml(evt.message)}</span>`;
        } else if (evt.type === "done") {
          chatTitle.textContent = evt.session_title;
          loadSessions();
        }
      }
    }
    streamDone = true;

    // Wait for the typewriter to finish painting before swapping in the final bubble.
    await new Promise(resolve => {
      const check = setInterval(() => {
        if (revealed.length >= accumulated.length) { clearInterval(check); resolve(); }
      }, 25);
    });

    typingMsg.remove();
    renderMessage("assistant", accumulated, sources, confidence);
    if (speakEnabled) speak(accumulated);

  } catch (err) {
    clearInterval(revealTimer);
    typingMsg.remove();
    renderMessage("assistant", `Error: ${err.message}`);
  }
});

// ================================================================
// Voice input (Web Speech API)
// ================================================================
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = "en-US";

  recognition.onresult = (e) => {
    userInput.value = e.results[0][0].transcript;
  };
  recognition.onend = () => {
    recognizing = false;
    micBtn.classList.remove("recording");
  };
  recognition.onerror = () => {
    recognizing = false;
    micBtn.classList.remove("recording");
    showToast("Voice input error — check mic permissions");
  };
} else {
  micBtn.style.display = "none";
}

micBtn.addEventListener("click", () => {
  if (!recognition) return;
  if (recognizing) {
    recognition.stop();
    return;
  }
  recognizing = true;
  micBtn.classList.add("recording");
  recognition.start();
});

// ================================================================
// Text-to-speech — best available natural voice, queued sentence-by-sentence
// ================================================================
const voiceSelect = document.getElementById("voiceSelect");
let availableVoices = [];

// Preference order: natural/neural cloud voices first, then any decent
// en-US/en-GB voice, then whatever the browser has.
const VOICE_RANK = [
  /Google US English/i, /Microsoft.*Online.*Natural/i, /Microsoft Aria/i,
  /Microsoft Jenny/i, /Microsoft Guy/i, /Samantha/i, /Google UK English Female/i,
  /Natural/i, /Neural/i,
];

function rankVoice(v) {
  for (let i = 0; i < VOICE_RANK.length; i++) if (VOICE_RANK[i].test(v.name)) return i;
  if (/^en/i.test(v.lang)) return VOICE_RANK.length;
  return VOICE_RANK.length + 1;
}

function populateVoices() {
  if (!("speechSynthesis" in window)) return;
  availableVoices = window.speechSynthesis.getVoices()
    .filter(v => v.lang && v.lang.toLowerCase().startsWith("en"))
    .sort((a, b) => rankVoice(a) - rankVoice(b));

  if (availableVoices.length === 0) return;

  const saved = localStorage.getItem("ragbase_voice");
  voiceSelect.innerHTML = availableVoices
    .map(v => `<option value="${v.name}">${v.name}${v.name.includes("Google") || v.name.includes("Natural") || v.name.includes("Neural") ? " ⭐" : ""}</option>`)
    .join("");

  const match = availableVoices.find(v => v.name === saved);
  voiceSelect.value = match ? match.name : availableVoices[0].name;
}

if ("speechSynthesis" in window) {
  populateVoices();
  window.speechSynthesis.onvoiceschanged = populateVoices;
}

voiceSelect.addEventListener("change", () => {
  localStorage.setItem("ragbase_voice", voiceSelect.value);
});

function updateSpeakUI() {
  speakToggle.classList.toggle("active", speakEnabled);
}
updateSpeakUI();
speakToggle.addEventListener("click", () => {
  speakEnabled = !speakEnabled;
  localStorage.setItem("ragbase_speak", speakEnabled ? "1" : "0");
  updateSpeakUI();
  showToast(speakEnabled ? "Voice replies enabled" : "Voice replies disabled");
  if (!speakEnabled) window.speechSynthesis.cancel();
});

function splitIntoSpeechChunks(text) {
  // Sentence-level chunking gives the speech engine natural pauses and
  // avoids the hard cutoff some browsers apply to very long utterances.
  return text
    .split(/(?<=[.!?])\s+/)
    .map(s => s.trim())
    .filter(Boolean);
}

function speak(text) {
  if (!("speechSynthesis" in window)) return;
  const clean = text.replace(/```[\s\S]*?```/g, "").replace(/[*_`#>]/g, "");
  const chunks = splitIntoSpeechChunks(clean).slice(0, 40); // safety cap
  if (chunks.length === 0) return;

  const chosenVoice = availableVoices.find(v => v.name === voiceSelect.value) || availableVoices[0];

  window.speechSynthesis.cancel();
  chunks.forEach((chunk, i) => {
    const utter = new SpeechSynthesisUtterance(chunk);
    if (chosenVoice) utter.voice = chosenVoice;
    utter.rate = 1.0;
    utter.pitch = 1.02;
    utter.volume = 1.0;
    window.speechSynthesis.speak(utter);
  });
}

// ================================================================
// Analytics
// ================================================================
async function loadAnalytics() {
  const res = await fetch("/api/analytics");
  const data = await res.json();

  const statGrid = document.getElementById("statGrid");
  statGrid.innerHTML = `
    <div class="stat-card"><div class="stat-value">${data.total_queries}</div><div class="stat-label">Total Queries</div></div>
    <div class="stat-card"><div class="stat-value">${data.avg_response_time}s</div><div class="stat-label">Avg Response Time</div></div>
    <div class="stat-card"><div class="stat-value">${data.uploads}</div><div class="stat-label">Files Uploaded</div></div>
  `;

  const chart = document.getElementById("topDocsChart");
  chart.innerHTML = "";
  const maxHits = Math.max(1, ...data.top_documents.map(d => d.hits));
  if (data.top_documents.length === 0) {
    chart.innerHTML = `<p class="muted">No queries yet.</p>`;
  }
  data.top_documents.forEach(d => {
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <span class="bar-label">${escapeHtml(d.name)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${(d.hits / maxHits) * 100}%"></div></div>
      <span class="bar-value">${d.hits}</span>
    `;
    chart.appendChild(row);
  });

  const recent = document.getElementById("recentQueries");
  recent.innerHTML = "";
  if (data.recent_queries.length === 0) {
    recent.innerHTML = `<p class="muted">No recent activity.</p>`;
  }
  data.recent_queries.forEach(q => {
    const row = document.createElement("div");
    row.className = "recent-item";
    row.innerHTML = `<span class="rq">${escapeHtml(q.q)}</span><span class="rt">${q.response_time}s · ${Math.round(q.confidence * 100)}%</span>`;
    recent.appendChild(row);
  });
}

// ================================================================
// Research — one smart input (auto-detects link vs raw text) or a file;
// renders a Wikipedia-style brief with live images, related links, and a map.
// ================================================================
const researchInput = document.getElementById("researchInput");
const researchFile = document.getElementById("researchFile");
const researchFileName = document.getElementById("researchFileName");
const researchGoBtn = document.getElementById("researchGoBtn");
const researchLoading = document.getElementById("researchLoading");
const researchArticle = document.getElementById("researchArticle");
const researchEmpty = document.getElementById("researchEmpty");
let lastBrief = null;

researchFile.addEventListener("change", () => {
  if (researchFile.files[0]) {
    researchFileName.textContent = `📎 ${researchFile.files[0].name}`;
    researchFileName.classList.remove("hidden");
    researchInput.value = "";
    researchInput.placeholder = "Using attached file — clear it to type instead";
  } else {
    researchFileName.classList.add("hidden");
  }
});

researchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); researchGoBtn.click(); }
});

researchGoBtn.addEventListener("click", async () => {
  const val = researchInput.value.trim();
  const file = researchFile.files[0];
  if (!val && !file) return showToast("Paste a link, some text, or attach a file");

  const fd = new FormData();
  if (file) fd.append("file", file);
  else fd.append("input", val);

  researchGoBtn.disabled = true;
  researchEmpty.classList.add("hidden");
  researchArticle.classList.add("hidden");
  researchLoading.classList.remove("hidden");

  try {
    const res = await fetch("/api/research", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Research failed");
    lastBrief = data;
    renderResearch(data);
  } catch (e) {
    showToast(e.message);
    researchEmpty.classList.remove("hidden");
  } finally {
    researchLoading.classList.add("hidden");
    researchGoBtn.disabled = false;
  }
});

function renderResearch(data) {
  document.getElementById("rTitle").textContent = data.title;
  document.getElementById("rMeta").textContent =
    `${data.read_minutes} min read · ${data.char_count.toLocaleString()} characters analyzed`;
  document.getElementById("rTldr").textContent = data.tldr;

  const sectionsEl = document.getElementById("rSections");
  sectionsEl.innerHTML = "";
  (data.sections || []).forEach(s => {
    const block = document.createElement("div");
    block.className = "research-section";
    let inner = `<h2>${escapeHtml(s.heading)}</h2>`;
    if (s.bullets && s.bullets.length) {
      inner += `<ul>${s.bullets.map(b => `<li>${escapeHtml(b)}</li>`).join("")}</ul>`;
    } else if (s.content) {
      inner += `<p>${escapeHtml(s.content)}</p>`;
    }
    block.innerHTML = inner;
    if (s.content || (s.bullets && s.bullets.length)) sectionsEl.appendChild(block);
  });

  // Images
  const imgCard = document.getElementById("rImageCard");
  const imgWrap = document.getElementById("rImages");
  if (data.images && data.images.length) {
    imgWrap.innerHTML = data.images.slice(0, 4).map(img =>
      `<figure><img src="${img.src}" alt="${escapeHtml(img.caption)}" loading="lazy"><figcaption>${escapeHtml(img.caption)}</figcaption></figure>`
    ).join("");
    imgCard.classList.remove("hidden");
  } else {
    imgCard.classList.add("hidden");
  }

  // Keywords
  const factsCard = document.getElementById("rFactsCard");
  const kwEl = document.getElementById("rKeywords");
  if (data.keywords && data.keywords.length) {
    kwEl.innerHTML = data.keywords.map(k => `<span class="kw-chip">${escapeHtml(k)}</span>`).join("");
    factsCard.classList.remove("hidden");
  } else {
    factsCard.classList.add("hidden");
  }

  // Map
  const mapCard = document.getElementById("rMapCard");
  if (data.map) {
    document.getElementById("rMapFrame").src = data.map.osm_embed;
    document.getElementById("rMapLink").href = data.map.gmaps_url;
    mapCard.classList.remove("hidden");
  } else {
    mapCard.classList.add("hidden");
  }

  // Related topics
  const relCard = document.getElementById("rRelatedCard");
  const relEl = document.getElementById("rRelated");
  if (data.related && data.related.length) {
    relEl.innerHTML = data.related.map(r =>
      `<a href="${r.url}" target="_blank" rel="noopener" class="related-link">
         <span class="related-dot">●</span>
         <span><strong>${escapeHtml(r.title)}</strong><br><small>${escapeHtml(r.snippet || "")}</small></span>
       </a>`
    ).join("");
    relCard.classList.remove("hidden");
  } else {
    relCard.classList.add("hidden");
  }

  // Original source
  const srcCard = document.getElementById("rSourceCard");
  if (data.source_url) {
    const link = document.getElementById("rSourceLink");
    link.href = data.source_url;
    link.textContent = data.source_url;
    srcCard.classList.remove("hidden");
  } else {
    srcCard.classList.add("hidden");
  }

  researchArticle.classList.remove("hidden");
}

document.getElementById("rCopyBtn").addEventListener("click", () => {
  if (!lastBrief) return;
  const bullets = (lastBrief.sections || [])
    .map(s => s.bullets ? `${s.heading}\n${s.bullets.map(b => `• ${b}`).join("\n")}` : `${s.heading}\n${s.content}`)
    .join("\n\n");
  navigator.clipboard.writeText(`${lastBrief.title}\n\n${lastBrief.tldr}\n\n${bullets}`);
  showToast("Brief copied to clipboard");
});

document.getElementById("rSpeakBtn").addEventListener("click", () => {
  if (!lastBrief) return;
  speak(`${lastBrief.title}. ${lastBrief.tldr}`);
});

// ================================================================
// Init
// ================================================================
loadSessions();
loadDocuments();
