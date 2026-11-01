(() => {
  "use strict";

  const links = Array.from(
    document.querySelectorAll(".site-nav a.nav-link"),
  );
  if (links.length === 0) {
    return;
  }

  const path = window.location.pathname;
  let activeLink = null;
  let activeLength = -1;

  links.forEach((link) => {
    let target;
    try {
      target = new URL(link.href, window.location.origin).pathname;
    } catch (_error) {
      return;
    }
    const matches =
      target === "/"
        ? path === "/"
        : path === target ||
          path.startsWith(target.endsWith("/") ? target : `${target}/`);
    if (matches && target.length > activeLength) {
      activeLink = link;
      activeLength = target.length;
    }
  });

  links.forEach((link) => {
    const isActive = link === activeLink;
    link.classList.toggle("is-active", isActive);
    if (isActive) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
})();
