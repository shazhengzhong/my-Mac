"""Owner-scoped diary and pronunciation pages."""

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
    validate_assessment_wav,
    validate_recording_wav,
)
from services.pronunciation import syllable_hint
from services.translation import TranslationError, get_translator
from services.tts import TTSError, get_tts_provider, tts_cache_key, word_tts_context

from .forms import DiaryForm, EnglishVersionForm, IpaCorrectionForm
from .models import (
    AudioAsset,
    DiaryEntry,
    DiaryReadAloud,
    PronunciationAttempt,
    Sentence,
    TtsRender,
    WordToken,
    WordTtsRender,
)
from .services import (
    AssessmentQuotaExceeded,
    TTSQuotaExceeded,
    TranslationQuotaExceeded,
    consume_assessment_quota,
    consume_translation_quota,
    consume_tts_quota,
    create_aligned_english_version,
    create_diary_read_aloud,
    create_english_version,
    create_pronunciation_attempt,
    create_recording,
    create_tts_render,
    create_word_tts_render,
)


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
        sentence_ids = [sentence.id for sentence in sentences]
        renders = TtsRender.objects.filter(
            owner=request.user,
            sentence_id__in=sentence_ids,
        ).select_related("audio")
        tts_map = {(render.sentence_id, render.speed): render for render in renders}
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
    previous_chinese_ordinal = None
    has_aligned_chinese = False
    bilingual_groups = []
    current_group = None
    for sentence in sentences:
        sentence.tts_normal = tts_map.get((sentence.id, TtsRender.Speed.NORMAL))
        sentence.tts_slow = tts_map.get((sentence.id, TtsRender.Speed.SLOW))
        for token in sentence.tokens.all():
            token.latest_assessment = assessment_map.get(token.id)
            token.syllable_hint = syllable_hint(token.surface)
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
    if version is None:
        return JsonResponse({"ok": False, "error": "这篇日记还没有英文。"}, status=400)
    sentences = list(version.sentences.order_by("ordinal"))
    if not sentences:
        return JsonResponse(
            {"ok": False, "error": "这篇日记还没有英文句子。"},
            status=400,
        )

    existing = (
        DiaryReadAloud.objects.filter(owner=request.user, version=version)
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
                "duration_ms": existing.audio.duration_ms,
                "timings": existing.timings,
                "cached": True,
            }
        )

    try:
        provider = get_tts_provider()
    except TTSError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)

    full_text = "\n".join(sentence.text for sentence in sentences)
    try:
        consume_tts_quota(request.user, len(full_text))
        result = provider.synthesize(
            full_text,
            speed="normal",
            style="natural",
            enable_subtitles=True,
        )
        read_aloud = create_diary_read_aloud(
            owner=request.user,
            version=version,
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
    form = IpaCorrectionForm(request.POST or None, tokens=tokens)
    rows = [
        {"token": token, "field": form[field_name]}
        for token, field_name in form.token_fields
    ]
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            for token, value in form.corrections():
                if value:
                    WordToken.objects.filter(pk=token.pk).update(
                        ipa=value,
                        source=WordToken.Source.MANUAL,
                    )
                else:
                    WordToken.objects.filter(pk=token.pk).update(
                        ipa="",
                        source=WordToken.Source.UNKNOWN,
                    )
        messages.success(request, "音标已更新。")
        return redirect("diary_detail", diary_id=sentence.version.diary_id)

    return render(
        request,
        "diaries/ipa_edit.html",
        {"sentence": sentence, "form": form, "tokens": tokens, "rows": rows},
    )


@login_required
@require_POST
@never_cache
def generate_sentence_tts(request, sentence_id, speed):
    sentence = _owned_sentence(request, sentence_id)
    if speed not in TtsRender.Speed.values:
        raise Http404("Unknown TTS speed")

    try:
        provider = get_tts_provider()
    except TTSError as exc:
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
        messages.info(request, "这句的示范音频已经生成，直接使用缓存。")
        return _sentence_redirect(sentence.version.diary_id, sentence.id)

    try:
        consume_tts_quota(request.user, len(sentence.text))
        result = provider.synthesize(sentence.text, speed=speed, style=style)
        create_tts_render(
            owner=request.user,
            sentence=sentence,
            result=result,
            speed=speed,
            style=style,
            cache_key=cache_key,
        )
    except TTSQuotaExceeded as exc:
        messages.error(request, str(exc))
    except TTSError as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, "示范音频生成失败，请稍后再试。")
    else:
        messages.success(request, "示范音频已生成并缓存。")
    return _sentence_redirect(sentence.version.diary_id, sentence.id)


@login_required
@require_POST
@never_cache
def word_tts(request, token_id):
    token = _owned_token(request, token_id)
    try:
        provider = get_tts_provider()
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
            "audio_url": reverse("serve_audio_asset", args=[recording.audio_id]),
            "duration_ms": duration_ms,
        },
        status=201,
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
