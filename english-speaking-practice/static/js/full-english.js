(() => {
  "use strict";

  const section = document.querySelector("[data-full-english]");
  if (!section) {
    return;
  }

  const toggle = section.querySelector("[data-full-english-toggle]");
  const body = section.querySelector("[data-full-english-body]");
  const modeButtons = Array.from(section.querySelectorAll("[data-reading-mode]"));
  const englishView = section.querySelector("[data-reading-en]");
  const chineseView = section.querySelector("[data-reading-zh]");
  if (!toggle || !body || !englishView || !chineseView) {
    return;
  }

  function pauseReadingAudio() {
    section.querySelectorAll("audio").forEach((audio) => {
      try {
        audio.pause();
      } catch (_error) {
        // Ignore pause failures.
      }
    });
    const speech = window.speechSynthesis;
    if (speech) {
      speech.cancel();
    }
  }

  function setMode(mode) {
    if (mode !== "zh" && mode !== "en") {
      return;
    }
    englishView.hidden = mode !== "en";
    chineseView.hidden = mode !== "zh";
    modeButtons.forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        button.dataset.readingMode === mode ? "true" : "false",
      );
    });
    if (mode === "zh") {
      pauseReadingAudio();
      const status = section.querySelector(".read-aloud-status");
      if (status) {
        status.textContent = "";
        delete status.dataset.kind;
      }
    }
  }

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setMode(button.dataset.readingMode);
    });
  });

  toggle.addEventListener("click", () => {
    const expanded = toggle.getAttribute("aria-expanded") === "true";
    const nextExpanded = !expanded;
    body.hidden = !nextExpanded;
    toggle.setAttribute("aria-expanded", nextExpanded ? "true" : "false");
    toggle.textContent = nextExpanded ? "收起" : "展开";

    if (!nextExpanded) {
      pauseReadingAudio();
    }
  });
})();
