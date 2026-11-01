(() => {
  "use strict";

  const controls = Array.from(
    document.querySelectorAll("[data-diary-read-control]"),
  );
  if (controls.length === 0) {
    return;
  }

  let activeSession = null;
  let requestCounter = 0;

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

  function statusFor(control) {
    return control.querySelector(".diary-read-status");
  }

  function setStatus(control, message, kind = "") {
    const status = statusFor(control);
    if (!status) {
      return;
    }
    status.textContent = message;
    if (kind) {
      status.dataset.kind = kind;
    } else {
      delete status.dataset.kind;
    }
  }

  function wordsFor(control) {
    const group = control.closest(".bilingual-group");
    const sentence = group ? group.querySelector(".bilingual-en") : null;
    return sentence
      ? Array.from(sentence.querySelectorAll(".karaoke-word"))
      : [];
  }

  function clearWords(words) {
    words.forEach((word) => {
      word.classList.remove("karaoke-active", "karaoke-done");
    });
  }

  function buttonsFor(control) {
    return Array.from(control.querySelectorAll("[data-diary-read-speed]"));
  }

  function setBusy(control, busy) {
    buttonsFor(control).forEach((button) => {
      button.disabled = busy;
    });
  }

  function buildTimings(words, rawTimings, durationMs) {
    const usable =
      Array.isArray(rawTimings) &&
      rawTimings.length === words.length &&
      rawTimings.every((item) => {
        if (!item || typeof item !== "object") {
          return false;
        }
        return (
          Number.isFinite(Number(item.start_ms)) &&
          Number.isFinite(Number(item.end_ms))
        );
      });
    if (usable) {
      return rawTimings.map((item) => ({
        start_ms: Number(item.start_ms),
        end_ms: Number(item.end_ms),
      }));
    }

    const weights = words.map((word) =>
      Math.max(1, (word.textContent || "").replace(/\s+/g, "").length),
    );
    const total = weights.reduce((sum, value) => sum + value, 0) || 1;
    const duration = Math.max(1, Number(durationMs) || 3000);
    let cursor = 0;
    return weights.map((weight) => {
      const start = cursor;
      cursor += (duration * weight) / total;
      return { start_ms: start, end_ms: cursor };
    });
  }

  function stopAnimation(session) {
    if (session.frame !== null) {
      cancelAnimationFrame(session.frame);
      session.frame = null;
    }
  }

  function updateHighlight(session) {
    if (!session.audio || !session.timings.length) {
      return;
    }
    const now = session.audio.currentTime * 1000;
    let activeIndex = -1;
    for (let index = 0; index < session.timings.length; index += 1) {
      if (now >= session.timings[index].start_ms) {
        activeIndex = index;
      }
      if (now < session.timings[index].end_ms) {
        break;
      }
    }
    session.words.forEach((word, index) => {
      word.classList.toggle("karaoke-active", index === activeIndex);
      word.classList.toggle("karaoke-done", index < activeIndex);
    });
    if (!session.audio.paused && !session.audio.ended) {
      session.frame = requestAnimationFrame(() => updateHighlight(session));
    } else {
      session.frame = null;
    }
  }

  function finishSession(session) {
    stopAnimation(session);
    session.words.forEach((word) => {
      word.classList.remove("karaoke-active");
      word.classList.add("karaoke-done");
    });
    session.button.classList.remove("is-playing");
    session.button.setAttribute("aria-pressed", "false");
    setBusy(session.control, false);
    setStatus(session.control, "朗读完成");
    if (activeSession === session) {
      activeSession = null;
    }
  }

  function stopActive(clearHighlights = true) {
    requestCounter += 1;
    const session = activeSession;
    activeSession = null;
    controls.forEach((control) => setBusy(control, false));
    if (!session) {
      return;
    }
    stopAnimation(session);
    if (session.audio) {
      try {
        session.audio.pause();
      } catch (_error) {
        // Ignore pause failures.
      }
    }
    session.button.classList.remove("is-playing");
    session.button.setAttribute("aria-pressed", "false");
    if (clearHighlights) {
      clearWords(session.words);
      setStatus(session.control, "");
    }
  }

  function markPlaying(control, button) {
    buttonsFor(control).forEach((item) => {
      item.classList.toggle("is-playing", item === button);
      item.setAttribute("aria-pressed", item === button ? "true" : "false");
    });
  }

  async function startAudio(control, button, speed, cached, playbackRate) {
    const words = wordsFor(control);
    if (words.length === 0) {
      setStatus(control, "找不到可高亮的单词。", "error");
      return;
    }

    stopActive();
    document.querySelectorAll(".read-aloud-audio").forEach((player) => {
      try {
        player.pause();
      } catch (_error) {
        // Ignore pause failures.
      }
    });
    clearWords(words);
    setBusy(control, true);
    const audio = new Audio(cached.audioUrl);
    audio.preservesPitch = true;
    audio.playbackRate = playbackRate;
    const timings = buildTimings(words, cached.timings, cached.durationMs);
    const session = {
      control,
      button,
      speed,
      audio,
      words,
      timings,
      frame: null,
    };
    activeSession = session;

    audio.addEventListener("play", () => {
      setBusy(control, false);
      markPlaying(control, button);
      setStatus(control, "朗读中…");
      if (session.frame === null) {
        session.frame = requestAnimationFrame(() => updateHighlight(session));
      }
    });
    audio.addEventListener("ended", () => finishSession(session));
    audio.addEventListener("error", () => {
      stopActive(true);
      setStatus(control, "音频播放失败，请重试。", "error");
    });

    try {
      await audio.play();
    } catch (_error) {
      setBusy(control, false);
      if (activeSession === session) {
        activeSession = null;
      }
      button.classList.remove("is-playing");
      setStatus(control, "已生成，请再点一次播放。", "warning");
    }
  }

  async function requestAudio(control, button, speed) {
    const words = wordsFor(control);
    if (words.length === 0) {
      setStatus(control, "找不到可高亮的单词。", "error");
      return;
    }

    const controlCache = control._readCache || (control._readCache = {});
    const playbackRate =
      speed === "slow"
        ? Number(control.dataset.slowPlaybackRate) || 0.8
        : 1;
    if (controlCache[speed]) {
      await startAudio(control, button, speed, controlCache[speed], playbackRate);
      return;
    }

    const url =
      speed === "slow" ? control.dataset.slowUrl : control.dataset.normalUrl;
    if (!url) {
      setStatus(control, "这一句的朗读地址缺失。", "error");
      return;
    }
    const csrfToken = getCookie("csrftoken");
    if (!csrfToken) {
      setStatus(control, "页面安全令牌缺失，请刷新页面后重试。", "error");
      return;
    }

    stopActive();
    document.querySelectorAll(".read-aloud-audio").forEach((player) => {
      try {
        player.pause();
      } catch (_error) {
        // Ignore pause failures.
      }
    });
    clearWords(words);
    controls.forEach((item) => setBusy(item, false));
    setBusy(control, true);
    setStatus(control, "正在生成…");
    const requestId = (requestCounter += 1);

    try {
      const formData = new FormData();
      formData.append("format", "json");
      const response = await fetch(url, {
        method: "POST",
        body: formData,
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
          payload && payload.error ? payload.error : "朗读生成失败，请稍后重试。",
        );
      }
      if (!payload || !payload.ok) {
        throw new Error("朗读没有生成成功，请刷新页面后重试。");
      }
      if (requestId !== requestCounter) {
        return;
      }

      controlCache[speed] = {
        audioUrl: payload.audio_url,
        timings: payload.timings,
        durationMs: payload.duration_ms,
      };
      await startAudio(control, button, speed, controlCache[speed], playbackRate);
    } catch (error) {
      if (requestId !== requestCounter) {
        return;
      }
      setBusy(control, false);
      setStatus(control, error.message || "朗读失败，请重试。", "error");
    }
  }

  controls.forEach((control) => {
    buttonsFor(control).forEach((button) => {
      button.addEventListener("click", () => {
        const speed = button.dataset.diaryReadSpeed;
        if (
          activeSession &&
          activeSession.control === control &&
          activeSession.speed === speed &&
          activeSession.audio &&
          !activeSession.audio.paused
        ) {
          stopActive(true);
          setStatus(control, "已停止");
          return;
        }
        void requestAudio(control, button, speed);
      });
    });
  });

  const readAloudButton = document.querySelector("[data-read-aloud-button]");
  if (readAloudButton) {
    readAloudButton.addEventListener("click", () => stopActive(true));
  }

  window.FamilySentenceReader = {
    stop: () => stopActive(true),
  };
})();
