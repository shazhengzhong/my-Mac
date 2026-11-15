(() => {
  "use strict";

  const buttons = Array.from(document.querySelectorAll("[data-assess-button]"));
  if (buttons.length === 0) {
    return;
  }

  const MAX_SECONDS = 3;
  const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
  let activeSession = null;
  let feedbackContext = null;
  let assessmentPlayer = null;

  function ensureFeedbackContext() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      return null;
    }
    if (!feedbackContext) {
      try {
        feedbackContext = new AudioContextClass();
      } catch (_error) {
        return null;
      }
    }
    if (feedbackContext.state === "suspended") {
      feedbackContext.resume().catch(() => {
        // The score is still shown when audio feedback is unavailable.
      });
    }
    return feedbackContext;
  }

  function tone(context, frequency, startAt, duration, volume = 0.045) {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(frequency, startAt);
    gain.gain.setValueAtTime(0.0001, startAt);
    gain.gain.exponentialRampToValueAtTime(volume, startAt + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, startAt + duration);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start(startAt);
    oscillator.stop(startAt + duration + 0.03);
  }

  function playScoreTone(score) {
    const context = ensureFeedbackContext();
    if (!context) {
      return;
    }
    const run = () => {
      const now = context.currentTime + 0.02;
      if (score < 70) {
        tone(context, 220, now, 0.2, 0.08);
        tone(context, 174, now + 0.24, 0.28, 0.08);
      } else {
        tone(context, 660, now, 0.12, 0.07);
        tone(context, 880, now + 0.15, 0.18, 0.07);
      }
    };
    if (context.state === "suspended") {
      context.resume().then(run).catch(() => {
        // Ignore audio feedback failures.
      });
    } else {
      run();
    }
  }

  function unitFor(button) {
    return button.closest("[data-word-unit], .word-chip");
  }

  function setButtonLabel(button, label) {
    const labelSpan = button.querySelector(".button-label");
    if (labelSpan) {
      labelSpan.textContent = label;
    } else {
      button.textContent = label;
    }
    button.setAttribute("aria-label", label);
  }

  function setResult(button, message, kind = "", audioUrl = "") {
    const chip = unitFor(button);
    const result = chip ? chip.querySelector(".assess-result") : null;
    if (!result) return;
    result.textContent = message;
    result.classList.add("is-visible");
    if (kind) {
      result.dataset.kind = kind;
    } else {
      delete result.dataset.kind;
    }
    if (audioUrl) {
      if (button.dataset.scoreOnly === "true") {
        const play = document.createElement("button");
        play.type = "button";
        play.className = "assess-play-button";
        play.setAttribute("aria-label", "播放我的录音");
        play.title = "播放我的录音";
        play.innerHTML =
          '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
          '<path d="M8 5v14l11-7z" fill="currentColor"></path>' +
          "</svg>";
        play.addEventListener("click", () => {
          if (assessmentPlayer) {
            assessmentPlayer.pause();
          }
          assessmentPlayer = new Audio(audioUrl);
          assessmentPlayer.play().catch(() => {
            setResult(button, "录音播放失败，请重试。", "error");
          });
        });
        result.appendChild(play);
      } else {
        const link = document.createElement("a");
        link.href = audioUrl;
        link.target = "_blank";
        link.rel = "noopener";
        link.className = "assess-play";
        link.textContent = " 回放";
        result.appendChild(link);
      }
    }
  }

  function updateButtons() {
    buttons.forEach((button) => {
      if (activeSession && activeSession.button === button) {
        setButtonLabel(button, activeSession.busy ? "评分中…" : "停止");
        button.disabled = activeSession.busy;
        button.classList.toggle("is-recording", !activeSession.busy);
      } else {
        setButtonLabel(button, "测评");
        button.disabled = Boolean(activeSession);
        button.classList.remove("is-recording");
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

      if (button.dataset.scoreOnly === "true") {
        const rawScore =
          payload.overall_score !== null && payload.overall_score !== undefined
            ? payload.overall_score
            : payload.accuracy;
        const score = Number(rawScore);
        if (Number.isFinite(score)) {
          setResult(
            button,
            `${Math.round(score)} 分`,
            score < 70 ? "warning" : "success",
            payload.audio_url || "",
          );
          playScoreTone(score);
        } else {
          setResult(button, "— 分", "error");
        }
      } else {
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
      }
    } catch (error) {
      setResult(button, error.message || "测评失败，请重试。", "error");
    } finally {
      stopTracks(session);
      await closeContext(session);
      if (activeSession === session) {
        activeSession = null;
        updateButtons();
        setButtonLabel(button, "重测");
      }
    }
  }

  async function start(button) {
    ensureFeedbackContext();
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
      // Safari 26 emits empty blobs for small timeslice values. Recording
      // without a timeslice yields one complete blob when we call stop().
      recorder.start();
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
