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
_MOBY_PATH = (
    Path(__file__).resolve().parent / "data" / "moby-hyphenation.txt"
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
_ARPABET_VOWELS = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER",
    "EY", "IH", "IY", "OW", "OY", "UH", "UW",
}


@dataclass(frozen=True)
class PhoneticSyllable:
    """One CMU-derived syllable, used for the phonetic syllable row."""

    ipa: str
    phones: str
    stressed: bool


@lru_cache(maxsize=1)
def _moby_entries() -> dict[str, tuple[tuple[str, ...], ...]]:
    """Load Moby's public-domain written hyphenation data.

    Moby stores alternate hyphenations for some words.  We keep all candidates
    and choose a balanced, lower-case split later.
    """
    entries: dict[str, tuple[tuple[str, ...], ...]] = {}
    if not _MOBY_PATH.exists():
        return entries
    with _MOBY_PATH.open(encoding="latin-1") as handle:
        for raw_line in handle:
            line = raw_line.strip("\r\n")
            if not line or " " in line or "\xa5" not in line:
                continue
            parts = tuple(part for part in line.split("\xa5") if part)
            word = "".join(parts)
            if not word or not re.fullmatch(r"[A-Za-z][A-Za-z'’-]*", word):
                continue
            key = word.lower().replace("’", "'")
            entries.setdefault(key, ())
            entries[key] += (parts,)
    return entries


def written_syllables(word: str) -> tuple[str, ...]:
    """Return balanced written syllables, preferring Moby over hyphenation.

    The original casing is preserved by slicing the input word using the
    lengths from the chosen dictionary entry.
    """
    cleaned = (word or "").strip()
    if not cleaned:
        return ()
    key = cleaned.lower().replace("’", "'")
    candidates = _moby_entries().get(key, ())
    if candidates:
        def score(parts: tuple[str, ...]) -> tuple:
            lengths = [len(part) for part in parts]
            mean = sum(lengths) / len(lengths)
            variance = sum((length - mean) ** 2 for length in lengths)
            # Prefer lower-case entries, then balanced lengths.
            return (0 if "".join(parts).islower() else 1, variance, -len(parts))

        parts = min(candidates, key=score)
        lengths = [len(part) for part in parts]
        result = []
        cursor = 0
        for length in lengths:
            result.append(cleaned[cursor : cursor + length])
            cursor += length
        if cursor == len(cleaned) and all(result):
            return tuple(result)

    hinted = syllable_hint(cleaned)
    if "·" in hinted:
        parts = tuple(part for part in hinted.split("·") if part)
        if parts and "".join(parts) == cleaned:
            return parts
    return (cleaned,)


_IPA_VOWEL_SYMBOLS = set("aeiouæɑɒɔəɛɜɪʊʌɐɚɝɞɘɵɨʉɤɯ")
_IPA_VOWEL_GROUPS = (
    "eɪ",
    "aɪ",
    "ɔɪ",
    "aʊ",
    "oʊ",
    "əʊ",
    "ɪə",
    "eə",
    "ɛə",
    "ʊə",
    "ər",
    "ɜr",
    "ɑr",
    "ɔr",
    "ɪr",
    "ɛr",
    "ʊr",
)


def _ipa_syllable_count(ipa: str) -> int:
    """Count vowel nuclei in broad IPA, treating diphthongs as one."""
    cleaned = "".join(
        char
        for char in (ipa or "")
        if char not in "ˈˌ/ " and char != "ː"
    )
    groups = sorted(_IPA_VOWEL_GROUPS, key=len, reverse=True)
    count = 0
    index = 0
    while index < len(cleaned):
        match = next(
            (group for group in groups if cleaned.startswith(group, index)),
            None,
        )
        if match:
            count += 1
            index += len(match)
            continue
        if cleaned[index] in _IPA_VOWEL_SYMBOLS:
            count += 1
        index += 1
    return count


def display_ipa(ipa: str) -> str:
    """Return learner-facing IPA without stress marks on one-syllable words.

    CMUdict and Britfone store primary stress on monosyllables (``N EY1 M D``),
    but dictionaries conventionally omit the stress mark when there is only
    one syllable to stress: ``/neɪmd/`` rather than ``/ˈneɪmd/``.
    """
    value = (ipa or "").strip()
    if not value:
        return ""
    if _ipa_syllable_count(value) == 1:
        return value.replace("ˈ", "").replace("ˌ", "")
    return value


def _ipa_from_cmu_phones(phones: list[str]) -> str:
    prefix = ""
    parts: list[str] = []
    for token in phones:
        match = re.fullmatch(r"([A-Z]+)([012])?", token)
        if not match:
            return ""
        symbol, stress_text = match.groups()
        if symbol in _ARPABET_VOWELS:
            stress = int(stress_text or 0)
            if stress in (1, 2) and not prefix:
                prefix = _STRESS_MARKS[str(stress)]
            if symbol == "AH":
                parts.append("ə" if stress == 0 else "ʌ")
            elif symbol == "ER":
                parts.append("ər" if stress == 0 else "ɜr")
            else:
                mapped = _ARPABET_TO_IPA.get(symbol)
                if mapped is None:
                    return ""
                parts.append(mapped)
        else:
            mapped = _ARPABET_TO_IPA.get(symbol)
            if mapped is None:
                return ""
            parts.append(mapped)
    return prefix + "".join(parts)


@lru_cache(maxsize=100_000)
def phonetic_syllables_for_word(
    word: str, accent: str = "us"
) -> tuple[PhoneticSyllable, ...]:
    """Return CMU phonetic syllables with stress marks.

    British IPA currently has no phonetic syllable boundary data, so the
    phonetic row is US-only; UK callers fall back to the written row.
    """
    if accent != "us":
        return ()
    normalized = normalize_word(word)
    if not normalized:
        return ()
    try:
        parsed = syllabify(normalized)
    except (ValueError, KeyError, IndexError):
        return ()

    syllables: list[PhoneticSyllable] = []
    try:
        for parsed_word in parsed.words:
            for syllable in parsed_word.syllables:
                stress = int(getattr(syllable, "stress", 0) or 0)
                prefix = _STRESS_MARKS.get(str(stress), "")
                phones: list[str] = []
                ipa_parts: list[str] = []
                for part in (syllable.onset, syllable.nucleus, syllable.coda):
                    for phoneme in part:
                        symbol = getattr(phoneme, "phoneme", None)
                        if not symbol:
                            continue
                        if symbol in _ARPABET_VOWELS:
                            vowel_stress = int(
                                getattr(phoneme, "stress", 0) or 0
                            )
                            phones.append(f"{symbol}{vowel_stress}")
                            if symbol == "AH":
                                ipa_parts.append(
                                    "ə" if vowel_stress == 0 else "ʌ"
                                )
                            elif symbol == "ER":
                                ipa_parts.append(
                                    "ər" if vowel_stress == 0 else "ɜr"
                                )
                            else:
                                mapped = _ARPABET_TO_IPA.get(symbol)
                                if mapped is None:
                                    return ()
                                ipa_parts.append(mapped)
                        else:
                            phones.append(symbol)
                            mapped = _ARPABET_TO_IPA.get(symbol)
                            if mapped is None:
                                return ()
                            ipa_parts.append(mapped)
                syllables.append(
                    PhoneticSyllable(
                        ipa=prefix + "".join(ipa_parts),
                        phones=" ".join(phones),
                        stressed=bool(prefix),
                    )
                )
    except (AttributeError, TypeError):
        return ()

    # Apply the maximal-onset principle across an empty onset.  This turns
    # syllabify's ba-nan-a into ba-na-na and tab-by's coda /b/ into the next
    # onset for phonetic display.
    phone_lists = [item.phones.split() for item in syllables]
    for index in range(len(phone_lists) - 1):
        current = phone_lists[index]
        following = phone_lists[index + 1]
        if not current or not following:
            continue
        following_starts_vowel = bool(
            re.fullmatch(r"[A-Z]+[012]", following[0])
        )
        current_ends_consonant = not bool(
            re.fullmatch(r"[A-Z]+[012]", current[-1])
        )
        if following_starts_vowel and current_ends_consonant:
            following.insert(0, current.pop())
    result: list[PhoneticSyllable] = []
    for phones in phone_lists:
        ipa = _ipa_from_cmu_phones(phones)
        if not ipa:
            return ()
        result.append(
            PhoneticSyllable(
                ipa=ipa,
                phones=" ".join(phones),
                stressed=any(
                    bool(re.fullmatch(r"[A-Z]+[12]", phone))
                    for phone in phones
                ),
            )
        )
    if len(result) == 1:
        only = result[0]
        result = [
            PhoneticSyllable(
                ipa=display_ipa(only.ipa),
                phones=only.phones,
                stressed=only.stressed,
            )
        ]
    return tuple(result)


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
        return display_ipa(_britfone().get(normalized_word, "")) or None
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
    return display_ipa(result) if result else None


@lru_cache(maxsize=100_000)
def syllable_hint(word: str) -> str:
    """Return a written syllable split such as ``ba·na·na``.

    Moby's public-domain hyphenation list is preferred; pyphen is used only as
    an OOV fallback.  One-syllable words return an empty string.
    """
    cleaned = (word or "").strip()
    if not cleaned or len(cleaned) < 4:
        return ""
    key = cleaned.lower().replace("’", "'")
    candidates = _moby_entries().get(key, ())
    if candidates:
        def score(parts: tuple[str, ...]) -> tuple:
            lengths = [len(part) for part in parts]
            mean = sum(lengths) / len(lengths)
            variance = sum((length - mean) ** 2 for length in lengths)
            return (0 if "".join(parts).islower() else 1, variance, -len(parts))

        parts = min(candidates, key=score)
        lengths = [len(part) for part in parts]
        result = []
        cursor = 0
        for length in lengths:
            result.append(cleaned[cursor : cursor + length])
            cursor += length
        if cursor == len(cleaned) and all(result):
            return "·".join(result)
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
