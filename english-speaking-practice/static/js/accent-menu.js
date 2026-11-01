(() => {
  "use strict";

  const menus = Array.from(document.querySelectorAll("[data-accent-menu]"));
  if (menus.length === 0) {
    return;
  }

  function closeOthers(except) {
    menus.forEach((menu) => {
      if (menu !== except) {
        menu.open = false;
      }
    });
  }

  menus.forEach((menu) => {
    const summary = menu.querySelector("summary");
    menu.addEventListener("toggle", () => {
      if (menu.open) {
        closeOthers(menu);
      }
    });
    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        menu.open = false;
        if (summary) {
          summary.focus();
        }
      }
    });
  });

  document.addEventListener("click", (event) => {
    menus.forEach((menu) => {
      if (menu.open && !menu.contains(event.target)) {
        menu.open = false;
      }
    });
  });
})();
