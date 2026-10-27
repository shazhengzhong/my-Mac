"""English text cleanup and sentence segmentation."""

import re

from django.core.exceptions import ValidationError

MAX_SENTENCES = 200
_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[\"'“‘A-Z0-9])")


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
