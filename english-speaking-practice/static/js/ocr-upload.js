(() => {
  "use strict";

  const input = document.querySelector("#ocr-image");
  const form = input ? input.closest("form") : null;
  const status = document.querySelector("#ocr-file-status");
  if (!input || !form || !status) {
    return;
  }

  const MAX_BYTES = 5 * 1024 * 1024;
  const MAX_DIMENSION = 2400;
  const ALLOWED_TYPES = new Set([
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/bmp",
  ]);
  const cropModal = document.querySelector("[data-crop-modal]");
  const cropCanvas = document.querySelector("[data-crop-canvas]");
  const cropWrap = document.querySelector("[data-crop-canvas-wrap]");
  const cropApply = document.querySelector("[data-crop-apply]");
  const cropCancelButtons = Array.from(
    document.querySelectorAll("[data-crop-cancel]"),
  );
  const cropFields = {
    x: form.elements.namedItem("crop_x"),
    y: form.elements.namedItem("crop_y"),
    w: form.elements.namedItem("crop_w"),
    h: form.elements.namedItem("crop_h"),
  };
  const isShell = /FamilyDiaryShell\//.test(navigator.userAgent);
  let converting = false;
  let cropping = false;
  let cropState = null;
  let cropResizeHandler = null;

  function setStatus(message, isError = false) {
    status.textContent = message;
    status.dataset.kind = isError ? "error" : "";
    if (!isError) {
      delete status.dataset.kind;
    }
  }

  function sizeLabel(bytes) {
    if (bytes >= 1024 * 1024) {
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }

  async function loadImage(file) {
    if (typeof createImageBitmap === "function") {
      try {
        return await createImageBitmap(file, {
          imageOrientation: "from-image",
        });
      } catch (error) {
        return await createImageBitmap(file);
      }
    }
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const image = new Image();
      image.onload = () => {
        URL.revokeObjectURL(url);
        resolve(image);
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("image decode failed"));
      };
      image.src = url;
    });
  }

  function toJpegBlob(image) {
    const width = image.width || image.naturalWidth || 0;
    const height = image.height || image.naturalHeight || 0;
    if (!width || !height) {
      throw new Error("image has no dimensions");
    }
    const scale = Math.min(1, MAX_DIMENSION / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("canvas unavailable");
    }
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.imageSmoothingQuality = "high";
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    if (typeof image.close === "function") {
      image.close();
    }
    return new Promise((resolve, reject) => {
      canvas.toBlob(
        (blob) => {
          if (blob) {
            resolve(blob);
          } else {
            reject(new Error("jpeg conversion failed"));
          }
        },
        "image/jpeg",
        0.88,
      );
    });
  }

  function replaceFile(blob) {
    if (typeof DataTransfer !== "function") {
      throw new Error("DataTransfer unavailable");
    }
    const transfer = new DataTransfer();
    transfer.items.add(
      new File([blob], "photo.jpg", {
        type: "image/jpeg",
        lastModified: Date.now(),
      }),
    );
    input.files = transfer.files;
  }

  async function handleFile() {
    const file = input.files && input.files[0];
    if (!file) {
      setStatus("");
      return;
    }
    const needsConversion =
      !ALLOWED_TYPES.has(file.type) || file.size > MAX_BYTES;
    if (!needsConversion) {
      setStatus(`已选择 ${file.name}（${sizeLabel(file.size)}）。`);
      return;
    }

    converting = true;
    setStatus("正在把照片转换成适合识别的 JPG，请稍候……");
    try {
      const image = await loadImage(file);
      const blob = await toJpegBlob(image);
      if (blob.size > MAX_BYTES) {
        throw new Error("converted image is still too large");
      }
      replaceFile(blob);
      setStatus(
        `照片已转换为 JPG（${sizeLabel(blob.size)}），可以直接识别。`,
      );
    } catch (error) {
      setStatus(
        "这张照片无法在浏览器里转换。请换一张 JPG/PNG 图片，或先把照片截图再上传。",
        true,
      );
    } finally {
      converting = false;
    }
  }

  function clearCropFields() {
    for (const field of Object.values(cropFields)) {
      if (field) {
        field.value = "";
      }
    }
  }

  function setCropFields(rect, imageWidth, imageHeight) {
    if (
      !cropFields.x ||
      !cropFields.y ||
      !cropFields.w ||
      !cropFields.h ||
      !imageWidth ||
      !imageHeight
    ) {
      return false;
    }
    const values = {
      x: rect.x / imageWidth,
      y: rect.y / imageHeight,
      w: rect.w / imageWidth,
      h: rect.h / imageHeight,
    };
    cropFields.x.value = Math.min(1, Math.max(0, values.x)).toFixed(6);
    cropFields.y.value = Math.min(1, Math.max(0, values.y)).toFixed(6);
    cropFields.w.value = Math.min(1, Math.max(0, values.w)).toFixed(6);
    cropFields.h.value = Math.min(1, Math.max(0, values.h)).toFixed(6);
    return true;
  }

  function shouldCrop(file) {
    return Boolean(
      cropModal &&
        cropCanvas &&
        cropWrap &&
        cropApply &&
        cropFields.x &&
        cropFields.y &&
        cropFields.w &&
        cropFields.h &&
        !isShell &&
        file &&
        typeof file.type === "string" &&
        file.type.startsWith("image/"),
    );
  }

  function cropPoint(event) {
    const rect = cropCanvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  function cropModeAt(x, y) {
    if (!cropState) {
      return 0;
    }
    const crop = cropState.crop;
    const slop = 24;
    const left = Math.abs(x - crop.x) <= slop;
    const right = Math.abs(x - (crop.x + crop.w)) <= slop;
    const top = Math.abs(y - crop.y) <= slop;
    const bottom = Math.abs(y - (crop.y + crop.h)) <= slop;
    if (left && top) {
      return 2 | 4;
    }
    if (right && top) {
      return 8 | 4;
    }
    if (left && bottom) {
      return 2 | 16;
    }
    if (right && bottom) {
      return 8 | 16;
    }
    if (left) {
      return 2;
    }
    if (right) {
      return 8;
    }
    if (top) {
      return 4;
    }
    if (bottom) {
      return 16;
    }
    if (
      x >= crop.x &&
      x <= crop.x + crop.w &&
      y >= crop.y &&
      y <= crop.y + crop.h
    ) {
      return 1;
    }
    return 0;
  }

  function moveCrop(dx, dy) {
    if (!cropState) {
      return;
    }
    const state = cropState;
    const crop = state.crop;
    const minSize = 48;
    if (state.mode === 1) {
      crop.x += dx;
      crop.y += dy;
      crop.x = Math.max(
        state.displayX,
        Math.min(crop.x, state.displayX + state.displayW - crop.w),
      );
      crop.y = Math.max(
        state.displayY,
        Math.min(crop.y, state.displayY + state.displayH - crop.h),
      );
    } else {
      if ((state.mode & 2) !== 0) {
        const nextX = Math.max(
          state.displayX,
          Math.min(crop.x + dx, crop.x + crop.w - minSize),
        );
        crop.w += crop.x - nextX;
        crop.x = nextX;
      }
      if ((state.mode & 8) !== 0) {
        crop.w = Math.max(
          minSize,
          Math.min(
            crop.w + dx,
            state.displayX + state.displayW - crop.x,
          ),
        );
      }
      if ((state.mode & 4) !== 0) {
        const nextY = Math.max(
          state.displayY,
          Math.min(crop.y + dy, crop.y + crop.h - minSize),
        );
        crop.h += crop.y - nextY;
        crop.y = nextY;
      }
      if ((state.mode & 16) !== 0) {
        crop.h = Math.max(
          minSize,
          Math.min(
            crop.h + dy,
            state.displayY + state.displayH - crop.y,
          ),
        );
      }
    }
    drawCrop();
  }

  function drawCrop() {
    if (!cropState) {
      return;
    }
    const state = cropState;
    const context = cropCanvas.getContext("2d");
    if (!context) {
      return;
    }
    context.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    context.clearRect(0, 0, state.cssWidth, state.cssHeight);
    context.fillStyle = "#000";
    context.fillRect(0, 0, state.cssWidth, state.cssHeight);
    context.imageSmoothingEnabled = true;
    context.drawImage(
      state.image,
      state.displayX,
      state.displayY,
      state.displayW,
      state.displayH,
    );

    const crop = state.crop;
    context.fillStyle = "rgba(0, 0, 0, 0.56)";
    context.fillRect(0, 0, state.cssWidth, crop.y);
    context.fillRect(
      0,
      crop.y + crop.h,
      state.cssWidth,
      state.cssHeight - (crop.y + crop.h),
    );
    context.fillRect(0, crop.y, crop.x, crop.h);
    context.fillRect(
      crop.x + crop.w,
      crop.y,
      state.cssWidth - (crop.x + crop.w),
      crop.h,
    );

    context.strokeStyle = "#fff";
    context.lineWidth = 2;
    context.strokeRect(crop.x, crop.y, crop.w, crop.h);

    context.strokeStyle = "rgba(255, 255, 255, 0.35)";
    context.lineWidth = 1;
    for (let index = 1; index <= 2; index++) {
      const x = crop.x + (crop.w * index) / 3;
      const y = crop.y + (crop.h * index) / 3;
      context.beginPath();
      context.moveTo(x, crop.y);
      context.lineTo(x, crop.y + crop.h);
      context.stroke();
      context.beginPath();
      context.moveTo(crop.x, y);
      context.lineTo(crop.x + crop.w, y);
      context.stroke();
    }

    const corners = [
      [crop.x, crop.y],
      [crop.x + crop.w, crop.y],
      [crop.x, crop.y + crop.h],
      [crop.x + crop.w, crop.y + crop.h],
    ];
    context.fillStyle = "#2563eb";
    for (const [x, y] of corners) {
      context.beginPath();
      context.arc(x, y, 7, 0, Math.PI * 2);
      context.fill();
    }
    context.strokeStyle = "#fff";
    context.lineWidth = 1.5;
    context.strokeRect(crop.x, crop.y, crop.w, crop.h);
  }

  function layoutCrop() {
    if (!cropState) {
      return;
    }
    const wrapRect = cropWrap.getBoundingClientRect();
    const cssWidth = Math.max(1, Math.floor(wrapRect.width));
    const cssHeight = Math.max(1, Math.floor(wrapRect.height));
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cropCanvas.width = Math.max(1, Math.round(cssWidth * dpr));
    cropCanvas.height = Math.max(1, Math.round(cssHeight * dpr));
    cropCanvas.style.width = `${cssWidth}px`;
    cropCanvas.style.height = `${cssHeight}px`;

    const state = cropState;
    state.cssWidth = cssWidth;
    state.cssHeight = cssHeight;
    state.dpr = dpr;
    const padding = 12;
    state.scale = Math.min(
      (cssWidth - padding * 2) / state.imageWidth,
      (cssHeight - padding * 2) / state.imageHeight,
    );
    state.scale = Math.max(state.scale, 0.0001);
    state.displayW = state.imageWidth * state.scale;
    state.displayH = state.imageHeight * state.scale;
    state.displayX = (cssWidth - state.displayW) / 2;
    state.displayY = (cssHeight - state.displayH) / 2;

    const insetX = state.displayW * 0.02;
    const insetY = state.displayH * 0.02;
    state.crop = {
      x: state.displayX + insetX,
      y: state.displayY + insetY,
      w: state.displayW - insetX * 2,
      h: state.displayH - insetY * 2,
    };
    state.mode = 0;
    state.pointerId = null;
    drawCrop();
  }

  function cropToSourceRect() {
    const state = cropState;
    const crop = state.crop;
    const left = Math.max(
      0,
      Math.round((crop.x - state.displayX) / state.scale),
    );
    const top = Math.max(
      0,
      Math.round((crop.y - state.displayY) / state.scale),
    );
    const right = Math.min(
      state.imageWidth,
      Math.round((crop.x + crop.w - state.displayX) / state.scale),
    );
    const bottom = Math.min(
      state.imageHeight,
      Math.round((crop.y + crop.h - state.displayY) / state.scale),
    );
    return {
      x: left,
      y: top,
      w: Math.max(1, right - left),
      h: Math.max(1, bottom - top),
    };
  }

  function closeCrop() {
    if (cropModal) {
      cropModal.hidden = true;
    }
    document.body.classList.remove("crop-modal-open");
    if (cropResizeHandler) {
      window.removeEventListener("resize", cropResizeHandler);
      cropResizeHandler = null;
    }
    if (cropState && cropState.image && typeof cropState.image.close === "function") {
      cropState.image.close();
    }
    cropState = null;
    cropping = false;
    if (cropCanvas) {
      cropCanvas.width = 0;
      cropCanvas.height = 0;
    }
    if (cropApply) {
      cropApply.disabled = false;
    }
  }

  function cancelCrop() {
    if (!cropping) {
      return;
    }
    closeCrop();
    input.value = "";
    clearCropFields();
    setStatus("已取消裁剪，请重新选择照片。");
  }

  async function openCrop(file) {
    cropping = true;
    setStatus("请拖动方框选择要识别的文字区域，然后点“完成”。");
    cropModal.hidden = false;
    document.body.classList.add("crop-modal-open");
    if (cropApply) {
      cropApply.disabled = true;
    }

    window.requestAnimationFrame(async () => {
      try {
        const image = await loadImage(file);
        if (!cropping) {
          if (image && typeof image.close === "function") {
            image.close();
          }
          return;
        }
        const imageWidth = image.width || image.naturalWidth || 0;
        const imageHeight = image.height || image.naturalHeight || 0;
        if (!imageWidth || !imageHeight) {
          throw new Error("image has no dimensions");
        }
        cropState = {
          image,
          imageWidth,
          imageHeight,
          cssWidth: 1,
          cssHeight: 1,
          dpr: 1,
          displayX: 0,
          displayY: 0,
          displayW: 1,
          displayH: 1,
          scale: 1,
          crop: { x: 0, y: 0, w: 1, h: 1 },
          mode: 0,
          pointerId: null,
        };
        cropResizeHandler = () => layoutCrop();
        window.addEventListener("resize", cropResizeHandler);
        layoutCrop();
        if (cropApply) {
          cropApply.disabled = false;
          cropApply.focus({ preventScroll: true });
        }
      } catch (error) {
        closeCrop();
        clearCropFields();
        setStatus(
          "这张照片无法在浏览器里预览裁剪，将直接使用原图识别；需要裁剪请先在相册里裁好再选择。",
        );
      }
    });
  }

  function applyCrop() {
    if (!cropping || !cropState || !cropApply || cropApply.disabled) {
      return;
    }
    const state = cropState;
    const rect = cropToSourceRect();
    if (!setCropFields(rect, state.imageWidth, state.imageHeight)) {
      setStatus("裁剪区域保存失败，请重新选择照片。", true);
      return;
    }
    closeCrop();
    setStatus("已选择裁剪区域，点「识别文字」开始识别。");
  }

  function onCropPointerDown(event) {
    if (!cropState) {
      return;
    }
    const point = cropPoint(event);
    const mode = cropModeAt(point.x, point.y);
    if (!mode) {
      return;
    }
    cropState.mode = mode;
    cropState.pointerId = event.pointerId;
    cropState.lastX = point.x;
    cropState.lastY = point.y;
    if (cropCanvas.setPointerCapture) {
      cropCanvas.setPointerCapture(event.pointerId);
    }
    event.preventDefault();
  }

  function onCropPointerMove(event) {
    if (
      !cropState ||
      !cropState.mode ||
      event.pointerId !== cropState.pointerId
    ) {
      return;
    }
    const point = cropPoint(event);
    const dx = point.x - cropState.lastX;
    const dy = point.y - cropState.lastY;
    cropState.lastX = point.x;
    cropState.lastY = point.y;
    moveCrop(dx, dy);
    event.preventDefault();
  }

  function onCropPointerUp(event) {
    if (!cropState || event.pointerId !== cropState.pointerId) {
      return;
    }
    cropState.mode = 0;
    cropState.pointerId = null;
    if (cropCanvas.releasePointerCapture) {
      try {
        cropCanvas.releasePointerCapture(event.pointerId);
      } catch (error) {
        // The pointer may already have been released.
      }
    }
  }

  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    clearCropFields();
    if (!file) {
      setStatus("");
      return;
    }
    if (shouldCrop(file)) {
      void openCrop(file);
      return;
    }
    void handleFile();
  });

  if (cropApply) {
    cropApply.addEventListener("click", applyCrop);
  }
  cropCancelButtons.forEach((button) => {
    button.addEventListener("click", cancelCrop);
  });
  if (cropModal) {
    cropModal.addEventListener("click", (event) => {
      if (event.target === cropModal) {
        cancelCrop();
      }
    });
  }
  if (cropCanvas) {
    cropCanvas.addEventListener("pointerdown", onCropPointerDown);
    cropCanvas.addEventListener("pointermove", onCropPointerMove);
    cropCanvas.addEventListener("pointerup", onCropPointerUp);
    cropCanvas.addEventListener("pointercancel", onCropPointerUp);
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && cropping) {
      event.preventDefault();
      cancelCrop();
    }
  });

  form.addEventListener("submit", (event) => {
    if (cropping) {
      event.preventDefault();
      setStatus("请先完成裁剪，或点取消重新选择照片。", true);
      return;
    }
    if (converting) {
      event.preventDefault();
      setStatus("照片还在转换，请稍等一下再点识别。", true);
    }
  });
})();
