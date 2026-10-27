"""TTS provider interface. M3 uses a clearly-labelled local mock only."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import math
import struct
import wave
from typing import Protocol

from django.conf import settings

MOCK_RATE = 16_000


class TTSError(Exception):
    """A user-safe TTS failure."""


@dataclass(frozen=True)
class TTSResult:
    data: bytes
    content_type: str
    extension: str
    duration_ms: int
    provider: str
    model: str
    voice: str
    style: str


class TTSProvider(Protocol):
    provider: str
    model: str
    voice: str

    def synthesize(self, text: str, *, speed: str, style: str) -> TTSResult: ...


class MockTTSProvider:
    """Generate a short, soft two-tone placeholder instead of fake speech."""

    provider = "mock"
    model = "mock"
    voice = "mock"

    def synthesize(self, text: str, *, speed: str, style: str) -> TTSResult:
        duration = min(4.0, max(0.8, len(text or "") * 0.025))
        if speed == "slow":
            duration = min(5.0, duration * 1.25)

        rate = MOCK_RATE
        total_frames = int(rate * duration)
        first_tone_start = 0.12
        first_tone_duration = 0.20
        second_tone_start = 0.48
        second_tone_duration = 0.18
        fade_time = 0.02
        frames = bytearray()

        def envelope(local: float, tone_duration: float) -> float:
            return max(
                0.0,
                min(1.0, local / fade_time, (tone_duration - local) / fade_time),
            )

        for index in range(total_frames):
            time_in_seconds = index / rate
            amplitude = 0.0
            if first_tone_start <= time_in_seconds < first_tone_start + first_tone_duration:
                local = time_in_seconds - first_tone_start
                amplitude = 0.10 * envelope(local, first_tone_duration) * math.sin(
                    2 * math.pi * 440 * local
                )
            elif second_tone_start <= time_in_seconds < second_tone_start + second_tone_duration:
                local = time_in_seconds - second_tone_start
                amplitude = 0.09 * envelope(local, second_tone_duration) * math.sin(
                    2 * math.pi * 554 * local
                )
            frames.extend(struct.pack("<h", int(32767 * amplitude)))

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(bytes(frames))

        return TTSResult(
            data=buffer.getvalue(),
            content_type="audio/wav",
            extension="wav",
            duration_ms=int(duration * 1000),
            provider=self.provider,
            model=self.model,
            voice=self.voice,
            style=style,
        )


def tts_cache_key(
    *,
    provider: str,
    model: str,
    voice: str,
    style: str,
    speed: str,
    text: str,
) -> str:
    material = "\x1f".join([provider, model, voice, style, speed, text])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get_tts_provider() -> TTSProvider:
    provider = settings.TTS_PROVIDER
    if provider == "mock":
        return MockTTSProvider()
    if provider == "volcengine":
        raise TTSError("真实情感语音尚未接入，当前只能使用模拟音频。")
    raise TTSError("语音服务配置错误，请联系管理员。")
