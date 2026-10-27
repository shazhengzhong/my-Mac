(() => {
  "use strict";

  const button = document.querySelector("[data-chinese-toggle]");
  if (!button) {
    return;
  }

  const STORAGE_KEY = "familyDiaryHideChinese";

  function apply(hidden) {
    document.body.classList.toggle("hide-zh", hidden);
    button.textContent = hidden ? "显示中文" : "隐藏中文";
    button.setAttribute("aria-pressed", hidden ? "true" : "false");
  }

  let hidden = false;
  try {
    hidden = window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch (_error) {
    // Private browsing may block localStorage; default to showing Chinese.
  }
  apply(hidden);

  button.addEventListener("click", () => {
    const next = !document.body.classList.contains("hide-zh");
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch (_error) {
      // The toggle still works for this page view.
    }
    apply(next);
  });
})();
