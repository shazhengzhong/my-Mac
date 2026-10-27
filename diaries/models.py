"""Per-user diaries, English versions, sentences, IPA tokens, and usage counters."""

import hashlib
import uuid

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone


def text_hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


class DiaryEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="diary_entries",
    )
    entry_date = models.DateField(default=timezone.localdate)
    title = models.CharField(max_length=100, blank=True)
    chinese_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-entry_date", "-created_at"]
        indexes = [models.Index(fields=["owner", "entry_date"])]

    @property
    def current_version(self):
        return self.english_versions.order_by("-version_no").first()

    @property
    def display_title(self) -> str:
        return self.title.strip() or f"{self.entry_date:%Y-%m-%d} 的日记"

    def __str__(self) -> str:
        return self.display_title


class EnglishVersion(models.Model):
    class Source(models.TextChoices):
        MOCK = "mock", "模拟翻译"
        DEEPSEEK = "deepseek", "DeepSeek 翻译"
        MANUAL = "manual", "手动英文"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diary = models.ForeignKey(
        DiaryEntry,
        on_delete=models.CASCADE,
        related_name="english_versions",
    )
    version_no = models.PositiveIntegerField()
    english_text = models.TextField()
    source = models.CharField(max_length=20, choices=Source.choices)
    provider_model = models.CharField(max_length=100, blank=True)
    source_chinese_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["diary", "version_no"],
                name="diaries_unique_version_number",
            )
        ]

    @property
    def is_stale(self) -> bool:
        """Whether the Chinese text changed after this English version was made."""
        return self.source_chinese_hash != text_hash(self.diary.chinese_text)

    def __str__(self) -> str:
        return f"{self.diary.display_title} · 版本 {self.version_no}"


class Sentence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(
        EnglishVersion,
        on_delete=models.CASCADE,
        related_name="sentences",
    )
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    chinese_text = models.TextField(blank=True, default="")
    chinese_ordinal = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["ordinal"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "ordinal"],
                name="diaries_unique_sentence_order",
            )
        ]

    def __str__(self) -> str:
        return self.text


class WordToken(models.Model):
    class Source(models.TextChoices):
        DICTIONARY = "dictionary", "发音词典"
        MANUAL = "manual", "人工修正"
        UNKNOWN = "unknown", "未收录"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sentence = models.ForeignKey(
        Sentence,
        on_delete=models.CASCADE,
        related_name="tokens",
    )
    ordinal = models.PositiveIntegerField()
    surface = models.CharField(max_length=120)
    ipa = models.CharField(max_length=120, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices)

    class Meta:
        ordering = ["ordinal"]
        constraints = [
            models.UniqueConstraint(
                fields=["sentence", "ordinal"],
                name="diaries_unique_token_order",
            )
        ]

    def __str__(self) -> str:
        return self.surface


class UsageCounter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="usage_counters",
    )
    date = models.DateField(default=timezone.localdate)
    feature = models.CharField(max_length=32)
    request_count = models.PositiveIntegerField(default=0)
    char_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date", "feature"],
                name="diaries_unique_daily_usage",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.date} {self.feature}"


class AudioAsset(models.Model):
    class Purpose(models.TextChoices):
        RECORDING = "recording", "用户录音"
        TTS = "tts", "示范朗读"
        WORD_TTS = "word_tts", "单词发音"
        ASSESSMENT = "assessment", "单词测评"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="audio_assets",
    )
    sentence = models.ForeignKey(
        Sentence,
        on_delete=models.CASCADE,
        related_name="audio_assets",
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    relative_path = models.CharField(max_length=255, unique=True)
    content_type = models.CharField(max_length=50)
    byte_size = models.PositiveIntegerField()
    duration_ms = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.purpose} {self.id}"


class Recording(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recordings",
    )
    sentence = models.ForeignKey(
        Sentence,
        on_delete=models.CASCADE,
        related_name="recordings",
    )
    audio = models.OneToOneField(
        AudioAsset,
        on_delete=models.CASCADE,
        related_name="recording",
    )
    target_text = models.TextField()
    duration_ms = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"录音 {self.id}"


class TtsRender(models.Model):
    class Speed(models.TextChoices):
        NORMAL = "normal", "正常"
        SLOW = "slow", "慢速"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tts_renders",
    )
    sentence = models.ForeignKey(
        Sentence,
        on_delete=models.CASCADE,
        related_name="tts_renders",
    )
    audio = models.OneToOneField(
        AudioAsset,
        on_delete=models.CASCADE,
        related_name="tts_render",
    )
    speed = models.CharField(max_length=10, choices=Speed.choices)
    style = models.CharField(max_length=40)
    voice = models.CharField(max_length=100)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=100)
    cache_key = models.CharField(max_length=64)
    char_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "cache_key"],
                name="diaries_unique_user_tts_cache",
            )
        ]

    def __str__(self) -> str:
        return f"{self.speed} TTS {self.id}"


class WordTtsRender(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="word_tts_renders",
    )
    sentence = models.ForeignKey(
        Sentence,
        on_delete=models.CASCADE,
        related_name="word_tts_renders",
    )
    audio = models.OneToOneField(
        AudioAsset,
        on_delete=models.CASCADE,
        related_name="word_tts_render",
    )
    target_word = models.CharField(max_length=120)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=100)
    voice = models.CharField(max_length=100)
    style = models.CharField(max_length=40)
    cache_key = models.CharField(max_length=64)
    char_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "cache_key"],
                name="diaries_unique_user_word_tts_cache",
            )
        ]

    def __str__(self) -> str:
        return f"单词发音 {self.target_word} {self.id}"


class PronunciationAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pronunciation_attempts",
    )
    word_token = models.ForeignKey(
        WordToken,
        on_delete=models.CASCADE,
        related_name="assessment_attempts",
    )
    audio = models.OneToOneField(
        AudioAsset,
        on_delete=models.CASCADE,
        related_name="pronunciation_attempt",
    )
    target_word = models.CharField(max_length=120)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=100)
    overall_score = models.FloatField(null=True, blank=True)
    accuracy = models.FloatField(null=True, blank=True)
    fluency = models.FloatField(null=True, blank=True)
    completeness = models.FloatField(null=True, blank=True)
    match_tag = models.PositiveSmallIntegerField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"测评 {self.target_word} {self.id}"


@receiver(post_delete, sender=AudioAsset)
def _remove_private_audio_file(sender, instance, **kwargs):
    """Remove a private file when its database row is deleted."""
    from services.audio import remove_private_bytes

    remove_private_bytes(instance.relative_path)
