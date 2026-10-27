"""Diary ownership, translation, IPA, versioning, and quota tests."""

import io
import json
from pathlib import Path
import tempfile
import wave

import httpx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Family, User
from services.audio import (
    AudioValidationError,
    RangeNotSatisfiable,
    parse_byte_range,
    validate_recording_wav,
)
from services.pronunciation import analyze_sentence, clean_manual_ipa, ipa_for_word
from services.text import split_english_sentences
from services.translation import (
    DeepSeekTranslator,
    MockTranslator,
    TranslationError,
    get_translator,
)

from .models import (
    AudioAsset,
    DiaryEntry,
    EnglishVersion,
    Recording,
    Sentence,
    TtsRender,
    UsageCounter,
    WordToken,
)
from .services import create_english_version

MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"
PASSWORD = "Brisk-Cobalt-Orbit-42"


def make_user(family, *, phone, display_name, role=User.Role.MEMBER):
    return User.objects.create_user(
        phone=phone,
        password=PASSWORD,
        display_name=display_name,
        family=family,
        role=role,
    )


def make_diary(owner, *, chinese_text="今天天气很好。", title="测试日记"):
    return DiaryEntry.objects.create(
        owner=owner,
        entry_date=timezone.localdate(),
        title=title,
        chinese_text=chinese_text,
    )


class PronunciationServiceTests(TestCase):
    def test_known_words_have_american_ipa_and_stress(self):
        self.assertEqual(ipa_for_word("water"), "ˈwɔtər")
        self.assertEqual(ipa_for_word("thought"), "ˈθɔt")
        self.assertEqual(ipa_for_word("comfortable"), "ˈkʌmfərtəbəl")
        self.assertEqual(ipa_for_word("don't"), "ˈdoʊnt")

    def test_unknown_word_is_not_guessed(self):
        self.assertIsNone(ipa_for_word("shazhengzhong"))

    def test_analyze_sentence_marks_unknown_and_preserves_order(self):
        tokens = analyze_sentence("I wrote water for Shazhengzhong.")
        self.assertEqual(
            [token.surface for token in tokens],
            ["I", "wrote", "water", "for", "Shazhengzhong"],
        )
        self.assertTrue(tokens[0].ipa)
        self.assertEqual(tokens[-1].source, "unknown")
        self.assertEqual(tokens[-1].ipa, "")

    def test_manual_ipa_cleaning(self):
        self.assertEqual(clean_manual_ipa(" /ˈwɔtər/ "), "ˈwɔtər")
        self.assertEqual(clean_manual_ipa(""), "")
        with self.assertRaises(ValueError):
            clean_manual_ipa("<script>")
        with self.assertRaises(ValueError):
            clean_manual_ipa("x" * 121)


class TextServiceTests(TestCase):
    def test_split_lines_and_fallback_punctuation(self):
        self.assertEqual(
            split_english_sentences("One sentence. Two sentences?\nThird!"),
            ["One sentence.", "Two sentences?", "Third!"],
        )

    def test_strips_simple_bullets_and_ignores_blank_lines(self):
        self.assertEqual(
            split_english_sentences("- Hello there.\n\n* How are you?"),
            ["Hello there.", "How are you?"],
        )

    def test_empty_text(self):
        self.assertEqual(split_english_sentences(" \n "), [])


class TranslationServiceTests(TestCase):
    def test_mock_translator_does_not_use_network(self):
        result = MockTranslator().translate("今天很好。")
        self.assertIn("Today I wrote", result)

    def test_deepseek_request_shape_and_response(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["authorization"] = request.headers.get("Authorization")
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                request=request,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "Hello there.\nHow are you?"
                            }
                        }
                    ]
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        translator = DeepSeekTranslator(
            api_key="test-key",
            base_url="https://api.example.invalid",
            model="deepseek-chat",
            client=client,
        )
        result = translator.translate("你好。")

        self.assertEqual(result, "Hello there.\nHow are you?")
        self.assertEqual(
            captured["url"], "https://api.example.invalid/chat/completions"
        )
        self.assertEqual(captured["authorization"], "Bearer test-key")
        self.assertEqual(captured["payload"]["model"], "deepseek-chat")
        self.assertEqual(captured["payload"]["messages"][0]["role"], "system")
        self.assertEqual(captured["payload"]["messages"][1]["content"], "你好。")

    def test_deepseek_http_error_is_generic(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        translator = DeepSeekTranslator(
            api_key="test-key",
            base_url="https://api.example.invalid",
            model="deepseek-chat",
            client=client,
        )
        with self.assertRaises(TranslationError):
            translator.translate("你好。")

    @override_settings(TRANSLATION_PROVIDER="deepseek", DEEPSEEK_API_KEY="")
    def test_missing_key_is_rejected_without_network(self):
        with self.assertRaises(TranslationError):
            get_translator()


class DiaryFixtureMixin:
    def setUp(self):
        self.family = Family.objects.create(name="测试家庭")
        self.owner = make_user(
            self.family,
            phone="+8613800000000",
            display_name="管理员",
            role=User.Role.OWNER,
        )
        self.member = make_user(
            self.family,
            phone="+8613900000000",
            display_name="成员",
        )
        self.client.force_login(self.owner, backend=MODEL_BACKEND)


class DiaryPageTests(DiaryFixtureMixin, TestCase):
    def test_list_requires_login_and_only_shows_own_diaries(self):
        own = make_diary(self.owner, title="我的日记")
        other = make_diary(self.member, title="成员日记")
        response = self.client.get(reverse("diary_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own.title)
        self.assertNotContains(response, other.title)

        self.client.logout()
        response = self.client.get(reverse("diary_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_owner_cannot_access_member_detail(self):
        other = make_diary(self.member)
        response = self.client.get(reverse("diary_detail", args=[other.id]))
        self.assertEqual(response.status_code, 404)

    def test_create_diary_is_owner_scoped(self):
        response = self.client.post(
            reverse("diary_create"),
            {
                "entry_date": timezone.localdate().isoformat(),
                "title": "今天",
                "chinese_text": "今天我去公园散步。",
            },
        )
        self.assertEqual(response.status_code, 302)
        diary = DiaryEntry.objects.get(title="今天")
        self.assertEqual(diary.owner, self.owner)

    def test_edit_chinese_diary(self):
        diary = make_diary(self.owner, title="旧标题")
        response = self.client.post(
            reverse("diary_edit", args=[diary.id]),
            {
                "entry_date": diary.entry_date.isoformat(),
                "title": "新标题",
                "chinese_text": "修改后的中文。",
            },
        )
        self.assertEqual(response.status_code, 302)
        diary.refresh_from_db()
        self.assertEqual(diary.title, "新标题")
        self.assertEqual(diary.chinese_text, "修改后的中文。")

    def test_delete_diary_requires_confirmation_and_cascades(self):
        diary = make_diary(self.owner)
        version = EnglishVersion.objects.create(
            diary=diary,
            version_no=1,
            english_text="Hello.",
            source=EnglishVersion.Source.MANUAL,
            source_chinese_hash="hash",
        )
        sentence = Sentence.objects.create(version=version, ordinal=0, text="Hello.")
        WordToken.objects.create(
            sentence=sentence,
            ordinal=0,
            surface="Hello",
            ipa="həˈloʊ",
            source=WordToken.Source.MANUAL,
        )

        self.assertEqual(
            self.client.get(reverse("diary_delete", args=[diary.id])).status_code,
            200,
        )
        response = self.client.post(reverse("diary_delete", args=[diary.id]))
        self.assertRedirects(response, reverse("diary_list"))
        self.assertFalse(DiaryEntry.objects.filter(pk=diary.pk).exists())
        self.assertEqual(Sentence.objects.count(), 0)
        self.assertEqual(WordToken.objects.count(), 0)

    def test_translation_requires_post(self):
        diary = make_diary(self.owner)
        response = self.client.get(reverse("diary_translate", args=[diary.id]))
        self.assertEqual(response.status_code, 405)

    def test_cross_user_mutations_return_404(self):
        other = make_diary(self.member)
        version = EnglishVersion.objects.create(
            diary=other,
            version_no=1,
            english_text="Hello.",
            source=EnglishVersion.Source.MANUAL,
            source_chinese_hash="hash",
        )
        sentence = Sentence.objects.create(version=version, ordinal=0, text="Hello.")
        token = WordToken.objects.create(
            sentence=sentence,
            ordinal=0,
            surface="Hello",
            ipa="həˈloʊ",
            source=WordToken.Source.DICTIONARY,
        )
        checks = [
            ("get", reverse("diary_detail", args=[other.id])),
            ("get", reverse("diary_edit", args=[other.id])),
            ("get", reverse("diary_edit_english", args=[other.id])),
            ("post", reverse("diary_translate", args=[other.id])),
            ("get", reverse("diary_delete", args=[other.id])),
            ("post", reverse("diary_delete", args=[other.id])),
            ("get", reverse("edit_sentence_ipa", args=[sentence.id])),
            (
                "post",
                reverse("edit_sentence_ipa", args=[sentence.id]),
                {f"ipa_{token.pk.hex}": "test"},
            ),
        ]
        for method, url, *payload in checks:
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(
                    url, *(payload or [{}])
                )
                self.assertEqual(response.status_code, 404)
        self.assertTrue(DiaryEntry.objects.filter(pk=other.pk).exists())


class TranslationFlowTests(DiaryFixtureMixin, TestCase):
    def test_mock_translation_creates_version_sentences_and_ipa(self):
        diary = make_diary(self.owner)
        response = self.client.post(reverse("diary_translate", args=[diary.id]))
        self.assertRedirects(response, reverse("diary_detail", args=[diary.id]))

        version = diary.current_version
        self.assertIsNotNone(version)
        self.assertEqual(version.source, EnglishVersion.Source.MOCK)
        self.assertEqual(version.version_no, 1)
        self.assertGreaterEqual(version.sentences.count(), 3)
        self.assertTrue(WordToken.objects.filter(sentence__version=version).exists())
        self.assertEqual(
            UsageCounter.objects.get(user=self.owner, feature="translation").request_count,
            1,
        )

        detail = self.client.get(reverse("diary_detail", args=[diary.id]))
        self.assertContains(detail, "模拟翻译模式")
        self.assertContains(detail, "ˈ")

    def test_retranslate_creates_new_version_and_preserves_old(self):
        diary = make_diary(self.owner)
        self.client.post(reverse("diary_translate", args=[diary.id]))
        self.client.post(reverse("diary_translate", args=[diary.id]))
        versions = list(diary.english_versions.order_by("version_no"))
        self.assertEqual([v.version_no for v in versions], [1, 2])
        self.assertEqual(diary.current_version.version_no, 2)

    @override_settings(TRANSLATION_DAILY_REQUEST_LIMIT=1)
    def test_translation_daily_quota_blocks_second_call(self):
        diary = make_diary(self.owner)
        self.client.post(reverse("diary_translate", args=[diary.id]))
        response = self.client.post(
            reverse("diary_translate", args=[diary.id]),
            follow=True,
        )
        self.assertContains(response, "今天最多翻译 1 次")
        self.assertEqual(diary.english_versions.count(), 1)

    def test_manual_english_marks_unknown_tokens(self):
        diary = make_diary(self.owner)
        response = self.client.post(
            reverse("diary_edit_english", args=[diary.id]),
            {"english_text": "Shazhengzhong reads water."},
        )
        self.assertRedirects(response, reverse("diary_detail", args=[diary.id]))
        version = diary.current_version
        self.assertEqual(version.source, EnglishVersion.Source.MANUAL)
        unknown = WordToken.objects.get(surface="Shazhengzhong")
        self.assertEqual(unknown.source, WordToken.Source.UNKNOWN)
        self.assertEqual(unknown.ipa, "")

    def test_editing_chinese_marks_english_as_stale(self):
        diary = make_diary(self.owner)
        self.client.post(reverse("diary_translate", args=[diary.id]))
        self.client.post(
            reverse("diary_edit", args=[diary.id]),
            {
                "entry_date": diary.entry_date.isoformat(),
                "title": diary.title or "",
                "chinese_text": "中文后来改了。",
            },
        )
        response = self.client.get(reverse("diary_detail", args=[diary.id]))
        self.assertContains(response, "中文日记在生成这版英文后又修改过")

    def test_ipa_correction_updates_only_owned_current_text(self):
        diary = make_diary(self.owner)
        self.client.post(
            reverse("diary_edit_english", args=[diary.id]),
            {"english_text": "I read water."},
        )
        sentence = diary.current_version.sentences.first()
        tokens = list(sentence.tokens.all())
        target = next(token for token in tokens if token.surface.lower() == "water")
        data = {f"ipa_{token.pk.hex}": token.ipa for token in tokens}
        data[f"ipa_{target.pk.hex}"] = "ˈwɔtər"

        response = self.client.post(
            reverse("edit_sentence_ipa", args=[sentence.id]),
            data,
        )
        self.assertRedirects(response, reverse("diary_detail", args=[diary.id]))
        target.refresh_from_db()
        self.assertEqual(target.source, WordToken.Source.MANUAL)
        self.assertEqual(target.ipa, "ˈwɔtər")

    def test_invalid_ipa_is_rejected(self):
        diary = make_diary(self.owner)
        self.client.post(
            reverse("diary_edit_english", args=[diary.id]),
            {"english_text": "I read water."},
        )
        sentence = diary.current_version.sentences.first()
        tokens = list(sentence.tokens.all())
        target = next(token for token in tokens if token.surface.lower() == "water")
        original = target.ipa
        data = {f"ipa_{token.pk.hex}": token.ipa for token in tokens}
        data[f"ipa_{target.pk.hex}"] = "<bad>"
        response = self.client.post(
            reverse("edit_sentence_ipa", args=[sentence.id]),
            data,
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.ipa, original)


class AudioUtilityTests(TestCase):
    @staticmethod
    def make_wav(duration_ms=500, rate=16000, channels=1, sample_width=2):
        frame_count = int(rate * duration_ms / 1000)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(sample_width)
            wav.setframerate(rate)
            wav.writeframes(b"\x00\x00" * frame_count * channels * (sample_width // 2))
        return buffer.getvalue()

    def test_valid_wav(self):
        self.assertEqual(validate_recording_wav(self.make_wav(500)), 500)

    def test_rejects_wrong_channels_rate_and_too_long(self):
        cases = [
            self.make_wav(channels=2),
            self.make_wav(rate=8000),
            self.make_wav(duration_ms=61_000),
        ]
        for data in cases:
            with self.subTest(), self.assertRaises(AudioValidationError):
                validate_recording_wav(data)

    def test_rejects_non_wav(self):
        with self.assertRaises(AudioValidationError):
            validate_recording_wav(b"not a wav file")

    def test_byte_ranges(self):
        self.assertEqual(parse_byte_range("bytes=0-99", 1000), (0, 99))
        self.assertEqual(parse_byte_range("bytes=900-", 1000), (900, 999))
        self.assertEqual(parse_byte_range("bytes=-50", 1000), (950, 999))
        self.assertEqual(parse_byte_range("bytes=999-2000", 1000), (999, 999))
        for value in ("bytes=1000-", "bytes=20-10", "bytes=abc", "bytes=-0"):
            with self.subTest(value=value), self.assertRaises(RangeNotSatisfiable):
                parse_byte_range(value, 1000)


class AudioTestBase(DiaryFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(PRIVATE_MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_dir.cleanup)

    def make_sentence(self, owner=None, text="I read water slowly."):
        owner = owner or self.owner
        diary = make_diary(owner)
        version = create_english_version(diary, text, source="manual")
        return diary, version.sentences.first()

    @staticmethod
    def wav_bytes(duration_ms=500):
        rate = 16000
        frame_count = int(rate * duration_ms / 1000)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(b"\x00\x00" * frame_count)
        return buffer.getvalue()


class RecordingAndAudioTests(AudioTestBase):
    def test_upload_recording_creates_private_asset(self):
        diary, sentence = self.make_sentence()
        wav_data = self.wav_bytes()
        upload = SimpleUploadedFile("voice.wav", wav_data, content_type="audio/wav")
        response = self.client.post(
            reverse("upload_recording", args=[sentence.id]),
            {"audio": upload},
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("/diaries/audio/", payload["audio_url"])

        asset = AudioAsset.objects.get(owner=self.owner, purpose=AudioAsset.Purpose.RECORDING)
        recording = Recording.objects.get(owner=self.owner, sentence=sentence)
        self.assertEqual(recording.audio, asset)
        self.assertEqual(recording.duration_ms, 500)
        stored_path = Path(self.media_dir.name) / asset.relative_path
        self.assertTrue(stored_path.exists())
        self.assertEqual(stored_path.read_bytes(), wav_data)

    def test_invalid_recording_is_rejected(self):
        _, sentence = self.make_sentence()
        upload = SimpleUploadedFile("voice.wav", b"not a wav", content_type="audio/wav")
        response = self.client.post(
            reverse("upload_recording", args=[sentence.id]),
            {"audio": upload},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Recording.objects.exists())
        self.assertFalse(AudioAsset.objects.exists())

    def test_cross_user_upload_is_404(self):
        _, member_sentence = self.make_sentence(self.member)
        upload = SimpleUploadedFile("voice.wav", self.wav_bytes(), content_type="audio/wav")
        response = self.client.post(
            reverse("upload_recording", args=[member_sentence.id]),
            {"audio": upload},
        )
        self.assertEqual(response.status_code, 404)

    def test_audio_requires_login_and_ownership(self):
        _, sentence = self.make_sentence()
        upload = SimpleUploadedFile("voice.wav", self.wav_bytes(), content_type="audio/wav")
        self.client.post(reverse("upload_recording", args=[sentence.id]), {"audio": upload})
        asset = AudioAsset.objects.get(owner=self.owner)
        url = reverse("serve_audio_asset", args=[asset.id])

        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.member, backend=MODEL_BACKEND)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.owner, backend=MODEL_BACKEND)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "audio/wav")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertIn("no-store", response["Cache-Control"])

    def test_audio_range_and_head_requests(self):
        _, sentence = self.make_sentence()
        wav_data = self.wav_bytes()
        upload = SimpleUploadedFile("voice.wav", wav_data, content_type="audio/wav")
        self.client.post(reverse("upload_recording", args=[sentence.id]), {"audio": upload})
        asset = AudioAsset.objects.get(owner=self.owner)
        url = reverse("serve_audio_asset", args=[asset.id])

        ranged = self.client.get(url, HTTP_RANGE="bytes=0-99")
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(ranged.content, wav_data[:100])
        self.assertEqual(ranged["Content-Range"], f"bytes 0-99/{len(wav_data)}")

        suffix = self.client.get(url, HTTP_RANGE="bytes=-64")
        self.assertEqual(suffix.status_code, 206)
        self.assertEqual(suffix.content, wav_data[-64:])

        head = self.client.head(url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertEqual(head["Content-Length"], str(len(wav_data)))

        invalid = self.client.get(url, HTTP_RANGE=f"bytes={len(wav_data)}-")
        self.assertEqual(invalid.status_code, 416)

    def test_deleting_diary_removes_audio_file(self):
        diary, sentence = self.make_sentence()
        upload = SimpleUploadedFile("voice.wav", self.wav_bytes(), content_type="audio/wav")
        self.client.post(reverse("upload_recording", args=[sentence.id]), {"audio": upload})
        asset = AudioAsset.objects.get(owner=self.owner)
        path = Path(self.media_dir.name) / asset.relative_path
        self.assertTrue(path.exists())

        response = self.client.post(reverse("diary_delete", args=[diary.id]))
        self.assertRedirects(response, reverse("diary_list"))
        self.assertFalse(path.exists())
        self.assertFalse(AudioAsset.objects.exists())


class TTSFlowTests(AudioTestBase):
    def test_mock_tts_generates_private_audio_and_cache(self):
        diary, sentence = self.make_sentence()
        url = reverse("sentence_tts", args=[sentence.id, "normal"])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        render = TtsRender.objects.get(owner=self.owner, sentence=sentence)
        self.assertEqual(render.speed, TtsRender.Speed.NORMAL)
        self.assertEqual(render.provider, "mock")
        self.assertEqual(render.char_count, len(sentence.text))
        path = Path(self.media_dir.name) / render.audio.relative_path
        self.assertTrue(path.exists())
        self.assertEqual(render.audio.content_type, "audio/wav")
        counter = UsageCounter.objects.get(user=self.owner, feature="tts")
        self.assertEqual(counter.request_count, 1)

        # A second click uses the cache and does not consume quota again.
        self.client.post(url)
        self.assertEqual(TtsRender.objects.count(), 1)
        counter.refresh_from_db()
        self.assertEqual(counter.request_count, 1)

        detail = self.client.get(reverse("diary_detail", args=[diary.id]))
        self.assertContains(detail, "模拟提示音")
        self.assertContains(detail, "我的录音")

    def test_normal_and_slow_have_separate_cache_entries(self):
        _, sentence = self.make_sentence()
        self.client.post(reverse("sentence_tts", args=[sentence.id, "normal"]))
        self.client.post(reverse("sentence_tts", args=[sentence.id, "slow"]))
        renders = TtsRender.objects.filter(owner=self.owner, sentence=sentence)
        self.assertEqual(renders.count(), 2)
        self.assertEqual(
            set(renders.values_list("speed", flat=True)),
            {TtsRender.Speed.NORMAL, TtsRender.Speed.SLOW},
        )

    @override_settings(TTS_DAILY_CHAR_LIMIT=1)
    def test_tts_quota_blocks_generation(self):
        _, sentence = self.make_sentence()
        response = self.client.post(
            reverse("sentence_tts", args=[sentence.id, "normal"]),
            follow=True,
        )
        self.assertContains(response, "字符额度")
        self.assertFalse(TtsRender.objects.exists())

    @override_settings(TTS_PROVIDER="volcengine")
    def test_real_tts_is_not_accidentally_enabled(self):
        _, sentence = self.make_sentence()
        response = self.client.post(
            reverse("sentence_tts", args=[sentence.id, "normal"]),
            follow=True,
        )
        self.assertContains(response, "尚未接入")
        self.assertFalse(TtsRender.objects.exists())

    def test_cross_user_and_anonymous_cannot_access_tts_audio(self):
        _, sentence = self.make_sentence()
        self.client.post(reverse("sentence_tts", args=[sentence.id, "normal"]))
        render = TtsRender.objects.get(owner=self.owner)
        url = reverse("serve_audio_asset", args=[render.audio_id])

        self.client.force_login(self.member, backend=MODEL_BACKEND)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_tts_endpoints_require_post_and_correct_speed(self):
        _, sentence = self.make_sentence()
        self.assertEqual(
            self.client.get(reverse("sentence_tts", args=[sentence.id, "normal"])).status_code,
            405,
        )
        self.assertEqual(
            self.client.post(reverse("sentence_tts", args=[sentence.id, "fast"])).status_code,
            404,
        )

    def test_tts_upload_endpoint_rejects_other_users_sentence(self):
        _, member_sentence = self.make_sentence(self.member)
        response = self.client.post(
            reverse("sentence_tts", args=[member_sentence.id, "normal"])
        )
        self.assertEqual(response.status_code, 404)

    def test_deleting_diary_removes_tts_audio_file(self):
        diary, sentence = self.make_sentence()
        self.client.post(reverse("sentence_tts", args=[sentence.id, "normal"]))
        render = TtsRender.objects.get(owner=self.owner)
        path = Path(self.media_dir.name) / render.audio.relative_path
        self.assertTrue(path.exists())
        self.client.post(reverse("diary_delete", args=[diary.id]))
        self.assertFalse(path.exists())
        self.assertFalse(TtsRender.objects.exists())
