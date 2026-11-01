"""Owner-scoped diary and pronunciation pages."""

import logging
import re
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_http_methods

from services.assessment import AssessmentError, get_assessor
from services.audio import (
    MAX_AUDIO_BYTES,
    AudioValidationError,
    RangeNotSatisfiable,
    parse_byte_range,
    read_private_bytes,
    remove_private_bytes,
    validate_assessment_wav,
    validate_recording_wav,
)
from services.ocr import (
    MAX_OCR_TEXT_CHARS,
    MAX_OCR_UPLOAD_BYTES,
    OCRError,
    get_ocr_provider,
    prepare_ocr_image,
    validate_ocr_image,
)
from services.phonics import (
    HUMAN_VOICE,
    PhonicsError,
    generate_phoneme_audio,
    phonics_for_word,
    syllable_audio_text,
)
from services.pronunciation import accent_label, syllable_hint
from services.translation import TranslationError, get_translator
from services.tts import (
    TTSError,
    TTSResult,
    get_tts_provider,
    tts_cache_key,
    word_tts_context,
)

from .forms import DiaryForm, EnglishVersionForm, IpaCorrectionForm
from .models import (
    AudioAsset,
    DiaryEntry,
    DiaryReadAloud,
    PronunciationAttempt,
    Recording,
    Sentence,
    TtsRender,
    WordLookup,
    WordToken,
    WordTtsRender,
)
from .services import (
    AssessmentQuotaExceeded,
    OCRQuotaExceeded,
    TTSQuotaExceeded,
    TranslationQuotaExceeded,
    consume_assessment_quota,
    consume_ocr_quota,
    consume_translation_quota,
    consume_tts_quota,
    create_aligned_english_version,
    create_diary_read_aloud,
    create_english_version,
    create_ocr_diary,
    create_pronunciation_attempt,
    create_recording,
    create_tts_render,
    create_word_tts_render,
    lookup_word,
)


logger = logging.getLogger(__name__)


def _owned_diary(request, diary_id) -> DiaryEntry:
    return get_object_or_404(DiaryEntry, pk=diary_id, owner=request.user)


def _owned_sentence(request, sentence_id) -> Sentence:
    return get_object_or_404(
        Sentence.objects.select_related("version__diary"),
        pk=sentence_id,
        version__diary__owner=request.user,
    )


def _owned_token(request, token_id) -> WordToken:
    return get_object_or_404(
        WordToken.objects.select_related("sentence__version__diary"),
        pk=token_id,
        sentence__version__diary__owner=request.user,
    )


def _translation_status() -> dict:
    provider = settings.TRANSLATION_PROVIDER
    if provider == "mock":
        return {
            "is_mock": True,
            "ready": True,
            "message": "当前是模拟翻译模式，英文内容仅用于界面测试。",
        }
    if provider == "deepseek" and not settings.DEEPSEEK_API_KEY:
        return {
            "is_mock": False,
            "ready": False,
            "message": "真实翻译尚未配置 API Key。",
        }
    if provider == "deepseek":
        return {
            "is_mock": False,
            "ready": True,
            "message": "真实翻译已启用；每次翻译会消耗 DeepSeek API 用量。",
        }
    return {
        "is_mock": False,
        "ready": False,
        "message": "翻译服务配置异常。",
    }


def _tts_status() -> dict:
    provider = settings.TTS_PROVIDER
    if provider == "mock":
        return {
            "is_mock": True,
            "ready": True,
            "message": "当前示范音频是模拟提示音，不是真人语音，也不会产生费用。",
        }
    if provider == "cosyvoice":
        ready = bool(
            settings.DASHSCOPE_API_KEY
            and settings.COSYVOICE_TTS_VOICE_US
        )
        if not ready:
            return {
                "is_mock": False,
                "ready": False,
                "message": "阿里云 CosyVoice 尚未配置完整凭据或音色。",
            }
        return {
            "is_mock": False,
            "ready": True,
            "message": "真实语音已启用（阿里云 CosyVoice 3.5 Plus）；每句会消耗 TTS 字符额度。",
        }
    if provider == "volcengine":
        credentials_ready = bool(
            settings.VOLCENGINE_API_KEY
            or (settings.VOLCENGINE_APP_ID and settings.VOLCENGINE_ACCESS_TOKEN)
        )
        if not credentials_ready or not settings.VOLCENGINE_TTS_VOICE:
            return {
                "is_mock": False,
                "ready": False,
                "message": "真实语音尚未配置完整的凭据或音色。",
            }
        return {
            "is_mock": False,
            "ready": True,
            "message": "真实语音已启用；每句会消耗 TTS 字符额度。",
        }
    return {
        "is_mock": False,
        "ready": False,
        "message": "语音服务配置异常。",
    }


def _assessment_status() -> dict:
    provider = settings.ASSESSMENT_PROVIDER
    if provider == "mock":
        return {
            "is_mock": True,
            "ready": True,
            "message": "当前是模拟单词测评，不联网、不产生费用。",
        }
    if provider == "tencent":
        ready = bool(
            settings.TENCENT_SOE_APP_ID
            and settings.TENCENTCLOUD_SECRET_ID
            and settings.TENCENTCLOUD_SECRET_KEY
        )
        if not ready:
            return {
                "is_mock": False,
                "ready": False,
                "message": "腾讯云口语评测尚未配置完整凭据。",
            }
        return {
            "is_mock": False,
            "ready": True,
            "message": "真实单词测评已启用；每次会消耗腾讯云调用次数。",
        }
    return {
        "is_mock": False,
        "ready": False,
        "message": "单词测评服务配置异常。",
    }


def _ocr_status() -> dict:
    provider = settings.OCR_PROVIDER
    if provider == "mock":
        return {
            "is_mock": True,
            "ready": True,
            "message": "当前是模拟 OCR，识别结果是固定示例，不联网、不产生费用。",
        }
    if provider == "tencent":
        ready = bool(
            settings.TENCENTCLOUD_SECRET_ID
            and settings.TENCENTCLOUD_SECRET_KEY
        )
        if not ready:
            return {
                "is_mock": False,
                "ready": False,
                "message": "腾讯云 OCR 尚未配置完整凭据。",
            }
        return {
            "is_mock": False,
            "ready": True,
            "message": "真实 OCR 已启用；每张照片会发送给腾讯云识别一次。",
        }
    return {
        "is_mock": False,
        "ready": False,
        "message": "OCR 服务配置异常。",
    }


def _sentence_redirect(diary_id, sentence_id):
    return redirect(
        reverse("diary_detail", args=[diary_id]) + f"#sentence-{sentence_id}"
    )


@login_required
@never_cache
def diary_list(request):
    entries = DiaryEntry.objects.filter(owner=request.user).order_by(
        "-entry_date", "-created_at"
    )
    items = [{"diary": diary, "version": diary.current_version} for diary in entries]
    return render(request, "diaries/list.html", {"items": items})


@login_required
@never_cache
def diary_create(request):
    form = DiaryForm(
        request.POST or None,
        initial={"entry_date": timezone.localdate()},
    )
    if request.method == "POST" and form.is_valid():
        diary = form.save(commit=False)
        diary.owner = request.user
        diary.save()
        messages.success(request, "中文日记已保存。下一步可以生成英文翻译。")
        return redirect("diary_detail", diary_id=diary.id)

    return render(
        request,
        "diaries/form.html",
        {"form": form, "heading": "写一篇新日记", "submit_label": "保存日记"},
    )


@login_required
@never_cache
def diary_edit(request, diary_id):
    diary = _owned_diary(request, diary_id)
    form = DiaryForm(request.POST or None, instance=diary)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "中文日记已更新。如英文已过时，请重新翻译或编辑英文。")
        return redirect("diary_detail", diary_id=diary.id)

    return render(
        request,
        "diaries/form.html",
        {"form": form, "heading": "编辑中文日记", "submit_label": "保存修改", "diary": diary},
    )


_WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")


def _split_gap(gap: str) -> tuple[str, str]:
    """Split text between two words into trailing and leading punctuation.

    ``"morning! I'm"`` has the gap ``"! "``: the exclamation belongs to the
    previous word. ``'said, "Hello'`` has the gap ``', "'``: the comma belongs
    to the previous word and the opening quote to the next one.
    """
    if not gap or gap.isspace():
        return "", ""
    stripped = gap.rstrip()
    last_space = max(stripped.rfind(" "), stripped.rfind("\t"), stripped.rfind("\n"))
    if last_space == -1:
        return stripped, ""
    return stripped[:last_space].rstrip(), stripped[last_space + 1 :]


def _display_segments(sentence: Sentence) -> list[dict]:
    """Pairs sentence words with punctuation and their pronunciation tokens.

    The template uses this to render the practice line as clickable word units
    while keeping punctuation attached to the right word (``morning!``,
    ``Wu.``, opening quotes, etc.).
    """
    text = sentence.text or ""
    tokens = list(sentence.tokens.all())
    matches = list(_WORD_RE.finditer(text))
    if not matches:
        return [{"token": None, "word": text, "display_word": text}]

    segments: list[dict] = []
    token_cursor = 0
    previous_end = 0
    for index, match in enumerate(matches):
        word = match.group(0)
        normalized = word.lower().replace("’", "'")
        token = None
        for candidate_index in range(token_cursor, len(tokens)):
            candidate = tokens[candidate_index]
            candidate_word = candidate.surface.strip().lower().replace("’", "'")
            if candidate_word == normalized:
                token = candidate
                token_cursor = candidate_index + 1
                break
        if token is None and token_cursor < len(tokens):
            token = tokens[token_cursor]
            token_cursor += 1

        if index == 0:
            prefix = text[: match.start()].strip()
        else:
            trailing, prefix = _split_gap(text[previous_end : match.start()])
            if trailing:
                segments[-1]["display_word"] += trailing

        segments.append(
            {
                "token": token,
                "word": word,
                "display_word": f"{prefix}{word}",
            }
        )
        previous_end = match.end()

    tail = text[previous_end:].rstrip()
    if tail:
        segments[-1]["display_word"] += tail
    return segments


@login_required
@never_cache
def diary_detail(request, diary_id):
    diary = _owned_diary(request, diary_id)
    current = diary.current_version
    sentences = (
        list(current.sentences.prefetch_related("tokens", "recordings__audio"))
        if current is not None
        else []
    )
    previous_count = (
        diary.english_versions.exclude(pk=current.pk).count()
        if current is not None
        else 0
    )
    tts_map = {}
    if sentences:
        try:
            tts_provider = get_tts_provider(request.user.accent)
        except TTSError:
            tts_provider = None
        if tts_provider is not None:
            sentence_ids = [sentence.id for sentence in sentences]
            renders = TtsRender.objects.filter(
                owner=request.user,
                sentence_id__in=sentence_ids,
            ).select_related("audio")
            renders_by_key = {render.cache_key: render for render in renders}
            for sentence in sentences:
                for tts_speed, tts_style in (
                    (TtsRender.Speed.NORMAL, "natural"),
                    (TtsRender.Speed.SLOW, "neutral"),
                ):
                    key = tts_cache_key(
                        provider=tts_provider.provider,
                        model=tts_provider.model,
                        voice=tts_provider.voice,
                        style=tts_style,
                        speed=tts_speed,
                        rate=tts_provider.speech_rate(tts_speed),
                        text=sentence.text,
                    )
                    tts_render = renders_by_key.get(key)
                    if tts_render is not None:
                        tts_map[(sentence.id, tts_speed)] = tts_render
    assessment_map = {}
    if sentences:
        attempts = (
            PronunciationAttempt.objects.filter(
                owner=request.user,
                word_token__sentence_id__in=[sentence.id for sentence in sentences],
            )
            .select_related("audio")
            .order_by("word_token_id", "-created_at")
        )
        for attempt in attempts:
            assessment_map.setdefault(attempt.word_token_id, attempt)
    accent = request.user.accent
    previous_chinese_ordinal = None
    has_aligned_chinese = False
    bilingual_groups = []
    current_group = None
    for sentence in sentences:
        sentence.tts_normal = tts_map.get((sentence.id, TtsRender.Speed.NORMAL))
        sentence.tts_slow = tts_map.get((sentence.id, TtsRender.Speed.SLOW))
        for token in sentence.tokens.all():
            token.display_ipa = (
                token.ipa_uk if accent == "uk" else token.ipa
            )
            token.latest_assessment = assessment_map.get(token.id)
            token.syllable_hint = syllable_hint(token.surface)
        sentence.display_segments = _display_segments(sentence)
        sentence.karaoke_words = sentence.text.split()
        if sentence.chinese_text:
            has_aligned_chinese = True
        sentence.show_chinese = (
            bool(sentence.chinese_text)
            and sentence.chinese_ordinal != previous_chinese_ordinal
        )
        if sentence.chinese_text and sentence.chinese_ordinal is not None:
            if (
                current_group is None
                or current_group["ordinal"] != sentence.chinese_ordinal
            ):
                current_group = {
                    "ordinal": sentence.chinese_ordinal,
                    "chinese_text": sentence.chinese_text,
                    "sentences": [],
                }
                bilingual_groups.append(current_group)
            current_group["sentences"].append(sentence)
        if sentence.chinese_ordinal is not None:
            previous_chinese_ordinal = sentence.chinese_ordinal
        else:
            previous_chinese_ordinal = None

    return render(
        request,
        "diaries/detail.html",
        {
            "diary": diary,
            "current": current,
            "sentences": sentences,
            "previous_count": previous_count,
            "has_aligned_chinese": has_aligned_chinese,
            "bilingual_groups": bilingual_groups,
            "translation": _translation_status(),
            "tts": _tts_status(),
            "assessment": _assessment_status(),
            "accent": accent,
            "accent_label": accent_label(accent),
        },
    )


@login_required
@require_POST
@never_cache
def diary_translate(request, diary_id):
    diary = _owned_diary(request, diary_id)
    try:
        translator = get_translator()
    except TranslationError as exc:
        messages.error(request, str(exc))
        return redirect("diary_detail", diary_id=diary.id)

    try:
        consume_translation_quota(request.user, len(diary.chinese_text))
        pairs = translator.translate_pairs(diary.chinese_text)
        version = create_aligned_english_version(
            diary,
            pairs,
            source=translator.source,
            provider_model=translator.model,
        )
    except TranslationQuotaExceeded as exc:
        messages.error(request, str(exc))
    except TranslationError as exc:
        messages.error(request, str(exc))
    except ValidationError as exc:
        messages.error(request, "；".join(exc.messages))
    else:
        messages.success(request, f"已生成第 {version.version_no} 版英文。")
    return redirect("diary_detail", diary_id=diary.id)


@login_required
@require_POST
@never_cache
def diary_read_aloud(request, diary_id):
    diary = _owned_diary(request, diary_id)
    version = diary.current_version
    speed = request.POST.get("speed", DiaryReadAloud.Speed.NORMAL)
    if speed not in DiaryReadAloud.Speed.values:
        return JsonResponse(
            {"ok": False, "error": "未知的朗读速度。"},
            status=400,
        )
    accent = request.user.accent
    if accent not in DiaryReadAloud.Accent.values:
        accent = DiaryReadAloud.Accent.US
    if version is None:
        return JsonResponse({"ok": False, "error": "这篇日记还没有英文。"}, status=400)
    sentences = list(version.sentences.order_by("ordinal"))
    if not sentences:
        return JsonResponse(
            {"ok": False, "error": "这篇日记还没有英文句子。"},
            status=400,
        )

    try:
        provider = get_tts_provider(accent)
    except TTSError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)

    existing = (
        DiaryReadAloud.objects.filter(
            owner=request.user,
            version=version,
            speed=speed,
            accent=accent,
        )
        .select_related("audio")
        .first()
    )
    if existing is not None and (
        existing.provider != provider.provider
        or existing.model != provider.model
        or existing.voice != provider.voice
    ):
        stale_audio = existing.audio
        stale_path = stale_audio.relative_path
        with transaction.atomic():
            existing.delete()
            stale_audio.delete()
        try:
            remove_private_bytes(stale_path)
        except OSError:
            logger.warning(
                "Could not remove stale read-aloud file %s",
                stale_path,
                exc_info=True,
            )
        existing = None
    if existing is not None:
        return JsonResponse(
            {
                "ok": True,
                "audio_url": reverse(
                    "serve_audio_asset", args=[existing.audio_id]
                ),
                "duration_ms": existing.audio.duration_ms,
                "timings": existing.timings,
                "speed": existing.speed,
                "cached": True,
            }
        )

    full_text = "\n".join(sentence.text for sentence in sentences)
    try:
        consume_tts_quota(request.user, len(full_text))
        result = provider.synthesize(
            full_text,
            speed=speed,
            style="natural",
            enable_subtitles=True,
        )
        read_aloud = create_diary_read_aloud(
            owner=request.user,
            version=version,
            speed=speed,
            accent=accent,
            sentence=sentences[0],
            result=result,
            timings=result.timings,
            char_count=len(full_text),
        )
    except TTSQuotaExceeded as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=429)
    except TTSError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "全文朗读生成失败，请稍后再试。"},
            status=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "audio_url": reverse(
                "serve_audio_asset", args=[read_aloud.audio_id]
            ),
            "duration_ms": result.duration_ms,
            "timings": list(result.timings),
            "speed": read_aloud.speed,
            "cached": False,
        }
    )


@login_required
@never_cache
def diary_edit_english(request, diary_id):
    diary = _owned_diary(request, diary_id)
    current = diary.current_version
    form = EnglishVersionForm(
        request.POST or None,
        initial={"english_text": current.english_text if current else ""},
    )
    if request.method == "POST" and form.is_valid():
        try:
            version = create_english_version(
                diary,
                form.cleaned_data["english_text"],
                source="manual",
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"已保存第 {version.version_no} 版英文。")
            return redirect("diary_detail", diary_id=diary.id)

    return render(
        request,
        "diaries/edit_english.html",
        {"diary": diary, "form": form, "current": current},
    )


@login_required
@require_http_methods(["GET", "POST"])
@never_cache
def diary_delete(request, diary_id):
    diary = _owned_diary(request, diary_id)
    if request.method == "POST":
        diary.delete()
        messages.success(request, "这篇日记及它的英文版本、音标已删除。")
        return redirect("diary_list")
    return render(request, "diaries/delete.html", {"diary": diary})


@login_required
@require_http_methods(["GET", "POST"])
@never_cache
def edit_sentence_ipa(request, sentence_id):
    sentence = _owned_sentence(request, sentence_id)
    tokens = list(sentence.tokens.all())
    accent = request.user.accent
    form = IpaCorrectionForm(
        request.POST or None,
        tokens=tokens,
        accent=accent,
    )
    rows = [
        {"token": token, "field": form[field_name]}
        for token, field_name in form.token_fields
    ]
    if request.method == "POST" and form.is_valid():
        field = "ipa_uk" if accent == "uk" else "ipa"
        with transaction.atomic():
            for token, value in form.corrections():
                update = {
                    field: value,
                    "source": (
                        WordToken.Source.MANUAL
                        if value
                        else WordToken.Source.UNKNOWN
                    ),
                }
                WordToken.objects.filter(pk=token.pk).update(**update)
        messages.success(
            request,
            f"{accent_label(accent)}音标已更新。",
        )
        return redirect("diary_detail", diary_id=sentence.version.diary_id)

    return render(
        request,
        "diaries/ipa_edit.html",
        {
            "sentence": sentence,
            "form": form,
            "tokens": tokens,
            "rows": rows,
            "accent": accent,
            "accent_label": accent_label(accent),
        },
    )


@login_required
@require_POST
@never_cache
def generate_sentence_tts(request, sentence_id, speed):
    sentence = _owned_sentence(request, sentence_id)
    if speed not in TtsRender.Speed.values:
        raise Http404("Unknown TTS speed")

    wants_json = (
        request.headers.get("x-requested-with", "").lower() == "fetch"
        or request.POST.get("format") == "json"
    )

    def json_error(message: str, status: int) -> JsonResponse:
        return JsonResponse({"ok": False, "error": message}, status=status)

    try:
        provider = get_tts_provider(request.user.accent)
    except TTSError as exc:
        if wants_json:
            return json_error(str(exc), 503)
        messages.error(request, str(exc))
        return _sentence_redirect(sentence.version.diary_id, sentence.id)

    style = "neutral" if speed == TtsRender.Speed.SLOW else "natural"
    cache_key = tts_cache_key(
        provider=provider.provider,
        model=provider.model,
        voice=provider.voice,
        style=style,
        speed=speed,
        rate=provider.speech_rate(speed),
        text=sentence.text,
    )
    existing = (
        TtsRender.objects.filter(owner=request.user, cache_key=cache_key)
        .select_related("audio")
        .first()
    )
    if existing is not None:
        if wants_json:
            return JsonResponse(
                {
                    "ok": True,
                    "audio_url": reverse(
                        "serve_audio_asset", args=[existing.audio_id]
                    ),
                    "cached": True,
                    "duration_ms": existing.audio.duration_ms,
                    "timings": existing.timings or [],
                }
            )
        messages.info(request, "这句的示范音频已经生成，直接使用缓存。")
        return _sentence_redirect(sentence.version.diary_id, sentence.id)

    try:
        consume_tts_quota(request.user, len(sentence.text))
        result = provider.synthesize(
            sentence.text,
            speed=speed,
            style=style,
            enable_subtitles=True,
        )
        render = create_tts_render(
            owner=request.user,
            sentence=sentence,
            result=result,
            speed=speed,
            style=style,
            cache_key=cache_key,
        )
    except TTSQuotaExceeded as exc:
        if wants_json:
            return json_error(str(exc), 429)
        messages.error(request, str(exc))
    except TTSError as exc:
        if wants_json:
            return json_error(str(exc), 502)
        messages.error(request, str(exc))
    except Exception:
        if wants_json:
            return json_error("示范音频生成失败，请稍后再试。", 500)
        messages.error(request, "示范音频生成失败，请稍后再试。")
    else:
        if wants_json:
            return JsonResponse(
                {
                    "ok": True,
                    "audio_url": reverse(
                        "serve_audio_asset", args=[render.audio_id]
                    ),
                    "cached": False,
                    "duration_ms": result.duration_ms,
                    "timings": list(result.timings),
                }
            )
        messages.success(request, "示范音频已生成并缓存。")
    return _sentence_redirect(sentence.version.diary_id, sentence.id)


@login_required
@require_POST
@never_cache
def word_tts(request, token_id):
    token = _owned_token(request, token_id)
    try:
        provider = get_tts_provider(request.user.accent)
    except TTSError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)

    style = "natural"
    speed = "word"
    context = word_tts_context(token.surface)
    cache_key = tts_cache_key(
        provider=provider.provider,
        model=provider.model,
        voice=provider.voice,
        style=style,
        speed=speed,
        rate=provider.speech_rate(speed),
        text=token.surface,
        context=context,
    )
    existing = (
        WordTtsRender.objects.filter(owner=request.user, cache_key=cache_key)
        .select_related("audio")
        .first()
    )
    if existing is not None:
        return JsonResponse(
            {
                "ok": True,
                "audio_url": reverse(
                    "serve_audio_asset", args=[existing.audio_id]
                ),
                "cached": True,
                "duration_ms": existing.audio.duration_ms,
            }
        )

    try:
        consume_tts_quota(request.user, len(token.surface))
        result = provider.synthesize(
            token.surface, speed=speed, style=style, context_text=context
        )
        render = create_word_tts_render(
            owner=request.user,
            sentence=token.sentence,
            word=token.surface,
            result=result,
            cache_key=cache_key,
        )
    except TTSQuotaExceeded as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=429)
    except TTSError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "单词发音生成失败，请稍后再试。"},
            status=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "audio_url": reverse("serve_audio_asset", args=[render.audio_id]),
            "cached": False,
            "duration_ms": result.duration_ms,
        }
    )


@login_required
@require_POST
@never_cache
def assess_word(request, token_id):
    token = _owned_token(request, token_id)
    uploaded = request.FILES.get("audio")
    if uploaded is None:
        return JsonResponse({"ok": False, "error": "没有收到录音文件。"}, status=400)

    data = uploaded.read()
    try:
        duration_ms = validate_assessment_wav(data)
    except AudioValidationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    try:
        assessor = get_assessor()
    except AssessmentError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)

    try:
        consume_assessment_quota(request.user, token.surface)
    except AssessmentQuotaExceeded as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=429)

    try:
        result = assessor.assess(token.surface, data)
    except AssessmentError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "单词测评失败，请稍后再试。"},
            status=500,
        )

    try:
        attempt = create_pronunciation_attempt(
            owner=request.user,
            word_token=token,
            data=data,
            duration_ms=duration_ms,
            result=result,
        )
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "测评结果保存失败，请稍后再试。"},
            status=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "attempt_id": str(attempt.id),
            "overall_score": result.overall_score,
            "accuracy": result.accuracy,
            "fluency": result.fluency,
            "completeness": result.completeness,
            "match_tag": result.match_tag,
            "detail": result.detail,
            "audio_url": reverse("serve_audio_asset", args=[attempt.audio_id]),
        }
    )


def _ocr_page_context(**overrides) -> dict:
    context = {
        "ocr": _ocr_status(),
        "translation": _translation_status(),
        "step": "upload",
        "source_text": "",
        "english_text": "",
        "title": f"拍照识别 {timezone.localdate():%Y-%m-%d}",
        "line_count": 0,
        "direction": "en_to_zh",
        "error": "",
    }
    context.update(overrides)
    if "source_text" in overrides and "english_text" not in overrides:
        context["english_text"] = overrides["source_text"]
    if "english_text" in overrides and "source_text" not in overrides:
        context["source_text"] = overrides["english_text"]
    return context


def _ocr_direction_for_text(text: str) -> str:
    has_chinese = any("\u4e00" <= char <= "\u9fff" for char in text)
    has_english = any(char.isascii() and char.isalpha() for char in text)
    return "zh_to_en" if has_chinese and not has_english else "en_to_zh"


def _ocr_create_from_text(request):
    source_text = (
        request.POST.get("source_text")
        or request.POST.get("english_text")
        or ""
    ).strip()
    direction = (request.POST.get("direction") or "en_to_zh").strip()
    default_title = f"拍照识别 {timezone.localdate():%Y-%m-%d}"
    title = (request.POST.get("title") or "").strip() or default_title
    context = _ocr_page_context(
        step="review",
        source_text=source_text,
        english_text=source_text,
        title=title,
        direction=direction,
    )

    error = ""
    if direction not in {"en_to_zh", "zh_to_en"}:
        error = "请选择翻译方向。"
    elif not source_text:
        error = "请先确认或填写识别出的文字。"
    elif len(source_text) > MAX_OCR_TEXT_CHARS:
        error = f"识别内容不能超过 {MAX_OCR_TEXT_CHARS} 个字符。"
    elif direction == "en_to_zh" and not any(
        char.isascii() and char.isalpha() for char in source_text
    ):
        error = "没有找到英文内容，请先校对识别结果。"
    elif direction == "zh_to_en" and not any(
        "\u4e00" <= char <= "\u9fff" for char in source_text
    ):
        error = "没有找到中文内容，请先校对识别结果。"
    elif len(title) > 100:
        error = "标题不能超过 100 个字符。"
    if error:
        context["error"] = error
        return render(request, "diaries/ocr_review.html", context)

    try:
        translator = get_translator()
    except TranslationError as exc:
        context["error"] = str(exc)
        return render(request, "diaries/ocr_review.html", context)

    try:
        consume_translation_quota(request.user, len(source_text))
        if direction == "zh_to_en":
            pairs = translator.translate_pairs(source_text)
        else:
            pairs = translator.translate_english_pairs(source_text)
        diary, version = create_ocr_diary(
            owner=request.user,
            pairs=pairs,
            title=title,
            provider_model=translator.model,
        )
    except TranslationQuotaExceeded as exc:
        context["error"] = str(exc)
    except TranslationError as exc:
        context["error"] = str(exc)
    except ValidationError as exc:
        context["error"] = "；".join(exc.messages)
    except Exception:
        logger.exception("Unexpected OCR diary creation failure")
        context["error"] = "生成练习失败，请稍后再试。"
    else:
        messages.success(
            request,
            f"拍照识别已生成第 {version.version_no} 版练习。",
        )
        return redirect("diary_detail", diary_id=diary.id)
    return render(request, "diaries/ocr_review.html", context)


def _parse_ocr_crop(post) -> tuple[float, float, float, float] | None:
    """Parse normalized crop coordinates supplied by the OCR cropper."""
    names = ("crop_x", "crop_y", "crop_w", "crop_h")
    values = [(post.get(name) or "").strip() for name in names]
    if not any(values):
        return None
    try:
        crop = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        raise OCRError("裁剪区域无效，请重新选择照片和裁剪范围。")
    x, y, width, height = crop
    if not (
        0 <= x < 1
        and 0 <= y < 1
        and 0 < width <= 1
        and 0 < height <= 1
        and x + width <= 1.0001
        and y + height <= 1.0001
        and width * height >= 0.0001
    ):
        raise OCRError("裁剪区域无效，请重新选择照片和裁剪范围。")
    return crop


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def ocr_upload(request):
    if request.method == "GET":
        return render(request, "diaries/ocr.html", _ocr_page_context())

    if request.POST.get("step") == "create":
        return _ocr_create_from_text(request)

    uploaded = request.FILES.get("image")
    if uploaded is None:
        return render(
            request,
            "diaries/ocr.html",
            _ocr_page_context(error="请选择一张照片。"),
        )
    if uploaded.size > MAX_OCR_UPLOAD_BYTES:
        return render(
            request,
            "diaries/ocr.html",
            _ocr_page_context(
                error="照片不能超过 25MB，请压缩或先截图后再上传。"
            ),
        )

    data = uploaded.read()
    try:
        crop = _parse_ocr_crop(request.POST)
        data = prepare_ocr_image(data, crop)
        validate_ocr_image(data)
        provider = get_ocr_provider()
    except OCRError as exc:
        return render(
            request,
            "diaries/ocr.html",
            _ocr_page_context(error=str(exc)),
        )

    try:
        consume_ocr_quota(request.user)
    except OCRQuotaExceeded as exc:
        return render(
            request,
            "diaries/ocr.html",
            _ocr_page_context(error=str(exc)),
        )

    try:
        result = provider.recognize(data)
    except OCRError as exc:
        return render(
            request,
            "diaries/ocr.html",
            _ocr_page_context(error=str(exc)),
        )
    except Exception:
        logger.exception("Unexpected OCR provider failure")
        return render(
            request,
            "diaries/ocr.html",
            _ocr_page_context(error="照片识别失败，请稍后再试。"),
        )

    return render(
        request,
        "diaries/ocr_review.html",
        _ocr_page_context(
            step="review",
            source_text=result.text,
            english_text=result.text,
            line_count=result.line_count,
            direction=_ocr_direction_for_text(result.text),
        ),
    )


def _phonics_page_context(
    request,
    display_word,
    *,
    back_url,
    word_audio_url,
    syllable_audio_url,
    phoneme_audio_url,
    sentence=None,
    lookup=None,
):
    return {
        "phonics": phonics_for_word(display_word, request.user.accent),
        "sentence": sentence,
        "lookup": lookup,
        "back_url": back_url,
        "word_audio_url": word_audio_url,
        "syllable_audio_url": syllable_audio_url,
        "phoneme_audio_url": phoneme_audio_url,
    }


@login_required
@never_cache
def word_phonics(request, token_id):
    token = _owned_token(request, token_id)
    return render(
        request,
        "diaries/phonics.html",
        _phonics_page_context(
            request,
            token.surface,
            back_url=reverse(
                "diary_detail",
                args=[token.sentence.version.diary_id],
            ),
            word_audio_url=reverse("word_tts", args=[token.id]),
            syllable_audio_url=reverse(
                "word_phonics_audio",
                args=[token.id, "syllable"],
            ),
            phoneme_audio_url=reverse(
                "word_phonics_audio",
                args=[token.id, "phoneme"],
            ),
            sentence=token.sentence,
        ),
    )


@login_required
@never_cache
def lookup_phonics(request, lookup_id):
    lookup = get_object_or_404(WordLookup, pk=lookup_id)
    back_url = f"{reverse('word_lookup')}?{urlencode({'q': lookup.display_word})}"
    return render(
        request,
        "diaries/phonics.html",
        _phonics_page_context(
            request,
            lookup.display_word,
            back_url=back_url,
            word_audio_url=reverse("lookup_tts", args=[lookup.id]),
            syllable_audio_url=reverse(
                "lookup_phonics_audio",
                args=[lookup.id, "syllable"],
            ),
            phoneme_audio_url=reverse(
                "lookup_phonics_audio",
                args=[lookup.id, "phoneme"],
            ),
            lookup=lookup,
        ),
    )


def _phonics_audio_response(request, *, token=None, lookup=None, mode):
    if (token is None) == (lookup is None):
        return JsonResponse(
            {"ok": False, "error": "拼读对象无效。"},
            status=400,
        )
    if mode not in {"syllable", "phoneme"}:
        return JsonResponse(
            {"ok": False, "error": "未知的拼读模式。"},
            status=400,
        )

    display_word = token.surface if token is not None else lookup.display_word
    data = phonics_for_word(display_word, request.user.accent)
    if not data.phonemes:
        return JsonResponse(
            {"ok": False, "error": "这个单词还没有可用的拼读数据。"},
            status=400,
        )
    target_kwargs = (
        {"sentence": token.sentence} if token is not None else {"lookup": lookup}
    )

    if mode == "syllable":
        try:
            provider = get_tts_provider(data.accent)
        except TTSError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=503)

        text = syllable_audio_text(data)
        cache_key = tts_cache_key(
            provider=provider.provider,
            model=provider.model,
            voice=provider.voice,
            style="phonics_syllable",
            speed="word",
            rate=provider.speech_rate("word"),
            text=text,
            context=data.accent,
        )
        existing = (
            WordTtsRender.objects.filter(
                owner=request.user,
                cache_key=cache_key,
            )
            .select_related("audio")
            .first()
        )
        if existing is not None:
            return JsonResponse(
                {
                    "ok": True,
                    "audio_url": reverse(
                        "serve_audio_asset",
                        args=[existing.audio_id],
                    ),
                    "cached": True,
                    "duration_ms": existing.audio.duration_ms,
                }
            )
        try:
            consume_tts_quota(request.user, len(text))
            result = provider.synthesize(
                text,
                speed="word",
                style="natural",
            )
        except TTSQuotaExceeded as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=429)
        except TTSError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=502)
        try:
            render = create_word_tts_render(
                owner=request.user,
                word=display_word,
                result=result,
                cache_key=cache_key,
                **target_kwargs,
            )
        except Exception:
            return JsonResponse(
                {"ok": False, "error": "音节示范音频保存失败，请稍后再试。"},
                status=500,
            )
    else:
        cache_key = tts_cache_key(
            provider="human_phonemes",
            model="ipa",
            voice=HUMAN_VOICE,
            style="phonics_phoneme",
            speed="phonics",
            rate=0,
            text=data.display_word,
            context=f"{data.accent}:v3",
        )
        existing = (
            WordTtsRender.objects.filter(
                owner=request.user,
                cache_key=cache_key,
            )
            .select_related("audio")
            .first()
        )
        if existing is not None:
            return JsonResponse(
                {
                    "ok": True,
                    "audio_url": reverse(
                        "serve_audio_asset",
                        args=[existing.audio_id],
                    ),
                    "cached": True,
                    "duration_ms": existing.audio.duration_ms,
                }
            )
        try:
            wav, voice, duration_ms = generate_phoneme_audio(data)
        except PhonicsError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=503)
        result = TTSResult(
            data=wav,
            content_type="audio/wav",
            extension="wav",
            duration_ms=duration_ms,
            provider="human_phonemes",
            model="ipa",
            voice=HUMAN_VOICE,
            style="phonics",
        )
        try:
            render = create_word_tts_render(
                owner=request.user,
                word=display_word,
                result=result,
                cache_key=cache_key,
                **target_kwargs,
            )
        except Exception:
            return JsonResponse(
                {"ok": False, "error": "音素示范音频保存失败，请稍后再试。"},
                status=500,
            )

    return JsonResponse(
        {
            "ok": True,
            "audio_url": reverse("serve_audio_asset", args=[render.audio_id]),
            "cached": False,
            "duration_ms": result.duration_ms,
        }
    )


@login_required
@require_POST
@never_cache
def word_phonics_audio(request, token_id, mode):
    token = _owned_token(request, token_id)
    return _phonics_audio_response(request, token=token, mode=mode)


@login_required
@require_POST
@never_cache
def lookup_phonics_audio(request, lookup_id, mode):
    lookup = get_object_or_404(WordLookup, pk=lookup_id)
    return _phonics_audio_response(request, lookup=lookup, mode=mode)


@login_required
@never_cache
def word_lookup(request):
    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    lookup = None
    error = ""
    if request.method == "POST" or (request.method == "GET" and query):
        try:
            lookup = lookup_word(request.user, query)
        except ValidationError as exc:
            error = "；".join(exc.messages)
        except TranslationQuotaExceeded as exc:
            error = str(exc)
        except TranslationError as exc:
            error = str(exc)

    accent = request.user.accent
    if lookup is not None:
        lookup.display_ipa = (
            lookup.ipa_uk if accent == "uk" else lookup.ipa
        )
    lookup_url = reverse("word_lookup")
    accent_next = (
        f"{lookup_url}?{urlencode({'q': query})}" if query else lookup_url
    )

    return render(
        request,
        "diaries/lookup.html",
        {
            "query": query,
            "lookup": lookup,
            "error": error,
            "tts": _tts_status(),
            "assessment": _assessment_status(),
            "accent": accent,
            "accent_label": accent_label(accent),
            "accent_next": accent_next,
        },
    )


@login_required
@require_POST
@never_cache
def lookup_tts(request, lookup_id):
    lookup = get_object_or_404(WordLookup, pk=lookup_id)
    try:
        provider = get_tts_provider(request.user.accent)
    except TTSError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)

    style = "natural"
    speed = "word"
    text = lookup.word
    context = word_tts_context(text)
    cache_key = tts_cache_key(
        provider=provider.provider,
        model=provider.model,
        voice=provider.voice,
        style=style,
        speed=speed,
        rate=provider.speech_rate(speed),
        text=text,
        context=context,
    )
    existing = (
        WordTtsRender.objects.filter(owner=request.user, cache_key=cache_key)
        .select_related("audio")
        .first()
    )
    if existing is not None:
        return JsonResponse(
            {
                "ok": True,
                "audio_url": reverse(
                    "serve_audio_asset", args=[existing.audio_id]
                ),
                "cached": True,
                "duration_ms": existing.audio.duration_ms,
            }
        )

    try:
        consume_tts_quota(request.user, len(text))
        result = provider.synthesize(
            text, speed=speed, style=style, context_text=context
        )
        render = create_word_tts_render(
            owner=request.user,
            lookup=lookup,
            word=lookup.display_word,
            result=result,
            cache_key=cache_key,
        )
    except TTSQuotaExceeded as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=429)
    except TTSError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "单词发音生成失败，请稍后再试。"},
            status=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "audio_url": reverse("serve_audio_asset", args=[render.audio_id]),
            "cached": False,
            "duration_ms": result.duration_ms,
        }
    )


@login_required
@require_POST
@never_cache
def assess_lookup(request, lookup_id):
    lookup = get_object_or_404(WordLookup, pk=lookup_id)
    uploaded = request.FILES.get("audio")
    if uploaded is None:
        return JsonResponse({"ok": False, "error": "没有收到录音文件。"}, status=400)

    data = uploaded.read()
    try:
        duration_ms = validate_assessment_wav(data)
    except AudioValidationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    try:
        assessor = get_assessor()
    except AssessmentError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)

    try:
        consume_assessment_quota(request.user, lookup.word)
    except AssessmentQuotaExceeded as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=429)

    try:
        result = assessor.assess(lookup.word, data)
    except AssessmentError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "单词测评失败，请稍后再试。"},
            status=500,
        )

    try:
        attempt = create_pronunciation_attempt(
            owner=request.user,
            lookup=lookup,
            data=data,
            duration_ms=duration_ms,
            result=result,
        )
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "测评结果保存失败，请稍后再试。"},
            status=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "attempt_id": str(attempt.id),
            "overall_score": result.overall_score,
            "accuracy": result.accuracy,
            "fluency": result.fluency,
            "completeness": result.completeness,
            "match_tag": result.match_tag,
            "detail": result.detail,
            "audio_url": reverse("serve_audio_asset", args=[attempt.audio_id]),
        }
    )


@login_required
@require_POST
@never_cache
def upload_recording(request, sentence_id):
    sentence = _owned_sentence(request, sentence_id)
    uploaded = request.FILES.get("audio")
    if uploaded is None:
        return JsonResponse({"ok": False, "error": "没有收到录音文件。"}, status=400)
    if uploaded.size > MAX_AUDIO_BYTES:
        return JsonResponse(
            {"ok": False, "error": "录音文件太大，最大 5 MB。"},
            status=400,
        )

    try:
        data = uploaded.read()
        duration_ms = validate_recording_wav(data)
    except AudioValidationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except OSError:
        return JsonResponse(
            {"ok": False, "error": "读取录音失败，请重新录制。"},
            status=400,
        )

    try:
        recording = create_recording(
            owner=request.user,
            sentence=sentence,
            data=data,
            duration_ms=duration_ms,
        )
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "保存录音失败，请稍后再试。"},
            status=500,
        )

    response = JsonResponse(
        {
            "ok": True,
            "recording_id": str(recording.id),
            "audio_url": reverse("serve_audio_asset", args=[recording.audio_id]),
            "delete_url": reverse("delete_recording", args=[recording.id]),
            "created_at_label": timezone.localtime(recording.created_at).strftime(
                "%m-%d %H:%M"
            ),
            "recording_count": Recording.objects.filter(
                owner=request.user,
                sentence=sentence,
            ).count(),
            "duration_ms": duration_ms,
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
@never_cache
def delete_recording(request, recording_id):
    """Delete one of the signed-in user's sentence recordings and its file."""
    recording = get_object_or_404(
        Recording.objects.select_related("audio", "sentence"),
        id=recording_id,
        owner=request.user,
    )
    sentence = recording.sentence
    audio = recording.audio
    relative_path = audio.relative_path

    with transaction.atomic():
        recording.delete()
        audio.delete()

    try:
        remove_private_bytes(relative_path)
    except OSError:
        logger.warning(
            "Could not remove private recording file %s",
            relative_path,
            exc_info=True,
        )

    remaining = Recording.objects.filter(
        owner=request.user,
        sentence=sentence,
    ).count()
    response = JsonResponse(
        {
            "ok": True,
            "recording_id": str(recording_id),
            "remaining": remaining,
        }
    )
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["GET", "HEAD"])
@never_cache
def serve_audio_asset(request, asset_id):
    """Serve one private audio file, including byte ranges needed by Safari."""
    asset = get_object_or_404(AudioAsset, pk=asset_id, owner=request.user)
    try:
        data = read_private_bytes(asset.relative_path)
    except (OSError, ValueError) as exc:
        raise Http404("Audio file unavailable") from exc

    size = len(data)
    range_header = request.headers.get("Range")
    is_head = request.method == "HEAD"

    if range_header:
        try:
            start, end = parse_byte_range(range_header, size)
        except RangeNotSatisfiable:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            response["Accept-Ranges"] = "bytes"
            response["Cache-Control"] = "private, no-store"
            response["Content-Length"] = "0"
            return response
        payload = data[start : end + 1]
        response = HttpResponse(
            b"" if is_head else payload,
            status=206,
            content_type=asset.content_type,
        )
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(len(payload))
    else:
        response = HttpResponse(
            b"" if is_head else data,
            status=200,
            content_type=asset.content_type,
        )
        response["Content-Length"] = str(size)

    extension = asset.relative_path.rsplit(".", 1)[-1] if "." in asset.relative_path else "bin"
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = f'inline; filename="{asset.id}.{extension}"'
    return response
