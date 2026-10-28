"""TTS provider interface with a mock default and a Volcengine adapter."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import io
import json
import math
import struct
import uuid
import wave
from typing import Protocol

import httpx
from django.conf import settings

MOCK_RATE = 16_000
VOLCENGINE_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
VOLCENGINE_END_CODE = 20_000_000
VOLCENGINE_SAMPLE_RATES = {8_000, 16_000, 22_050, 24_000, 32_000, 44_100, 48_000}


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
    timings: tuple[dict, ...] = ()


class TTSProvider(Protocol):
    provider: str
    model: str
    voice: str

    def speech_rate(self, speed: str) -> int: ...

    def synthesize(
        self,
        text: str,
        *,
        speed: str,
        style: str,
        context_text: str = "",
        enable_subtitles: bool = False,
    ) -> TTSResult: ...


class MockTTSProvider:
    """Generate a short, soft two-tone placeholder instead of fake speech."""

    provider = "mock"
    model = "mock"
    voice = "mock"

    def speech_rate(self, speed: str) -> int:
        return 0

    def synthesize(
        self,
        text: str,
        *,
        speed: str,
        style: str,
        context_text: str = "",
        enable_subtitles: bool = False,
    ) -> TTSResult:
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

        words = (text or "").split()
        timings: tuple[dict, ...] = ()
        if enable_subtitles and words:
            duration_ms = int(duration * 1000)
            step = max(1, duration_ms // len(words))
            timings = tuple(
                {
                    "word": word,
                    "start_ms": index * step,
                    "end_ms": (
                        duration_ms
                        if index == len(words) - 1
                        else (index + 1) * step
                    ),
                }
                for index, word in enumerate(words)
            )
        return TTSResult(
            data=buffer.getvalue(),
            content_type="audio/wav",
            extension="wav",
            duration_ms=int(duration * 1000),
            provider=self.provider,
            model=self.model,
            voice=self.voice,
            style=style,
            timings=timings,
        )


class VolcengineTTSProvider:
    """Volcengine Doubao TTS v3 over the HTTP SSE unidirectional endpoint.

    The service streams base64 PCM chunks. They are wrapped in a WAV container
    so the rest of the app keeps one audio format and can derive the duration
    from the PCM byte count.
    """

    provider = "volcengine"

    def __init__(
        self,
        *,
        api_key: str = "",
        app_id: str = "",
        access_token: str = "",
        resource_id: str,
        voice: str,
        sample_rate: int = 24_000,
        normal_speech_rate: int = 0,
        slow_speech_rate: int = -20,
        word_speech_rate: int = 0,
        client: httpx.Client | None = None,
    ):
        if sample_rate not in VOLCENGINE_SAMPLE_RATES:
            raise TTSError("语音采样率配置无效。")
        if resource_id.startswith("seed-tts-2.0") and not voice.endswith(
            "_uranus_bigtts"
        ):
            raise TTSError("音色与 2.0 资源不匹配：2.0 音色应以 _uranus_bigtts 结尾。")
        if resource_id.startswith("seed-tts-1.0") and voice.endswith(
            "_uranus_bigtts"
        ):
            raise TTSError("音色与 1.0 资源不匹配：1.0 资源不能使用 2.0 音色。")
        if not api_key and not (app_id and access_token):
            raise TTSError("语音服务凭据尚未配置。")
        self.api_key = api_key
        self.app_id = app_id
        self.access_token = access_token
        self.model = resource_id
        self.voice = voice
        self.sample_rate = sample_rate
        self.normal_speech_rate = normal_speech_rate
        self.slow_speech_rate = slow_speech_rate
        self.word_speech_rate = word_speech_rate
        self.endpoint = VOLCENGINE_ENDPOINT
        self._client = client

    def speech_rate(self, speed: str) -> int:
        if speed == "slow":
            return self.slow_speech_rate
        if speed == "word":
            return self.word_speech_rate
        return self.normal_speech_rate

    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {"X-Api-Key": self.api_key}
        return {
            "X-Api-App-Id": self.app_id,
            "X-Api-Access-Key": self.access_token,
        }

    def _request_payload(
        self,
        text: str,
        *,
        speed: str,
        style: str,
        context_text: str = "",
        enable_subtitles: bool = False,
    ) -> dict:
        audio_params = {
            "format": "pcm",
            "sample_rate": self.sample_rate,
            "speech_rate": self.speech_rate(speed),
            "loudness_rate": 0,
        }
        emotion = {
            "happy": "happy",
            "gentle": "pleased",
            "sad": "sad",
            "narrator": "narrator",
        }.get(style)
        if emotion is not None:
            audio_params["emotion"] = emotion
        if enable_subtitles:
            audio_params["enable_subtitle"] = True
        payload = {
            "user": {"uid": "family-english-diary"},
            "req_params": {
                "text": text,
                "speaker": self.voice,
                "audio_params": audio_params,
            },
        }
        if context_text:
            payload["req_params"]["additions"] = json.dumps(
                {
                    "explicit_language": "en",
                    "context_text": context_text,
                    "context_language": "en",
                }
            )
        return payload

    def _request_headers(self, request_id: str) -> dict[str, str]:
        return {
            "X-Api-Resource-Id": self.model,
            "X-Api-Request-Id": request_id,
            "X-Control-Require-Usage-Tokens-Return": "text_words",
            "Content-Type": "application/json",
            **self._auth_headers(),
        }

    @staticmethod
    def _parse_event(line: str) -> dict | None:
        line = line.strip()
        if not line or line.startswith(":") or line.startswith("event:"):
            return None
        if not line.startswith("data:"):
            return None
        raw = line[5:].strip()
        if not raw:
            return None
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return event if isinstance(event, dict) else None

    @staticmethod
    def _error_message(code, message: str) -> str:
        text = (message or "").lower()
        if "quota" in text or "concurrency" in text:
            return "语音服务额度或并发已用完，请稍后再试。"
        if "max limit" in text or "too long" in text:
            return "这句话太长，语音服务拒绝生成。"
        if code == 55_000_000 or "mismatch" in text:
            return "语音服务返回错误，请检查音色与资源版本是否匹配。"
        if "speaker" in text or "permission" in text or "access denied" in text:
            return "当前音色未获授权，请检查控制台音色配置。"
        return "语音服务生成失败，请稍后再试。"

    @staticmethod
    def _status_message(status_code: int) -> str:
        if status_code in (401, 403):
            return "语音服务鉴权失败，请检查凭据。"
        if status_code == 429:
            return "语音服务请求过于频繁，请稍后再试。"
        if status_code >= 500:
            return "语音服务暂时不可用，请稍后再试。"
        return f"语音服务返回错误（{status_code}），请稍后再试。"

    def _wrap_pcm_as_wav(self, pcm: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm)
        return buffer.getvalue()

    def _request(
        self,
        client: httpx.Client,
        text: str,
        *,
        speed: str,
        style: str,
        context_text: str = "",
        enable_subtitles: bool = False,
    ) -> TTSResult:
        request_id = str(uuid.uuid4())
        payload = self._request_payload(
            text,
            speed=speed,
            style=style,
            context_text=context_text,
            enable_subtitles=enable_subtitles,
        )
        headers = self._request_headers(request_id)
        chunks: list[bytes] = []
        timings: list[dict] = []

        try:
            with client.stream(
                "POST",
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=httpx.Timeout(60.0, connect=10.0),
            ) as response:
                if response.status_code != 200:
                    raise TTSError(self._status_message(response.status_code))

                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    response.read()
                    try:
                        error = response.json()
                    except ValueError:
                        error = {}
                    code = error.get("code") if isinstance(error, dict) else None
                    message = (
                        str(error.get("message", "")) if isinstance(error, dict) else ""
                    )
                    raise TTSError(self._error_message(code, message))

                for line in response.iter_lines():
                    event = self._parse_event(line)
                    if event is None:
                        continue

                    if enable_subtitles:
                        sentence = event.get("sentence")
                        if isinstance(sentence, dict):
                            for item in sentence.get("words") or []:
                                if not isinstance(item, dict):
                                    continue
                                word = item.get("word")
                                try:
                                    start_ms = int(
                                        round(float(item["startTime"]) * 1000)
                                    )
                                    end_ms = int(
                                        round(float(item["endTime"]) * 1000)
                                    )
                                except (KeyError, TypeError, ValueError):
                                    continue
                                if isinstance(word, str) and word:
                                    timings.append(
                                        {
                                            "word": word,
                                            "start_ms": start_ms,
                                            "end_ms": end_ms,
                                        }
                                    )

                    code = event.get("code", 0)
                    if code == VOLCENGINE_END_CODE:
                        if enable_subtitles:
                            continue
                        break
                    if code != 0:
                        raise TTSError(
                            self._error_message(code, str(event.get("message", "")))
                        )
                    audio = event.get("data")
                    if isinstance(audio, str) and audio:
                        chunks.append(base64.b64decode(audio))
        except httpx.TimeoutException as exc:
            raise TTSError("语音服务响应超时，请稍后再试。") from exc
        except httpx.HTTPError as exc:
            raise TTSError("暂时无法连接语音服务，请检查网络后再试。") from exc
        except (ValueError, binascii.Error) as exc:
            raise TTSError("语音服务返回了无法识别的内容，请稍后再试。") from exc

        if not chunks:
            raise TTSError("语音服务没有返回音频，请稍后再试。")
        pcm = b"".join(chunks)
        if len(pcm) < 2:
            raise TTSError("语音服务返回的音频无效，请稍后再试。")
        return TTSResult(
            data=self._wrap_pcm_as_wav(pcm),
            content_type="audio/wav",
            extension="wav",
            duration_ms=max(1, int(len(pcm) / (self.sample_rate * 2) * 1000)),
            provider=self.provider,
            model=self.model,
            voice=self.voice,
            style=style,
            timings=tuple(timings),
        )

    def synthesize(
        self,
        text: str,
        *,
        speed: str,
        style: str,
        context_text: str = "",
        enable_subtitles: bool = False,
    ) -> TTSResult:
        if self._client is not None:
            return self._request(
                self._client,
                text,
                speed=speed,
                style=style,
                context_text=context_text,
                enable_subtitles=enable_subtitles,
            )
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                return self._request(
                    client,
                    text,
                    speed=speed,
                    style=style,
                    context_text=context_text,
                    enable_subtitles=enable_subtitles,
                )
        except httpx.HTTPError as exc:
            raise TTSError("暂时无法连接语音服务，请检查网络后再试。") from exc


WORD_TTS_CONTEXTS = {
    "i'm": "I'm going home now.",
    "they": "They are my friends.",
}


def word_tts_context(word: str) -> str:
    """Return a carrier sentence for words the isolated-word voice misreads."""
    normalized = (word or "").strip().lower().replace("’", "'")
    return WORD_TTS_CONTEXTS.get(normalized, "")


def tts_cache_key(
    *,
    provider: str,
    model: str,
    voice: str,
    style: str,
    speed: str,
    rate: int,
    text: str,
    context: str = "",
) -> str:
    parts = [provider, model, voice, style, speed, str(rate), text]
    if context:
        parts.append(context)
    material = "\x1f".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get_tts_provider() -> TTSProvider:
    provider = settings.TTS_PROVIDER
    if provider == "mock":
        return MockTTSProvider()
    if provider == "volcengine":
        if not settings.VOLCENGINE_TTS_VOICE:
            raise TTSError("真实语音尚未配置音色（VOLCENGINE_TTS_VOICE）。")
        if not settings.VOLCENGINE_API_KEY and not (
            settings.VOLCENGINE_APP_ID and settings.VOLCENGINE_ACCESS_TOKEN
        ):
            raise TTSError("语音服务凭据尚未配置。")
        return VolcengineTTSProvider(
            api_key=settings.VOLCENGINE_API_KEY,
            app_id=settings.VOLCENGINE_APP_ID,
            access_token=settings.VOLCENGINE_ACCESS_TOKEN,
            resource_id=settings.VOLCENGINE_RESOURCE_ID,
            voice=settings.VOLCENGINE_TTS_VOICE,
            sample_rate=settings.VOLCENGINE_TTS_SAMPLE_RATE,
            normal_speech_rate=settings.VOLCENGINE_TTS_NORMAL_SPEECH_RATE,
            slow_speech_rate=settings.VOLCENGINE_TTS_SLOW_SPEECH_RATE,
            word_speech_rate=settings.VOLCENGINE_TTS_WORD_SPEECH_RATE,
        )
    raise TTSError("语音服务配置错误，请联系管理员。")
