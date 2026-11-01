(() => {
  "use strict";

  const buttons = Array.from(
    document.querySelectorAll("[data-sentence-audio]"),
  );
  if (buttons.length === 0) {
    return;
  }

  let activeAudio = null;
  let activeButton = null;
  let activeUnits = [];
  let activeTimings = [];
  let frame = null;
  let requestToken = 0;

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

  function cardFor(button) {
    return button.closest(".sentence-card");
  }

  function statusFor(button) {
    const card = cardFor(button);
    return card ? card.querySelector(".sentence-audio-status") : null;
  }

  function setStatus(button, message, kind = "") {
    const status = statusFor(button);
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

  function buttonsFor(button) {
    const card = cardFor(button);
    return card
      ? Array.from(card.querySelectorAll("[data-sentence-audio]"))
      : [button];
  }

  function setBusy(button, busy) {
    buttonsFor(button).forEach((item) => {
      item.disabled = busy;
      item.classList.toggle("is-loading", busy);
    });
  }

  function unitsFor(button) {
    const card = cardFor(button);
    return card ? Array.from(card.querySelectorAll(".word-unit")) : [];
  }

  function clearUnits(units) {
    units.forEach((unit) => {
      unit.classList.remove("is-reading", "is-read");
    });
  }

  function buildTimings(payload, units) {
    const raw = Array.isArray(payload.timings) ? payload.timings : [];
    const usable =
      raw.length === units.length &&
      raw.every(
        (item) =>
          item &&
          Number.isFinite(Number(item.start_ms)) &&
          Number.isFinite(Number(item.end_ms)),
      );
    if (usable) {
      return raw.map((item) => ({
        start_ms: Number(item.start_ms),
        end_ms: Number(item.end_ms),
      }));
    }

    const weights = units.map((unit) => {
      const token = unit.querySelector(".word-token");
      return Math.max(1, (token ? token.textContent : "").replace(/\s+/g, "").length);
    });
    const total = weights.reduce((sum, value) => sum + value, 0) || 1;
    const duration = Math.max(1, Number(payload.duration_ms) || 3000);
    let cursor = 0;
    return weights.map((weight) => {
      const start = cursor;
      cursor += (duration * weight) / total;
      return { start_ms: start, end_ms: cursor };
    });
  }

  function stopAnimation() {
    if (frame !== null) {
      cancelAnimationFrame(frame);
      frame = null;
    }
  }

  function updateHighlight() {
    if (!activeAudio || activeTimings.length === 0) {
      return;
    }
    const now = activeAudio.currentTime * 1000;
    let activeIndex = -1;
    for (let index = 0; index < activeTimings.length; index += 1) {
      if (now >= activeTimings[index].start_ms) {
        activeIndex = index;
      }
      if (now < activeTimings[index].end_ms) {
        break;
      }
    }
    activeUnits.forEach((unit, index) => {
      unit.classList.toggle("is-reading", index === activeIndex);
      unit.classList.toggle("is-read", index < activeIndex);
    });
    if (!activeAudio.paused && !activeAudio.ended) {
      frame = requestAnimationFrame(updateHighlight);
    } else {
      frame = null;
    }
  }

  function stop() {
    requestToken += 1;
    stopAnimation();
    if (activeAudio) {
      try {
        activeAudio.pause();
      } catch (_error) {
        // Ignore pause failures.
      }
    }
    if (activeButton) {
      activeButton.classList.remove("is-playing");
      activeButton.setAttribute("aria-pressed", "false");
    }
    buttons.forEach((button) => {
      button.disabled = false;
      button.classList.remove("is-loading");
      setStatus(button, "");
    });
    clearUnits(activeUnits);
    activeAudio = null;
    activeButton = null;
    activeUnits = [];
    activeTimings = [];
  }

  function finish() {
    stopAnimation();
    activeUnits.forEach((unit) => {
      unit.classList.remove("is-reading");
      unit.classList.add("is-read");
    });
    if (activeButton) {
      activeButton.classList.remove("is-playing");
      activeButton.setAttribute("aria-pressed", "false");
      setStatus(activeButton, "朗读完成");
    }
    buttons.forEach((button) => {
      button.disabled = false;
      button.classList.remove("is-loading");
    });
    activeAudio = null;
    activeButton = null;
    activeUnits = [];
    activeTimings = [];
  }

  function playPayload(button, payload, playbackRate = 1) {
    const units = unitsFor(button);
    if (units.length === 0) {
      setStatus(button, "找不到可高亮的单词。", "error");
      setBusy(button, false);
      return;
    }

    const audio = new Audio(payload.audio_url);
    audio.preservesPitch = true;
    audio.playbackRate = playbackRate;
    activeAudio = audio;
    activeButton = button;
    activeUnits = units;
    activeTimings = buildTimings(payload, units);
    clearUnits(units);
    setBusy(button, false);
    button.classList.add("is-playing");
    button.setAttribute("aria-pressed", "true");
    setStatus(button, "朗读中…");

    audio.addEventListener("error", () => {
      if (activeAudio === audio) {
        stop();
        setStatus(button, "音频播放失败，请重试。", "error");
      }
    });
    audio.addEventListener("ended", () => {
      if (activeAudio === audio) {
        finish();
      }
    });

    const playback = audio.play();
    if (playback && typeof playback.catch === "function") {
      playback
        .then(() => {
          stopAnimation();
          frame = requestAnimationFrame(updateHighlight);
        })
        .catch(() => {
          if (activeAudio === audio) {
            stop();
            button._audioPayload = payload;
            setStatus(button, "已生成，请再点一次播放。", "error");
          }
        });
    } else {
      frame = requestAnimationFrame(updateHighlight);
    }
  }

  async function start(button) {
    if (activeButton === button && activeAudio && !activeAudio.paused) {
      stop();
      return;
    }
    const playbackRate = Number(button.dataset.playbackRate) || 1;
    if (button._audioPayload) {
      stop();
      playPayload(button, button._audioPayload, playbackRate);
      return;
    }

    const url = button.dataset.ttsUrl;
    if (!url) {
      return;
    }
    const csrfToken = getCookie("csrftoken");
    if (!csrfToken) {
      setStatus(button, "页面安全令牌缺失，请刷新页面后重试。", "error");
      return;
    }

    stop();
    const token = (requestToken += 1);
    setBusy(button, true);
    setStatus(button, "正在生成…");

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
      if (token !== requestToken) {
        return;
      }

      button._audioPayload = payload;
      playPayload(button, payload, playbackRate);
    } catch (error) {
      if (token !== requestToken) {
        return;
      }
      setBusy(button, false);
      setStatus(button, error.message || "朗读失败，请重试。", "error");
    }
  }

  buttons.forEach((button) => {
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => {
      void start(button);
    });
  });

  document.querySelectorAll("[data-word-play]").forEach((wordButton) => {
    wordButton.addEventListener("click", stop);
  });

  window.FamilySentenceAudio = { stop };
})();
