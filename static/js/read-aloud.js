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
  let timings = [];
  let spans = [];
  let animation = null;

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
    setStatus("正在生成全文朗读…", "loading");

    try {
      const response = await fetch(url, {
        method: "POST",
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

      timings = Array.isArray(payload.timings) ? payload.timings : [];
      collectSpans();
      audio.src = payload.audio_url;
      audio.hidden = false;
      audio.load();

      if (!timings.length) {
        setStatus("没有拿到字幕时间轴，暂时只播放音频。", "warning");
      } else if (timings.length !== spans.length) {
        setStatus(
          `字幕时间轴与页面文字不一致（${timings.length} / ${spans.length}），暂时只播放音频。`,
          "warning",
        );
        timings = [];
      } else {
        setStatus("");
      }

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
    }
  }

  button.addEventListener("click", () => {
    void loadAndPlay();
  });
})();
