(() => {
  "use strict";

  function getCookie(name) {
    const encoded = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = document.cookie.match(
      new RegExp(`(?:^|; )${encoded}=([^;]*)`),
    );
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function deleteRecording(button) {
    if (button.disabled) {
      return;
    }
    if (!window.confirm("删除这条录音？删除后无法恢复。")) {
      return;
    }

    const item = button.closest("[data-recording-item]");
    const history = button.closest("[data-recording-history]");
    const url = button.dataset.deleteUrl;
    const csrfToken = getCookie("csrftoken");
    if (!item || !history || !url) {
      return;
    }
    if (!csrfToken) {
      window.alert("页面安全令牌缺失，请刷新页面后重试。");
      return;
    }

    const audio = item.querySelector("audio");
    if (audio) {
      try {
        audio.pause();
      } catch (_error) {
        // Ignore playback errors while deleting.
      }
    }

    button.disabled = true;
    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
      });
      const contentType = response.headers.get("content-type") || "";
      if (!response.ok || response.redirected || !contentType.includes("application/json")) {
        throw new Error("删除失败，请刷新页面后重试。");
      }
      const payload = await response.json();
      if (!payload.ok) {
        throw new Error(payload.error || "删除失败，请刷新页面后重试。");
      }

      item.remove();
      const remaining =
        typeof payload.remaining === "number"
          ? payload.remaining
          : history.querySelectorAll("[data-recording-item]").length;
      const count = history.querySelector("[data-recording-count]");
      if (count) {
        count.textContent = String(remaining);
      }

      if (remaining <= 0) {
        const card = history.closest(".sentence-card");
        history.remove();
        const recordButton = card
          ? card.querySelector(".js-record-button")
          : null;
        if (recordButton) {
          recordButton.focus({ preventScroll: true });
        }
      }
    } catch (error) {
      button.disabled = false;
      window.alert(error.message || "删除失败，请稍后再试。");
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-delete-recording]");
    if (!button) {
      return;
    }
    event.preventDefault();
    void deleteRecording(button);
  });
})();
