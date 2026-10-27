"""Deterministic CMUdict-based word-level American IPA generation.

The output is broad word-level IPA for display and practice. It intentionally
does not attempt connected-speech transcription (linking, flapping, reductions).
"""

from dataclasses import dataclass
from functools import lru_cache
import re

from syllabify import syllabify

_WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
MAX_IPA_LENGTH = 120

_ARPABET_TO_IPA = {
    "AA": "ɑ",
    "AE": "æ",
    "AO": "ɔ",
    "AW": "aʊ",
    "AY": "aɪ",
    "B": "b",
    "CH": "tʃ",
    "D": "d",
    "DH": "ð",
    "EH": "ɛ",
    "EY": "eɪ",
    "F": "f",
    "G": "g",
    "HH": "h",
    "IH": "ɪ",
    "IY": "i",
    "JH": "dʒ",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "NG": "ŋ",
    "OW": "oʊ",
    "OY": "ɔɪ",
    "P": "p",
    "R": "r",
    "S": "s",
    "SH": "ʃ",
    "T": "t",
    "TH": "θ",
    "UH": "ʊ",
    "UW": "u",
    "V": "v",
    "W": "w",
    "Y": "j",
    "Z": "z",
    "ZH": "ʒ",
    "AX": "ə",
    "AXR": "ɚ",
}
_STRESS_MARKS = {"1": "ˈ", "2": "ˌ"}


@dataclass(frozen=True)
class WordPronunciation:
    surface: str
    normalized: str
    ipa: str
    source: str


def normalize_word(word: str) -> str:
    return (word or "").strip().lower().replace("’", "'")


@lru_cache(maxsize=100_000)
def ipa_for_word(normalized_word: str) -> str | None:
    """Return broad American IPA without surrounding slashes, or None."""
    if not normalized_word:
        return None
    try:
        parsed = syllabify(normalized_word)
    except (ValueError, KeyError, IndexError):
        return None

    syllables_out: list[str] = []
    try:
        for word in parsed.words:
            for syllable in word.syllables:
                stress = str(getattr(syllable, "stress", "0"))
                prefix = _STRESS_MARKS.get(stress, "")
                phoneme_parts: list[str] = []
                for phoneme in syllable.phonemes:
                    symbol = getattr(phoneme, "phoneme", None)
                    if symbol is None:
                        return None
                    if symbol == "AH":
                        part = "ə" if stress == "0" else "ʌ"
                    elif symbol == "ER":
                        part = "ər" if stress == "0" else "ɜr"
                    else:
                        part = _ARPABET_TO_IPA.get(symbol)
                    if part is None:
                        return None
                    phoneme_parts.append(part)
                syllables_out.append(prefix + "".join(phoneme_parts))
    except (AttributeError, TypeError):
        return None

    result = "".join(syllables_out).strip()
    return result or None


def tokenize_words(text: str) -> list[str]:
    """Extract English word tokens in display order, excluding punctuation."""
    return [match.group(0) for match in _WORD_RE.finditer(text or "")]


def analyze_sentence(text: str) -> list[WordPronunciation]:
    """Analyze each English word; unknown dictionary words are explicitly marked."""
    tokens: list[WordPronunciation] = []
    for surface in tokenize_words(text):
        normalized = normalize_word(surface)
        ipa = ipa_for_word(normalized)
        tokens.append(
            WordPronunciation(
                surface=surface,
                normalized=normalized,
                ipa=ipa or "",
                source="dictionary" if ipa else "unknown",
            )
        )
    return tokens


def clean_manual_ipa(value: str) -> str:
    """Normalize a user-entered IPA value, rejecting unsafe control characters."""
    cleaned = (value or "").strip().strip("/").strip()
    if not cleaned:
        return ""
    if len(cleaned) > MAX_IPA_LENGTH:
        raise ValueError(f"音标不能超过 {MAX_IPA_LENGTH} 个字符。")
    if re.search(r"[\x00-\x1f\x7f<>]", cleaned):
        raise ValueError("音标包含不支持的字符。")
    return cleaned
