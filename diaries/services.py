"""Domain services for English versions and daily provider limits."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from services.audio import remove_private_bytes, write_private_bytes
from services.pronunciation import analyze_sentence
from services.text import split_english_sentences
from services.translation import TranslationPair

from .models import (
    AudioAsset,
    DiaryEntry,
    EnglishVersion,
    PronunciationAttempt,
    Recording,
    Sentence,
    TtsRender,
    UsageCounter,
    WordToken,
    text_hash,
)


class TranslationQuotaExceeded(Exception):
    """The user has reached the configured daily translation request limit."""


class TTSQuotaExceeded(Exception):
    """The user has reached the configured daily TTS character limit."""


class AssessmentQuotaExceeded(Exception):
    """The user has reached the configured daily assessment request limit."""


def consume_translation_quota(user, char_count: int) -> None:
    """Reserve one translation request before making an external paid call."""
    limit = settings.TRANSLATION_DAILY_REQUEST_LIMIT
    today = timezone.localdate()
    with transaction.atomic():
        counter, _ = UsageCounter.objects.select_for_update().get_or_create(
            user=user,
            date=today,
            feature="translation",
        )
        if counter.request_count >= limit:
            raise TranslationQuotaExceeded(
                f"今天最多翻译 {limit} 次，请明天再试。"
            )
        counter.request_count += 1
        counter.char_count += max(0, char_count)
        counter.save(update_fields=["request_count", "char_count"])


def consume_tts_quota(user, char_count: int) -> None:
    """Reserve TTS characters before generating a paid or mock audio file."""
    limit = settings.TTS_DAILY_CHAR_LIMIT
    today = timezone.localdate()
    requested = max(0, char_count)
    with transaction.atomic():
        counter, _ = UsageCounter.objects.select_for_update().get_or_create(
            user=user,
            date=today,
            feature="tts",
        )
        if counter.char_count + requested > limit:
            raise TTSQuotaExceeded(f"今天示范朗读字符额度为 {limit}，请明天再试。")
        counter.request_count += 1
        counter.char_count += requested
        counter.save(update_fields=["request_count", "char_count"])


def consume_assessment_quota(user, word: str) -> None:
    """Reserve one word assessment before making an external paid call."""
    limit = settings.ASSESSMENT_DAILY_REQUEST_LIMIT
    today = timezone.localdate()
    with transaction.atomic():
        counter, _ = UsageCounter.objects.select_for_update().get_or_create(
            user=user,
            date=today,
            feature="assessment",
        )
        if counter.request_count >= limit:
            raise AssessmentQuotaExceeded(
                f"今天最多测评 {limit} 次，请明天再试。"
            )
        counter.request_count += 1
        counter.char_count += len(word or "")
        counter.save(update_fields=["request_count", "char_count"])


def create_pronunciation_attempt(
    *,
    owner,
    word_token,
    data: bytes,
    duration_ms: int,
    result,
) -> PronunciationAttempt:
    """Store a private word recording and its assessment result atomically."""
    relative_path, digest, byte_size = write_private_bytes(
        owner_id=owner.pk,
        purpose="assessments",
        data=data,
        extension="wav",
    )
    try:
        with transaction.atomic():
            asset = AudioAsset.objects.create(
                owner=owner,
                sentence=word_token.sentence,
                purpose=AudioAsset.Purpose.ASSESSMENT,
                relative_path=relative_path,
                content_type="audio/wav",
                byte_size=byte_size,
                duration_ms=duration_ms,
                sha256=digest,
            )
            return PronunciationAttempt.objects.create(
                owner=owner,
                word_token=word_token,
                audio=asset,
                target_word=word_token.surface,
                provider=result.provider,
                model=result.model,
                overall_score=result.overall_score,
                accuracy=result.accuracy,
                fluency=result.fluency,
                completeness=result.completeness,
                match_tag=result.match_tag,
                detail=result.detail,
            )
    except Exception:
        remove_private_bytes(relative_path)
        raise


def create_recording(
    *,
    owner,
    sentence: Sentence,
    data: bytes,
    duration_ms: int,
) -> Recording:
    """Store a validated WAV recording and its private audio row atomically."""
    relative_path, digest, byte_size = write_private_bytes(
        owner_id=owner.pk,
        purpose="recordings",
        data=data,
        extension="wav",
    )
    try:
        with transaction.atomic():
            asset = AudioAsset.objects.create(
                owner=owner,
                sentence=sentence,
                purpose=AudioAsset.Purpose.RECORDING,
                relative_path=relative_path,
                content_type="audio/wav",
                byte_size=byte_size,
                duration_ms=duration_ms,
                sha256=digest,
            )
            return Recording.objects.create(
                owner=owner,
                sentence=sentence,
                audio=asset,
                target_text=sentence.text,
                duration_ms=duration_ms,
            )
    except Exception:
        remove_private_bytes(relative_path)
        raise


def create_tts_render(
    *,
    owner,
    sentence: Sentence,
    result,
    speed: str,
    style: str,
    cache_key: str,
) -> TtsRender:
    """Store generated TTS audio privately, rolling back the file on DB failure."""
    relative_path, digest, byte_size = write_private_bytes(
        owner_id=owner.pk,
        purpose="tts",
        data=result.data,
        extension=result.extension,
    )
    try:
        with transaction.atomic():
            asset = AudioAsset.objects.create(
                owner=owner,
                sentence=sentence,
                purpose=AudioAsset.Purpose.TTS,
                relative_path=relative_path,
                content_type=result.content_type,
                byte_size=byte_size,
                duration_ms=result.duration_ms,
                sha256=digest,
            )
            return TtsRender.objects.create(
                owner=owner,
                sentence=sentence,
                audio=asset,
                speed=speed,
                style=style,
                voice=result.voice,
                provider=result.provider,
                model=result.model,
                cache_key=cache_key,
                char_count=len(sentence.text),
            )
    except Exception:
        remove_private_bytes(relative_path)
        raise


def _create_version_with_sentences(
    diary: DiaryEntry,
    specs: list[tuple[str, str, int | None]],
    *,
    source: str,
    provider_model: str = "",
) -> EnglishVersion:
    """Create an immutable version from (english, chinese, chinese_ordinal) rows."""
    if source not in EnglishVersion.Source.values:
        raise ValueError("Unknown English version source")
    if not specs:
        raise ValidationError("英文内容为空，无法建立练习句子。")

    with transaction.atomic():
        locked_diary = DiaryEntry.objects.select_for_update().get(pk=diary.pk)
        latest_no = (
            locked_diary.english_versions.aggregate(max_no=Max("version_no"))["max_no"]
            or 0
        )
        version = EnglishVersion.objects.create(
            diary=locked_diary,
            version_no=latest_no + 1,
            english_text="\n".join(english for english, _, _ in specs),
            source=source,
            provider_model=provider_model[:100],
            source_chinese_hash=text_hash(locked_diary.chinese_text),
        )
        for sentence_index, (sentence_text, chinese_text, chinese_ordinal) in enumerate(
            specs
        ):
            sentence = Sentence.objects.create(
                version=version,
                ordinal=sentence_index,
                text=sentence_text,
                chinese_text=chinese_text,
                chinese_ordinal=chinese_ordinal,
            )
            tokens = analyze_sentence(sentence_text)
            WordToken.objects.bulk_create(
                [
                    WordToken(
                        sentence=sentence,
                        ordinal=token_index,
                        surface=token.surface,
                        ipa=token.ipa,
                        source=token.source,
                    )
                    for token_index, token in enumerate(tokens)
                ]
            )
        DiaryEntry.objects.filter(pk=locked_diary.pk).update(updated_at=timezone.now())
    return version


def create_english_version(
    diary: DiaryEntry,
    english_text: str,
    *,
    source: str,
    provider_model: str = "",
) -> EnglishVersion:
    """Create an immutable English version without Chinese sentence alignment."""
    sentences = split_english_sentences(english_text)
    if not sentences:
        raise ValidationError("英文内容为空，无法建立练习句子。")
    return _create_version_with_sentences(
        diary,
        [(sentence, "", None) for sentence in sentences],
        source=source,
        provider_model=provider_model,
    )


def create_aligned_english_version(
    diary: DiaryEntry,
    pairs: list[TranslationPair],
    *,
    source: str,
    provider_model: str = "",
) -> EnglishVersion:
    """Create a version whose English sentences keep their Chinese source group."""
    if not pairs:
        raise ValidationError("翻译结果为空，无法建立练习句子。")

    specs: list[tuple[str, str, int | None]] = []
    for chinese_ordinal, pair in enumerate(pairs):
        chinese = (pair.chinese or "").strip()
        english = (pair.english or "").strip()
        if not chinese or not english:
            raise ValidationError("翻译结果包含空句子，无法建立练习句子。")
        english_sentences = split_english_sentences(english)
        if not english_sentences:
            raise ValidationError("英文内容为空，无法建立练习句子。")
        for sentence in english_sentences:
            specs.append((sentence, chinese, chinese_ordinal))

    return _create_version_with_sentences(
        diary,
        specs,
        source=source,
        provider_model=provider_model,
    )
