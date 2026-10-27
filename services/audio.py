"""Validated private audio storage and HTTP byte-range helpers."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import uuid
import wave

from django.conf import settings

TARGET_SAMPLE_RATE = 16_000
TARGET_CHANNELS = 1
TARGET_SAMPLE_WIDTH = 2
MAX_DURATION_SECONDS = 60
MIN_DURATION_SECONDS = 0.2
MAX_AUDIO_BYTES = 5 * 1024 * 1024
_ALLOWED_EXTENSIONS = {"wav", "mp3"}
_PURPOSES = {"recordings", "tts", "word_tts", "assessments"}


class AudioValidationError(ValueError):
    """Uploaded audio does not meet the project's narrow WAV contract."""


class RangeNotSatisfiable(ValueError):
    """The requested byte range cannot be served."""


def validate_recording_wav(
    data: bytes, *, max_duration_seconds: int = MAX_DURATION_SECONDS
) -> int:
    """Validate a browser recording and return its duration in milliseconds."""
    if not data:
        raise AudioValidationError("录音文件为空。")
    if len(data) > MAX_AUDIO_BYTES:
        raise AudioValidationError("录音文件太大，最大 5 MB。")

    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise AudioValidationError("录音必须是未压缩的 WAV。")
            if wav.getnchannels() != TARGET_CHANNELS:
                raise AudioValidationError("录音必须是单声道。")
            if wav.getsampwidth() != TARGET_SAMPLE_WIDTH:
                raise AudioValidationError("录音必须是 16 位 PCM。")
            if wav.getframerate() != TARGET_SAMPLE_RATE:
                raise AudioValidationError("录音采样率必须是 16 kHz。")
            frames = wav.getnframes()
            duration = frames / float(TARGET_SAMPLE_RATE)
    except AudioValidationError:
        raise
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioValidationError("无法识别这个音频文件。") from exc

    if duration < MIN_DURATION_SECONDS:
        raise AudioValidationError("录音太短，请至少朗读半秒钟。")
    if duration > max_duration_seconds:
        raise AudioValidationError(f"录音不能超过 {max_duration_seconds} 秒。")
    return int(round(duration * 1000))


def validate_assessment_wav(data: bytes) -> int:
    """Validate a short word-assessment recording (max 10 seconds)."""
    return validate_recording_wav(data, max_duration_seconds=10)


def _private_root() -> Path:
    root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def private_path(relative_path: str) -> Path:
    """Resolve a server-generated relative path without escaping the private root."""
    root = _private_root()
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Invalid private audio path")
    return candidate


def write_private_bytes(
    *,
    owner_id,
    purpose: str,
    data: bytes,
    extension: str,
) -> tuple[str, str, int]:
    """Write private audio and return (relative_path, sha256, byte_size)."""
    if purpose not in _PURPOSES:
        raise ValueError("Unknown audio purpose")
    extension = extension.lower().lstrip(".")
    if extension not in _ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported audio extension")

    directory = _private_root() / purpose / str(owner_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    filename = f"{uuid.uuid4().hex}.{extension}"
    path = directory / filename

    # O_EXCL prevents accidental overwrite, even though UUID collisions are negligible.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)
    relative = path.relative_to(_private_root()).as_posix()
    return relative, hashlib.sha256(data).hexdigest(), len(data)


def read_private_bytes(relative_path: str) -> bytes:
    return private_path(relative_path).read_bytes()


def remove_private_bytes(relative_path: str) -> None:
    try:
        private_path(relative_path).unlink(missing_ok=True)
    except (OSError, ValueError):
        # Cleanup must not make database deletion fail. The path is server-generated.
        pass


def parse_byte_range(range_header: str, size: int) -> tuple[int, int]:
    """Parse a single HTTP Range header and return inclusive start/end bytes."""
    if size <= 0:
        raise RangeNotSatisfiable("Empty audio")
    value = (range_header or "").strip()
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if match is None:
        raise RangeNotSatisfiable("Unsupported range")
    start_raw, end_raw = match.groups()
    if not start_raw and not end_raw:
        raise RangeNotSatisfiable("Empty range")

    if not start_raw:
        suffix = int(end_raw)
        if suffix <= 0:
            raise RangeNotSatisfiable("Invalid suffix range")
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(start_raw)
        if start >= size:
            raise RangeNotSatisfiable("Range starts after end of file")
        end = size - 1 if not end_raw else min(int(end_raw), size - 1)

    if end < start:
        raise RangeNotSatisfiable("Range end precedes start")
    return start, end
