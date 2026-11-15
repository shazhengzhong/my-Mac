(() => {
  "use strict";

  const section = document.querySelector("[data-full-english]");
  if (!section) {
    return;
  }

  const toggle = section.querySelector("[data-full-english-toggle]");
  const body = section.querySelector("[data-full-english-body]");
  if (!toggle || !body) {
    return;
  }

  toggle.addEventListener("click", () => {
    const expanded = toggle.getAttribute("aria-expanded") === "true";
    const nextExpanded = !expanded;
    body.hidden = !nextExpanded;
    toggle.setAttribute("aria-expanded", nextExpanded ? "true" : "false");
    toggle.textContent = nextExpanded ? "收起" : "展开";

    if (!nextExpanded) {
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
  });
})();
