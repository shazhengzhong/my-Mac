(() => {
  "use strict";

  const control = document.querySelector("[data-read-aloud]");
  if (!control) {
    return;
  }
  const button = control.querySelector("[data-read-aloud-button]");
  const status = control.querySelector(".read-aloud-status");
  const audio = control.querySelector(".read-aloud-audio");
  if (!button || !status || !audio) {
    return;
  }

  const url = control.dataset.url;
  const speedButtons = Array.from(
    control.querySelectorAll("[data-read-aloud-speed]"),
  );
  const SPEED_KEY = "familyDiaryReadAloudSpeed";
  let speed = "normal";
  let timings = [];
  let spans = [];
  let animation = null;
  let durationMs = 0;

  function getCookie(name) {
    const encoded = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = document.cookie.match(new RegExp(`(?:^|; )${encoded}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function setStatus(message, kind = "") {
    status.textContent = message;
    if (kind) {
      status.dataset.kind = kind;
    } else {
      delete status.dataset.kind;
    }
  }


  function normalizeWord(value) {
    return (value || "")
      .toLowerCase()
      .replace(/[’]/g, "'")
      .replace(/[^a-z0-9']/g, "");
  }

  function alignTimings(rawTimings, textSpans) {
    if (
      !Array.isArray(rawTimings) ||
      rawTimings.length === 0 ||
      textSpans.length === 0
    ) {
      return [];
    }

    const aligned = [];
    let timingIndex = 0;
    for (let spanIndex = 0; spanIndex < textSpans.length; spanIndex += 1) {
      const target = normalizeWord(textSpans[spanIndex].textContent);
      if (!target) {
        const previous = aligned[aligned.length - 1];
        const edge = previous ? previous.end_ms : 0;
        aligned.push({ start_ms: edge, end_ms: edge });
        continue;
      }

      let joined = "";
      let start = null;
      let end = null;
      let consumed = 0;
      while (timingIndex + consumed < rawTimings.length) {
        const item = rawTimings[timingIndex + consumed];
        const word = normalizeWord(item && item.word);
        if (word) {
          const itemStart = Number(item.start_ms);
          const itemEnd = Number(item.end_ms);
          if (Number.isFinite(itemStart) && Number.isFinite(itemEnd)) {
            if (start === null) {
              start = itemStart;
            }
            end = itemEnd;
            joined += word;
          }
        }
        consumed += 1;
        if (joined === target) {
          break;
        }
        if (!target.startsWith(joined)) {
          break;
        }
      }

      if (
        start === null ||
        end === null ||
        !joined ||
        (!joined.startsWith(target) && !target.startsWith(joined))
      ) {
        return [];
      }
      aligned.push({ start_ms: start, end_ms: end });
      timingIndex += Math.max(1, consumed);
    }

    return aligned.length === textSpans.length ? aligned : [];
  }

  function approximateTimings(textSpans, totalMs) {
    const weights = textSpans.map((span) => {
      const normalized = normalizeWord(span.textContent);
      return Math.max(1, normalized.length);
    });
    const total = weights.reduce((sum, value) => sum + value, 0) || 1;
    const duration = Math.max(1, Number(totalMs) || 3000);
    let cursor = 0;
    return weights.map((weight) => {
      const start = cursor;
      cursor += (duration * weight) / total;
      return { start_ms: start, end_ms: cursor };
    });
  }

  function collectSpans() {
    spans = Array.from(
      document.querySelectorAll(".bilingual-list .karaoke-word"),
    );
  }

  function stopAnimation() {
    if (animation !== null) {
      cancelAnimationFrame(animation);
      animation = null;
    }
  }

  function speedLabel(value) {
    return value === "slow" ? "慢速" : "正常";
  }

  function applyPlaybackRate() {
    audio.preservesPitch = true;
    audio.playbackRate = speed === "slow" ? 0.8 : 1;
  }

  function applySpeedState() {
    speedButtons.forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        button.dataset.readAloudSpeed === speed ? "true" : "false",
      );
    });
  }

  function resetForSpeedChange() {
    stopAnimation();
    if (audio.src) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      audio.hidden = true;
    }
    timings = [];
    spans = [];
    document
      .querySelectorAll(".bilingual-list .karaoke-word")
      .forEach((span) => {
        span.classList.remove("karaoke-active", "karaoke-done");
      });
    setStatus("");
  }

  function setSpeed(next) {
    if (next !== "normal" && next !== "slow") {
      return;
    }
    speed = next;
    applySpeedState();
    resetForSpeedChange();
    try {
      window.localStorage.setItem(SPEED_KEY, speed);
    } catch (_error) {
      // Ignore storage errors.
    }
  }

  function updateHighlight() {
    if (!timings.length || !spans.length) {
      return;
    }
    const ms = audio.currentTime * 1000;
    let active = -1;
    for (let index = 0; index < timings.length; index += 1) {
      if (ms >= timings[index].start_ms) {
        active = index;
      }
      if (ms < timings[index].end_ms) {
        break;
      }
    }
    spans.forEach((span, index) => {
      span.classList.toggle("karaoke-active", index === active);
      span.classList.toggle("karaoke-done", index < active);
    });
  }

  function animate() {
    updateHighlight();
    if (!audio.paused && !audio.ended) {
      animation = requestAnimationFrame(animate);
    } else {
      animation = null;
    }
  }

  function startAnimation() {
    stopAnimation();
    animation = requestAnimationFrame(animate);
  }

  function finishHighlight() {
    stopAnimation();
    spans.forEach((span) => {
      span.classList.remove("karaoke-active");
      span.classList.add("karaoke-done");
    });
  }

  audio.addEventListener("play", () => {
    collectSpans();
    startAnimation();
  });
  audio.addEventListener("pause", stopAnimation);
  audio.addEventListener("ended", finishHighlight);
  audio.addEventListener("seeked", updateHighlight);
  audio.addEventListener("timeupdate", updateHighlight);

  async function loadAndPlay() {
    if (audio.src && timings.length) {
      applyPlaybackRate();
      audio.currentTime = 0;
      updateHighlight();
      try {
        await audio.play();
      } catch (_error) {
        setStatus("请点播放器的播放按钮开始。", "warning");
      }
      return;
    }

    const csrfToken = getCookie("csrftoken");
    if (!csrfToken) {
      setStatus("页面安全令牌缺失，请刷新页面后重试。", "error");
      return;
    }

    button.disabled = true;
    speedButtons.forEach((speedButton) => {
      speedButton.disabled = true;
    });
    setStatus(`正在生成${speedLabel(speed)}全文朗读…`, "loading");

    try {
      const requestSpeed = speed === "slow" ? "normal" : speed;
      const formData = new FormData();
      formData.append("speed", requestSpeed);
      const response = await fetch(url, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
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
          payload && payload.error
            ? payload.error
            : "全文朗读生成失败，请稍后重试。",
        );
      }
      if (!payload || !payload.ok) {
        throw new Error("全文朗读没有成功，请刷新页面后重试。");
      }

      collectSpans();
      durationMs = Number(payload.duration_ms) || 0;
      timings = alignTimings(
        Array.isArray(payload.timings) ? payload.timings : [],
        spans,
      );
      if (timings.length !== spans.length) {
        timings = approximateTimings(spans, durationMs);
      }
      setStatus("");

      audio.src = payload.audio_url;
      audio.hidden = false;
      audio.load();
      applyPlaybackRate();

      audio.currentTime = 0;
      updateHighlight();
      try {
        await audio.play();
      } catch (_error) {
        setStatus("已生成，请点播放器的播放按钮开始。", "warning");
      }
    } catch (error) {
      setStatus(error.message || "全文朗读生成失败，请重试。", "error");
    } finally {
      button.disabled = false;
      speedButtons.forEach((speedButton) => {
        speedButton.disabled = false;
      });
    }
  }

  try {
    const stored = window.localStorage.getItem(SPEED_KEY);
    if (stored === "normal" || stored === "slow") {
      speed = stored;
    }
  } catch (_error) {
    // Use the default normal speed.
  }
  applySpeedState();

  speedButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setSpeed(button.dataset.readAloudSpeed);
    });
  });

  button.addEventListener("click", () => {
    void loadAndPlay();
  });
})();
