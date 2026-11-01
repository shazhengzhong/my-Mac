"""English and Chinese text cleanup and sentence segmentation."""

import re

from django.core.exceptions import ValidationError

MAX_SENTENCES = 200
_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[\"'“‘A-Z0-9])")
_CHINESE_END = set("。！？；!?;…")
_HAS_CONTENT = re.compile(r"[一-鿿A-Za-z0-9]")


def split_english_sentences(text: str) -> list[str]:
    """Return practice-sized English sentences, one per list item.

    The translation prompt asks for one sentence per line. This also handles
    multi-line paragraphs and simple fallback punctuation splits. It is not a
    linguistic sentence tokenizer and may split after some abbreviations.
    """
    if not text or not text.strip():
        return []

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    sentences: list[str] = []
    for raw_line in normalized.split("\n"):
        line = _BULLET_PREFIX.sub("", raw_line.strip())
        if not line:
            continue
        for part in _SENTENCE_BREAK.split(line):
            cleaned = " ".join(part.split())
            if cleaned:
                sentences.append(cleaned)

    if len(sentences) > MAX_SENTENCES:
        raise ValidationError(f"英文句子过多，最多支持 {MAX_SENTENCES} 句。")
    return sentences


def split_chinese_sentences(text: str) -> list[str]:
    """Split Chinese diary text after full-width punctuation and newlines.

    Consecutive end marks (for example ``……``) stay attached to the sentence.
    ASCII periods are deliberately not used as breaks to avoid splitting
    decimals and abbreviations.
    """
    if not text or not text.strip():
        return []

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    sentences: list[str] = []
    buffer = ""
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if char == "\n":
            if buffer.strip():
                sentences.append(buffer.strip())
            buffer = ""
            index += 1
            continue
        buffer += char
        if char in _CHINESE_END:
            while (
                index + 1 < len(normalized)
                and normalized[index + 1] in _CHINESE_END
            ):
                index += 1
                buffer += normalized[index]
            sentences.append(buffer.strip())
            buffer = ""
        index += 1
    if buffer.strip():
        sentences.append(buffer.strip())

    cleaned = [sentence for sentence in sentences if _HAS_CONTENT.search(sentence)]
    if len(cleaned) > MAX_SENTENCES:
        raise ValidationError(f"中文句子过多，最多支持 {MAX_SENTENCES} 句。")
    return cleaned
