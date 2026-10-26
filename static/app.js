/* =========================================================================
   智译学研 · Polyglot Scholar Online (v4.0 Multi-User Website Edition)
   ========================================================================= */

function getOrCreateGuestId() {
  try {
    let gid = localStorage.getItem("ps_guest_id");
    if (!gid || !/^guest_[a-zA-Z0-9_-]{6,48}$/.test(gid)) {
      const rand = Array.from(crypto.getRandomValues(new Uint8Array(10)))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("");
      gid = `guest_${rand}`;
      localStorage.setItem("ps_guest_id", gid);
    }
    return gid;
  } catch (_) {
    return "default";
  }
}

function getAuthToken() {
  try {
    return localStorage.getItem("ps_auth_token") || "";
  } catch (_) {
    return "";
  }
}

function setAuthToken(tok) {
  try {
    if (tok) localStorage.setItem("ps_auth_token", tok);
    else localStorage.removeItem("ps_auth_token");
  } catch (_) {}
}

const state = {
  guestId: getOrCreateGuestId(),
  authToken: getAuthToken(),
  currentUser: null,
  userStats: null,
  authMode: "login", // login | register

  papers: [],
  paperFilter: "all",
  currentPaper: null,
  layout: "parallel",
  showStress: true,
  showAcademicHl: true,
  fontSize: 17,

  lastWordData: null,
  lastWordContextZh: "",
  lastSentenceData: null,

  vocabList: [],
  vocabLangFilter: "",
  vocabSearch: "",

  trainerMode: "flashcard",
  trainerLang: "all",
  hideStressFront: false,
  deck: [],
  deckIndex: 0,
  cardFlipped: false,

  settings: {},
  selectedPdfFile: null,
  notesTimer: null,
  doiImporting: false,
};

const LLM_PRESETS = {
  deepseek: { base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  qwen: { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  siliconflow: { base_url: "https://api.siliconflow.cn/v1", model: "Qwen/Qwen2.5-72B-Instruct" },
  ollama: { base_url: "http://localhost:11434/v1", model: "qwen2.5:7b" },
};

// ---------- Utilities ----------
function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function stripStress(str) {
  return String(str ?? "").replace(/[\u0301\u0300]/g, "");
}

function isMobileScreen() {
  return window.innerWidth <= 920;
}

function showToast(msg, duration = 2800) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.add("hidden"), duration);
}

function buildAuthQuery() {
  const p = new URLSearchParams();
  if (state.authToken) p.set("token", state.authToken);
  if (state.guestId) p.set("guest_id", state.guestId);
  return p.toString();
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.authToken) {
    headers.set("Authorization", `Bearer ${state.authToken}`);
  }
  if (state.guestId) {
    headers.set("X-Guest-Id", state.guestId);
  }
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const errJson = await res.json();
      if (errJson.detail) detail = errJson.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function simpleMarkdownToHtml(md) {
  if (!md) return "";
  const lines = md.split("\n");
  let html = "";
  let inList = false;
  for (let raw of lines) {
    let line = esc(raw.trim());
    if (!line) {
      if (inList) { html += "</ul>"; inList = false; }
      continue;
    }
    line = line
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");

    if (line.startsWith("### ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h3>${line.slice(4)}</h3>`;
    } else if (line.startsWith("## ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h3>${line.slice(3)}</h3>`;
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${line.slice(2)}</li>`;
    } else if (line.startsWith("&gt; ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<div class="acad-tip-box" style="margin-top:8px">${line.slice(5)}</div>`;
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<p style="margin:6px 0">${line}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html;
}

// ---------- Neural TTS Playback ----------
function playTTS(text, lang = "ru", slow = false) {
  const clean = stripStress(text).trim();
  if (!clean) return;
  const audio = document.getElementById("ttsAudio");
  const url = `/api/tts?text=${encodeURIComponent(clean)}&lang=${encodeURIComponent(lang)}&slow=${slow ? 1 : 0}&${buildAuthQuery()}`;
  audio.src = url;
  audio.play().catch(() => {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(clean);
      u.lang = lang === "ru" ? "ru-RU" : "en-US";
      u.rate = slow ? 0.75 : 1.0;
      window.speechSynthesis.speak(u);
    } else {
      showToast("当前环境暂无法播放音频");
    }
  });
}

// ---------- Initialization ----------
document.addEventListener("DOMContentLoaded", async () => {
  if (isMobileScreen()) {
    document.getElementById("paperSidebar")?.classList.add("collapsed");
    document.getElementById("inspectorPane")?.classList.add("collapsed");
  }
  bindGlobalEvents();
  await loadAuthMe();
  await reloadWorkspaceData();

  // Returning logged-in users go straight to Reader; fresh visitors see the Academic Website Portal!
  if (state.currentUser) {
    switchMainView("reader");
  } else {
    switchMainView("portal");
  }
});

async function reloadWorkspaceData() {
  await Promise.all([loadSettings(), loadVocab(), loadPapers()]);
  renderPortalSampleCards();
  if (state.papers.length > 0) {
    const keepId = state.currentPaper && state.papers.some((p) => p.id === state.currentPaper.id)
      ? state.currentPaper.id
      : state.papers[0].id;
    await selectPaper(keepId);
  }
}

// ---------- Mobile Drawer Helpers ----------
function syncMobileBackdrop() {
  const backdrop = document.getElementById("mobileDrawerBackdrop");
  if (!backdrop) return;
  if (!isMobileScreen()) {
    backdrop.classList.add("hidden");
    return;
  }
  const sideOpen = !document.getElementById("paperSidebar")?.classList.contains("collapsed");
  const inspOpen = !document.getElementById("inspectorPane")?.classList.contains("collapsed");
  backdrop.classList.toggle("hidden", !sideOpen && !inspOpen);
}

function closeMobileDrawers() {
  if (!isMobileScreen()) return;
  document.getElementById("paperSidebar")?.classList.add("collapsed");
  document.getElementById("inspectorPane")?.classList.add("collapsed");
  syncMobileBackdrop();
}

// ---------- Event Bindings ----------
function bindGlobalEvents() {
  // Brand Logo -> Portal
  document.getElementById("brandHomeLink")?.addEventListener("click", () => switchMainView("portal"));

  // Top Navigation Tabs
  document.querySelectorAll(".nav-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchMainView(btn.dataset.view));
  });

  // Portal Hero Actions
  document.getElementById("btnEnterReaderHero")?.addEventListener("click", () => switchMainView("reader"));
  document.getElementById("btnHeroRegister")?.addEventListener("click", () => {
    if (state.currentUser) openProfileModal();
    else openAuthModal("register");
  });
  document.getElementById("heroDoiForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const val = (document.getElementById("heroDoiInput")?.value || "").trim();
    submitDoiImport(val, true, "hero");
  });

  // Theme Switcher (both top bar and profile modal)
  document.querySelectorAll("[data-set-theme]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const theme = btn.dataset.setTheme;
      document.documentElement.setAttribute("data-theme", theme);
      document.querySelectorAll(".theme-btn").forEach((b) => b.classList.toggle("active", b.dataset.setTheme === theme));
    });
  });

  // Sidebar & Inspector Toggles + Mobile Close Buttons
  document.getElementById("btnToggleSidebar")?.addEventListener("click", () => {
    if (document.getElementById("viewPortal")?.classList.contains("active")) {
      switchMainView("reader");
    }
    const sb = document.getElementById("paperSidebar");
    sb?.classList.toggle("collapsed");
    if (isMobileScreen() && !sb?.classList.contains("collapsed")) {
      document.getElementById("inspectorPane")?.classList.add("collapsed");
    }
    syncMobileBackdrop();
  });

  document.getElementById("btnToggleInspector")?.addEventListener("click", () => {
    const ip = document.getElementById("inspectorPane");
    ip?.classList.toggle("collapsed");
    if (isMobileScreen() && !ip?.classList.contains("collapsed")) {
      document.getElementById("paperSidebar")?.classList.add("collapsed");
    }
    syncMobileBackdrop();
  });

  document.getElementById("btnCloseSidebarMobile")?.addEventListener("click", () => {
    document.getElementById("paperSidebar")?.classList.add("collapsed");
    syncMobileBackdrop();
  });
  document.getElementById("btnCloseInspectorMobile")?.addEventListener("click", () => {
    document.getElementById("inspectorPane")?.classList.add("collapsed");
    syncMobileBackdrop();
  });
  document.getElementById("mobileDrawerBackdrop")?.addEventListener("click", closeMobileDrawers);

  // Paper Language Filter in Sidebar
  document.querySelectorAll("[data-paper-filter]").forEach((chip) => {
    chip.addEventListener("click", () => {
      state.paperFilter = chip.dataset.paperFilter;
      document.querySelectorAll("[data-paper-filter]").forEach((c) => c.classList.toggle("active", c === chip));
      renderPaperList();
    });
  });

  // Reader Layout Segmented Control
  document.querySelectorAll("#layoutSegmented .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.layout = btn.dataset.layout;
      document.querySelectorAll("#layoutSegmented .seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
      applyReaderLayout();
    });
  });

  // Russian Stress Toggle
  document.getElementById("btnToggleStress")?.addEventListener("click", async () => {
    if (!state.currentPaper || state.currentPaper.lang !== "ru") {
      showToast("俄语重音标注仅针对俄语文献生效");
      return;
    }
    state.showStress = !state.showStress;
    document.getElementById("btnToggleStress").classList.toggle("active", state.showStress);
    if (state.showStress) {
      const missingStress = state.currentPaper.paragraphs.some((p) => !p.stressed_text);
      if (missingStress) {
        showToast("正在为俄语全文智能标注重音符号 (ударе́ние)...");
        try {
          const updated = await apiFetch(`/api/papers/${state.currentPaper.id}/stress`, { method: "POST" });
          state.currentPaper = updated;
        } catch (e) {
          showToast("重音标注失败：" + e.message);
        }
      }
    }
    renderCurrentPaper();
  });

  // Academic Highlight Toggle
  document.getElementById("btnToggleAcademicHl")?.addEventListener("click", () => {
    state.showAcademicHl = !state.showAcademicHl;
    document.getElementById("btnToggleAcademicHl").classList.toggle("active", state.showAcademicHl);
    document.getElementById("paperArticle")?.classList.toggle("show-academic-hl", state.showAcademicHl);
  });

  // Translate / Re-translate Paper
  document.getElementById("btnTranslatePaper")?.addEventListener("click", async () => {
    if (!state.currentPaper) return;
    const allTranslated = state.currentPaper.paragraphs.every((p) => (p.zh_text || "").trim());
    const force = allTranslated;
    const btn = document.getElementById("btnTranslatePaper");
    btn.disabled = true;
    btn.innerHTML = "<span>⏳ 翻译中...</span>";
    showToast(force ? "正在重新翻译整篇文献..." : "正在自动补全未翻译段落...");
    try {
      const updated = await apiFetch(`/api/papers/${state.currentPaper.id}/translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force_retranslate: force }),
      });
      state.currentPaper = updated;
      renderCurrentPaper();
      await loadPapers();
      showToast("✅ 中文学术译文已更新");
    } catch (e) {
      showToast("翻译出错：" + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = "<span>🌐 补全/重译</span>";
    }
  });

  // Font Size Controls
  document.getElementById("btnFontDec")?.addEventListener("click", () => {
    state.fontSize = Math.max(14, state.fontSize - 1);
    document.documentElement.style.setProperty("--reader-font-size", `${state.fontSize}px`);
  });
  document.getElementById("btnFontInc")?.addEventListener("click", () => {
    state.fontSize = Math.min(23, state.fontSize + 1);
    document.documentElement.style.setProperty("--reader-font-size", `${state.fontSize}px`);
  });

  // Inspector Sub-tabs
  document.querySelectorAll(".insp-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchInspectorTab(tab.dataset.insp));
  });

  // Quick Lookup Bar (also smartly detects DOIs!)
  function handleQuickSearchOrDoi() {
    const val = (document.getElementById("quickLookupInput")?.value || "").trim();
    if (!val) return;
    if (/(?:doi\.org\/|^doi\s*[:：]|\b10\s*\.\s*\d{4,9}\s*\/)/i.test(val)) {
      submitDoiImport(val, true, "quick");
      return;
    }
    inspectWord(val, null, "", "");
  }

  document.getElementById("btnQuickLookup")?.addEventListener("click", handleQuickSearchOrDoi);
  document.getElementById("quickLookupInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleQuickSearchOrDoi();
    }
  });

  // Left Sidebar Quick DOI Form
  document.getElementById("sidebarDoiForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const val = (document.getElementById("sidebarDoiInput")?.value || "").trim();
    submitDoiImport(val, true, "sidebar");
  });

  // Paper Notes Auto-Save & Markdown Export
  document.getElementById("paperNotesArea")?.addEventListener("input", (e) => {
    if (!state.currentPaper) return;
    document.getElementById("notesSaveHint").textContent = "正在同步...";
    clearTimeout(state.notesTimer);
    const pid = state.currentPaper.id;
    const val = e.target.value;
    state.notesTimer = setTimeout(async () => {
      try {
        await apiFetch(`/api/papers/${pid}/notes`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ notes: val }),
        });
        if (state.currentPaper && state.currentPaper.id === pid) {
          state.currentPaper.notes = val;
        }
        document.getElementById("notesSaveHint").textContent = "已云端同步 ✓";
      } catch (_) {
        document.getElementById("notesSaveHint").textContent = "保存失败";
      }
    }, 600);
  });

  document.getElementById("btnExportPaperMd")?.addEventListener("click", exportCurrentPaperMarkdown);

  // Import Modal & Quick Buttons
  function openImportModal(tabKey = "doi") {
    document.querySelectorAll(".mtab").forEach((x) => x.classList.toggle("active", x.dataset.itab === tabKey));
    document.getElementById("itabDoi")?.classList.toggle("active", tabKey === "doi");
    document.getElementById("itabPdf")?.classList.toggle("active", tabKey === "pdf");
    document.getElementById("itabText")?.classList.toggle("active", tabKey === "text");
    document.getElementById("itabArxiv")?.classList.toggle("active", tabKey === "arxiv");
    document.getElementById("modalImport")?.classList.remove("hidden");
    if (tabKey === "doi") {
      setTimeout(() => document.getElementById("impDoiInput")?.focus(), 60);
    }
  }

  document.getElementById("btnOpenDoiQuick")?.addEventListener("click", () => openImportModal("doi"));
  document.getElementById("btnOpenImport")?.addEventListener("click", () => openImportModal("doi"));
  document.getElementById("btnOpenSettings")?.addEventListener("click", () => {
    populateSettingsModal();
    document.getElementById("modalSettings")?.classList.remove("hidden");
  });
  document.getElementById("btnAddManualVocab")?.addEventListener("click", () => {
    document.getElementById("modalManualVocab")?.classList.remove("hidden");
  });

  // User Account Button (opens Login/Register or Profile Modal)
  document.getElementById("btnUserAccount")?.addEventListener("click", () => {
    if (state.currentUser) openProfileModal();
    else openAuthModal("login");
  });

  document.querySelectorAll(".auth-tab").forEach((tab) => {
    tab.addEventListener("click", () => setAuthModalMode(tab.dataset.atab));
  });
  document.getElementById("authForm")?.addEventListener("submit", handleAuthSubmit);
  document.getElementById("btnLogout")?.addEventListener("click", handleLogout);

  // Modal Close Buttons & Backdrop Click
  document.querySelectorAll(".close-modal").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById(btn.dataset.close)?.classList.add("hidden");
    });
  });
  document.querySelectorAll(".modal-backdrop").forEach((bd) => {
    bd.addEventListener("click", (e) => {
      if (e.target === bd) bd.classList.add("hidden");
    });
  });

  document.querySelectorAll(".mtab").forEach((t) => {
    t.addEventListener("click", () => openImportModal(t.dataset.itab));
  });

  document.querySelectorAll("[data-sample-doi]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const inp = document.getElementById("impDoiInput");
      if (inp) {
        inp.value = chip.dataset.sampleDoi;
        inp.focus();
      }
    });
  });

  document.getElementById("modalDoiForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    handleImportDoi();
  });

  // PDF Drag & Drop
  const dropzone = document.getElementById("pdfDropzone");
  const fileInput = document.getElementById("pdfFileInput");
  dropzone?.addEventListener("click", () => fileInput?.click());
  dropzone?.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.style.borderColor = "var(--primary)"; });
  dropzone?.addEventListener("dragleave", () => { dropzone.style.borderColor = ""; });
  dropzone?.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.style.borderColor = "";
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      state.selectedPdfFile = e.dataTransfer.files[0];
      document.getElementById("selectedPdfName").textContent = `已选择：${state.selectedPdfFile.name}`;
    }
  });
  fileInput?.addEventListener("change", () => {
    if (fileInput.files && fileInput.files[0]) {
      state.selectedPdfFile = fileInput.files[0];
      document.getElementById("selectedPdfName").textContent = `已选择：${state.selectedPdfFile.name}`;
    }
  });

  document.getElementById("btnSubmitPdf")?.addEventListener("click", handleUploadPdf);
  document.getElementById("btnSubmitText")?.addEventListener("click", handleImportText);
  document.getElementById("btnSubmitArxiv")?.addEventListener("click", handleImportArxiv);

  // Settings Modal
  document.querySelectorAll("[data-preset]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const p = LLM_PRESETS[chip.dataset.preset];
      if (!p) return;
      document.getElementById("cfgBaseUrl").value = p.base_url;
      document.getElementById("cfgModel").value = p.model;
      document.getElementById("cfgLlmEnabled").checked = true;
      document.getElementById("ollamaHint").classList.toggle("hidden", chip.dataset.preset !== "ollama");
    });
  });
  document.getElementById("btnTestLlm")?.addEventListener("click", handleTestLlm);
  document.getElementById("btnSaveSettings")?.addEventListener("click", handleSaveSettings);

  // Vocab View & Exports (with User Auth Query)
  document.querySelectorAll("#vocabLangFilter .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.vocabLangFilter = btn.dataset.vlang;
      document.querySelectorAll("#vocabLangFilter .seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
      loadVocab();
    });
  });
  document.getElementById("vocabSearchInput")?.addEventListener("input", (e) => {
    state.vocabSearch = e.target.value;
    loadVocab();
  });
  document.getElementById("btnSaveManualVocab")?.addEventListener("click", handleSaveManualVocab);
  document.getElementById("btnExportAnki")?.addEventListener("click", () => {
    window.open(`/api/vocab/export?fmt=anki&${buildAuthQuery()}`, "_blank");
  });
  document.getElementById("btnExportVocabMd")?.addEventListener("click", () => {
    window.open(`/api/vocab/export?fmt=md&${buildAuthQuery()}`, "_blank");
  });

  // Trainer View Controls
  document.querySelectorAll("#trainerModeSwitch .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.trainerMode = btn.dataset.tmode;
      document.querySelectorAll("#trainerModeSwitch .seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
      buildTrainerDeck();
    });
  });
  document.getElementById("trainerLangSelect")?.addEventListener("change", (e) => {
    state.trainerLang = e.target.value;
    buildTrainerDeck();
  });
  document.getElementById("chkHideStressFront")?.addEventListener("change", (e) => {
    state.hideStressFront = e.target.checked;
    renderTrainerCurrent();
  });
  document.getElementById("flashcardContainer")?.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    flipFlashcard();
  });
  document.querySelectorAll(".sm2-btn").forEach((btn) => {
    btn.addEventListener("click", () => submitFlashcardReview(parseInt(btn.dataset.quality, 10)));
  });
}

function switchMainView(view) {
  document.querySelectorAll(".nav-tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  document.getElementById("viewPortal")?.classList.toggle("active", view === "portal");
  document.getElementById("viewReader")?.classList.toggle("active", view === "reader");
  document.getElementById("viewVocab")?.classList.toggle("active", view === "vocab");
  document.getElementById("viewTrainer")?.classList.toggle("active", view === "trainer");
  if (view === "vocab") loadVocab();
  if (view === "trainer") buildTrainerDeck();
}

function switchInspectorTab(tabKey) {
  document.querySelectorAll(".insp-tab").forEach((t) => t.classList.toggle("active", t.dataset.insp === tabKey));
  document.getElementById("inspWordPanel")?.classList.toggle("active", tabKey === "word");
  document.getElementById("inspSentencePanel")?.classList.toggle("active", tabKey === "sentence");
  document.getElementById("inspNotesPanel")?.classList.toggle("active", tabKey === "notes");
  document.getElementById("inspectorPane")?.classList.remove("collapsed");
  if (isMobileScreen()) {
    document.getElementById("paperSidebar")?.classList.add("collapsed");
  }
  syncMobileBackdrop();
}

// ---------- Multi-User Authentication ----------
async function loadAuthMe() {
  try {
    const res = await apiFetch("/api/auth/me");
    state.currentUser = res.authenticated ? res.user : null;
    state.userStats = res.stats || null;
    if (!res.authenticated && state.authToken) {
      state.authToken = "";
      setAuthToken("");
    }
  } catch (_) {
    state.currentUser = null;
  }
  updateAccountButtonUI();
}

function updateAccountButtonUI() {
  const btn = document.getElementById("btnUserAccount");
  const lbl = document.getElementById("userAccountLabel");
  const heroBtn = document.getElementById("btnHeroRegister");
  if (!btn || !lbl) return;

  if (state.currentUser) {
    btn.classList.add("logged-in");
    lbl.textContent = `🎓 ${state.currentUser.display_name}`;
    if (heroBtn) heroBtn.textContent = `🎓 我的空间 (${state.currentUser.display_name})`;
  } else {
    btn.classList.remove("logged-in");
    lbl.textContent = "👤 登录 / 注册";
    if (heroBtn) heroBtn.textContent = "✨ 免费注册个人学术账号";
  }
}

function openAuthModal(mode = "login") {
  setAuthModalMode(mode);
  document.getElementById("authErrorMsg")?.classList.add("hidden");
  document.getElementById("modalAuth")?.classList.remove("hidden");
  setTimeout(() => document.getElementById("authUsername")?.focus(), 60);
}

function setAuthModalMode(mode) {
  state.authMode = mode;
  document.querySelectorAll(".auth-tab").forEach((t) => t.classList.toggle("active", t.dataset.atab === mode));
  document.getElementById("authDisplayNameRow")?.classList.toggle("hidden", mode !== "register");
  const btn = document.getElementById("btnAuthSubmit");
  if (btn) {
    btn.textContent = mode === "register" ? "✨ 创建个人账号并同步书架" : "登录并同步我的书架";
  }
  document.getElementById("authErrorMsg")?.classList.add("hidden");
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const username = (document.getElementById("authUsername")?.value || "").trim();
  const password = document.getElementById("authPassword")?.value || "";
  const displayName = (document.getElementById("authDisplayName")?.value || "").trim();
  const errBox = document.getElementById("authErrorMsg");
  const btn = document.getElementById("btnAuthSubmit");

  errBox?.classList.add("hidden");
  if (btn) btn.disabled = true;

  try {
    const endpoint = state.authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const body = state.authMode === "register"
      ? { username, password, display_name: displayName }
      : { username, password };

    const res = await apiFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    state.authToken = res.token;
    setAuthToken(res.token);
    state.currentUser = res.user;
    state.userStats = res.stats;
    updateAccountButtonUI();
    document.getElementById("modalAuth")?.classList.add("hidden");
    document.getElementById("authPassword").value = "";

    await reloadWorkspaceData();
    switchMainView("reader");
    showToast(`🎉 欢迎，${res.user.display_name}！已进入你的独立云端学术空间`, 3800);
  } catch (err) {
    if (errBox) {
      errBox.textContent = `❌ ${err.message}`;
      errBox.classList.remove("hidden");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function openProfileModal() {
  await loadAuthMe();
  const u = state.currentUser;
  const st = state.userStats || { custom_papers: 0, ru_vocab: 0, en_vocab: 0, mastered_vocab: 0 };
  if (!u) return;

  const box = document.getElementById("profileSummaryBox");
  box.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <div class="brand-mark" style="width:42px;height:42px;font-size:20px;border-radius:50%">${esc(u.display_name.slice(0, 1).toUpperCase())}</div>
      <div>
        <div style="font-size:16px;font-weight:700">${esc(u.display_name)}</div>
        <div class="muted">登录账号：${esc(u.username)} · 云端数据隔离保护中</div>
      </div>
    </div>
    <div class="profile-stats-grid">
      <div class="stat-tile">
        <div class="stat-num">${st.custom_papers}</div>
        <div class="stat-lbl">个人导入文献（篇）</div>
      </div>
      <div class="stat-tile">
        <div class="stat-num">${st.ru_vocab}</div>
        <div class="stat-lbl">🇷🇺 俄语学术词条</div>
      </div>
      <div class="stat-tile">
        <div class="stat-num">${st.en_vocab}</div>
        <div class="stat-lbl">🇬🇧 英语学术词条</div>
      </div>
      <div class="stat-tile">
        <div class="stat-num">${st.mastered_vocab}</div>
        <div class="stat-lbl">🏆 SM-2 熟练掌握</div>
      </div>
    </div>
  `;
  document.getElementById("modalProfile")?.classList.remove("hidden");
}

async function handleLogout() {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } catch (_) {}
  state.authToken = "";
  setAuthToken("");
  state.currentUser = null;
  updateAccountButtonUI();
  document.getElementById("modalProfile")?.classList.add("hidden");
  await reloadWorkspaceData();
  showToast("已退出账号，当前处于独立访客体验模式");
}

// ---------- Portal Sample Paper Cards ----------
function renderPortalSampleCards() {
  const grid = document.getElementById("portalPaperCards");
  if (!grid) return;
  grid.innerHTML = state.papers
    .slice(0, 4)
    .map((p) => {
      const langBadge = p.lang === "ru"
        ? `<span class="lang-tag ru">🇷🇺 Русский · 俄语学术文献</span>`
        : `<span class="lang-tag en">🇬🇧 English · 英语学术文献</span>`;
      return `
        <div class="portal-paper-card" data-open-pid="${p.id}">
          <div>${langBadge}</div>
          <h4>${esc(p.title)}</h4>
          <div style="color:var(--primary);font-weight:600;font-size:13px;margin-bottom:4px">${esc(p.title_zh)}</div>
          <div class="muted">${esc(p.authors || p.source || "")} · 点击开启双语精读 →</div>
        </div>
      `;
    })
    .join("");

  grid.querySelectorAll("[data-open-pid]").forEach((card) => {
    card.addEventListener("click", async () => {
      const pid = parseInt(card.dataset.openPid, 10);
      switchMainView("reader");
      await selectPaper(pid);
    });
  });
}

// ---------- Paper Library & Reader ----------
async function loadPapers() {
  const data = await apiFetch("/api/papers");
  state.papers = data.papers || [];
  renderPaperList();
}

function renderPaperList() {
  const container = document.getElementById("paperList");
  if (!container) return;
  const filtered = state.papers.filter((p) => state.paperFilter === "all" || p.lang === state.paperFilter);
  if (!filtered.length) {
    container.innerHTML = `<div class="muted" style="padding:14px">暂无符合筛选条件的论文，点击右上角「＋ 导入论文」添加。</div>`;
    return;
  }

  container.innerHTML = filtered
    .map((p) => {
      const isAct = state.currentPaper && state.currentPaper.id === p.id;
      const langLabel = p.lang === "ru" ? "🇷🇺 俄语" : "🇬🇧 英语";
      const delBtn = p.can_delete
        ? `<button class="paper-del-btn" data-del-pid="${p.id}" title="删除该文献">✕</button>`
        : `<span class="muted" style="font-size:10.5px">精选</span>`;
      return `
        <div class="paper-item ${isAct ? "active" : ""}" data-pid="${p.id}">
          <div class="paper-item-top">
            <span class="lang-tag ${p.lang}">${langLabel}</span>
            ${delBtn}
          </div>
          <div class="paper-item-title">${esc(p.title)}</div>
          <div class="paper-item-zh">${esc(p.title_zh || p.source || "")}</div>
        </div>
      `;
    })
    .join("");

  container.querySelectorAll(".paper-item").forEach((el) => {
    el.addEventListener("click", async (e) => {
      if (e.target.closest(".paper-del-btn")) return;
      await selectPaper(parseInt(el.dataset.pid, 10));
      closeMobileDrawers();
    });
  });

  container.querySelectorAll(".paper-del-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const pid = parseInt(btn.dataset.delPid, 10);
      if (!confirm("确定从个人书架删除这篇文献吗？")) return;
      try {
        await apiFetch(`/api/papers/${pid}`, { method: "DELETE" });
        await loadPapers();
        if (state.currentPaper && state.currentPaper.id === pid && state.papers.length) {
          await selectPaper(state.papers[0].id);
        }
        showToast("已从书架移除该文献");
      } catch (err) {
        showToast(err.message);
      }
    });
  });
}

async function selectPaper(paperId) {
  const paper = await apiFetch(`/api/papers/${paperId}`);
  state.currentPaper = paper;
  renderPaperList();

  const badge = document.getElementById("currentLangBadge");
  if (paper.lang === "ru") {
    badge.className = "lang-pill ru";
    badge.textContent = "🇷🇺 Русский · 俄语学术";
    document.getElementById("btnToggleStress")?.classList.remove("hidden");
    document.getElementById("btnToggleStress")?.classList.toggle("active", state.showStress);
  } else {
    badge.className = "lang-pill en";
    badge.textContent = "🇬🇧 English · 英语学术";
    document.getElementById("btnToggleStress")?.classList.add("hidden");
  }

  const pdfBtn = document.getElementById("btnPdfSplitLayout");
  if (paper.pdf_filename) {
    pdfBtn?.classList.remove("hidden");
    document.getElementById("pdfIframe").src = `/api/uploads/${encodeURIComponent(paper.pdf_filename)}`;
  } else {
    pdfBtn?.classList.add("hidden");
    if (state.layout === "pdf_split") {
      state.layout = "parallel";
      document.querySelectorAll("#layoutSegmented .seg-btn").forEach((b) =>
        b.classList.toggle("active", b.dataset.layout === "parallel")
      );
    }
  }

  document.getElementById("paperNotesArea").value = paper.notes || "";
  document.getElementById("notesSaveHint").textContent = "已同步保存";

  applyReaderLayout();
  renderCurrentPaper();
}

function applyReaderLayout() {
  const art = document.getElementById("paperArticle");
  if (!art) return;
  art.className = `paper-article layout-${state.layout} ${state.showAcademicHl ? "show-academic-hl" : ""}`;
  document.getElementById("pdfViewerPane")?.classList.toggle("hidden", state.layout !== "pdf_split");
}

function tokenizeSentenceHtml(sentence, stressedSentence, lang, acadSet, sentKey) {
  const displaySent = (lang === "ru" && state.showStress && stressedSentence) ? stressedSentence : sentence;
  const regex = lang === "ru"
    ? /([а-яА-ЯёЁ\u0301\u0300]+(?:-[а-яА-ЯёЁ\u0301\u0300]+)*)/g
    : /([a-zA-Z]+(?:-[a-zA-Z]+)*)/g;

  const parts = displaySent.split(regex);
  return parts
    .map((part) => {
      if (!part) return "";
      if (regex.test(part)) {
        regex.lastIndex = 0;
        const bareLow = stripStress(part).toLowerCase();
        let isAcad = acadSet.has(bareLow);
        if (!isAcad && bareLow.length >= 6) {
          for (const aw of acadSet) {
            if (aw.length >= 5 && bareLow.startsWith(aw.slice(0, -2))) {
              isAcad = true;
              break;
            }
          }
        }
        return `<span class="w-tok ${isAcad ? "is-acad" : ""}" data-word="${esc(stripStress(part))}" data-skey="${sentKey}">${esc(part)}</span>`;
      }
      regex.lastIndex = 0;
      return esc(part);
    })
    .join("");
}

function renderCurrentPaper() {
  const p = state.currentPaper;
  const art = document.getElementById("paperArticle");
  if (!p || !art) return;

  const acadSet = new Set((p.academic_words || []).map((w) => w.toLowerCase()));
  const sentenceStore = {};

  const doiMatch = (p.source || "").match(/DOI:\s*(10\.\d{4,9}\/[^\s)·]+)/i);
  const doiLinkHtml = doiMatch
    ? `<a class="sent-btn" style="text-decoration:none" href="https://doi.org/${encodeURIComponent(doiMatch[1])}" target="_blank" rel="noopener">🔗 原刊 DOI</a>`
    : "";

  let html = `
    <header class="paper-header">
      <h1 class="paper-orig-title">${esc(p.title)}</h1>
      ${p.title_zh ? `<div class="paper-zh-title">${esc(p.title_zh)}</div>` : ""}
      <div class="paper-meta">
        ${p.authors ? `<span>👤 ${esc(p.authors)}</span>` : ""}
        ${p.source ? `<span>🏛️ ${esc(p.source)}</span>` : ""}
        ${doiLinkHtml}
        <button class="sent-btn" id="btnSpeakTitle">🔊 朗读标题</button>
      </div>
    </header>
  `;

  for (const para of p.paragraphs || []) {
    const isHeading = para.type === "heading";
    const origSentences = para.sentences && para.sentences.length ? para.sentences : [para.text];
    const stressedSentences = para.stressed_text
      ? splitClientSentences(para.stressed_text, origSentences.length)
      : [];
    const zhSentences = para.zh_sentences && para.zh_sentences.length ? para.zh_sentences : (para.zh_text ? [para.zh_text] : []);

    const origSpans = origSentences
      .map((s, idx) => {
        const skey = `${para.id}_s${idx}`;
        const zhMatch = zhSentences[idx] || para.zh_text || "";
        sentenceStore[skey] = { orig: s, zh: zhMatch };
        const stSent = stressedSentences[idx] || "";
        const tokHtml = tokenizeSentenceHtml(s, stSent, p.lang, acadSet, skey);
        const actions = isHeading
          ? ""
          : `<span class="sent-actions">
               <button class="sent-btn" data-speak-skey="${skey}" title="母语朗读此句">🔊</button>
               <button class="sent-btn" data-analyze-skey="${skey}" title="长难句结构与语法拆解">拆解</button>
             </span>`;
        return `<span class="sent-span" data-sync="${skey}">${tokHtml}${actions}</span> `;
      })
      .join("");

    let zhHtml = "";
    if (zhSentences.length) {
      zhHtml = zhSentences
        .map((zs, idx) => {
          const skey = `${para.id}_s${Math.min(idx, origSentences.length - 1)}`;
          return `<span class="sent-span" data-sync="${skey}">${esc(zs)}</span> `;
        })
        .join("");
    } else {
      zhHtml = `<span class="muted">（尚未翻译，可点击顶部「🌐 补全/重译」一键生成中文译文）</span>`;
    }

    html += `
      <section class="para-block ${isHeading ? "is-heading" : ""}" data-para-id="${para.id}">
        <div class="para-grid">
          <div class="para-orig">${origSpans}</div>
          <div class="para-zh" title="${state.layout === "cloze_read" ? "点击或悬停显示中文译文" : ""}">${zhHtml}</div>
        </div>
      </section>
    `;
  }

  art.innerHTML = html;

  document.getElementById("btnSpeakTitle")?.addEventListener("click", () => playTTS(p.title, p.lang, false));

  art.querySelectorAll(".para-zh").forEach((zEl) => {
    zEl.addEventListener("click", () => zEl.classList.toggle("revealed"));
  });

  art.querySelectorAll(".sent-span").forEach((sp) => {
    const key = sp.dataset.sync;
    sp.addEventListener("mouseenter", () => {
      art.querySelectorAll(`.sent-span[data-sync="${key}"]`).forEach((m) => m.classList.add("sync-hover"));
    });
    sp.addEventListener("mouseleave", () => {
      art.querySelectorAll(`.sent-span[data-sync="${key}"]`).forEach((m) => m.classList.remove("sync-hover"));
    });
  });

  art.querySelectorAll(".w-tok").forEach((tok) => {
    tok.addEventListener("click", (e) => {
      e.stopPropagation();
      art.querySelectorAll(".w-tok.selected").forEach((x) => x.classList.remove("selected"));
      tok.classList.add("selected");
      const skey = tok.dataset.skey;
      const ctx = sentenceStore[skey] || { orig: "", zh: "" };
      inspectWord(tok.dataset.word, p.lang, ctx.orig, ctx.zh);
    });
  });

  art.querySelectorAll("[data-speak-skey]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const ctx = sentenceStore[btn.dataset.speakSkey];
      if (ctx) playTTS(ctx.orig, p.lang, false);
    });
  });

  art.querySelectorAll("[data-analyze-skey]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const skey = btn.dataset.analyzeSkey;
      art.querySelectorAll(".sent-span.active-sent").forEach((x) => x.classList.remove("active-sent"));
      art.querySelectorAll(`.sent-span[data-sync="${skey}"]`).forEach((x) => x.classList.add("active-sent"));
      const ctx = sentenceStore[skey];
      if (ctx) analyzeSentence(ctx.orig, p.lang);
    });
  });
}

function splitClientSentences(stressedPara, targetLen) {
  const parts = stressedPara.split(/(?<=[.!?])\s+(?=[A-ZА-ЯЁ0-9«"(\[])/);
  if (parts.length === targetLen) return parts;
  return [stressedPara];
}

// ---------- Word Inspector ----------
async function inspectWord(word, langHint = null, contextSentence = "", contextZh = "") {
  switchInspectorTab("word");
  const panel = document.getElementById("inspWordPanel");
  panel.innerHTML = `<div class="empty-inspector"><p>⏳ 正在解析「<strong>${esc(word)}</strong>」的词源、重音与变格体系...</p></div>`;

  try {
    const data = await apiFetch("/api/nlp/word", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        word,
        lang: langHint,
        context_sentence: contextSentence,
      }),
    });
    state.lastWordData = data;
    state.lastWordContextZh = contextZh;
    renderWordInspector(data);
  } catch (e) {
    panel.innerHTML = `<div class="empty-inspector"><p style="color:#ef4444">词法查询失败：${esc(e.message)}</p></div>`;
  }
}

function renderWordInspector(d) {
  const panel = document.getElementById("inspWordPanel");
  const isRu = d.lang === "ru";
  const alreadySaved = state.vocabList.some(
    (v) => v.lang === d.lang && v.lemma.toLowerCase() === (d.lemma || d.word).toLowerCase()
  );

  const headDisplay = isRu ? (d.stressed_word || d.word) : d.word;
  const lemmaDisplay = isRu ? (d.stressed_lemma || d.lemma) : d.lemma;
  const phoneticInfo = isRu
    ? [d.syllables ? `音节: ${d.syllables}` : "", d.translit ? `拉丁转写: ${d.translit}` : ""].filter(Boolean).join(" · ")
    : (d.ipa ? `音标: ${d.ipa}` : "");

  const bridgeChips = (d.bridge_terms || [])
    .map((term) => {
      const cleanTerm = term.replace(/^\(主动:\s*|\)$/g, "").trim();
      return `<button class="bridge-chip" data-bterm="${esc(cleanTerm)}" data-blang="${esc(d.bridge_lang)}" title="点击听取该跨语种对应词发音">
        <span>🔊 ${esc(term)}</span>
      </button>`;
    })
    .join("");

  const tagsHtml = (d.tags || []).map((t) => `<span class="morph-tag">${esc(t)}</span>`).join("");

  let altHtml = "";
  if (d.alt_parses && d.alt_parses.length) {
    altHtml = `
      <div class="info-card">
        <div class="info-card-label">🔀 同形异格其他可能性（结合上下文判断）</div>
        <div class="info-card-content" style="font-size:12px;color:var(--text-secondary)">
          ${d.alt_parses.map((a) => `• 原形 <strong>${esc(a.lemma)}</strong>：${esc(a.summary)}`).join("<br>")}
        </div>
      </div>
    `;
  }

  let paradigmHtml = "";
  if (d.paradigm && d.paradigm.rows) {
    const ths = d.paradigm.headers.map((h) => `<th>${esc(h)}</th>`).join("");
    const trs = d.paradigm.rows
      .map((r) => {
        const tds = r.cells
          .map((c) => {
            const speakVal = c.text.includes(":") ? c.text.split(":").pop().trim() : c.text;
            const clickable = speakVal && speakVal !== "—";
            return `<td class="paradigm-cell ${c.active ? "active-form" : ""}" ${
              clickable ? `data-speak-ru="${esc(speakVal)}" title="点击朗读：${esc(speakVal)}"` : ""
            }>${esc(c.text)}</td>`;
          })
          .join("");
        return `<tr><td title="${esc(r.hint || "")}"><strong>${esc(r.label)}</strong></td>${tds}</tr>`;
      })
      .join("");

    paradigmHtml = `
      <div class="info-card">
        <div class="info-card-label">
          <span>📊 ${esc(d.paradigm.title)}</span>
          <span class="muted">点击任一词形可朗读</span>
        </div>
        <table class="paradigm-table">
          <thead><tr>${ths}</tr></thead>
          <tbody>${trs}</tbody>
        </table>
      </div>
    `;
  }

  let enDefsHtml = "";
  if (!isRu && d.en_definitions && d.en_definitions.length) {
    enDefsHtml = `
      <div class="info-card">
        <div class="info-card-label">📘 英文学术原版释义 (English Definitions)</div>
        <div class="info-card-content" style="font-size:12.5px">
          ${d.en_definitions
            .map(
              (ed) =>
                `<div style="margin-bottom:6px"><strong>[${esc(ed.pos)}]</strong> ${esc(ed.definition)}${
                  ed.example ? `<div class="muted">例: "${esc(ed.example)}"</div>` : ""
                }</div>`
            )
            .join("")}
        </div>
      </div>
    `;
  }

  panel.innerHTML = `
    <div class="word-hero">
      <div class="word-hero-top">
        <div>
          <div class="word-main-title">${esc(headDisplay)}</div>
          <div class="word-lemma-line">
            词典原形：<strong>${esc(lemmaDisplay)}</strong>
            ${d.participle_base ? ` · 形动词原形：<strong>${esc(d.participle_base)}</strong>` : ""}
          </div>
          ${phoneticInfo ? `<div class="muted" style="margin-top:3px">${esc(phoneticInfo)}</div>` : ""}
        </div>
        <button id="btnSaveWordToVocab" class="btn ${alreadySaved ? "btn-secondary" : "btn-primary"} btn-sm">
          ${alreadySaved ? "✅ 已收生词" : "⭐ 加入生词本"}
        </button>
      </div>

      <div class="audio-row">
        <button class="btn btn-tool" id="btnWordSpeakNormal">🔊 标准 (1.0x)</button>
        <button class="btn btn-tool" id="btnWordSpeakSlow">🐢 慢速 (0.75x)</button>
        ${d.word.toLowerCase() !== d.lemma.toLowerCase() ? `<button class="btn btn-tool" id="btnLemmaSpeak">🔊 读原形 (${esc(lemmaDisplay)})</button>` : ""}
      </div>
    </div>

    <div class="info-card">
      <div class="info-card-label">🇨🇳 中文学术释义</div>
      <div class="info-card-content"><strong>${esc(d.meaning_zh || d.primary_zh || "暂无释义")}</strong></div>
    </div>

    <div class="info-card bridge-card">
      <div class="info-card-label">${esc(d.bridge_label || "跨语种互学")}</div>
      <div class="bridge-chips">${bridgeChips || `<span class="muted">${esc(d.bridge_meaning || "—")}</span>`}</div>
    </div>

    <div class="info-card">
      <div class="info-card-label">🧬 语法形态解析</div>
      <div class="morph-tags">${tagsHtml}</div>
      ${d.academic_tip ? `<div class="acad-tip-box" style="margin-bottom:0">${esc(d.academic_tip)}</div>` : ""}
    </div>

    ${altHtml}
    ${paradigmHtml}
    ${enDefsHtml}
  `;

  document.getElementById("btnWordSpeakNormal")?.addEventListener("click", () => playTTS(d.word, d.lang, false));
  document.getElementById("btnWordSpeakSlow")?.addEventListener("click", () => playTTS(d.word, d.lang, true));
  document.getElementById("btnLemmaSpeak")?.addEventListener("click", () => playTTS(d.lemma, d.lang, false));

  panel.querySelectorAll("[data-bterm]").forEach((chip) => {
    chip.addEventListener("click", () => playTTS(chip.dataset.bterm, chip.dataset.blang, false));
  });

  panel.querySelectorAll("[data-speak-ru]").forEach((td) => {
    td.addEventListener("click", () => playTTS(td.dataset.speakRu, "ru", false));
  });

  document.getElementById("btnSaveWordToVocab")?.addEventListener("click", async () => {
    const btn = document.getElementById("btnSaveWordToVocab");
    const payload = {
      word: d.word,
      lemma: d.lemma || d.word,
      lang: d.lang,
      stressed_or_ipa: d.lang === "ru" ? (d.stressed_lemma || d.lemma) : (d.ipa || d.lemma),
      pos_summary: d.pos_summary || "",
      meaning_zh: d.meaning_zh || d.primary_zh || "",
      bridge_meaning: d.bridge_meaning || "",
      grammar_note: d.academic_tip || "",
      context_sentence: d.context_sentence || "",
      context_zh: state.lastWordContextZh || "",
      paper_id: state.currentPaper ? state.currentPaper.id : null,
      paper_title: state.currentPaper ? state.currentPaper.title : "",
    };
    await apiFetch("/api/vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    btn.textContent = "✅ 已收生词";
    btn.className = "btn btn-secondary btn-sm";
    await loadVocab();
    showToast(`已将「${payload.stressed_or_ipa || payload.lemma}」保存到你的生词本`);
  });
}

// ---------- Sentence Syntax & AI Coach ----------
async function analyzeSentence(sentence, lang, useLlm = null, question = "") {
  switchInspectorTab("sentence");
  const panel = document.getElementById("inspSentencePanel");
  panel.innerHTML = `<div class="empty-inspector"><p>⏳ 正在拆解长难句结构、生成英俄对照表达与语法讲义...</p></div>`;

  try {
    const res = await apiFetch("/api/nlp/sentence", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sentence, lang, use_llm: useLlm, question }),
    });
    state.lastSentenceData = res;
    renderSentenceInspector(res);
  } catch (e) {
    panel.innerHTML = `<div class="empty-inspector"><p style="color:#ef4444">长难句分析失败：${esc(e.message)}</p></div>`;
  }
}

function renderSentenceInspector(s) {
  const panel = document.getElementById("inspSentencePanel");

  const tokenRibbonHtml = (s.structure.tokens || [])
    .filter((t) => t.is_word)
    .map(
      (t) => `
      <div class="tok-pill role-${esc(t.role)}" data-tok-word="${esc(t.text)}" title="原形: ${esc(t.lemma)} (点击查看完整变格与释义)">
        <span class="t-word">${esc(t.stressed || t.text)}</span>
        <span class="t-badge">${esc(t.badge)}</span>
      </div>
    `
    )
    .join("");

  const clausesHtml = (s.structure.clauses || [])
    .map(
      (c, i) => `
      <div class="clause-item">
        <div class="clause-label">${i + 1}. ${esc(c.label)}</div>
        <div class="clause-text">${esc(c.text)}</div>
        <div class="clause-note">${esc(c.note)}</div>
      </div>
    `
    )
    .join("");

  let phrasesHtml = "";
  if (s.structure.academic_phrases && s.structure.academic_phrases.length) {
    phrasesHtml = `
      <div class="info-card">
        <div class="info-card-label">📌 句中学术论文高频句式模板</div>
        ${s.structure.academic_phrases
          .map(
            (ap) => `
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding:5px 0;border-bottom:1px dashed var(--border)">
              <div>
                <strong>${esc(ap.phrase)}</strong>
                <div class="muted">${esc(ap.meaning)}</div>
              </div>
              <button class="btn btn-secondary btn-xs" data-save-phrase="${esc(ap.phrase)}" data-phrase-meaning="${esc(ap.meaning)}">＋收藏</button>
            </div>
          `
          )
          .join("")}
      </div>
    `;
  }

  panel.innerHTML = `
    <div class="info-card" style="background:var(--bg-subtle)">
      <div class="info-card-label">
        <span>📜 原句（已标重音）</span>
        <span>
          <button class="sent-btn" id="btnSentPlay1">🔊 1.0x</button>
          <button class="sent-btn" id="btnSentPlaySlow">🐢 0.75x 跟读</button>
        </span>
      </div>
      <div class="info-card-content" style="font-family:'PT Serif',Georgia,'Liberation Serif',serif;font-size:15px">
        ${esc(s.stressed_sentence || s.sentence)}
      </div>
    </div>

    <div class="info-card">
      <div class="info-card-label">🇨🇳 中文学术译文</div>
      <div class="info-card-content"><strong>${esc(s.zh_translation)}</strong></div>
    </div>

    <div class="info-card bridge-card">
      <div class="info-card-label">
        <span>${esc(s.cross_label)}</span>
        <button class="sent-btn" id="btnCrossPlay">🔊 朗读对照句</button>
      </div>
      <div class="info-card-content" style="font-family:'PT Serif',Georgia,'Liberation Serif',serif">
        ${esc(s.cross_translation)}
      </div>
    </div>

    <div class="info-card">
      <div class="info-card-label"><span>📐 意群与分句结构拆解</span></div>
      ${clausesHtml}
    </div>

    <div class="info-card">
      <div class="info-card-label">
        <span>🎨 逐词语法角色彩带</span>
        <span class="muted">点击任意词块查变格</span>
      </div>
      <div class="muted" style="margin-bottom:6px;font-size:11px">
        <span style="color:#2563eb">■ 主格/核心词</span> ·
        <span style="color:#dc2626">■ 谓语动词</span> ·
        <span style="color:#9333ea">■ 形动词/分词</span> ·
        <span style="color:#d97706">■ 二格属格链</span> ·
        <span style="color:#059669">■ 连词/前置词</span>
      </div>
      <div class="token-ribbon">${tokenRibbonHtml}</div>
    </div>

    ${phrasesHtml}

    <div class="info-card">
      <div class="info-card-label">
        <span>🤖 语法深度讲解 (${esc(s.ai_source)})</span>
        <button class="btn btn-secondary btn-xs" id="btnForceLlmExplain">✨ AI 深度重讲</button>
      </div>
      <div class="md-explain">${simpleMarkdownToHtml(s.explanation_md)}</div>
      <div class="tutor-ask-box">
        <input id="sentQuestionInput" type="text" placeholder="针对此句追问语法（如：为什么用第五格？）" />
        <button id="btnAskSentTutor" class="btn btn-primary btn-xs">提问</button>
      </div>
    </div>
  `;

  document.getElementById("btnSentPlay1")?.addEventListener("click", () => playTTS(s.sentence, s.lang, false));
  document.getElementById("btnSentPlaySlow")?.addEventListener("click", () => playTTS(s.sentence, s.lang, true));
  document.getElementById("btnCrossPlay")?.addEventListener("click", () => playTTS(s.cross_translation, s.cross_lang, false));

  panel.querySelectorAll("[data-tok-word]").forEach((pill) => {
    pill.addEventListener("click", () => inspectWord(pill.dataset.tokWord, s.lang, s.sentence, s.zh_translation));
  });

  panel.querySelectorAll("[data-save-phrase]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const phrase = btn.dataset.savePhrase;
      const meaning = btn.dataset.phraseMeaning;
      await apiFetch("/api/vocab", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          word: phrase,
          lemma: phrase,
          lang: s.lang,
          stressed_or_ipa: s.lang === "ru" ? phrase : "",
          pos_summary: "学术高频固定搭配 / 句式",
          meaning_zh: meaning,
          context_sentence: s.sentence,
          context_zh: s.zh_translation,
          paper_id: state.currentPaper ? state.currentPaper.id : null,
          paper_title: state.currentPaper ? state.currentPaper.title : "",
        }),
      });
      btn.textContent = "✓ 已收";
      await loadVocab();
      showToast(`已收藏学术句式「${phrase}」`);
    });
  });

  document.getElementById("btnForceLlmExplain")?.addEventListener("click", () => {
    if (!s.llm_configured) {
      showToast("请先在右上角「⚙️ 设置」中启用并配置个人大模型 API Key");
      populateSettingsModal();
      document.getElementById("modalSettings")?.classList.remove("hidden");
      return;
    }
    analyzeSentence(s.sentence, s.lang, true, "");
  });

  document.getElementById("btnAskSentTutor")?.addEventListener("click", () => {
    const q = (document.getElementById("sentQuestionInput")?.value || "").trim();
    if (q) analyzeSentence(s.sentence, s.lang, true, q);
  });
}

// ---------- Export Paper Markdown ----------
function exportCurrentPaperMarkdown() {
  const p = state.currentPaper;
  if (!p) return;
  const lines = [
    `# ${p.title}`,
    p.title_zh ? `## ${p.title_zh}` : "",
    p.authors ? `- **作者**：${p.authors}` : "",
    p.source ? `- **来源**：${p.source}` : "",
    "",
    "---",
    "## 一、双语对照正文",
    "",
  ];

  for (const para of p.paragraphs || []) {
    if (para.type === "heading") {
      lines.push(`### ${para.text} ${para.zh_text ? `（${para.zh_text}）` : ""}\n`);
    } else {
      lines.push(`${para.stressed_text || para.text}\n`);
      if (para.zh_text) lines.push(`> ${para.zh_text}\n`);
    }
  }

  if (p.notes) {
    lines.push("---\n## 二、个人精读笔记\n");
    lines.push(p.notes + "\n");
  }

  const paperVocab = state.vocabList.filter((v) => v.paper_id === p.id);
  if (paperVocab.length) {
    lines.push("---\n## 三、本篇积累核心词汇\n");
    paperVocab.forEach((v, idx) => {
      lines.push(`${idx + 1}. **${v.stressed_or_ipa || v.lemma}** (\`${v.word}\`) — ${v.meaning_zh} ${v.bridge_meaning ? `| 互证: *${v.bridge_meaning}*` : ""}`);
    });
  }

  const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `bilingual_notes_paper_${p.id}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast("已导出双语精读讲义 (.md)");
}

// ---------- Import Handlers (DOI / PDF / Text / arXiv) ----------
async function handleImportDoi() {
  const doi = (document.getElementById("impDoiInput")?.value || "").trim();
  const preferFulltext = Boolean(document.getElementById("chkDoiFulltext")?.checked);
  await submitDoiImport(doi, preferFulltext, "modal");
}

async function submitDoiImport(doi, preferFulltext = true, triggerSource = "modal") {
  if (state.doiImporting) return;
  if (!doi) {
    showToast("请输入有效的论文 DOI 编号或链接（如 10.60797/IRJ.2026.170.43）");
    const banner = document.getElementById("doiProgressBanner");
    if (banner && triggerSource === "modal") {
      banner.className = "doi-progress-banner is-error";
      banner.textContent = "⚠️ 请先在上方输入框粘贴或输入论文 DOI 编号。";
      banner.classList.remove("hidden");
    }
    return;
  }

  state.doiImporting = true;
  const st = document.getElementById("importDoiStatus");
  const banner = document.getElementById("doiProgressBanner");
  const btnModal = document.getElementById("btnSubmitDoi");
  const btnSide = document.getElementById("btnSidebarDoi");

  const progressMsg = preferFulltext
    ? `⏳ 正在并发检索 DOI (${doi}) 的元数据、摘要与开放获取 PDF 全文，请稍候 2~8 秒...`
    : `⏳ 正在解析 DOI (${doi}) 的论文题录与双语摘要...`;

  showToast(progressMsg, 6000);
  if (st) st.textContent = "⏳ 正在解析 DOI...";
  if (banner) {
    banner.className = "doi-progress-banner";
    banner.textContent = progressMsg;
    banner.classList.remove("hidden");
  }
  if (btnModal) {
    btnModal.disabled = true;
    btnModal.textContent = "⏳ 正在解析导入...";
  }
  if (btnSide) {
    btnSide.disabled = true;
    btnSide.textContent = "解析中...";
  }

  try {
    const paper = await apiFetch("/api/papers/import-doi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doi, prefer_fulltext: preferFulltext, auto_translate: true }),
    });

    document.getElementById("modalImport")?.classList.add("hidden");
    if (document.getElementById("impDoiInput")) document.getElementById("impDoiInput").value = "";
    if (document.getElementById("sidebarDoiInput")) document.getElementById("sidebarDoiInput").value = "";
    if (document.getElementById("heroDoiInput")) document.getElementById("heroDoiInput").value = "";
    if (triggerSource === "quick" && document.getElementById("quickLookupInput")) {
      document.getElementById("quickLookupInput").value = "";
    }
    if (st) st.textContent = "";
    if (banner) banner.classList.add("hidden");

    await loadPapers();
    switchMainView("reader");
    await selectPaper(paper.id);
    closeMobileDrawers();

    if (paper.import_mode === "full_pdf") {
      showToast(`✅ DOI 全文导入成功（共 ${paper.paragraphs.length} 段）！可点击顶部「原版 PDF」开启分屏对照`, 4800);
    } else if (paper.import_mode === "abstract") {
      showToast("✅ DOI 导入成功！已获取题录、摘要与关键词并生成中文译文", 3800);
    } else {
      showToast("ℹ️ 已导入该 DOI 题录信息（期刊正文受订阅限制，若有本地 PDF 可直接上传）", 4500);
    }

    const hasUntranslated = (paper.paragraphs || []).some((p) => !(p.zh_text || "").trim());
    if (hasUntranslated) {
      autoCompleteRemainingTranslations(paper.id);
    }
  } catch (e) {
    if (st) st.textContent = "";
    if (banner) {
      banner.className = "doi-progress-banner is-error";
      banner.textContent = `❌ 导入失败：${e.message}`;
      banner.classList.remove("hidden");
    }
    showToast(`❌ DOI 导入失败：${e.message}`, 4500);
  } finally {
    state.doiImporting = false;
    if (btnModal) {
      btnModal.disabled = false;
      btnModal.textContent = "🔍 解析 DOI 并导入精读";
    }
    if (btnSide) {
      btnSide.disabled = false;
      btnSide.textContent = "导入";
    }
  }
}

async function autoCompleteRemainingTranslations(paperId) {
  try {
    const updated = await apiFetch(`/api/papers/${paperId}/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force_retranslate: false }),
    });
    if (state.currentPaper && state.currentPaper.id === paperId) {
      state.currentPaper = updated;
      renderCurrentPaper();
      showToast("✨ 全文剩余段落的中文学术译文已自动补全");
    }
    await loadPapers();
  } catch (_) {}
}

async function handleUploadPdf() {
  if (!state.selectedPdfFile) {
    showToast("请先选择一个 PDF 论文文件");
    return;
  }
  const st = document.getElementById("importPdfStatus");
  const btn = document.getElementById("btnSubmitPdf");
  st.textContent = "⏳ 正在提取 PDF 段落并生成学术中文译文...";
  btn.disabled = true;

  try {
    const fd = new FormData();
    fd.append("file", state.selectedPdfFile);
    fd.append("auto_translate", "true");
    const paper = await apiFetch("/api/papers/upload-pdf", { method: "POST", body: fd });
    document.getElementById("modalImport")?.classList.add("hidden");
    st.textContent = "";
    state.selectedPdfFile = null;
    document.getElementById("selectedPdfName").textContent = "";
    await loadPapers();
    switchMainView("reader");
    await selectPaper(paper.id);
    showToast("✅ PDF 论文解析成功！点击顶部「原版 PDF」可开启分屏对照");
    if ((paper.paragraphs || []).some((p) => !(p.zh_text || "").trim())) {
      autoCompleteRemainingTranslations(paper.id);
    }
  } catch (e) {
    st.textContent = "❌ " + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function handleImportText() {
  const title = (document.getElementById("impTextTitle")?.value || "").trim();
  const authors = (document.getElementById("impTextAuthors")?.value || "").trim();
  const lang = document.getElementById("impTextLang")?.value || "auto";
  const text = (document.getElementById("impTextContent")?.value || "").trim();
  if (!text) {
    showToast("请粘贴论文文本内容");
    return;
  }

  const st = document.getElementById("importTextStatus");
  const btn = document.getElementById("btnSubmitText");
  st.textContent = "⏳ 正在分句并自动翻译前序段落...";
  btn.disabled = true;

  try {
    const paper = await apiFetch("/api/papers/import-text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, authors, lang, text, auto_translate: true }),
    });
    document.getElementById("modalImport")?.classList.add("hidden");
    document.getElementById("impTextTitle").value = "";
    document.getElementById("impTextContent").value = "";
    st.textContent = "";
    await loadPapers();
    switchMainView("reader");
    await selectPaper(paper.id);
    showToast("✅ 文本论文已导入并生成对照译文");
    if ((paper.paragraphs || []).some((p) => !(p.zh_text || "").trim())) {
      autoCompleteRemainingTranslations(paper.id);
    }
  } catch (e) {
    st.textContent = "❌ " + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function handleImportArxiv() {
  const arxivId = (document.getElementById("impArxivId")?.value || "").trim();
  const preferFulltext = Boolean(document.getElementById("chkArxivFulltext")?.checked);
  if (!arxivId) {
    showToast("请输入 arXiv 编号或链接");
    return;
  }
  const st = document.getElementById("importArxivStatus");
  const btn = document.getElementById("btnSubmitArxiv");
  st.textContent = preferFulltext ? "⏳ 正在抓取 arXiv 元数据与原版 PDF 全文..." : "⏳ 正在抓取 arXiv 摘要...";
  btn.disabled = true;

  try {
    const paper = await apiFetch("/api/papers/import-arxiv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arxiv_id: arxivId, prefer_fulltext: preferFulltext, auto_translate: true }),
    });
    document.getElementById("modalImport")?.classList.add("hidden");
    document.getElementById("impArxivId").value = "";
    st.textContent = "";
    await loadPapers();
    switchMainView("reader");
    await selectPaper(paper.id);
    showToast(paper.import_mode === "full_pdf" ? "✅ arXiv 原版 PDF 全文导入成功！" : "✅ arXiv 论文摘要导入成功");
    if ((paper.paragraphs || []).some((p) => !(p.zh_text || "").trim())) {
      autoCompleteRemainingTranslations(paper.id);
    }
  } catch (e) {
    st.textContent = "❌ " + e.message;
  } finally {
    btn.disabled = false;
  }
}

// ---------- Vocabulary Notebook ----------
async function loadVocab() {
  const params = new URLSearchParams();
  if (state.vocabLangFilter) params.set("lang", state.vocabLangFilter);
  if (state.vocabSearch.trim()) params.set("search", state.vocabSearch.trim());
  const data = await apiFetch(`/api/vocab?${params.toString()}`);
  state.vocabList = data.items || [];
  const badge = document.getElementById("navVocabCount");
  if (badge) badge.textContent = state.vocabList.length;
  renderVocabGrid();
}

function renderVocabGrid() {
  const grid = document.getElementById("vocabGrid");
  if (!grid) return;
  if (!state.vocabList.length) {
    grid.innerHTML = `<div class="muted" style="grid-column:1/-1;padding:28px;text-align:center">暂无生词记录。在「双语精读」点击任意俄语或英语单词即可一键收藏！</div>`;
    return;
  }

  grid.innerHTML = state.vocabList
    .map((v) => {
      const langBadge = v.lang === "ru" ? `<span class="lang-tag ru">🇷🇺 俄语</span>` : `<span class="lang-tag en">🇬🇧 英语</span>`;
      const bridgePrefix = v.lang === "ru" ? "🇬🇧 EN 互证" : "🇷🇺 RU 互证";
      const mastery =
        v.repetitions >= 3
          ? `<span style="color:#10b981;font-weight:600">熟练 (${Math.round(v.interval_days)}天周期)</span>`
          : v.repetitions >= 1
          ? `<span style="color:#3b82f6">复习中 (${v.repetitions}次)</span>`
          : `<span>新收录</span>`;

      return `
        <div class="vocab-card">
          <div class="vocab-card-head">
            <div>
              <span class="vocab-word-big">${esc(v.stressed_or_ipa && v.lang === "ru" ? v.stressed_or_ipa : v.lemma)}</span>
              ${v.word.toLowerCase() !== v.lemma.toLowerCase() ? `<span class="muted">（文中: ${esc(v.word)}）</span>` : ""}
              ${v.lang === "en" && v.stressed_or_ipa ? `<span class="muted">${esc(v.stressed_or_ipa)}</span>` : ""}
            </div>
            <div style="display:flex;align-items:center;gap:5px">
              <button class="sent-btn" data-vspeak="${esc(v.lemma)}" data-vlang="${v.lang}" title="朗读">🔊</button>
              ${langBadge}
            </div>
          </div>
          ${v.pos_summary ? `<div class="muted">${esc(v.pos_summary)}</div>` : ""}
          <div class="vocab-zh">${esc(v.meaning_zh)}</div>
          ${v.bridge_meaning ? `<div class="vocab-bridge">${bridgePrefix}：${esc(v.bridge_meaning)}</div>` : ""}
          ${v.grammar_note ? `<div class="muted">${esc(v.grammar_note)}</div>` : ""}
          ${v.context_sentence ? `<div class="vocab-ctx">${esc(v.context_sentence)}${v.context_zh ? `<div class="muted">${esc(v.context_zh)}</div>` : ""}</div>` : ""}
          <div class="vocab-foot">
            <span>${mastery}</span>
            <button class="paper-del-btn" style="opacity:1" data-del-vid="${v.id}">🗑 删除</button>
          </div>
        </div>
      `;
    })
    .join("");

  grid.querySelectorAll("[data-vspeak]").forEach((btn) => {
    btn.addEventListener("click", () => playTTS(btn.dataset.vspeak, btn.dataset.vlang, false));
  });
  grid.querySelectorAll("[data-del-vid]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiFetch(`/api/vocab/${btn.dataset.delVid}`, { method: "DELETE" });
      await loadVocab();
      showToast("已删除词条");
    });
  });
}

async function handleSaveManualVocab() {
  const word = (document.getElementById("mvWord")?.value || "").trim();
  const lang = document.getElementById("mvLang")?.value || "ru";
  const stressed = (document.getElementById("mvStressed")?.value || "").trim();
  const bridge = (document.getElementById("mvBridge")?.value || "").trim();
  const meaningZh = (document.getElementById("mvMeaningZh")?.value || "").trim();
  const ctx = (document.getElementById("mvContext")?.value || "").trim();

  if (!word || !meaningZh) {
    showToast("请至少填写单词与中文释义");
    return;
  }

  await apiFetch("/api/vocab", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      word,
      lemma: stripStress(word),
      lang,
      stressed_or_ipa: stressed,
      meaning_zh: meaningZh,
      bridge_meaning: bridge,
      context_sentence: ctx,
    }),
  });
  document.getElementById("modalManualVocab")?.classList.add("hidden");
  document.getElementById("mvWord").value = "";
  document.getElementById("mvMeaningZh").value = "";
  document.getElementById("mvContext").value = "";
  await loadVocab();
  showToast("✅ 已添加到你的生词本");
}

// ---------- SM-2 Flashcards & Cloze Trainer ----------
async function buildTrainerDeck() {
  const allData = await apiFetch("/api/vocab");
  let pool = allData.items || [];
  if (state.trainerLang !== "all") {
    pool = pool.filter((x) => x.lang === state.trainerLang);
  }
  const nowSec = Date.now() / 1000;
  pool.sort((a, b) => {
    const aDue = (a.next_review || 0) <= nowSec ? 0 : 1;
    const bDue = (b.next_review || 0) <= nowSec ? 0 : 1;
    if (aDue !== bDue) return aDue - bDue;
    return (a.next_review || 0) - (b.next_review || 0);
  });

  state.deck = pool;
  state.deckIndex = 0;
  state.cardFlipped = false;

  document.getElementById("flashcardStage")?.classList.toggle("hidden", state.trainerMode !== "flashcard");
  document.getElementById("clozeStage")?.classList.toggle("hidden", state.trainerMode !== "cloze");
  renderTrainerCurrent();
}

function renderTrainerCurrent() {
  if (state.trainerMode === "flashcard") renderFlashcard();
  else renderClozeQuiz();
}

function renderFlashcard() {
  const prog = document.getElementById("flashcardProgress");
  const cardEl = document.getElementById("flashcardEl");
  const front = document.getElementById("cardFront");
  const back = document.getElementById("cardBack");
  const actions = document.getElementById("flashcardActions");

  cardEl.classList.remove("flipped");
  state.cardFlipped = false;
  actions.classList.add("hidden");

  if (!state.deck.length) {
    prog.textContent = "";
    front.innerHTML = `<div style="text-align:center"><p>当前筛选下暂无生词卡片，先去阅读论文点击收藏几个词汇吧！</p></div>`;
    back.innerHTML = "";
    return;
  }

  if (state.deckIndex >= state.deck.length) {
    prog.textContent = "🎉 本轮训练全部完成！";
    front.innerHTML = `
      <div style="text-align:center">
        <div style="font-size:36px;margin-bottom:8px">🏆</div>
        <h3>太棒了！已完成本组 ${state.deck.length} 张学术词汇复习</h3>
        <button class="btn btn-primary" id="btnRestartDeck" style="margin-top:12px">再来一轮强化</button>
      </div>
    `;
    document.getElementById("btnRestartDeck")?.addEventListener("click", () => {
      state.deckIndex = 0;
      renderFlashcard();
    });
    return;
  }

  const item = state.deck[state.deckIndex];
  prog.textContent = `训练进度：${state.deckIndex + 1} / ${state.deck.length} · ${item.lang === "ru" ? "🇷🇺 俄语" : "🇬🇧 英语"}`;

  let frontWord = item.lang === "ru" ? (item.stressed_or_ipa || item.lemma) : item.lemma;
  if (item.lang === "ru" && state.hideStressFront) frontWord = stripStress(frontWord);

  front.innerHTML = `
    <div style="text-align:center">
      <span class="lang-tag ${item.lang}">${item.lang === "ru" ? "🇷🇺 Русский" : "🇬🇧 English"}</span>
    </div>
    <div class="fc-word">${esc(frontWord)}</div>
    <div class="fc-sub">
      ${item.word.toLowerCase() !== item.lemma.toLowerCase() ? `论文出现词形：<strong>${esc(item.word)}</strong> · ` : ""}
      <button class="sent-btn" id="btnFcFrontSpeak">🔊 听发音</button>
    </div>
    ${item.context_sentence ? `<div class="fc-sentence">${esc(item.context_sentence)}</div>` : ""}
    <div class="fc-hint-tap">👆 点击卡片翻转查看释义、重音与英俄互证</div>
  `;

  back.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <strong style="font-size:22px;font-family:'PT Serif',Georgia,'Liberation Serif',serif">${esc(item.stressed_or_ipa && item.lang === "ru" ? item.stressed_or_ipa : item.lemma)}</strong>
      <button class="btn btn-tool" id="btnFcBackSpeak">🔊 朗读</button>
    </div>
    ${item.pos_summary ? `<div class="muted" style="margin-bottom:8px">${esc(item.pos_summary)}</div>` : ""}
    <div class="info-card" style="margin-bottom:8px">
      <div class="info-card-label">🇨🇳 中文释义</div>
      <div class="info-card-content"><strong>${esc(item.meaning_zh)}</strong></div>
    </div>
    ${item.bridge_meaning ? `
      <div class="info-card bridge-card" style="margin-bottom:8px">
        <div class="info-card-label">${item.lang === "ru" ? "🇬🇧 对应英语学术词" : "🇷🇺 对应俄语学术词"}</div>
        <div class="info-card-content">${esc(item.bridge_meaning)}</div>
      </div>
    ` : ""}
    ${item.grammar_note ? `<div class="muted" style="margin-bottom:6px">${esc(item.grammar_note)}</div>` : ""}
    ${item.context_zh ? `<div class="muted">原句译文：${esc(item.context_zh)}</div>` : ""}
  `;

  document.getElementById("btnFcFrontSpeak")?.addEventListener("click", (e) => {
    e.stopPropagation();
    playTTS(item.word, item.lang, false);
  });
  document.getElementById("btnFcBackSpeak")?.addEventListener("click", (e) => {
    e.stopPropagation();
    playTTS(item.lemma, item.lang, false);
  });
}

function flipFlashcard() {
  if (!state.deck.length || state.deckIndex >= state.deck.length) return;
  state.cardFlipped = !state.cardFlipped;
  document.getElementById("flashcardEl")?.classList.toggle("flipped", state.cardFlipped);
  document.getElementById("flashcardActions")?.classList.toggle("hidden", !state.cardFlipped);
}

async function submitFlashcardReview(quality) {
  const item = state.deck[state.deckIndex];
  if (!item) return;
  await apiFetch(`/api/vocab/${item.id}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ quality }),
  });
  state.deckIndex += 1;
  renderFlashcard();
}

function renderClozeQuiz() {
  const box = document.getElementById("clozeBox");
  const validItems = state.deck.filter((x) => x.context_sentence && x.word);
  if (!validItems.length) {
    box.innerHTML = `<p class="muted" style="text-align:center">暂无包含论文原句语境的词条。在阅读器中点击单词收藏会自动附带原句，即可开启语境填空训练！</p>`;
    return;
  }

  const idx = state.deckIndex % validItems.length;
  const target = validItems[idx];
  const escapedWord = target.word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const blankedSent = target.context_sentence.replace(
    new RegExp(escapedWord, "i"),
    `<span class="cloze-blank" id="clozeSlot">_______</span>`
  );

  const sameLangPool = state.vocabList.filter((v) => v.lang === target.lang && v.word.toLowerCase() !== target.word.toLowerCase());
  const fallbackRu = ["исследовании", "рассматривается", "позволяют", "методологии", "эффектов"];
  const fallbackEn = ["methodology", "subsequently", "architecture", "empirical", "facilitates"];
  const distractors = sameLangPool.map((v) => v.word);
  for (const fb of target.lang === "ru" ? fallbackRu : fallbackEn) {
    if (fb.toLowerCase() !== target.word.toLowerCase() && !distractors.includes(fb)) {
      distractors.push(fb);
    }
  }
  const choices = [target.word, ...distractors.slice(0, 3)].sort(() => Math.random() - 0.5);

  box.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center">
      <span class="lang-tag ${target.lang}">${target.lang === "ru" ? "🇷🇺 俄语原句格位/词形还原测试" : "🇬🇧 英语学术语境选词测试"}</span>
      <span class="muted">第 ${idx + 1} / ${validItems.length} 题</span>
    </div>
    <div class="cloze-sent">${blankedSent}</div>
    ${target.context_zh ? `<div class="info-card" style="background:var(--bg-subtle)"><div class="info-card-label">参考中文句意</div><div class="info-card-content">${esc(target.context_zh)}</div></div>` : ""}
    <div class="muted">💡 词法与释义提示：<strong>${esc(target.meaning_zh)}</strong> ${target.pos_summary ? `（${esc(target.pos_summary)}）` : ""}</div>
    <div class="cloze-options">
      ${choices.map((c) => `<button class="cloze-opt" data-choice="${esc(c)}">${esc(c)}</button>`).join("")}
    </div>
    <div id="clozeFeedback" class="hidden" style="margin-top:16px;display:flex;justify-content:space-between;align-items:center">
      <span id="clozeFeedbackText"></span>
      <button id="btnNextCloze" class="btn btn-primary btn-sm">下一题 →</button>
    </div>
  `;

  box.dataset.locked = "0";
  box.querySelectorAll(".cloze-opt").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (box.dataset.locked === "1") return;
      box.dataset.locked = "1";
      const picked = btn.dataset.choice;
      const isRight = picked.toLowerCase() === target.word.toLowerCase();
      btn.classList.add(isRight ? "correct" : "wrong");
      box.querySelectorAll(".cloze-opt").forEach((b) => {
        if (b.dataset.choice.toLowerCase() === target.word.toLowerCase()) b.classList.add("correct");
      });
      const slot = document.getElementById("clozeSlot");
      if (slot) slot.textContent = target.word;
      playTTS(target.context_sentence, target.lang, false);

      document.getElementById("clozeFeedback")?.classList.remove("hidden");
      document.getElementById("clozeFeedbackText").innerHTML = isRight
        ? `<strong style="color:#10b981">✅ 回答正确！</strong> 原形：${esc(target.stressed_or_ipa || target.lemma)}`
        : `<strong style="color:#ef4444">❌ 正确词形应为：${esc(target.word)}</strong>（原形：${esc(target.stressed_or_ipa || target.lemma)}）`;
    });
  });

  document.getElementById("btnNextCloze")?.addEventListener("click", () => {
    state.deckIndex += 1;
    renderClozeQuiz();
  });
}

// ---------- Per-User Hybrid Engine Settings ----------
async function loadSettings() {
  const data = await apiFetch("/api/settings");
  state.settings = data.settings || {};
  updateLlmStatusIndicator();
}

function updateLlmStatusIndicator() {
  const dot = document.getElementById("llmStatusDot");
  if (!dot) return;
  const s = state.settings;
  const active = Boolean(s.llm_enabled && (s.has_api_key || s.llm_api_key || String(s.llm_base_url || "").includes("11434")));
  dot.classList.toggle("llm-on", active);
  dot.title = active
    ? `已启用个人大模型引擎 (${s.llm_model})`
    : "当前使用内置免配置混合学术引擎";
}

function populateSettingsModal() {
  const s = state.settings;
  document.getElementById("cfgLlmEnabled").checked = Boolean(s.llm_enabled);
  document.getElementById("cfgBaseUrl").value = s.llm_base_url || "https://api.deepseek.com/v1";
  document.getElementById("cfgModel").value = s.llm_model || "deepseek-chat";
  document.getElementById("cfgApiKey").value = s.llm_api_key || "";
  document.getElementById("cfgRuVoice").value = s.ru_voice || "ru-RU-SvetlanaNeural";
  document.getElementById("cfgEnVoice").value = s.en_voice || "en-US-AriaNeural";
  document.getElementById("settingsStatus").textContent = "";
}

function collectSettingsForm() {
  return {
    llm_enabled: document.getElementById("cfgLlmEnabled").checked,
    llm_base_url: document.getElementById("cfgBaseUrl").value.trim(),
    llm_model: document.getElementById("cfgModel").value.trim(),
    llm_api_key: document.getElementById("cfgApiKey").value.trim(),
    ru_voice: document.getElementById("cfgRuVoice").value,
    en_voice: document.getElementById("cfgEnVoice").value,
  };
}

async function handleTestLlm() {
  const st = document.getElementById("settingsStatus");
  st.textContent = "⏳ 正在测试大模型接口连通性...";
  try {
    const res = await apiFetch("/api/settings/test-llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectSettingsForm()),
    });
    st.textContent = res.ok ? `✅ 连接成功！模型回复：${res.reply}` : `❌ 连接失败：${res.error}`;
  } catch (e) {
    st.textContent = `❌ 请求异常：${e.message}`;
  }
}

async function handleSaveSettings() {
  const res = await apiFetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectSettingsForm()),
  });
  state.settings = res.settings;
  updateLlmStatusIndicator();
  document.getElementById("modalSettings")?.classList.add("hidden");
  showToast("✅ 个人引擎与语音设置已保存");
}
