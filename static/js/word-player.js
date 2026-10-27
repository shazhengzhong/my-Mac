(() => {
  "use strict";

  const buttons = Array.from(document.querySelectorAll("[data-word-play]"));
  if (buttons.length === 0) {
    return;
  }

  let currentAudio = null;

  function getCookie(name) {
    const encoded = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = document.cookie.match(new RegExp(`(?:^|; )${encoded}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function statusFor(button) {
    const chip = button.closest(".word-chip");
    return chip ? chip.querySelector(".word-play-status") : null;
  }

  function setStatus(button, message, kind = "") {
    const status = statusFor(button);
    if (!status) return null;
    status.replaceChildren();
    status.textContent = message;
    if (kind) {
      status.dataset.kind = kind;
    } else {
      delete status.dataset.kind;
    }
    return status;
  }

  function stopCurrent() {
    if (currentAudio) {
      try {
        currentAudio.pause();
      } catch (_error) {
        // Ignore pause failures.
      }
      currentAudio = null;
    }
    document.querySelectorAll(".word-play-status audio").forEach((element) => {
      try {
        element.pause();
      } catch (_error) {
        // Ignore pause failures.
      }
    });
  }

  async function playWord(button) {
    if (button.disabled) {
      return;
    }

    const csrfToken = getCookie("csrftoken");
    if (!csrfToken) {
      setStatus(button, "页面安全令牌缺失，请刷新页面后重试。", "error");
      return;
    }

    button.disabled = true;
    setStatus(button, "正在生成…", "loading");

    try {
      const response = await fetch(button.dataset.wordPlayUrl, {
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
          payload && payload.error ? payload.error : "播放失败，请稍后重试。",
        );
      }
      if (!payload || !payload.ok) {
        throw new Error("播放没有成功，请刷新页面后重试。");
      }

      stopCurrent();
      const audio = new Audio(payload.audio_url);
      currentAudio = audio;
      setStatus(button, "播放中…", "playing");
      audio.addEventListener("ended", () => {
        if (currentAudio === audio) {
          currentAudio = null;
        }
        setStatus(button, "", "");
      });
      audio.addEventListener("error", () => {
        setStatus(button, "音频播放失败，请重试。", "error");
      });

      try {
        await audio.play();
      } catch (_error) {
        // Safari may block autoplay after the async request. Show a manual player.
        const status = setStatus(button, "", "");
        if (status) {
          const fallback = document.createElement("audio");
          fallback.controls = true;
          fallback.preload = "none";
          fallback.src = payload.audio_url;
          status.appendChild(fallback);
        }
      }
    } catch (error) {
      setStatus(button, error.message || "播放失败，请重试。", "error");
    } finally {
      button.disabled = false;
    }
  }

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      void playWord(button);
    });
  });
})();
