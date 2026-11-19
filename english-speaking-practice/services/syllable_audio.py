"""Build accurate per-syllable clips from a naturally spoken whole word.

CosyVoice's CMU SSML is reliable inside a full word, but an isolated open
syllable such as ``B AH0`` is rendered like "bye" and ``N AE1`` like "nah".
The same syllables are correct in the full-word reading, so we keep the
already-approved Edge whole-word audio, ask Tencent SOE for its phone
timestamps, and cut the syllables out of that word.  The cut clips are then
also the source for the "syllables + whole word" sequence.

If ffmpeg or SOE phone timings are unavailable the caller falls back to the
previous CMU SSML path; this module does not make up timings.
"""

from __future__ import annotations

import array
import io
import shutil
import subprocess
import wave
from dataclasses import dataclass

from services.assessment import AssessmentError, get_assessor
from services.phonics import phonics_for_word

PLAYBACK_RATE = 24_000
ALIGNMENT_RATE = 16_000
FADE_MS = 8
EDGE_PAD_MS = 0
MIN_CLIP_MS = 80
SYLLABLE_PAUSE_MS = 300
FULL_WORD_PAUSE_MS = 500

# ARPAbet vowels (without stress digits) and the labels Tencent SOE uses for
# English phone timings.  Keeping these separate makes the fallback below
# readable and avoids treating consonants as syllable nuclei.
CMU_VOWELS = {
    "AA",
    "AE",
    "AH",
    "AO",
    "AW",
    "AY",
    "EH",
    "ER",
    "EY",
    "IH",
    "IY",
    "OW",
    "OY",
    "UH",
    "UW",
}
SOE_VOWELS = {
    "aa",
    "ae",
    "ah",
    "ao",
    "aw",
    "ay",
    "ax",
    "eh",
    "er",
    "ey",
    "ih",
    "ix",
    "iy",
    "ow",
    "oy",
    "uh",
    "uw",
}


class SyllableAudioError(Exception):
    """A user-safe failure while slicing a word into syllables."""


@dataclass(frozen=True)
class SyllableClip:
    index: int
    ipa: str
    phones: str
    pcm: bytes
    duration_ms: int

    @property
    def wav_bytes(self) -> bytes:
        return pcm_to_wav(self.pcm)


@dataclass(frozen=True)
class SlicedWord:
    clips: tuple[SyllableClip, ...]
    full_word_pcm: bytes
    duration_ms: int


def _ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise SyllableAudioError("服务器缺少 ffmpeg，暂时无法切分音节。")
    return path


def _decode_pcm(audio: bytes, rate: int) -> bytes:
    if not audio:
        raise SyllableAudioError("整词音频为空。")
    try:
        process = subprocess.run(
            [
                _ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                str(rate),
                "pipe:1",
            ],
            input=audio,
            capture_output=True,
            timeout=30,
        )
    except subprocess.SubprocessError as exc:
        raise SyllableAudioError("整词音频解码超时。") from exc
    if process.returncode != 0 or not process.stdout:
        raise SyllableAudioError("整词音频解码失败。")
    # ffmpeg emits signed 16-bit little-endian mono PCM.
    if len(process.stdout) % 2:
        raise SyllableAudioError("整词音频数据不完整。")
    return process.stdout


def pcm_to_wav(pcm: bytes, rate: int = PLAYBACK_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm)
    return buffer.getvalue()


def _duration_ms(pcm: bytes, rate: int = PLAYBACK_RATE) -> int:
    return max(1, round(len(pcm) / 2 * 1000 / rate))


def _slice_pcm(
    pcm: bytes,
    *,
    start_ms: int,
    end_ms: int,
    rate: int = PLAYBACK_RATE,
    pad_ms: int = EDGE_PAD_MS,
    fade_ms: int = FADE_MS,
) -> bytes:
    total_samples = len(pcm) // 2
    start = max(0, int(round((start_ms - pad_ms) * rate / 1000)))
    end = min(total_samples, int(round((end_ms + pad_ms) * rate / 1000)))
    if end <= start:
        raise SyllableAudioError("音节时间范围无效。")

    samples = array.array("h")
    samples.frombytes(pcm[start * 2 : end * 2])
    fade_samples = min(len(samples), max(1, int(round(fade_ms * rate / 1000))))
    for offset in range(fade_samples):
        factor = offset / fade_samples
        samples[offset] = int(samples[offset] * factor)
        samples[-1 - offset] = int(samples[-1 - offset] * factor)
    return samples.tobytes()


def _phone_spans(word: str, audio: bytes) -> list[tuple[str, int, int]]:
    """Return Tencent SOE (phone, start, end) timings in milliseconds."""
    wav_bytes = pcm_to_wav(
        _decode_pcm(audio, ALIGNMENT_RATE),
        rate=ALIGNMENT_RATE,
    )
    try:
        result = get_assessor().assess(word, wav_bytes)
    except AssessmentError as exc:
        raise SyllableAudioError(str(exc)) from exc
    except Exception as exc:
        raise SyllableAudioError("音节对齐失败。") from exc

    words = result.detail.get("words") or []
    if not words or not isinstance(words[0], dict):
        raise SyllableAudioError("评测服务没有返回音素时间轴。")
    phones = words[0].get("PhoneInfos") or []
    if not phones:
        raise SyllableAudioError("评测服务没有返回音素时间轴。")

    spans: list[tuple[str, int, int]] = []
    for phone in phones:
        try:
            label = str(phone.get("Phone") or "").strip().lower()
            start = int(phone["MemBeginTime"])
            end = int(phone["MemEndTime"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SyllableAudioError("评测服务返回的音素时间轴无效。") from exc
        if end <= start:
            raise SyllableAudioError("评测服务返回的音素时间轴无效。")
        spans.append((label, start, end))
    return spans


def _syllable_ranges(syllables, spans) -> list[tuple[int, int]]:
    """Return one (start, end) range per CMU syllable.

    The direct path groups the observed phones by the number of CMU phones in
    each syllable.  If SOE merges or splits a phone (common in reduced
    syllables such as "actually"), fall back to vowel nuclei: every English
    syllable has one, and the CMU coda count tells us how many observed phones
    after that nucleus belong to the syllable.
    """
    expected_counts = [len(item.phones.split()) for item in syllables]
    if sum(expected_counts) == len(spans):
        ranges = []
        cursor = 0
        for count in expected_counts:
            group = spans[cursor : cursor + count]
            cursor += count
            ranges.append((group[0][1], group[-1][2]))
        return ranges

    vowel_indexes: list[int] = []
    coda_counts: list[int] = []
    for syllable in syllables:
        phones = [phone.rstrip("012") for phone in syllable.phones.split()]
        candidates = [
            index
            for index, phone in enumerate(phones)
            if phone in CMU_VOWELS
        ]
        if not candidates:
            raise SyllableAudioError("音标音节缺少元音。")
        vowel_index = candidates[0]
        vowel_indexes.append(vowel_index)
        coda_counts.append(len(phones) - vowel_index - 1)

    observed_vowels = [
        index
        for index, (label, _start, _end) in enumerate(spans)
        if label in SOE_VOWELS
    ]
    if len(observed_vowels) != len(syllables):
        raise SyllableAudioError("音素时间轴与音标音节数量不一致。")

    ranges = []
    start = spans[0][1]
    for position, syllable in enumerate(syllables):
        observed = observed_vowels[position]
        coda = coda_counts[position]
        end_index = min(observed + coda, len(spans) - 1)
        # Do not cut into the next syllable's vowel.
        if position + 1 < len(observed_vowels):
            end_index = min(end_index, observed_vowels[position + 1] - 1)
        end = spans[end_index][2]
        if end <= start:
            raise SyllableAudioError("音节时间范围无效。")
        ranges.append((start, end))
        start = end
    return ranges


def slice_word_audio(word: str, accent: str, audio: bytes) -> SlicedWord:
    """Cut a naturally spoken word into the phonetic syllables shown in the UI.

    The SOE phone timestamps and the CMU syllable phone counts must line up.
    If they do not (for example an out-of-dictionary word), the caller should
    use the CMU SSML fallback rather than guessing a cut point.
    """
    phonics = phonics_for_word(word, accent)
    syllables = tuple(phonics.phonetic_syllables)
    if not syllables:
        raise SyllableAudioError("这个单词没有可用的音标音节。")

    spans = _phone_spans(phonics.normalized_word or word, audio)
    ranges = _syllable_ranges(syllables, spans)

    full_word_pcm = _decode_pcm(audio, PLAYBACK_RATE)
    full_duration = _duration_ms(full_word_pcm)
    clips: list[SyllableClip] = []
    for index, (syllable, (start, end)) in enumerate(
        zip(syllables, ranges, strict=True)
    ):
        if end - start < MIN_CLIP_MS:
            deficit = MIN_CLIP_MS - (end - start)
            start = max(0, start - deficit)
            if end - start < MIN_CLIP_MS:
                end = start + MIN_CLIP_MS
        if end <= start:
            raise SyllableAudioError("音节时间范围无效。")
        clip_pcm = _slice_pcm(
            full_word_pcm,
            start_ms=start,
            end_ms=end,
        )
        clips.append(
            SyllableClip(
                index=index,
                ipa=syllable.ipa,
                phones=syllable.phones,
                pcm=clip_pcm,
                duration_ms=_duration_ms(clip_pcm),
            )
        )

    return SlicedWord(
        clips=tuple(clips),
        full_word_pcm=full_word_pcm,
        duration_ms=full_duration,
    )


def build_sequence(sliced: SlicedWord) -> tuple[bytes, int]:
    """Concatenate syllable clips, then the original whole-word reading."""
    if not sliced.clips:
        raise SyllableAudioError("没有可用的音节。")
    silence = b"\x00\x00" * int(SYLLABLE_PAUSE_MS * PLAYBACK_RATE / 1000)
    full_word_pause = b"\x00\x00" * int(
        FULL_WORD_PAUSE_MS * PLAYBACK_RATE / 1000
    )
    parts: list[bytes] = []
    for index, clip in enumerate(sliced.clips):
        if index:
            parts.append(silence)
        parts.append(clip.pcm)
    parts.append(full_word_pause)
    parts.append(sliced.full_word_pcm)
    combined = b"".join(parts)
    return pcm_to_wav(combined), _duration_ms(combined)
