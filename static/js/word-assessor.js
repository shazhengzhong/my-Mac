(() => {
  "use strict";

  const buttons = Array.from(document.querySelectorAll("[data-assess-button]"));
  if (buttons.length === 0) {
    return;
  }

  const MAX_SECONDS = 3;
  const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
  let activeSession = null;

  function setResult(button, message, kind = "", audioUrl = "") {
    const chip = button.closest(".word-chip");
    const result = chip ? chip.querySelector(".assess-result") : null;
    if (!result) return;
    result.textContent = message;
    if (kind) {
      result.dataset.kind = kind;
    } else {
      delete result.dataset.kind;
    }
    if (audioUrl) {
      const link = document.createElement("a");
      link.href = audioUrl;
      link.target = "_blank";
      link.rel = "noopener";
      link.className = "assess-play";
      link.textContent = " 回放";
      result.appendChild(link);
    }
  }

  function updateButtons() {
    buttons.forEach((button) => {
      if (activeSession && activeSession.button === button) {
        button.textContent = activeSession.busy ? "评分中…" : "停止";
        button.disabled = activeSession.busy;
      } else {
        button.textContent = "测评";
        button.disabled = Boolean(activeSession);
      }
    });
  }

  function stopTracks(session) {
    if (session.stream) {
      session.stream.getTracks().forEach((track) => track.stop());
    }
  }

  async function closeContext(session) {
    if (session.audioContext && session.audioContext.state !== "closed") {
      try {
        await session.audioContext.close();
      } catch (_error) {
        // The context may already be closed by the browser.
      }
    }
  }

  function formatScore(value) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    const number = Number(value);
    return Number.isFinite(number) ? String(Math.round(number)) : "—";
  }

  function phoneHint(detail) {
    const phones = detail && detail.phones;
    if (!Array.isArray(phones) || phones.length === 0) {
      return "";
    }
    const parts = phones
      .slice(0, 8)
      .map((phone) => {
        if (typeof phone === "string") {
          return phone;
        }
        const rawName = phone && (phone.Phone || phone.phone);
        const name = typeof rawName === "string" ? rawName : "";
        if (!name) return "";
        const rawScore = phone.PronAccuracy ?? phone.pron_accuracy;
        const score = formatScore(rawScore);
        return score === "—" ? name : `${name} ${score}`;
      })
      .filter(Boolean);
    return parts.length ? `音素 ${parts.join(" ")}` : "";
  }

  async function upload(button, wavBlob) {
    if (wavBlob.size > MAX_UPLOAD_BYTES) {
      throw new Error("录音太大，请重新录制。");
    }
    const csrfToken = window.FamilyAudio.getCookie("csrftoken");
    if (!csrfToken) {
      throw new Error("页面安全令牌缺失，请刷新页面后重试。");
    }

    const formData = new FormData();
    formData.append("audio", wavBlob, "word.wav");
    const response = await fetch(button.dataset.assessUrl, {
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
        payload && payload.error ? payload.error : "测评失败，请稍后重试。",
      );
    }
    if (!payload || !payload.ok) {
      throw new Error("测评没有成功，请刷新页面后重试。");
    }
    return payload;
  }

  function requestStop(session) {
    if (!session || session.stopping) return;
    session.stopping = true;
    if (session.timer) {
      clearInterval(session.timer);
      session.timer = null;
    }
    try {
      session.recorder.stop();
    } catch (_error) {
      // The recorder may already be stopping.
    }
  }

  async function finish(session) {
    const { button } = session;
    session.busy = true;
    updateButtons();
    setResult(button, "正在转换录音…", "recording");

    try {
      const blob = new Blob(session.chunks, {
        type:
          session.recorder.mimeType ||
          (session.chunks[0] && session.chunks[0].type) ||
          "audio/webm",
      });
      if (blob.size === 0) {
        throw new Error("没有录到声音，请重新录制。");
      }
      setResult(button, "正在上传并评分…", "recording");
      const wavBlob = await window.FamilyAudio.convertToWav(
        blob,
        session.audioContext,
      );
      const payload = await upload(button, wavBlob);

      let message = `准确度 ${formatScore(payload.accuracy)}`;
      if (payload.overall_score !== null && payload.overall_score !== undefined) {
        message += ` · 综合 ${formatScore(payload.overall_score)}`;
      }
      if (payload.match_tag === 4) {
        message += " · 不在词典";
      }
      const hint = phoneHint(payload.detail);
      if (hint) {
        message += ` · ${hint}`;
      }
      setResult(button, message, "success", payload.audio_url || "");
    } catch (error) {
      setResult(button, error.message || "测评失败，请重试。", "error");
    } finally {
      stopTracks(session);
      await closeContext(session);
      if (activeSession === session) {
        activeSession = null;
        updateButtons();
        button.textContent = "重测";
      }
    }
  }

  async function start(button) {
    if (!window.isSecureContext) {
      setResult(button, "需要通过 HTTPS 打开页面才能录音。", "error");
      return;
    }
    if (
      !navigator.mediaDevices ||
      !navigator.mediaDevices.getUserMedia ||
      !window.MediaRecorder
    ) {
      setResult(button, "当前浏览器不支持麦克风录音，请更新浏览器。", "error");
      return;
    }
    if (!window.FamilyAudio) {
      setResult(button, "音频转换脚本没有加载，请刷新页面。", "error");
      return;
    }

    let stream = null;
    let audioContext = null;
    let recorder = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const mimeType = window.FamilyAudio.chooseMimeType();
      recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) {
        throw new Error("当前浏览器无法处理录音，请更新浏览器。");
      }
      audioContext = new AudioContextClass();
      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }
    } catch (error) {
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
      if (audioContext) {
        try {
          await audioContext.close();
        } catch (_closeError) {
          // Ignore cleanup errors.
        }
      }
      let message = "无法开始录音，请检查麦克风设置。";
      if (
        error &&
        (error.name === "NotAllowedError" ||
          error.name === "PermissionDeniedError")
      ) {
        message = "麦克风权限被拒绝，请在浏览器中允许麦克风后重试。";
      } else if (error && error.name === "NotFoundError") {
        message = "没有找到麦克风设备。";
      } else if (error && error.name === "NotReadableError") {
        message = "麦克风可能正被其他程序占用。";
      } else if (error && error.message) {
        message = error.message;
      }
      setResult(button, message, "error");
      return;
    }

    const session = {
      button,
      stream,
      audioContext,
      recorder,
      chunks: [],
      timer: null,
      stopping: false,
      busy: false,
      startedAt: Date.now(),
    };

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data && event.data.size > 0) {
        session.chunks.push(event.data);
      }
    });
    recorder.addEventListener("error", () => {
      setResult(button, "录音设备发生错误，请重新录制。", "error");
    });
    recorder.addEventListener("stop", () => {
      void finish(session);
    });

    activeSession = session;
    try {
      recorder.start(250);
    } catch (_error) {
      stopTracks(session);
      await closeContext(session);
      activeSession = null;
      updateButtons();
      setResult(button, "无法开始录音，请重新尝试。", "error");
      return;
    }

    setResult(button, "录音中… 3.0 秒", "recording");
    session.timer = setInterval(() => {
      const elapsed = (Date.now() - session.startedAt) / 1000;
      const remaining = Math.max(0, MAX_SECONDS - elapsed);
      setResult(button, `录音中… ${remaining.toFixed(1)} 秒`, "recording");
      if (elapsed >= MAX_SECONDS) {
        requestStop(session);
      }
    }, 200);
    updateButtons();
    button.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      if (activeSession && activeSession.button === button) {
        requestStop(activeSession);
        return;
      }
      if (activeSession) {
        return;
      }
      void start(button);
    });
  });
})();
