(() => {
  "use strict";

  if (!("serviceWorker" in navigator)) {
    return;
  }

  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/service-worker.js", { scope: "/" })
      .catch(() => {
        // HTTP LAN and unsupported browsers simply use the normal page.
      });
  });
})();
