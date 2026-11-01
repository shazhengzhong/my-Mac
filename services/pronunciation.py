"""Deterministic word-level American and British IPA generation.

American IPA comes from CMUdict via syllabify. British IPA comes from the MIT
licensed Britfone RP dictionary bundled in ``services/data``. The output is
broad word-level IPA for display and practice; it does not attempt
connected-speech transcription (linking, flapping, reductions).
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

import pyphen
from syllabify import syllabify

_PYPHEN = pyphen.Pyphen(lang="en_US")
_BRITFONE_PATH = (
    Path(__file__).resolve().parent / "data" / "britfone.main.3.0.1.csv"
)

_WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
MAX_IPA_LENGTH = 120
ACCENT_LABELS = {"us": "美式", "uk": "英式"}
_IPA_VOWELS = set("aeiouæɑɒɔəɜɪʊʌɐɚ")

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


def accent_label(accent: str) -> str:
    return ACCENT_LABELS.get(accent, ACCENT_LABELS["us"])


def _normalize_british_ipa(raw: str) -> str:
    """Turn Britfone's strict phoneme spacing into learner-facing IPA.

    Britfone attaches stress marks to the stressed vowel and uses ɹ/ɐ/ɛ.
    Learners expect the stress mark at the start of the stressed syllable and
    the more familiar r/ʌ/e symbols.
    """
    ipa = raw.replace(" ", "").translate(
        str.maketrans({"ɹ": "r", "ɐ": "ʌ", "ɛ": "e"})
    )
    output: list[str] = []
    for char in ipa:
        if char not in "ˈˌ":
            output.append(char)
            continue
        previous_vowel = None
        for index, value in enumerate(output):
            if value in _IPA_VOWELS:
                previous_vowel = index
        if previous_vowel is None:
            position = 0
        else:
            position = previous_vowel + 1
            while position < len(output) and output[position] == "ː":
                position += 1
        output.insert(position, char)
    return "".join(output)


@lru_cache(maxsize=1)
def _britfone() -> dict[str, str]:
    entries: dict[str, str] = {}
    if not _BRITFONE_PATH.exists():
        return entries
    with _BRITFONE_PATH.open(encoding="utf-8") as dictionary:
        for line in dictionary:
            if "," not in line:
                continue
            word, raw_ipa = line.split(",", 1)
            word = normalize_word(word.split("(", 1)[0])
            word = word.replace("_", " ")
            if not word or " " in word or not raw_ipa.strip():
                continue
            entries.setdefault(
                word,
                _normalize_british_ipa(raw_ipa.strip()),
            )
    return entries


@lru_cache(maxsize=100_000)
def ipa_for_word(normalized_word: str, accent: str = "us") -> str | None:
    """Return broad IPA without surrounding slashes, or None."""
    normalized_word = normalize_word(normalized_word)
    if not normalized_word:
        return None
    if accent == "uk":
        return _britfone().get(normalized_word)
    if accent != "us":
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


@lru_cache(maxsize=100_000)
def syllable_hint(word: str) -> str:
    """Return a written syllable split such as ``com·fort·able``.

    One-syllable words and words the dictionary cannot split return an empty
    string so the UI does not repeat the whole word.
    """
    cleaned = (word or "").strip()
    if not cleaned or len(cleaned) < 4:
        return ""
    try:
        hinted = _PYPHEN.inserted(cleaned, "·")
    except (ValueError, KeyError):
        return ""
    return hinted if "·" in hinted else ""


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
