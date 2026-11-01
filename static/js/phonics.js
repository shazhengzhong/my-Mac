(() => {
  "use strict";

  const root = document.querySelector("[data-phonics-root]");
  if (!root) {
    return;
  }
  const audio = root.querySelector(".phonics-audio");
  const status = root.querySelector(".phonics-status");
  const wordButton = root.querySelector("[data-phonics-word]");
  const modeButtons = Array.from(
    root.querySelectorAll("[data-phonics-mode]"),
  );
  if (!audio || !status || !wordButton) {
    return;
  }

  const wordUrl = root.dataset.wordAudioUrl;
  let busy = false;

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

  const initiallyDisabled = new Map(
    modeButtons.map((button) => [button, button.disabled]),
  );

  function setBusy(value) {
    busy = value;
    wordButton.disabled = value;
    modeButtons.forEach((button) => {
      button.disabled = value || Boolean(initiallyDisabled.get(button));
    });
  }

  async function fetchAudio(url) {
    const csrfToken = getCookie("csrftoken");
    if (!csrfToken) {
      throw new Error("页面安全令牌缺失，请刷新页面后重试。");
    }
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    });
    if (response.redirected && response.url.includes("/accounts/login/")) {
      throw new Error("登录已过期，请刷新页面并重新登录。");
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    if (!response.ok || !payload || !payload.ok) {
      throw new Error(
        (payload && payload.error) || "拼读示范生成失败，请稍后再试。",
      );
    }
    return payload;
  }

  function playAudio(url) {
    return new Promise((resolve, reject) => {
      audio.onended = () => resolve();
      audio.onerror = () => reject(new Error("音频播放失败，请重试。"));
      audio.hidden = false;
      audio.src = url;
      audio.play().catch((error) => {
        if (error && error.name === "NotAllowedError") {
          reject(
            new Error("浏览器拦截了自动播放，请点下方播放器播放。"),
          );
        } else {
          reject(new Error("音频播放失败，请重试。"));
        }
      });
    });
  }

  async function playWord() {
    const payload = await fetchAudio(wordUrl);
    await playAudio(payload.audio_url);
  }

  async function runMode(button) {
    if (busy) {
      return;
    }
    setBusy(true);
    setStatus("正在生成示范音…");
    try {
      const payload = await fetchAudio(button.dataset.url);
      if (button.dataset.phonicsMode === "phoneme") {
        setStatus("正在播放音素…");
        await playAudio(payload.audio_url);
        setStatus("音素结束，正在播放整词…");
        await playWord();
      } else {
        setStatus("正在播放音节和整词…");
        await playAudio(payload.audio_url);
      }
      setStatus("播放完成。", "success");
    } catch (error) {
      setStatus(error.message || "拼读播放失败，请重试。", "error");
    } finally {
      setBusy(false);
    }
  }

  async function playWordOnly() {
    if (busy) {
      return;
    }
    setBusy(true);
    setStatus("正在播放整词发音…");
    try {
      await playWord();
      setStatus("播放完成。", "success");
    } catch (error) {
      setStatus(error.message || "整词发音失败，请重试。", "error");
    } finally {
      setBusy(false);
    }
  }

  wordButton.addEventListener("click", () => {
    void playWordOnly();
  });
  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      void runMode(button);
    });
  });
})();
