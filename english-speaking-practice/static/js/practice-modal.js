(() => {
  "use strict";

  const modal = document.querySelector("[data-practice-modal]");
  if (!modal) {
    return;
  }

  const panel = modal.querySelector(".practice-modal-panel");
  const scrollArea = modal.querySelector("[data-practice-scroll]");
  const closeButton = modal.querySelector(".practice-modal-close");
  const triggers = Array.from(
    document.querySelectorAll(".bilingual-group-link[data-practice-target]"),
  );
  let lastTrigger = null;
  let savedScrollY = 0;

  function clearFocusedCard() {
    modal.querySelectorAll(".sentence-card.is-focused").forEach((card) => {
      card.classList.remove("is-focused");
    });
  }

  function focusableElements() {
    return Array.from(
      modal.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => element.offsetParent !== null);
  }

  function openPractice(sentenceId, trigger) {
    // A missing target must not open an empty full-screen panel.
    const target = sentenceId ? document.getElementById(sentenceId) : null;
    if (!target) {
      return;
    }
    lastTrigger = trigger || null;
    savedScrollY = window.scrollY || window.pageYOffset || 0;
    if (window.FamilySentenceReader) {
      window.FamilySentenceReader.stop();
    }
    if (window.FamilySentenceAudio) {
      window.FamilySentenceAudio.stop();
    }
    document.querySelectorAll(".read-aloud-audio").forEach((player) => {
      try {
        player.pause();
      } catch (_error) {
        // Ignore pause failures.
      }
    });
    modal.hidden = false;
    document.body.classList.add("practice-modal-open");
    clearFocusedCard();

    if (panel) {
      panel.scrollTop = 0;
    }

    target.classList.add("is-focused");
    window.requestAnimationFrame(() => {
      if (!scrollArea) {
        return;
      }
      const scrollRect = scrollArea.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const nextTop =
        scrollArea.scrollTop + targetRect.top - scrollRect.top - 12;
      scrollArea.scrollTop = Math.max(0, nextTop);
      if (panel) {
        panel.scrollTop = 0;
      }
    });

    if (closeButton) {
      closeButton.focus({ preventScroll: true });
    }
  }

  function closePractice() {
    if (modal.hidden) {
      return;
    }
    modal.hidden = true;
    document.body.classList.remove("practice-modal-open");
    if (window.FamilySentenceAudio) {
      window.FamilySentenceAudio.stop();
    }
    clearFocusedCard();
    const restoreY = savedScrollY;
    window.scrollTo(0, restoreY);
    window.requestAnimationFrame(() => {
      window.scrollTo(0, restoreY);
    });
    if (lastTrigger && typeof lastTrigger.focus === "function") {
      lastTrigger.focus({ preventScroll: true });
    }
    lastTrigger = null;
  }

  triggers.forEach((trigger) => {
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      const sentenceId = trigger.dataset.practiceTarget || "";
      openPractice(sentenceId, trigger);
    });
  });

  // The ↗ marker and the group padding sit outside the link. Make the whole
  // box clickable while leaving the normal/slow read buttons independent.
  document.querySelectorAll(".bilingual-group.is-linked").forEach((group) => {
    const link = group.querySelector(
      ".bilingual-group-link[data-practice-target]",
    );
    if (!link) {
      return;
    }
    group.addEventListener("click", (event) => {
      if (
        event.target.closest(".diary-read-controls") ||
        event.target.closest(".bilingual-group-link")
      ) {
        return;
      }
      event.preventDefault();
      openPractice(link.dataset.practiceTarget || "", link);
    });
  });

  modal.querySelectorAll("[data-practice-close]").forEach((control) => {
    control.addEventListener("click", closePractice);
  });

  modal.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closePractice();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }

    const focusables = focusableElements();
    if (focusables.length === 0) {
      return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  // Sentence TTS is a normal form POST. Remember the sentence so the modal
  // can reopen on the reloaded page.
  modal.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", () => {
      const card = form.closest("[id^='sentence-']");
      if (card) {
        sessionStorage.setItem("focusDiarySentence", card.id);
      }
    });
  });

  // Reopen the same sentence after a recording reload.
  const pendingSentence = window.__pendingPracticeSentence;
  delete window.__pendingPracticeSentence;

  function openPendingPractice() {
    if (pendingSentence && document.getElementById(pendingSentence)) {
      openPractice(pendingSentence, null);
    }
  }

  function schedulePendingPractice() {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(openPendingPractice);
    });
  }

  if (document.readyState === "complete") {
    schedulePendingPractice();
  } else {
    window.addEventListener("DOMContentLoaded", schedulePendingPractice, {
      once: true,
    });
  }
})();
