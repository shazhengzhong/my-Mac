(() => {
  "use strict";

  const controls = Array.from(document.querySelectorAll("[data-record-control]"));

  // Shared with word-assessor.js on the diary detail page.
  window.FamilyAudio = { chooseMimeType, convertToWav, getCookie };

  if (controls.length === 0) {
    return;
  }

  const MAX_SECONDS = 60;
  const TARGET_RATE = 16000;
  const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
  let activeSession = null;

  function setStatus(control, message, kind = "") {
    const status = control.querySelector(".record-status");
    if (!status) return;
    status.textContent = message;
    if (kind) {
      status.dataset.kind = kind;
    } else {
      delete status.dataset.kind;
    }
  }

  function updateButtons() {
    controls.forEach((control) => {
      const button = control.querySelector(".js-record-button");
      if (!button) return;
      if (activeSession && activeSession.control === control) {
        button.textContent = activeSession.busy ? "正在处理…" : "停止录音";
        button.disabled = Boolean(activeSession.busy);
      } else {
        button.textContent = "开始录音";
        button.disabled = Boolean(activeSession);
      }
    });
  }

  function formatElapsed(seconds) {
    const whole = Math.max(0, Math.floor(seconds));
    return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
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

  function chooseMimeType() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) {
      return "";
    }
    const candidates = [
      "audio/mp4",
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
    ];
    return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
  }

  function getCookie(name) {
    const encoded = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = document.cookie.match(new RegExp(`(?:^|; )${encoded}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function encodeWav(audioBuffer) {
    const samples = audioBuffer.getChannelData(0);
    const bytesPerSample = 2;
    const dataSize = samples.length * bytesPerSample;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    function writeString(offset, value) {
      for (let index = 0; index < value.length; index += 1) {
        view.setUint8(offset + index, value.charCodeAt(index));
      }
    }

    writeString(0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, TARGET_RATE, true);
    view.setUint32(28, TARGET_RATE * bytesPerSample, true);
    view.setUint16(32, bytesPerSample, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, dataSize, true);

    let offset = 44;
    for (let index = 0; index < samples.length; index += 1) {
      const sample = Math.max(-1, Math.min(1, samples[index]));
      const int16 = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      view.setInt16(offset, int16, true);
      offset += bytesPerSample;
    }
    return new Blob([view], { type: "audio/wav" });
  }

  function resampleManually(sourceBuffer) {
    const frameCount = Math.min(
      Math.ceil(sourceBuffer.duration * TARGET_RATE),
      TARGET_RATE * MAX_SECONDS,
    );
    const output = new Float32Array(frameCount);
    const channels = sourceBuffer.numberOfChannels;
    const ratio = sourceBuffer.sampleRate / TARGET_RATE;
    const channelData = [];
    for (let channel = 0; channel < channels; channel += 1) {
      channelData.push(sourceBuffer.getChannelData(channel));
    }

    for (let frame = 0; frame < frameCount; frame += 1) {
      const sourcePosition = frame * ratio;
      const leftIndex = Math.floor(sourcePosition);
      const rightIndex = Math.min(leftIndex + 1, sourceBuffer.length - 1);
      const fraction = sourcePosition - leftIndex;
      let sample = 0;
      for (let channel = 0; channel < channels; channel += 1) {
        const data = channelData[channel];
        const left = data[Math.min(leftIndex, data.length - 1)];
        const right = data[rightIndex];
        sample += left + (right - left) * fraction;
      }
      output[frame] = sample / channels;
    }

    return {
      getChannelData: () => output,
    };
  }

  async function convertToWav(blob, audioContext) {
    const sourceBuffer = await audioContext.decodeAudioData(await blob.arrayBuffer());
    const OfflineContext = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!OfflineContext) {
      return encodeWav(resampleManually(sourceBuffer));
    }

    const frameCount = Math.min(
      Math.ceil(sourceBuffer.duration * TARGET_RATE),
      TARGET_RATE * MAX_SECONDS,
    );
    const offline = new OfflineContext(1, frameCount, TARGET_RATE);
    const source = offline.createBufferSource();
    source.buffer = sourceBuffer;
    source.connect(offline.destination);
    source.start(0);
    return encodeWav(await offline.startRendering());
  }

  async function uploadRecording(control, wavBlob) {
    if (wavBlob.size > MAX_UPLOAD_BYTES) {
      throw new Error("转换后的录音太大，请缩短到 60 秒以内。");
    }
    const csrfToken = getCookie("csrftoken");
    if (!csrfToken) {
      throw new Error("页面安全令牌缺失，请刷新页面后重试。");
    }

    const formData = new FormData();
    formData.append("audio", wavBlob, "recording.wav");
    const response = await fetch(control.dataset.uploadUrl, {
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
      throw new Error(payload && payload.error ? payload.error : "上传失败，请稍后重试。");
    }
    if (!payload || !payload.ok) {
      throw new Error("上传没有成功，请刷新页面后重试。");
    }
    return payload;
  }

  function cleanupSession(session) {
    if (!session) return;
    if (session.timer) {
      clearInterval(session.timer);
    }
    stopTracks(session);
    void closeContext(session);
  }

  async function finishRecording(session) {
    const { control } = session;
    session.busy = true;
    updateButtons();
    setStatus(control, "正在转换录音…");

    try {
      const blob = new Blob(session.chunks, {
        type: session.recorder.mimeType || (session.chunks[0] && session.chunks[0].type) || "audio/webm",
      });
      if (blob.size === 0) {
        throw new Error("没有录到声音，请重新录制。");
      }
      const wavBlob = await convertToWav(blob, session.audioContext);
      setStatus(control, "正在上传…");
      await uploadRecording(control, wavBlob);
      setStatus(control, "上传成功，正在刷新…", "success");
      const card = control.closest("[id^='sentence-']");
      if (card) {
        sessionStorage.setItem("focusDiarySentence", card.id);
      }
      window.location.reload();
    } catch (error) {
      setStatus(control, error.message || "录音处理失败，请重试。", "error");
    } finally {
      stopTracks(session);
      await closeContext(session);
      if (activeSession === session) {
        activeSession = null;
        updateButtons();
      }
    }
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
      cleanupSession(session);
      activeSession = null;
      updateButtons();
    }
  }

  async function startRecording(control) {
    if (activeSession) {
      setStatus(control, "请先停止当前这句的录音。", "error");
      return;
    }
    if (!window.isSecureContext) {
      setStatus(control, "需要通过 HTTPS 打开页面才能录音。", "error");
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      setStatus(control, "当前浏览器不支持麦克风录音，请更新浏览器。", "error");
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
      const mimeType = chooseMimeType();
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
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
      if (error && (error.name === "NotAllowedError" || error.name === "PermissionDeniedError")) {
        message = "麦克风权限被拒绝，请在浏览器中允许麦克风后重试。";
      } else if (error && error.name === "NotFoundError") {
        message = "没有找到麦克风设备。";
      } else if (error && error.name === "NotReadableError") {
        message = "麦克风可能正被其他程序占用。";
      } else if (error && error.message) {
        message = error.message;
      }
      setStatus(control, message, "error");
      return;
    }

    const session = {
      control,
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
      setStatus(control, "录音设备发生错误，请重新录制。", "error");
    });
    recorder.addEventListener("stop", () => {
      void finishRecording(session);
    });

    activeSession = session;
    try {
      recorder.start(250);
    } catch (_error) {
      cleanupSession(session);
      activeSession = null;
      updateButtons();
      setStatus(control, "无法开始录音，请重新尝试。", "error");
      return;
    }

    setStatus(control, "录音中 00:00");
    session.timer = setInterval(() => {
      const elapsed = (Date.now() - session.startedAt) / 1000;
      setStatus(control, `录音中 ${formatElapsed(elapsed)} / 01:00`);
      if (elapsed >= MAX_SECONDS) {
        requestStop(session);
      }
    }, 250);
    updateButtons();
    control.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  controls.forEach((control) => {
    const button = control.querySelector(".js-record-button");
    if (!button) return;
    button.addEventListener("click", () => {
      if (activeSession && activeSession.control === control) {
        requestStop(activeSession);
      } else {
        void startRecording(control);
      }
    });
  });

  const focusId = sessionStorage.getItem("focusDiarySentence");
  if (focusId) {
    sessionStorage.removeItem("focusDiarySentence");
    const target = document.getElementById(focusId);
    if (target) {
      target.scrollIntoView({ block: "center" });
    }
  }
})();
