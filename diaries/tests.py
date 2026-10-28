"""Diary ownership, translation, IPA, versioning, and quota tests."""

import base64
import hashlib
import hmac
import io
import json
from pathlib import Path
import tempfile
from urllib.parse import parse_qs, urlparse
import wave

import httpx
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Family, User
from services.assessment import (
    AssessmentError,
    MockAssessor,
    TencentSOEAssessor,
    get_assessor,
)
from services.audio import (
    AudioValidationError,
    RangeNotSatisfiable,
    parse_byte_range,
    validate_recording_wav,
)
from services.pronunciation import (
    analyze_sentence,
    clean_manual_ipa,
    ipa_for_word,
    syllable_hint,
)
from services.text import split_chinese_sentences, split_english_sentences
from services.translation import (
    DeepSeekTranslator,
    MockTranslator,
    TranslationError,
    TranslationPair,
    get_translator,
)
from services.tts import (
    MockTTSProvider,
    TTSError,
    VolcengineTTSProvider,
    get_tts_provider,
    tts_cache_key,
    word_tts_context,
)

from .models import (
    AudioAsset,
    DiaryEntry,
    DiaryReadAloud,
    EnglishVersion,
    PronunciationAttempt,
    Recording,
    Sentence,
    TtsRender,
    UsageCounter,
    WordLookup,
    WordToken,
    WordTtsRender,
)
from .services import (
    TranslationQuotaExceeded,
    create_aligned_english_version,
    create_english_version,
    lookup_word,
)

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

    def test_syllable_hint_splits_written_words(self):
        self.assertIn("·", syllable_hint("comfortable"))
        self.assertIn("·", syllable_hint("water"))
        self.assertEqual(syllable_hint("and"), "")
        self.assertEqual(syllable_hint("the"), "")

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

    def test_split_chinese_sentences_keeps_punctuation_and_ellipsis(self):
        text = "今天天气很好。我和家人去公园散步。\n晚上看电视！他说……后来呢？"
        self.assertEqual(
            split_chinese_sentences(text),
            [
                "今天天气很好。",
                "我和家人去公园散步。",
                "晚上看电视！",
                "他说……",
                "后来呢？",
            ],
        )

    def test_split_chinese_sentences_does_not_split_decimal_points(self):
        self.assertEqual(
            split_chinese_sentences("版本 1.5 很好。第二句。"),
            ["版本 1.5 很好。", "第二句。"],
        )
        self.assertEqual(split_chinese_sentences(" \n "), [])


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

    def test_mock_translator_returns_pairs_offline(self):
        pairs = MockTranslator().translate_pairs("今天很好。")
        self.assertEqual(len(pairs), 3)
        self.assertTrue(all(pair.chinese and pair.english for pair in pairs))

    def test_mock_translator_returns_word_translation(self):
        result = MockTranslator().translate_word("water")
        self.assertIn("water", result.translation)

    def test_deepseek_word_request_shape_and_response(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                request=request,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "translation": "水；水域",
                                        "part_of_speech": "n.",
                                    }
                                )
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
        result = translator.translate_word("water")

        self.assertEqual(result.translation, "水；水域")
        self.assertEqual(result.part_of_speech, "n.")
        self.assertEqual(
            captured["payload"]["messages"][1]["content"], "water"
        )
        self.assertIn(
            "English-Chinese dictionary",
            captured["payload"]["messages"][0]["content"],
        )

    def test_deepseek_pair_request_shape_and_response(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                request=request,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "translations": [
                                            "Hello there.",
                                            "How are you?",
                                        ]
                                    }
                                )
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
        pairs = translator.translate_pairs("你好。你好吗？")

        self.assertEqual([pair.chinese for pair in pairs], ["你好。", "你好吗？"])
        self.assertEqual(
            [pair.english for pair in pairs],
            ["Hello there.", "How are you?"],
        )
        self.assertIn(
            "translations", captured["payload"]["messages"][0]["content"]
        )
        self.assertEqual(
            json.loads(captured["payload"]["messages"][1]["content"]),
            ["你好。", "你好吗？"],
        )

    def test_deepseek_pair_count_mismatch_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                request=request,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"translations": ["Only one."]}
                                )
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
        with self.assertRaises(TranslationError):
            translator.translate_pairs("你好。你好吗？")


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

    def test_mock_translation_creates_chinese_alignment(self):
        diary = make_diary(self.owner)
        self.client.post(reverse("diary_translate", args=[diary.id]))

        version = diary.current_version
        sentences = list(version.sentences.order_by("ordinal"))
        self.assertTrue(all(sentence.chinese_text for sentence in sentences))
        self.assertEqual(
            [sentence.chinese_ordinal for sentence in sentences],
            [0, 1, 2],
        )

        detail = self.client.get(reverse("diary_detail", args=[diary.id]))
        self.assertContains(detail, "日记对照")
        self.assertContains(detail, "Today I wrote a short diary in Chinese.")
        self.assertContains(detail, 'data-view-mode="both"')
        self.assertContains(detail, 'data-view-mode="zh"')
        self.assertContains(detail, 'data-view-mode="en"')
        self.assertContains(detail, "en-only")
        self.assertContains(detail, "sentence-zh")
        self.assertContains(detail, "practice-zh")
        self.assertContains(detail, "今天我写了一篇中文日记。")

    def test_aligned_version_stores_grouped_sentences(self):
        diary = make_diary(self.owner)
        pairs = [
            TranslationPair("今天很好。", "It was a nice day. I went out."),
            TranslationPair("明天见。", "See you tomorrow."),
        ]
        version = create_aligned_english_version(
            diary,
            pairs,
            source="deepseek",
            provider_model="deepseek-chat",
        )

        sentences = list(version.sentences.order_by("ordinal"))
        self.assertEqual(
            [sentence.text for sentence in sentences],
            ["It was a nice day.", "I went out.", "See you tomorrow."],
        )
        self.assertEqual(
            [sentence.chinese_text for sentence in sentences],
            ["今天很好。", "今天很好。", "明天见。"],
        )
        self.assertEqual(
            [sentence.chinese_ordinal for sentence in sentences],
            [0, 0, 1],
        )

    def test_manual_english_version_shows_alignment_notice(self):
        diary = make_diary(self.owner)
        self.client.post(
            reverse("diary_edit_english", args=[diary.id]),
            {"english_text": "Hello world."},
        )
        detail = self.client.get(reverse("diary_detail", args=[diary.id]))
        self.assertContains(detail, "没有中英文句子对照")

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
    def test_real_tts_requires_voice_and_credentials(self):
        _, sentence = self.make_sentence()
        response = self.client.post(
            reverse("sentence_tts", args=[sentence.id, "normal"]),
            follow=True,
        )
        self.assertContains(response, "尚未配置音色")
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


class WordTTSFlowTests(AudioTestBase):
    def _token(self):
        _, sentence = self.make_sentence()
        return sentence.tokens.get(surface="water")

    def test_word_tts_context_word_creates_render(self):
        diary, sentence = self.make_sentence(text="I'm happy. They are here.")
        token = sentence.tokens.get(surface="I'm")
        response = self.client.post(reverse("word_tts", args=[token.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["cached"])
        self.assertTrue(WordTtsRender.objects.filter(target_word="I'm").exists())

    def test_word_chips_show_syllable_hint(self):
        diary, sentence = self.make_sentence()
        response = self.client.get(reverse("diary_detail", args=[diary.id]))
        self.assertContains(response, "wa·ter")

    def test_word_tts_generates_private_audio_and_cache(self):
        token = self._token()
        url = reverse("word_tts", args=[token.id])

        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        payload = first.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["cached"])
        self.assertIn("/diaries/audio/", payload["audio_url"])

        render = WordTtsRender.objects.get(owner=self.owner)
        self.assertEqual(render.target_word, "water")
        self.assertEqual(render.provider, "mock")
        self.assertEqual(render.audio.purpose, AudioAsset.Purpose.WORD_TTS)
        path = Path(self.media_dir.name) / render.audio.relative_path
        self.assertTrue(path.exists())

        audio = self.client.get(payload["audio_url"])
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio["Content-Type"], "audio/wav")

        counter = UsageCounter.objects.get(user=self.owner, feature="tts")
        self.assertEqual(counter.request_count, 1)
        self.assertEqual(counter.char_count, len("water"))

        second = self.client.post(url)
        self.assertEqual(second.status_code, 200)
        second_payload = second.json()
        self.assertTrue(second_payload["cached"])
        self.assertEqual(second_payload["audio_url"], payload["audio_url"])
        self.assertEqual(WordTtsRender.objects.count(), 1)
        counter.refresh_from_db()
        self.assertEqual(counter.request_count, 1)

    def test_word_tts_cache_is_per_user(self):
        token = self._token()
        self.client.post(reverse("word_tts", args=[token.id]))

        _, member_sentence = self.make_sentence(self.member)
        member_token = member_sentence.tokens.get(surface="water")
        self.client.force_login(self.member, backend=MODEL_BACKEND)
        response = self.client.post(reverse("word_tts", args=[member_token.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["cached"])
        self.assertEqual(WordTtsRender.objects.count(), 2)

    def test_cross_user_and_anonymous_cannot_generate_word_tts(self):
        _, sentence = self.make_sentence(self.member)
        token = sentence.tokens.get(surface="water")
        url = reverse("word_tts", args=[token.id])

        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

        self.client.logout()
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

    @override_settings(TTS_DAILY_CHAR_LIMIT=0)
    def test_word_tts_quota_blocks_generation(self):
        token = self._token()
        response = self.client.post(reverse("word_tts", args=[token.id]))
        self.assertEqual(response.status_code, 429)
        self.assertIn("字符额度", response.json()["error"])
        self.assertFalse(WordTtsRender.objects.exists())

    def test_word_tts_requires_post(self):
        token = self._token()
        response = self.client.get(reverse("word_tts", args=[token.id]))
        self.assertEqual(response.status_code, 405)

    def test_deleting_diary_removes_word_tts_audio(self):
        diary, sentence = self.make_sentence()
        token = sentence.tokens.get(surface="water")
        self.client.post(reverse("word_tts", args=[token.id]))
        render = WordTtsRender.objects.get(owner=self.owner)
        path = Path(self.media_dir.name) / render.audio.relative_path
        self.assertTrue(path.exists())

        self.client.post(reverse("diary_delete", args=[diary.id]))
        self.assertFalse(path.exists())
        self.assertFalse(WordTtsRender.objects.exists())


class ReadAloudFlowTests(AudioTestBase):
    def _make_aligned_diary(self, text="Hello there. How are you?"):
        diary = make_diary(self.owner)
        version = create_aligned_english_version(
            diary,
            [TranslationPair("你好。", text)],
            source="manual",
        )
        return diary, version

    def test_read_aloud_generates_private_audio_and_timings(self):
        diary, version = self._make_aligned_diary()
        url = reverse("diary_read_aloud", args=[diary.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["cached"])
        self.assertEqual(payload["speed"], "normal")
        self.assertTrue(payload["timings"])
        self.assertIn("/diaries/audio/", payload["audio_url"])

        read = DiaryReadAloud.objects.get(owner=self.owner, version=version)
        self.assertEqual(read.speed, "normal")
        self.assertEqual(read.audio.purpose, AudioAsset.Purpose.DIARY_TTS)
        self.assertTrue(read.timings)
        path = Path(self.media_dir.name) / read.audio.relative_path
        self.assertTrue(path.exists())

        counter = UsageCounter.objects.get(user=self.owner, feature="tts")
        self.assertEqual(counter.request_count, 1)
        self.assertEqual(
            counter.char_count,
            len("Hello there.\nHow are you?"),
        )

        second = self.client.post(url)
        self.assertEqual(second.status_code, 200)
        second_payload = second.json()
        self.assertTrue(second_payload["cached"])
        self.assertEqual(second_payload["audio_url"], payload["audio_url"])
        self.assertEqual(DiaryReadAloud.objects.count(), 1)
        counter.refresh_from_db()
        self.assertEqual(counter.request_count, 1)

    def test_normal_and_slow_are_cached_separately(self):
        diary, _version = self._make_aligned_diary()
        url = reverse("diary_read_aloud", args=[diary.id])

        normal = self.client.post(url, {"speed": "normal"})
        slow = self.client.post(url, {"speed": "slow"})
        self.assertEqual(normal.status_code, 200)
        self.assertEqual(slow.status_code, 200)
        self.assertNotEqual(
            normal.json()["audio_url"], slow.json()["audio_url"]
        )
        self.assertEqual(DiaryReadAloud.objects.count(), 2)
        self.assertEqual(
            set(DiaryReadAloud.objects.values_list("speed", flat=True)),
            {"normal", "slow"},
        )

        again = self.client.post(url, {"speed": "normal"})
        self.assertTrue(again.json()["cached"])
        self.assertEqual(DiaryReadAloud.objects.count(), 2)
        counter = UsageCounter.objects.get(user=self.owner, feature="tts")
        self.assertEqual(counter.request_count, 2)

    def test_invalid_read_aloud_speed_is_rejected(self):
        diary, _version = self._make_aligned_diary()
        response = self.client.post(
            reverse("diary_read_aloud", args=[diary.id]),
            {"speed": "fast"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DiaryReadAloud.objects.exists())

    def test_cross_user_and_anonymous_cannot_generate_read_aloud(self):
        other = make_diary(self.member)
        create_aligned_english_version(
            other,
            [TranslationPair("你好。", "Hello there.")],
            source="manual",
        )
        url = reverse("diary_read_aloud", args=[other.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

        self.client.logout()
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

    def test_read_aloud_requires_post(self):
        diary, _version = self._make_aligned_diary()
        response = self.client.get(reverse("diary_read_aloud", args=[diary.id]))
        self.assertEqual(response.status_code, 405)

    def test_deleting_diary_removes_read_aloud_audio(self):
        diary, _version = self._make_aligned_diary()
        self.client.post(reverse("diary_read_aloud", args=[diary.id]))
        read = DiaryReadAloud.objects.get(owner=self.owner)
        path = Path(self.media_dir.name) / read.audio.relative_path
        self.assertTrue(path.exists())

        self.client.post(reverse("diary_delete", args=[diary.id]))
        self.assertFalse(path.exists())
        self.assertFalse(DiaryReadAloud.objects.exists())

    def test_karaoke_spans_and_read_aloud_control_render(self):
        diary, _version = self._make_aligned_diary()
        response = self.client.get(reverse("diary_detail", args=[diary.id]))
        self.assertContains(response, "data-read-aloud")
        self.assertContains(response, 'data-read-aloud-speed="normal"')
        self.assertContains(response, 'data-read-aloud-speed="slow"')
        self.assertContains(response, "karaoke-word")
        self.assertContains(response, "全文朗读")


class VolcengineTTSServiceTests(TestCase):
    PCM = b"\x00\x01" * 24_000  # one second at 24 kHz, 16-bit mono

    def _sse_body(self, pcm: bytes, *, end: bool = True) -> bytes:
        middle = len(pcm) // 2
        events = [
            {"code": 0, "data": base64.b64encode(pcm[:middle]).decode("ascii")},
            {"code": 0, "data": base64.b64encode(pcm[middle:]).decode("ascii")},
        ]
        if end:
            events.append({"code": 20_000_000, "usage": {"text_words": 12}})
        return (
            "\n\n".join(f"data: {json.dumps(event)}" for event in events) + "\n\n"
        ).encode("utf-8")

    def _provider(self, handler, **overrides):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        options = {
            "api_key": "test-api-key",
            "resource_id": "seed-tts-2.0",
            "voice": "en_female_dacey_uranus_bigtts",
            "client": client,
        }
        options.update(overrides)
        return VolcengineTTSProvider(**options)

    def test_streams_pcm_and_wraps_wav(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=self._sse_body(self.PCM),
            )

        provider = self._provider(handler)
        result = provider.synthesize(
            "Hello there.", speed="normal", style="natural"
        )

        self.assertEqual(
            captured["url"],
            "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
        )
        self.assertEqual(captured["headers"]["x-api-key"], "test-api-key")
        self.assertEqual(captured["headers"]["x-api-resource-id"], "seed-tts-2.0")
        self.assertIn("x-api-request-id", captured["headers"])
        self.assertEqual(
            captured["headers"]["x-control-require-usage-tokens-return"],
            "text_words",
        )
        self.assertEqual(
            captured["payload"]["req_params"]["speaker"],
            "en_female_dacey_uranus_bigtts",
        )
        self.assertEqual(captured["payload"]["req_params"]["text"], "Hello there.")
        self.assertEqual(
            captured["payload"]["req_params"]["audio_params"]["format"], "pcm"
        )
        self.assertEqual(
            captured["payload"]["req_params"]["audio_params"]["sample_rate"], 24_000
        )
        self.assertEqual(
            captured["payload"]["req_params"]["audio_params"]["speech_rate"], 0
        )
        self.assertNotIn(
            "emotion", captured["payload"]["req_params"]["audio_params"]
        )

        self.assertEqual(result.content_type, "audio/wav")
        self.assertEqual(result.extension, "wav")
        self.assertEqual(result.duration_ms, 1_000)
        self.assertEqual(result.provider, "volcengine")
        self.assertEqual(result.model, "seed-tts-2.0")
        self.assertEqual(result.voice, "en_female_dacey_uranus_bigtts")
        self.assertEqual(result.style, "natural")

        with wave.open(io.BytesIO(result.data), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 24_000)
            self.assertEqual(wav.readframes(wav.getnframes()), self.PCM)

    def test_normal_speed_uses_configured_rate(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=self._sse_body(self.PCM),
            )

        provider = self._provider(handler, normal_speech_rate=-20)
        provider.synthesize("Hello there.", speed="normal", style="natural")

        audio = captured["payload"]["req_params"]["audio_params"]
        self.assertEqual(audio["speech_rate"], -20)

    def test_mock_tts_can_return_timings(self):
        result = MockTTSProvider().synthesize(
            "Hello there.",
            speed="normal",
            style="natural",
            enable_subtitles=True,
        )
        self.assertEqual(len(result.timings), 2)
        self.assertEqual(result.timings[0]["word"], "Hello")

    def test_subtitle_timings_are_collected(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            events = [
                {
                    "code": 0,
                    "data": base64.b64encode(
                        self.PCM[: len(self.PCM) // 2]
                    ).decode("ascii"),
                },
                {
                    "code": 0,
                    "sentence": {
                        "text": "Hello there.",
                        "words": [
                            {
                                "word": "Hello",
                                "startTime": 0.1,
                                "endTime": 0.4,
                            },
                            {
                                "word": "there.",
                                "startTime": 0.4,
                                "endTime": 0.7,
                            },
                        ],
                    },
                },
                {
                    "code": 0,
                    "data": base64.b64encode(
                        self.PCM[len(self.PCM) // 2 :]
                    ).decode("ascii"),
                },
                {"code": 20_000_000, "usage": {"text_words": 12}},
            ]
            body = (
                "\n\n".join(
                    f"data: {json.dumps(event)}" for event in events
                )
                + "\n\n"
            ).encode("utf-8")
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=body,
            )

        provider = self._provider(handler)
        result = provider.synthesize(
            "Hello there.",
            speed="normal",
            style="natural",
            enable_subtitles=True,
        )

        self.assertEqual(
            result.timings,
            (
                {"word": "Hello", "start_ms": 100, "end_ms": 400},
                {"word": "there.", "start_ms": 400, "end_ms": 700},
            ),
        )
        self.assertTrue(
            captured["payload"]["req_params"]["audio_params"][
                "enable_subtitle"
            ]
        )

    def test_word_tts_context_mapping(self):
        self.assertEqual(word_tts_context("I'm"), "I'm going home now.")
        self.assertEqual(word_tts_context("I’m"), "I'm going home now.")
        self.assertEqual(word_tts_context("they"), "They are my friends.")
        self.assertEqual(word_tts_context("water"), "")

    def test_word_context_is_sent_as_additions(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=self._sse_body(self.PCM),
            )

        provider = self._provider(handler)
        provider.synthesize(
            "I'm",
            speed="word",
            style="natural",
            context_text="I'm going home now.",
        )

        additions = json.loads(captured["payload"]["req_params"]["additions"])
        self.assertEqual(additions["explicit_language"], "en")
        self.assertEqual(additions["context_text"], "I'm going home now.")
        self.assertEqual(additions["context_language"], "en")

    def test_word_cache_key_includes_context(self):
        base = {
            "provider": "volcengine",
            "model": "seed-tts-2.0",
            "voice": "voice",
            "style": "natural",
            "speed": "word",
            "rate": -20,
            "text": "they",
        }
        self.assertNotEqual(
            tts_cache_key(**base),
            tts_cache_key(**base, context="They are my friends."),
        )
        self.assertNotEqual(
            tts_cache_key(**base, context="They are my friends."),
            tts_cache_key(**base, context="They are my friends!"),
        )

    def test_word_speed_uses_word_rate(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=self._sse_body(self.PCM),
            )

        provider = self._provider(handler, word_speech_rate=10)
        provider.synthesize("water", speed="word", style="natural")

        audio = captured["payload"]["req_params"]["audio_params"]
        self.assertEqual(audio["speech_rate"], 10)

    def test_slow_speed_uses_lower_speech_rate(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=self._sse_body(self.PCM),
            )

        provider = self._provider(handler)
        provider.synthesize("Hello there.", speed="slow", style="neutral")

        audio = captured["payload"]["req_params"]["audio_params"]
        self.assertEqual(audio["speech_rate"], -20)
        self.assertNotIn("emotion", audio)

    def test_legacy_app_id_and_token_auth(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=self._sse_body(self.PCM),
            )

        provider = self._provider(
            handler, api_key="", app_id="test-app", access_token="test-token"
        )
        provider.synthesize("Hello there.", speed="normal", style="natural")

        self.assertEqual(captured["headers"]["x-api-app-id"], "test-app")
        self.assertEqual(captured["headers"]["x-api-access-key"], "test-token")
        self.assertNotIn("x-api-key", captured["headers"])

    def test_voice_and_resource_mismatch_is_rejected_before_network(self):
        with self.assertRaises(TTSError):
            VolcengineTTSProvider(
                api_key="test-api-key",
                resource_id="seed-tts-2.0",
                voice="BV001_streaming",
            )
        with self.assertRaises(TTSError):
            VolcengineTTSProvider(
                api_key="test-api-key",
                resource_id="seed-tts-1.0",
                voice="en_female_dacey_uranus_bigtts",
            )

    def test_sse_error_frame_is_friendly(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"code": 55000000, '
                '"message": "resource id is mismatched with speaker related resource"}\n\n'
            ).encode("utf-8")
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=body
            )

        provider = self._provider(handler)
        with self.assertRaises(TTSError) as raised:
            provider.synthesize("Hello there.", speed="normal", style="natural")
        self.assertIn("音色与资源版本", str(raised.exception))

    def test_http_auth_error_is_friendly(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "unauthorized"})

        provider = self._provider(handler)
        with self.assertRaises(TTSError) as raised:
            provider.synthesize("Hello there.", speed="normal", style="natural")
        self.assertIn("鉴权失败", str(raised.exception))

    def test_json_error_body_is_friendly(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"code": 40000003, "message": "quota exceeded"},
            )

        provider = self._provider(handler)
        with self.assertRaises(TTSError) as raised:
            provider.synthesize("Hello there.", speed="normal", style="natural")
        self.assertIn("额度", str(raised.exception))

    def test_default_provider_is_mock(self):
        self.assertIsInstance(get_tts_provider(), MockTTSProvider)

    @override_settings(
        TTS_PROVIDER="volcengine",
        VOLCENGINE_API_KEY="test-api-key",
        VOLCENGINE_TTS_VOICE="en_female_dacey_uranus_bigtts",
        VOLCENGINE_RESOURCE_ID="seed-tts-2.0",
    )
    def test_get_provider_builds_volcengine_adapter(self):
        provider = get_tts_provider()
        self.assertIsInstance(provider, VolcengineTTSProvider)
        self.assertEqual(provider.model, "seed-tts-2.0")

    @override_settings(
        TTS_PROVIDER="volcengine",
        VOLCENGINE_API_KEY="",
        VOLCENGINE_APP_ID="",
        VOLCENGINE_ACCESS_TOKEN="",
        VOLCENGINE_TTS_VOICE="",
    )
    def test_get_provider_refuses_missing_configuration(self):
        with self.assertRaises(TTSError):
            get_tts_provider()


class AssessmentServiceTests(TestCase):
    def test_mock_assessor_returns_scores_without_network(self):
        result = MockAssessor().assess("water", b"audio-bytes")
        self.assertEqual(result.provider, "mock")
        self.assertEqual(result.overall_score, 86.0)
        self.assertEqual(result.accuracy, 88.0)
        self.assertEqual(result.fluency, 82.0)
        self.assertEqual(result.completeness, 100.0)
        self.assertTrue(result.detail["mock"])

    def test_default_assessor_is_mock(self):
        self.assertIsInstance(get_assessor(), MockAssessor)

    def test_tencent_signed_url_has_word_mode_and_valid_signature(self):
        assessor = TencentSOEAssessor(
            app_id="125922",
            secret_id="secret-id",
            secret_key="secret-key",
        )
        url = assessor._build_signed_url(
            "hello",
            voice_id="voice-1",
            timestamp=1722321759,
            nonce="42261112",
            expired=1722408159,
        )
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "wss")
        self.assertEqual(parsed.netloc, "soe.cloud.tencent.com")
        self.assertEqual(parsed.path, "/soe/api/125922")

        query = parse_qs(parsed.query, keep_blank_values=True)
        signature = query.pop("signature")[0]
        self.assertEqual(query["eval_mode"], ["0"])
        self.assertEqual(query["server_engine_type"], ["16k_en"])
        self.assertEqual(query["voice_format"], ["1"])
        self.assertEqual(query["rec_mode"], ["1"])
        self.assertEqual(query["ref_text"], ["hello"])
        self.assertEqual(query["secretid"], ["secret-id"])
        self.assertEqual(query["voice_id"], ["voice-1"])
        self.assertEqual(query["timestamp"], ["1722321759"])
        self.assertEqual(query["expired"], ["1722408159"])
        self.assertEqual(query["nonce"], ["42261112"])
        self.assertEqual(query["score_coeff"], ["1.0"])
        self.assertEqual(query["text_mode"], ["0"])
        self.assertEqual(query["sentence_info_enabled"], ["0"])
        self.assertEqual(query["keyword"], [""])

        source = "soe.cloud.tencent.com/soe/api/125922?" + "&".join(
            f"{key}={values[0]}" for key, values in sorted(query.items())
        )
        expected = base64.b64encode(
            hmac.new(b"secret-key", source.encode("utf-8"), hashlib.sha1).digest()
        ).decode("ascii")
        self.assertEqual(signature, expected)

    def test_tencent_assessor_sends_audio_and_parses_final_result(self):
        class FakeConnection:
            def __init__(self, messages):
                self.messages = list(messages)
                self.sent = []
                self.closed = False

            def send_binary(self, data):
                self.sent.append(("binary", data))

            def send(self, data):
                self.sent.append(("text", data))

            def recv(self):
                return self.messages.pop(0)

            def close(self):
                self.closed = True

        fake = FakeConnection(
            [
                json.dumps({"code": 0, "final": 0, "result": None}),
                json.dumps(
                    {
                        "code": 0,
                        "final": 1,
                        "result": {
                            "SuggestedScore": 92,
                            "PronAccuracy": 90,
                            "PronFluency": 88,
                            "PronCompletion": 100,
                            "MatchTag": 0,
                            "Phone": [{"Phone": "w"}],
                            "Stress": 1,
                            "DetectedStress": 0,
                        },
                    }
                ),
            ]
        )
        captured = {}

        def factory(url, timeout):
            captured["url"] = url
            captured["timeout"] = timeout
            return fake

        assessor = TencentSOEAssessor(
            app_id="app",
            secret_id="sid",
            secret_key="skey",
            connection_factory=factory,
        )
        result = assessor.assess("water", b"wav-bytes")

        self.assertEqual(result.overall_score, 92.0)
        self.assertEqual(result.accuracy, 90.0)
        self.assertEqual(result.fluency, 88.0)
        self.assertEqual(result.completeness, 100.0)
        self.assertEqual(result.match_tag, 0)
        self.assertEqual(result.detail["phones"], [{"Phone": "w"}])
        self.assertEqual(fake.sent[0], ("binary", b"wav-bytes"))
        self.assertEqual(json.loads(fake.sent[1][1]), {"type": "end"})
        self.assertTrue(fake.closed)
        self.assertIn("eval_mode=0", captured["url"])
        self.assertEqual(captured["timeout"], 20)

    def test_tencent_assessor_maps_oov_error(self):
        class FakeConnection:
            def __init__(self):
                self.closed = False

            def send_binary(self, data):
                pass

            def send(self, data):
                pass

            def recv(self):
                return json.dumps({"code": 4103, "message": "OOV", "final": 1})

            def close(self):
                self.closed = True

        fake = FakeConnection()
        assessor = TencentSOEAssessor(
            app_id="app",
            secret_id="sid",
            secret_key="skey",
            connection_factory=lambda url, timeout: fake,
        )
        with self.assertRaises(AssessmentError) as raised:
            assessor.assess("shazhengzhong", b"audio")
        self.assertIn("词典", str(raised.exception))
        self.assertTrue(fake.closed)

    @override_settings(
        ASSESSMENT_PROVIDER="tencent",
        TENCENT_SOE_APP_ID="",
        TENCENTCLOUD_SECRET_ID="",
        TENCENTCLOUD_SECRET_KEY="",
    )
    def test_tencent_requires_credentials(self):
        with self.assertRaises(AssessmentError):
            get_assessor()


class AssessmentFlowTests(AudioTestBase):
    def _upload(self, duration_ms=500, filename="word.wav"):
        return SimpleUploadedFile(
            filename,
            self.wav_bytes(duration_ms),
            content_type="audio/wav",
        )

    def test_mock_assessment_creates_private_attempt_and_scores(self):
        diary, sentence = self.make_sentence()
        token = sentence.tokens.first()
        response = self.client.post(
            reverse("assess_word", args=[token.id]),
            {"audio": self._upload()},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["overall_score"], 86.0)
        self.assertEqual(payload["accuracy"], 88.0)

        attempt = PronunciationAttempt.objects.get(owner=self.owner, word_token=token)
        self.assertEqual(attempt.target_word, token.surface)
        self.assertEqual(attempt.provider, "mock")
        self.assertEqual(attempt.audio.purpose, AudioAsset.Purpose.ASSESSMENT)
        path = Path(self.media_dir.name) / attempt.audio.relative_path
        self.assertTrue(path.exists())

        audio = self.client.get(payload["audio_url"])
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio["Content-Type"], "audio/wav")

        counter = UsageCounter.objects.get(user=self.owner, feature="assessment")
        self.assertEqual(counter.request_count, 1)
        self.assertEqual(counter.char_count, len(token.surface))

    def test_cross_user_and_anonymous_cannot_assess(self):
        _, sentence = self.make_sentence(self.member)
        token = sentence.tokens.first()
        url = reverse("assess_word", args=[token.id])

        response = self.client.post(url, {"audio": self._upload()})
        self.assertEqual(response.status_code, 404)

        self.client.logout()
        response = self.client.post(url, {"audio": self._upload()})
        self.assertEqual(response.status_code, 302)

    def test_rejects_invalid_audio(self):
        _, sentence = self.make_sentence()
        token = sentence.tokens.first()
        upload = SimpleUploadedFile("bad.txt", b"not audio", content_type="text/plain")
        response = self.client.post(
            reverse("assess_word", args=[token.id]),
            {"audio": upload},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PronunciationAttempt.objects.exists())

    def test_rejects_audio_longer_than_ten_seconds(self):
        _, sentence = self.make_sentence()
        token = sentence.tokens.first()
        response = self.client.post(
            reverse("assess_word", args=[token.id]),
            {"audio": self._upload(duration_ms=11_000)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("10", response.json()["error"])
        self.assertFalse(PronunciationAttempt.objects.exists())

    @override_settings(ASSESSMENT_DAILY_REQUEST_LIMIT=1)
    def test_assessment_quota_blocks_second_attempt(self):
        _, sentence = self.make_sentence()
        token = sentence.tokens.first()
        url = reverse("assess_word", args=[token.id])

        first = self.client.post(url, {"audio": self._upload()})
        self.assertEqual(first.status_code, 200)

        second = self.client.post(url, {"audio": self._upload()})
        self.assertEqual(second.status_code, 429)
        self.assertIn("最多测评 1 次", second.json()["error"])
        self.assertEqual(PronunciationAttempt.objects.count(), 1)

    def test_assessment_requires_post(self):
        _, sentence = self.make_sentence()
        token = sentence.tokens.first()
        response = self.client.get(reverse("assess_word", args=[token.id]))
        self.assertEqual(response.status_code, 405)

    def test_cross_user_cannot_access_assessment_audio(self):
        _, sentence = self.make_sentence()
        token = sentence.tokens.first()
        response = self.client.post(
            reverse("assess_word", args=[token.id]),
            {"audio": self._upload()},
        )
        attempt = PronunciationAttempt.objects.get(owner=self.owner)
        url = reverse("serve_audio_asset", args=[attempt.audio_id])

        self.client.force_login(self.member, backend=MODEL_BACKEND)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_deleting_diary_removes_assessment_audio(self):
        diary, sentence = self.make_sentence()
        token = sentence.tokens.first()
        self.client.post(
            reverse("assess_word", args=[token.id]),
            {"audio": self._upload()},
        )
        attempt = PronunciationAttempt.objects.get(owner=self.owner)
        path = Path(self.media_dir.name) / attempt.audio.relative_path
        self.assertTrue(path.exists())

        self.client.post(reverse("diary_delete", args=[diary.id]))
        self.assertFalse(path.exists())
        self.assertFalse(PronunciationAttempt.objects.exists())

    def test_latest_score_is_rendered_on_detail_page(self):
        diary, sentence = self.make_sentence()
        token = sentence.tokens.first()
        self.client.post(
            reverse("assess_word", args=[token.id]),
            {"audio": self._upload()},
        )
        response = self.client.get(reverse("diary_detail", args=[diary.id]))
        self.assertContains(response, "准确度")
        self.assertContains(response, "86")


class WordLookupServiceTests(DiaryFixtureMixin, TestCase):
    def test_lookup_word_uses_dictionary_and_cache(self):
        lookup = lookup_word(self.owner, "water")
        self.assertEqual(lookup.word, "water")
        self.assertEqual(lookup.display_word, "water")
        self.assertEqual(lookup.ipa, "ˈwɔtər")
        self.assertIn("·", lookup.syllables)
        self.assertIn("模拟释义", lookup.translation)

        counter = UsageCounter.objects.get(user=self.owner, feature="translation")
        self.assertEqual(counter.request_count, 1)

        again = lookup_word(self.owner, "Water")
        self.assertEqual(again.pk, lookup.pk)
        counter.refresh_from_db()
        self.assertEqual(counter.request_count, 1)

    def test_lookup_word_rejects_invalid_input(self):
        with self.assertRaises(ValidationError):
            lookup_word(self.owner, "")
        with self.assertRaises(ValidationError):
            lookup_word(self.owner, "hello world")

    @override_settings(TRANSLATION_DAILY_REQUEST_LIMIT=0)
    def test_lookup_word_quota_blocks_new_word(self):
        with self.assertRaises(TranslationQuotaExceeded):
            lookup_word(self.owner, "water")
        self.assertFalse(WordLookup.objects.exists())


class WordLookupPageTests(DiaryFixtureMixin, TestCase):
    def test_lookup_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("word_lookup"))
        self.assertEqual(response.status_code, 302)

    def test_lookup_page_renders_result_and_controls(self):
        response = self.client.post(reverse("word_lookup"), {"q": "water"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "water")
        self.assertContains(response, "ˈwɔtər")
        self.assertContains(response, "wa·ter")
        self.assertContains(response, "模拟释义")
        self.assertContains(response, "data-word-play")
        self.assertContains(response, "data-assess-button")
        self.assertEqual(WordLookup.objects.count(), 1)

    def test_lookup_page_reuses_cached_word(self):
        first = self.client.post(reverse("word_lookup"), {"q": "water"})
        second = self.client.post(reverse("word_lookup"), {"q": "Water"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WordLookup.objects.count(), 1)
        counter = UsageCounter.objects.get(user=self.owner, feature="translation")
        self.assertEqual(counter.request_count, 1)

    def test_lookup_page_shows_error_for_invalid_word(self):
        response = self.client.post(
            reverse("word_lookup"), {"q": "hello world"}
        )
        self.assertContains(response, "单个英文单词")
        self.assertFalse(WordLookup.objects.exists())


class LookupTTSFlowTests(AudioTestBase):
    def _lookup(self):
        return lookup_word(self.owner, "water")

    def test_lookup_tts_generates_private_audio_and_cache(self):
        lookup = self._lookup()
        url = reverse("lookup_tts", args=[lookup.id])

        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        payload = first.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["cached"])
        self.assertIn("/diaries/audio/", payload["audio_url"])

        render = WordTtsRender.objects.get(owner=self.owner, lookup=lookup)
        self.assertIsNone(render.sentence)
        self.assertEqual(render.target_word, "water")
        self.assertEqual(render.audio.purpose, AudioAsset.Purpose.WORD_TTS)
        path = Path(self.media_dir.name) / render.audio.relative_path
        self.assertTrue(path.exists())

        second = self.client.post(url)
        self.assertTrue(second.json()["cached"])
        self.assertEqual(WordTtsRender.objects.count(), 1)

    def test_lookup_tts_requires_post(self):
        lookup = self._lookup()
        response = self.client.get(reverse("lookup_tts", args=[lookup.id]))
        self.assertEqual(response.status_code, 405)


class LookupAssessmentFlowTests(AudioTestBase):
    def test_lookup_assessment_creates_attempt(self):
        lookup = lookup_word(self.owner, "water")
        upload = SimpleUploadedFile(
            "word.wav",
            self.wav_bytes(500),
            content_type="audio/wav",
        )
        response = self.client.post(
            reverse("assess_lookup", args=[lookup.id]),
            {"audio": upload},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["overall_score"], 86.0)

        attempt = PronunciationAttempt.objects.get(
            owner=self.owner, lookup=lookup
        )
        self.assertIsNone(attempt.word_token)
        self.assertEqual(attempt.target_word, "water")
        self.assertIsNone(attempt.audio.sentence)
        counter = UsageCounter.objects.get(
            user=self.owner, feature="assessment"
        )
        self.assertEqual(counter.request_count, 1)

    def test_lookup_assessment_requires_login(self):
        lookup = lookup_word(self.owner, "water")
        self.client.logout()
        upload = SimpleUploadedFile(
            "word.wav",
            self.wav_bytes(500),
            content_type="audio/wav",
        )
        response = self.client.post(
            reverse("assess_lookup", args=[lookup.id]),
            {"audio": upload},
        )
        self.assertEqual(response.status_code, 302)

    def test_lookup_assessment_rejects_invalid_audio(self):
        lookup = lookup_word(self.owner, "water")
        upload = SimpleUploadedFile(
            "bad.txt", b"not audio", content_type="text/plain"
        )
        response = self.client.post(
            reverse("assess_lookup", args=[lookup.id]),
            {"audio": upload},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PronunciationAttempt.objects.exists())
