(() => {
  "use strict";

  const buttons = Array.from(document.querySelectorAll("[data-view-mode]"));
  if (buttons.length === 0) {
    return;
  }

  const STORAGE_KEY = "familyDiaryViewMode";
  const LEGACY_KEY = "familyDiaryHideChinese";
  const MODES = new Set(["both", "zh", "en"]);

  function apply(mode) {
    document.body.classList.toggle("hide-zh", mode === "en");
    document.body.classList.toggle("hide-en", mode === "zh");
    buttons.forEach((button) => {
      const active = button.dataset.viewMode === mode;
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  let mode = "both";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (MODES.has(stored)) {
      mode = stored;
    } else if (window.localStorage.getItem(LEGACY_KEY) === "1") {
      mode = "en";
      window.localStorage.setItem(STORAGE_KEY, mode);
    }
    window.localStorage.removeItem(LEGACY_KEY);
  } catch (_error) {
    // Private browsing may block localStorage; default to showing both.
  }
  apply(mode);

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const next = button.dataset.viewMode;
      if (!MODES.has(next)) {
        return;
      }
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch (_error) {
        // The toggle still works for this page view.
      }
      apply(next);
    });
  });
})();
