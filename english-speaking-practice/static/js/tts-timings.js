(() => {
  "use strict";

  function normalizeWord(value) {
    return (value || "")
      .toLowerCase()
      .replace(/[’]/g, "'")
      .replace(/[^a-z0-9]/g, "");
  }

  function dedupeTimings(rawTimings) {
    if (!Array.isArray(rawTimings)) {
      return [];
    }
    const byStart = new Map();
    for (const item of rawTimings) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const word = normalizeWord(item.word);
      const start = Number(item.start_ms);
      const end = Number(item.end_ms);
      if (!word || !Number.isFinite(start) || !Number.isFinite(end)) {
        continue;
      }
      const key = `${word}|${start}`;
      const existing = byStart.get(key);
      if (!existing || end < existing.end_ms) {
        byStart.set(key, { word, start_ms: start, end_ms: end });
      }
    }
    return Array.from(byStart.values()).sort(
      (first, second) =>
        first.start_ms - second.start_ms || first.end_ms - second.end_ms,
    );
  }

  function approximateTimings(spans, durationMs) {
    const weights = spans.map((span) =>
      Math.max(
        1,
        (span.textContent || "").replace(/\s+/g, "").length,
      ),
    );
    const total = weights.reduce((sum, value) => sum + value, 0) || 1;
    const duration = Math.max(1, Number(durationMs) || 3000);
    let cursor = 0;
    return weights.map((weight) => {
      const start = cursor;
      cursor += (duration * weight) / total;
      return { start_ms: start, end_ms: cursor };
    });
  }

  function fillGaps(infos, timings, durationMs) {
    const totalDuration = Math.max(1, Number(durationMs) || 3000);
    let index = 0;
    while (index < infos.length) {
      if (timings[index]) {
        index += 1;
        continue;
      }
      let endIndex = index;
      while (endIndex < infos.length && !timings[endIndex]) {
        endIndex += 1;
      }
      const previousEnd =
        index > 0 && timings[index - 1] ? timings[index - 1].end_ms : 0;
      const nextStart =
        endIndex < infos.length && timings[endIndex]
          ? timings[endIndex].start_ms
          : totalDuration;
      let gapStart = previousEnd;
      let gapEnd = Math.max(gapStart, nextStart);
      if (gapEnd <= gapStart) {
        gapEnd = gapStart + 1;
      }
      const weights = [];
      for (let wordIndex = index; wordIndex < endIndex; wordIndex += 1) {
        weights.push(Math.max(1, infos[wordIndex].word.length));
      }
      const totalWeight =
        weights.reduce((sum, value) => sum + value, 0) || 1;
      let cursor = gapStart;
      for (let wordIndex = index; wordIndex < endIndex; wordIndex += 1) {
        const next =
          cursor +
          ((gapEnd - gapStart) * weights[wordIndex - index]) / totalWeight;
        timings[wordIndex] = {
          start_ms: Math.round(cursor),
          end_ms: Math.round(next),
        };
        cursor = next;
      }
      index = endIndex;
    }
  }

  function dropOverlaps(timings) {
    let previousEnd = 0;
    for (let index = 0; index < timings.length; index += 1) {
      const timing = timings[index];
      if (!timing) {
        continue;
      }
      if (timing.start_ms < previousEnd) {
        if (timing.end_ms <= previousEnd) {
          timings[index] = null;
          continue;
        }
        timing.start_ms = previousEnd;
      }
      previousEnd = timing.end_ms;
    }
  }

  function enforceOrder(timings) {
    let cursor = 0;
    for (const timing of timings) {
      if (!timing) {
        continue;
      }
      if (timing.start_ms < cursor) {
        timing.start_ms = cursor;
      }
      if (timing.end_ms < timing.start_ms) {
        timing.end_ms = timing.start_ms;
      }
      cursor = timing.end_ms;
    }
  }

  function extendEnds(timings, durationMs) {
    const totalDuration = Math.max(1, Number(durationMs) || 3000);
    for (let index = 0; index < timings.length; index += 1) {
      const timing = timings[index];
      if (!timing) {
        continue;
      }
      let next = null;
      for (let nextIndex = index + 1; nextIndex < timings.length; nextIndex += 1) {
        if (timings[nextIndex]) {
          next = timings[nextIndex];
          break;
        }
      }
      const nextStart = next ? next.start_ms : totalDuration;
      if (nextStart > timing.end_ms) {
        timing.end_ms = nextStart;
      }
    }
  }

  function build(spans, rawTimings, durationMs) {
    const list = Array.from(spans || []);
    if (list.length === 0) {
      return [];
    }

    const infos = [];
    let stream = "";
    list.forEach((span, index) => {
      const word = normalizeWord(span.textContent);
      const startChar = stream.length;
      if (word) {
        stream += word;
      }
      infos.push({
        index,
        word,
        startChar,
        endChar: stream.length,
      });
    });

    const events = dedupeTimings(rawTimings);
    if (!stream || events.length === 0) {
      return approximateTimings(list, durationMs);
    }

    const startChars = new Set(infos.map((info) => info.startChar));
    const timings = new Array(list.length).fill(null);
    let searchFrom = 0;

    events.forEach((event, eventIndex) => {
      const word = event.word;
      if (!word) {
        return;
      }
      let from = Math.max(0, searchFrom - word.length + 1);
      let position = stream.indexOf(word, from);
      while (
        position !== -1 &&
        position + word.length <= searchFrom
      ) {
        position = stream.indexOf(word, position + 1);
      }
      if (position === -1) {
        return;
      }
      // Timing events may repeat the previous word before the next one, but
      // they always begin on a word boundary.  Avoid matching a fragment in
      // the middle of a longer word.
      if (position !== 0 && !startChars.has(position)) {
        return;
      }

      const endChar = position + word.length;
      const overlaps = infos.filter(
        (info) =>
          info.endChar > position &&
          info.startChar < endChar &&
          !timings[info.index],
      );
      if (overlaps.length === 0) {
        searchFrom = Math.max(searchFrom, endChar);
        return;
      }

      let eventEnd = event.end_ms;
      const next = events[eventIndex + 1];
      if (overlaps.length > 1 && next) {
        // At a sentence boundary the provider sometimes folds the next word
        // into the current event and truncates its end time.  Extend merged
        // events into the following gap, but never swallow a long pause.
        eventEnd = Math.max(
          eventEnd,
          Math.min(next.start_ms, eventEnd + 500),
        );
      }
      const eventStart = event.start_ms;
      if (eventEnd < eventStart) {
        eventEnd = eventStart;
      }
      const duration = eventEnd - eventStart;

      for (const info of overlaps) {
        const overlapStart = Math.max(info.startChar, position);
        const overlapEnd = Math.min(info.endChar, endChar);
        if (overlapEnd <= overlapStart) {
          continue;
        }
        const start =
          eventStart +
          duration * ((overlapStart - position) / word.length);
        const end =
          eventStart +
          duration * ((overlapEnd - position) / word.length);
        timings[info.index] = {
          start_ms: Math.round(start),
          end_ms: Math.round(Math.max(start, end)),
        };
      }
      searchFrom = Math.max(searchFrom, endChar);
    });

    dropOverlaps(timings);
    fillGaps(infos, timings, durationMs);
    enforceOrder(timings);
    extendEnds(timings, durationMs);
    if (timings.some((timing) => !timing)) {
      return approximateTimings(list, durationMs);
    }
    return timings;
  }

  window.FamilyTtsTimings = {
    build,
    normalizeWord,
  };
})();
