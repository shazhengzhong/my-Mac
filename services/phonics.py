"""Syllable and phoneme breakdown data plus the local phoneme demo voice.

The natural Volcengine voice does not accept isolated phoneme input on the 2.0
voices. For the phonics demonstration we use the human IPA phoneme recordings
under ``data/phonemes`` (Wikimedia Commons; see CREDITS.md). Syllables and the
normal word audio still use the natural Volcengine voice.
"""

from __future__ import annotations

from dataclasses import dataclass
from array import array
import io
from functools import lru_cache
from pathlib import Path
import wave

from services.pronunciation import (
    accent_label,
    ipa_for_word,
    normalize_word,
    syllable_hint,
)


class PhonicsError(Exception):
    """A user-safe phonics demonstration failure."""


@dataclass(frozen=True)
class PhonicsData:
    display_word: str
    normalized_word: str
    syllables: tuple[str, ...]
    ipa: str
    phonemes: tuple[str, ...]
    accent: str

    @property
    def accent_label(self) -> str:
        return accent_label(self.accent)


_MULTI_PHONEMES = (
    "tʃ",
    "dʒ",
    "aɪ",
    "aʊ",
    "eɪ",
    "oʊ",
    "əʊ",
    "ɔɪ",
    "ɪə",
    "eə",
    "ɛə",
    "ʊə",
    "ɑː",
    "ɔː",
    "ɜː",
    "iː",
    "uː",
    "ər",
    "ɜr",
    "ɑr",
    "ɔr",
    "ɪr",
    "ɛr",
    "ʊr",
)
_STRESS_MARKS = set("ˈˌ")
_PHONEME_DIR = Path(__file__).resolve().parent / "data" / "phonemes"
_HUMAN_GAP_MS = 80
_HUMAN_MAX_SECONDS = 0.55
_HUMAN_CROSSFADE_MS = 35
HUMAN_VOICE = "human-commons-ipa"


def syllables_for_word(display_word: str) -> tuple[str, ...]:
    """Return written syllables, or the whole word when no split is useful."""
    word = (display_word or "").strip()
    if not word:
        return ()
    hinted = syllable_hint(word)
    if "·" in hinted:
        parts = tuple(part for part in hinted.split("·") if part)
        if parts and "".join(parts) == word:
            return parts
    return (word,)


def phonemes_for_ipa(ipa: str) -> tuple[str, ...]:
    """Split a broad IPA string into displayable phoneme symbols."""
    cleaned = (ipa or "").strip().strip("/").strip()
    if not cleaned:
        return ()
    cleaned = "".join(
        char for char in cleaned if char not in _STRESS_MARKS
    )
    symbols: list[str] = []
    index = 0
    ordered = sorted(_MULTI_PHONEMES, key=len, reverse=True)
    while index < len(cleaned):
        match = next(
            (candidate for candidate in ordered if cleaned.startswith(candidate, index)),
            None,
        )
        if match:
            symbols.append(match)
            index += len(match)
            continue
        char = cleaned[index]
        if char not in {" ", "/", "ː"}:
            symbols.append(char)
        index += 1
    return tuple(symbols)


def phonics_for_word(display_word: str, accent: str = "us") -> PhonicsData:
    normalized = normalize_word(display_word)
    ipa = ipa_for_word(normalized, accent) or ""
    return PhonicsData(
        display_word=(display_word or "").strip(),
        normalized_word=normalized,
        syllables=syllables_for_word(display_word),
        ipa=ipa,
        phonemes=phonemes_for_ipa(ipa),
        accent=accent if accent in {"us", "uk"} else "us",
    )


def syllable_audio_text(data: PhonicsData) -> str:
    """Natural-voice text: syllables with pauses, then the whole word."""
    parts = [part for part in data.syllables if part]
    if len(parts) == 1 and parts[0].lower() == data.display_word.lower():
        return f"{parts[0]}."
    parts.append(data.display_word)
    return ". ".join(part for part in parts if part) + "."


# Base recordings from the human IPA library. Rhotic/diphthong tokens are
# composed from these at runtime.
_HUMAN_BASE = {
    "p": "voiceless-bilabial-plosive.wav",
    "b": "voiced-bilabial-plosive.wav",
    "t": "voiceless-alveolar-plosive.wav",
    "d": "voiced-alveolar-plosive.wav",
    "tʃ": "voiceless-palato-alveolar-affricate.wav",
    "dʒ": "voiced-palato-alveolar-affricate.wav",
    "k": "voiceless-velar-plosive.wav",
    "g": "voiced-velar-plosive.wav",
    "ɡ": "voiced-velar-plosive.wav",
    "f": "voiceless-labiodental-fricative.wav",
    "v": "voiced-labiodental-fricative.wav",
    "θ": "voiceless-dental-fricative.wav",
    "ð": "voiced-dental-fricative.wav",
    "s": "voiceless-alveolar-sibilant.wav",
    "z": "voiced-alveolar-sibilant.wav",
    "ʃ": "voiceless-palato-alveolar-sibilant.wav",
    "ʒ": "voiced-palato-alveolar-sibilant.wav",
    "h": "voiceless-glottal-fricative.wav",
    "m": "bilabial-nasal.wav",
    "n": "alveolar-nasal.wav",
    "ŋ": "velar-nasal.wav",
    "l": "alveolar-lateral-approximant.wav",
    "ɫ": "alveolar-lateral-approximant.wav",
    "r": "alveolar-approximant.wav",
    "ɹ": "alveolar-approximant.wav",
    "ɾ": "voiced-alveolar-plosive.wav",
    "w": "voiced-labio-velar-approximant.wav",
    "j": "palatal-approximant.wav",
    "i": "close-front-unrounded-vowel.wav",
    "iː": "close-front-unrounded-vowel.wav",
    "ɪ": "near-close-near-front-unrounded-vowel.wav",
    "e": "open-mid-front-unrounded-vowel.wav",
    "ɛ": "open-mid-front-unrounded-vowel.wav",
    "æ": "near-open-front-unrounded-vowel.wav",
    "ʌ": "open-mid-back-unrounded-vowel.wav",
    "ɑ": "open-back-unrounded-vowel.wav",
    "ɑː": "open-back-unrounded-vowel.wav",
    "ɒ": "open-back-rounded-vowel.wav",
    "ɔ": "open-mid-back-rounded-vowel.wav",
    "ɔː": "open-mid-back-rounded-vowel.wav",
    "ʊ": "near-close-near-back-rounded-vowel.wav",
    "u": "close-back-rounded-vowel.wav",
    "uː": "close-back-rounded-vowel.wav",
    "ɜː": "open-mid-central-unrounded-vowel.wav",
    "ɝ": "open-mid-central-unrounded-vowel.wav",
    "ɝː": "open-mid-central-unrounded-vowel.wav",
    "ə": "mid-central-vowel.wav",
    "ɚ": "mid-central-vowel.wav",
}
_HUMAN_COMPOSITE = {
    "eɪ": ("e", "ɪ"),
    "aɪ": ("æ", "ɪ"),
    "aʊ": ("æ", "ʊ"),
    "oʊ": ("ə", "ʊ"),
    "əʊ": ("ə", "ʊ"),
    "ɔɪ": ("ɔː", "ɪ"),
    "ɪə": ("ɪ", "ə"),
    "eə": ("e", "ə"),
    "ɛə": ("e", "ə"),
    "ʊə": ("ʊ", "ə"),
    "ɑr": ("ɑː", "r"),
    "ɔr": ("ɔː", "r"),
    "ɜr": ("ɜː", "r"),
    "ər": ("ə", "r"),
    "ɪr": ("ɪ", "r"),
    "ɛr": ("e", "r"),
    "ʊr": ("ʊ", "r"),
}


@lru_cache(maxsize=128)
def _load_human_samples(filename: str) -> tuple[array, int]:
    path = _PHONEME_DIR / filename
    if not path.exists():
        raise PhonicsError("真人音素库缺少这个音的录音。")
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise PhonicsError("真人音素录音格式不支持。")
            samples = array("h")
            samples.frombytes(audio.readframes(audio.getnframes()))
            rate = audio.getframerate()
    except (wave.Error, EOFError) as exc:
        raise PhonicsError("真人音素录音读取失败。") from exc
    return samples, rate


def _cap_samples(samples: array, rate: int) -> array:
    limit = max(1, int(rate * _HUMAN_MAX_SECONDS))
    samples = array("h", samples[:limit])
    fade = max(1, int(rate * 0.01))
    if len(samples) > fade:
        for index in range(fade):
            factor = (len(samples) - 1 - (len(samples) - fade + index)) / fade
            samples[len(samples) - fade + index] = int(
                samples[len(samples) - fade + index] * factor
            )
    return samples


def _crossfade(first: array, second: array, rate: int) -> array:
    fade = min(
        len(first),
        len(second),
        max(1, int(rate * _HUMAN_CROSSFADE_MS / 1000)),
    )
    if fade <= 0:
        return first + second
    output = array("h", first[:-fade])
    for index in range(fade):
        blend = (index + 1) / fade
        output.append(
            int(first[-fade + index] * (1 - blend) + second[index] * blend)
        )
    output.extend(second[fade:])
    return output


@lru_cache(maxsize=128)
def _human_phoneme_audio(phoneme: str) -> tuple[bytes, int]:
    if phoneme in _HUMAN_COMPOSITE:
        parts = _HUMAN_COMPOSITE[phoneme]
        first, rate = _load_human_samples(_HUMAN_BASE[parts[0]])
        second, second_rate = _load_human_samples(_HUMAN_BASE[parts[1]])
        if rate != second_rate:
            raise PhonicsError("真人音素录音采样率不一致。")
        samples = _crossfade(_cap_samples(first, rate), _cap_samples(second, rate), rate)
    else:
        filename = _HUMAN_BASE.get(phoneme)
        if not filename:
            raise PhonicsError("这个单词含有暂不支持的音素，无法生成真人示范音。")
        samples, rate = _load_human_samples(filename)
        samples = _cap_samples(samples, rate)
    return samples.tobytes(), rate


def generate_phoneme_audio(data: PhonicsData) -> tuple[bytes, str, int]:
    """Build a WAV from the human phoneme recordings.

    Returns ``(wav_bytes, voice_label, duration_ms)``. The caller appends the
    natural whole-word audio afterwards.
    """
    if not data.phonemes:
        raise PhonicsError("这个单词还没有音素数据。")
    chunks: list[bytes] = []
    sample_rate = 22050
    for phoneme in data.phonemes:
        audio, rate = _human_phoneme_audio(phoneme)
        sample_rate = rate
        chunks.append(audio)
        chunks.append(b"\x00" * int(rate * _HUMAN_GAP_MS / 1000) * 2)
    pcm = b"".join(chunks)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)
    duration_ms = int(len(pcm) / (sample_rate * 2) * 1000)
    return buffer.getvalue(), HUMAN_VOICE, max(1, duration_ms)
