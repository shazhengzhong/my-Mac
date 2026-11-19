"""Microsoft Edge neural TTS used only for isolated word pronunciation.

This is intentionally separate from the sentence/full-diary TTS provider.
Edge TTS is an online service and is not an official Azure SLA endpoint; audio
is cached per word by the caller, with the normal TTS provider as fallback.
"""

from __future__ import annotations

import asyncio

try:
    import edge_tts as _edge_tts
except ImportError:  # pragma: no cover - exercised only when the optional package is absent
    _edge_tts = None

from .tts import TTSError, TTSResult


class EdgeTTSProvider:
    """Small synchronous adapter around edge-tts for one-word synthesis."""

    provider = "edge_tts"
    model = "edge-tts"

    def __init__(self, *, voice: str, timeout: int = 30):
        if _edge_tts is None:
            raise TTSError("Microsoft 单词发音组件尚未安装，请稍后再试。")
        if not (voice or "").strip():
            raise TTSError("Microsoft 单词发音音色尚未配置。")
        self.voice = voice.strip()
        self.timeout = timeout

    def speech_rate(self, speed: str) -> int:
        return 100

    def synthesize(
        self,
        text: str,
        *,
        speed: str,
        style: str,
        context_text: str = "",
        enable_subtitles: bool = False,
    ) -> TTSResult:
        if not (text or "").strip():
            raise TTSError("没有可朗读的文字。")

        async def collect() -> tuple[bytes, int]:
            chunks: list[bytes] = []
            duration_ms = 0
            communicate = _edge_tts.Communicate(
                text.strip(),
                self.voice,
                rate="+0%",
                volume="+0%",
                boundary="WordBoundary",
                connect_timeout=self.timeout,
                receive_timeout=self.timeout,
            )
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
                elif chunk.get("type") == "WordBoundary":
                    # Edge reports 100-nanosecond ticks.
                    offset = int(chunk.get("offset") or 0)
                    duration = int(chunk.get("duration") or 0)
                    duration_ms = max(
                        duration_ms, (offset + duration) // 10_000
                    )
            return b"".join(chunks), duration_ms

        try:
            audio, duration_ms = asyncio.run(collect())
        except Exception as exc:
            raise TTSError(
                "Microsoft 单词发音暂时不可用，请稍后再试。"
            ) from exc
        if not audio:
            raise TTSError("Microsoft 单词发音没有返回音频，请稍后再试。")

        return TTSResult(
            data=audio,
            content_type="audio/mpeg",
            extension="mp3",
            duration_ms=duration_ms,
            provider=self.provider,
            model=self.model,
            voice=self.voice,
            style=style,
        )
