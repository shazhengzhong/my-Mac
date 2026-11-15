(() => {
  "use strict";

  const sheet = document.querySelector("[data-word-sheet]");
  if (!sheet) {
    return;
  }

  const panel = sheet.querySelector("[data-word-sheet-panel]");
  const scroll = sheet.querySelector("[data-word-sheet-scroll]");
  const closeButton = sheet.querySelector("[data-word-sheet-close]");
  const wordElement = sheet.querySelector("[data-word-sheet-word]");
  const ipaElement = sheet.querySelector("[data-word-sheet-ipa]");
  const sensesElement = sheet.querySelector("[data-word-sheet-senses]");
  const syllablesSection = sheet.querySelector("[data-word-sheet-syllables]");
  const syllableList = sheet.querySelector("[data-word-sheet-syllable-list]");
  const syllableAll = sheet.querySelector("[data-word-sheet-syllable-all]");
  const statusElement = sheet.querySelector("[data-word-sheet-status]");
  const audio = sheet.querySelector("[data-word-sheet-audio]");
  const playButton = sheet.querySelector("[data-word-sheet-play]");
  const loopButton = sheet.querySelector("[data-word-sheet-loop]");
  const assessWrap = sheet.querySelector("[data-word-sheet-assess]");
  const assessButton = sheet.querySelector("[data-assess-button]");
  const assessResult = sheet.querySelector("[data-word-sheet-assess-result]");
  const dragHandle = sheet.querySelector("[data-word-sheet-drag]");

  if (
    !panel ||
    !scroll ||
    !wordElement ||
    !ipaElement ||
    !sensesElement ||
    !statusElement ||
    !audio ||
    !playButton ||
    !loopButton
  ) {
    return;
  }

  const SILENT_WAV =
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";

  let activeButton = null;
  let activeCard = null;
  let lastTrigger = null;
  let requestId = 0;
  let audioRequestId = 0;
  let loop = false;
  let primed = false;
  let dragStartY = 0;
  let dragging = false;

  function getCookie(name) {
    if (window.FamilyAudio && window.FamilyAudio.getCookie) {
      return window.FamilyAudio.getCookie(name);
    }
    const encoded = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = document.cookie.match(
      new RegExp(`(?:^|; )${encoded}=([^;]*)`),
    );
    return match ? decodeURIComponent(match[1]) : "";
  }

  function setStatus(message, kind = "") {
    statusElement.textContent = message || "";
    if (kind) {
      statusElement.dataset.kind = kind;
    } else {
      delete statusElement.dataset.kind;
    }
  }

  function setWordHighlight(button, active) {
    if (!button) {
      return;
    }
    button.classList.toggle("is-active-word", active);
    button.setAttribute("aria-expanded", active ? "true" : "false");
  }

  function stopAudio() {
    audioRequestId += 1;
    try {
      audio.pause();
    } catch (_error) {
      // Ignore pause failures.
    }
    audio.loop = false;
    audio.removeAttribute("src");
    audio.load();
  }

  function setLoop(next) {
    loop = Boolean(next);
    loopButton.setAttribute("aria-pressed", loop ? "true" : "false");
    audio.loop = loop;
  }

  function primeAudio() {
    if (primed) {
      return;
    }
    primed = true;
    audio.src = SILENT_WAV;
    audio.volume = 0;
    const attempt = audio.play();
    if (attempt && typeof attempt.catch === "function") {
      attempt.catch(() => {
        // The explicit play button remains as a fallback.
      });
    }
    window.setTimeout(() => {
      if (audio.src === SILENT_WAV) {
        audio.volume = 1;
      }
    }, 400);
  }

  async function postJson(url) {
    const csrfToken = getCookie("csrftoken");
    if (!csrfToken) {
      throw new Error("页面安全令牌缺失，请刷新页面后重试。");
    }
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": csrfToken,
        "X-Requested-With": "fetch",
      },
    });
    if (response.redirected && response.url.includes("/accounts/login/")) {
      throw new Error("登录已过期，请刷新页面并重新登录。");
    }
    let payload = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try {
        payload = await response.json();
      } catch (_error) {
        payload = null;
      }
    }
    if (!response.ok) {
      throw new Error(
        payload && payload.error ? payload.error : "请求失败，请稍后重试。",
      );
    }
    if (!payload || !payload.ok) {
      throw new Error("单词信息加载失败，请刷新页面后重试。");
    }
    return payload;
  }

  async function playUrl(url, { autoplay = true, message = "" } = {}) {
    const request = ++audioRequestId;
    audio.pause();
    audio.loop = loop;
    audio.src = url;
    audio.volume = 1;
    audio.load();
    if (message) {
      setStatus(message);
    }
    try {
      await audio.play();
      if (request === audioRequestId) {
        setStatus("");
      }
    } catch (_error) {
      // Autoplay may be blocked; the visible play button is the fallback.
      if (request === audioRequestId) {
        setStatus("");
      }
    }
  }

  async function playWord({ autoplay = true } = {}) {
    if (!activeCard || !activeCard.tts_ready || !activeCard.word_tts_url) {
      setStatus("当前没有可用的单词发音。", "warning");
      return;
    }
    if (activeCard.audioUrl) {
      await playUrl(activeCard.audioUrl, {
        autoplay,
        message: autoplay ? "" : "",
      });
      return;
    }

    const card = activeCard;
    const request = ++audioRequestId;
    setStatus("正在生成单词发音…", "loading");
    try {
      const payload = await postJson(card.word_tts_url);
      if (request !== audioRequestId || activeCard !== card) {
        return;
      }
      card.audioUrl = payload.audio_url;
      await playUrl(payload.audio_url, { autoplay });
    } catch (error) {
      if (request === audioRequestId) {
        setStatus(error.message || "单词发音生成失败，请重试。", "error");
      }
    }
  }

  const POS_LABELS = {
    n: "名词",
    noun: "名词",
    v: "动词",
    verb: "动词",
    adj: "形容词",
    adjective: "形容词",
    adv: "副词",
    adverb: "副词",
    prep: "介词",
    preposition: "介词",
    conj: "连词",
    conjunction: "连词",
    pron: "代词",
    pronoun: "代词",
    det: "限定词",
    determiner: "限定词",
    num: "数词",
    numeral: "数词",
    interj: "感叹词",
    interjection: "感叹词",
    int: "感叹词",
    aux: "助动词",
    auxiliary: "助动词",
    modal: "情态动词",
    art: "冠词",
    article: "冠词",
    phr: "短语",
    phrase: "短语",
    abbr: "缩写",
    abbreviation: "缩写",
  };

  function posLabel(value) {
    const raw = (value || "").trim();
    if (!raw) {
      return "";
    }
    const key = raw.toLowerCase().replace(/\./g, "").trim();
    if (POS_LABELS[key]) {
      return POS_LABELS[key];
    }
    const parts = raw
      .split(/[\/,]/)
      .map((part) => part.trim())
      .filter(Boolean);
    const translated = parts.map((part) => {
      const normalized = part.toLowerCase().replace(/\./g, "").trim();
      return POS_LABELS[normalized] || part;
    });
    return translated.join(" / ");
  }

  function renderSenses(data) {
    sensesElement.replaceChildren();
    if (!data.senses.length) {
      const empty = document.createElement("p");
      empty.className = "word-sheet-empty";
      empty.textContent = "暂时没有查到中文释义。";
      sensesElement.appendChild(empty);
      return;
    }

    data.senses.forEach((sense) => {
      const row = document.createElement("div");
      row.className = "word-sense";

      const pos = document.createElement("span");
      pos.className = "word-sense-pos";
      pos.textContent = posLabel(sense.pos);

      const meaning = document.createElement("span");
      meaning.className = "word-sense-meaning";
      meaning.textContent = sense.meaning || "";

      row.append(pos, meaning);
      sensesElement.appendChild(row);
    });
  }

  function resetAssess() {
    if (!assessWrap || !assessButton) {
      return;
    }
    assessWrap.hidden = true;
    assessButton.dataset.assessUrl = "";
    assessButton.dataset.word = "";
    if (assessResult) {
      assessResult.textContent = "";
      assessResult.classList.remove("is-visible");
      delete assessResult.dataset.kind;
    }
  }

  function configureAssess(data) {
    if (!assessWrap || !assessButton) {
      return;
    }
    resetAssess();
    if (!data.assessment_ready || !data.assess_url) {
      return;
    }
    assessButton.dataset.assessUrl = data.assess_url;
    assessButton.dataset.word = data.word || "";
    assessWrap.hidden = false;
  }

  function renderSyllables(data) {
    if (!syllablesSection || !syllableList) {
      return;
    }
    syllableList.replaceChildren();
    const syllables = Array.isArray(data.syllables) ? data.syllables : [];
    if (!syllables.length || !data.tts_ready) {
      syllablesSection.hidden = true;
      return;
    }
    syllablesSection.hidden = false;

    syllables.forEach((syllable, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "word-syllable";
      button.textContent = syllable;
      button.setAttribute("aria-label", `播放音节 ${syllable}`);
      button.addEventListener("click", () => {
        void playSyllable(index);
      });
      syllableList.appendChild(button);
    });

    const urls = Array.isArray(data.syllable_audio_urls)
      ? data.syllable_audio_urls
      : [];
    if (syllableAll) {
      syllableAll.disabled = !urls.length || !data.syllable_sequence_url;
      syllableAll.onclick = () => {
        void playSyllableSequence();
      };
    }
  }

  async function playSyllable(index) {
    if (!activeCard || !activeCard.syllable_audio_urls[index]) {
      setStatus("这个音节暂时没有可用发音。", "warning");
      return;
    }
    const card = activeCard;
    const request = ++audioRequestId;
    setLoop(false);
    setStatus("正在生成音节发音…", "loading");
    try {
      const payload = await postJson(card.syllable_audio_urls[index]);
      if (request !== audioRequestId || activeCard !== card) {
        return;
      }
      await playUrl(payload.audio_url, { autoplay: true });
    } catch (error) {
      if (request === audioRequestId) {
        setStatus(error.message || "音节发音生成失败，请重试。", "error");
      }
    }
  }

  async function playSyllableSequence() {
    if (!activeCard || !activeCard.syllable_sequence_url) {
      setStatus("这个单词暂时没有可用的拼读音频。", "warning");
      return;
    }
    const card = activeCard;
    const request = ++audioRequestId;
    setLoop(false);
    setStatus("正在生成整词拼读…", "loading");
    try {
      const payload = await postJson(card.syllable_sequence_url);
      if (request !== audioRequestId || activeCard !== card) {
        return;
      }
      await playUrl(payload.audio_url, { autoplay: true });
    } catch (error) {
      if (request === audioRequestId) {
        setStatus(error.message || "整词拼读生成失败，请重试。", "error");
      }
    }
  }

  function renderCard(data) {
    activeCard = {
      ...data,
      audioUrl: "",
    };
    wordElement.textContent = data.word || "";
    ipaElement.textContent = data.ipa ? `/${data.ipa}/` : "音标未收录";
    renderSenses(data);
    configureAssess(data);
    renderSyllables(data);

    if (playButton) {
      playButton.disabled = !data.tts_ready;
    }
    if (loopButton) {
      loopButton.disabled = !data.tts_ready;
    }
    if (data.warning) {
      setStatus(data.warning, "warning");
    } else {
      setStatus("");
    }
    scroll.scrollTop = 0;
    if (data.tts_ready) {
      void playWord({ autoplay: true });
    }
  }

  async function openWord(button) {
    const cardUrl = button.dataset.wordCardUrl;
    if (!cardUrl) {
      return;
    }

    if (activeButton && activeButton !== button) {
      setWordHighlight(activeButton, false);
    }
    if (loop) {
      setLoop(false);
    }
    stopAudio();
    document.querySelectorAll("audio").forEach((player) => {
      if (player !== audio) {
        try {
          player.pause();
        } catch (_error) {
          // Ignore pause failures.
        }
      }
    });
    setStatus("正在加载单词…", "loading");
    activeButton = button;
    lastTrigger = button;
    setWordHighlight(button, true);
    activeCard = null;
    requestId += 1;
    const request = requestId;

    wordElement.textContent = button.textContent.trim();
    ipaElement.textContent = "正在加载…";
    sensesElement.replaceChildren();
    syllablesSection.hidden = true;
    resetAssess();
    sheet.hidden = false;
    document.body.classList.add("word-sheet-open");
    window.requestAnimationFrame(() => sheet.classList.add("is-open"));
    primeAudio();
    if (closeButton) {
      closeButton.focus({ preventScroll: true });
    }

    try {
      const data = await postJson(cardUrl);
      if (request !== requestId) {
        return;
      }
      renderCard(data);
    } catch (error) {
      if (request !== requestId) {
        return;
      }
      ipaElement.textContent = "";
      sensesElement.replaceChildren();
      const message = document.createElement("p");
      message.className = "word-sheet-empty";
      message.textContent =
        error.message || "单词释义加载失败，请稍后再试。";
      sensesElement.appendChild(message);
      setStatus("", "");
    }
  }

  function closeSheet() {
    if (sheet.hidden) {
      return;
    }
    requestId += 1;
    stopAudio();
    setLoop(false);
    setWordHighlight(activeButton, false);
    activeButton = null;
    activeCard = null;
    sheet.classList.remove("is-open");
    document.body.classList.remove("word-sheet-open");
    window.setTimeout(() => {
      if (!sheet.classList.contains("is-open")) {
        sheet.hidden = true;
        if (lastTrigger && typeof lastTrigger.focus === "function") {
          lastTrigger.focus({ preventScroll: true });
        }
        lastTrigger = null;
      }
    }, 180);
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-word-card-url]");
    if (!trigger) {
      return;
    }
    event.preventDefault();
    void openWord(trigger);
  });

  sheet.querySelectorAll("[data-word-sheet-close]").forEach((control) => {
    control.addEventListener("click", closeSheet);
  });

  if (closeButton) {
    closeButton.addEventListener("click", closeSheet);
  }

  playButton.addEventListener("click", () => {
    void playWord({ autoplay: true });
  });

  loopButton.addEventListener("click", () => {
    const next = !loop;
    setLoop(next);
    if (next) {
      void playWord({ autoplay: true });
    }
  });

  audio.addEventListener("error", () => {
    setStatus("音频播放失败，请重试。", "error");
  });

  audio.addEventListener("ended", () => {
    // Keep the sheet height stable; playback status is intentionally hidden.
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !sheet.hidden) {
      event.preventDefault();
      closeSheet();
    }
  });

  function onDragStart(event) {
    if (!dragHandle || scroll.scrollTop > 0) {
      return;
    }
    dragStartY = event.clientY;
    dragging = true;
    panel.style.transition = "none";
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function onDragMove(event) {
    if (!dragging) {
      return;
    }
    const delta = Math.max(0, event.clientY - dragStartY);
    panel.style.transform = `translateY(${delta}px)`;
  }

  function onDragEnd(event) {
    if (!dragging) {
      return;
    }
    dragging = false;
    const delta = Math.max(0, event.clientY - dragStartY);
    panel.style.transition = "";
    panel.style.transform = "";
    if (delta > 90) {
      closeSheet();
    }
  }

  const header = sheet.querySelector(".word-sheet-header");
  [dragHandle, header].forEach((surface) => {
    if (!surface) {
      return;
    }
    surface.addEventListener("pointerdown", onDragStart);
    surface.addEventListener("pointermove", onDragMove);
    surface.addEventListener("pointerup", onDragEnd);
    surface.addEventListener("pointercancel", onDragEnd);
  });
})();
