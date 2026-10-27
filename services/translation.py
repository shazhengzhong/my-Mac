"""Translation provider adapters with a mock-first safety default."""

from dataclasses import dataclass
import json
from typing import Protocol

import httpx
from django.conf import settings

from services.text import split_chinese_sentences

MOCK_TRANSLATION = (
    "Today I wrote a short diary in Chinese.\n"
    "It was a quiet and ordinary day.\n"
    "I am practicing my English pronunciation one sentence at a time."
)

MOCK_PAIRS = (
    ("今天我写了一篇中文日记。", "Today I wrote a short diary in Chinese."),
    ("这是安静而普通的一天。", "It was a quiet and ordinary day."),
    (
        "我正在一句一句地练习英语发音。",
        "I am practicing my English pronunciation one sentence at a time.",
    ),
)

SYSTEM_PROMPT = (
    "You translate private Chinese diary entries into natural, idiomatic American English. "
    "Preserve the meaning, names, dates, and the writer's tone. Do not add facts, explanations, "
    "or commentary. Return only the English translation, with exactly one complete English "
    "sentence on each line. Do not use markdown or wrap the whole result in quotation marks."
)

PAIR_SYSTEM_PROMPT = (
    "You translate private Chinese diary sentences into natural, idiomatic American English. "
    "The user sends a JSON array of Chinese sentences. Return only a JSON object of the form "
    '{"translations": ["...", "..."]} with exactly one English translation per input sentence, '
    "in the same order. Keep names, dates, and the writer's tone. If one Chinese sentence needs "
    "more than one English sentence, put all of them in that item separated by spaces. Do not add "
    "facts, explanations, or commentary. Do not use markdown or code fences."
)


class TranslationError(Exception):
    """A user-safe translation failure; never include secrets or diary content."""


@dataclass(frozen=True)
class TranslationPair:
    chinese: str
    english: str


class Translator(Protocol):
    source: str
    model: str

    def translate(self, chinese_text: str) -> str: ...

    def translate_pairs(self, chinese_text: str) -> list[TranslationPair]: ...


class MockTranslator:
    """Development-only text with no network call and no cost."""

    source = "mock"
    model = "mock"

    def translate(self, chinese_text: str) -> str:
        return MOCK_TRANSLATION

    def translate_pairs(self, chinese_text: str) -> list[TranslationPair]:
        return [
            TranslationPair(chinese=chinese, english=english)
            for chinese, english in MOCK_PAIRS
        ]


def _parse_json_payload(content: str):
    """Parse JSON even if the model wrapped it in extra prose."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    starts = [position for position in (content.find("{"), content.find("[")) if position != -1]
    if not starts:
        raise TranslationError("翻译服务返回了无法识别的内容，请重试。")
    start = min(starts)
    end = max(content.rfind("}"), content.rfind("]"))
    if end <= start:
        raise TranslationError("翻译服务返回了无法识别的内容，请重试。")
    try:
        return json.loads(content[start : end + 1])
    except json.JSONDecodeError as exc:
        raise TranslationError("翻译服务返回了无法识别的内容，请重试。") from exc


class DeepSeekTranslator:
    source = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        client: httpx.Client | None = None,
    ):
        self.api_key = api_key
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
        self._client = client

    def _post(self, client: httpx.Client, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2048,
            "stream": False,
        }
        try:
            response = client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else "unknown"
            raise TranslationError(f"翻译服务返回错误（{code}），请稍后再试。") from exc
        except httpx.TimeoutException as exc:
            raise TranslationError("翻译服务响应超时，请稍后再试。") from exc
        except httpx.HTTPError as exc:
            raise TranslationError("暂时无法连接翻译服务，请检查网络后再试。") from exc

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise TranslationError("翻译服务返回了无法识别的内容，请稍后再试。") from exc

        if not isinstance(content, str) or not content.strip():
            raise TranslationError("翻译服务没有返回英文内容，请稍后再试。")

        cleaned = content.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        if not cleaned:
            raise TranslationError("翻译服务没有返回可用内容，请稍后再试。")
        return cleaned

    def _request(self, client: httpx.Client, chinese_text: str) -> str:
        return self._post(
            client,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": chinese_text},
            ],
        )

    def _request_pairs(
        self, client: httpx.Client, chinese_text: str
    ) -> list[TranslationPair]:
        sentences = split_chinese_sentences(chinese_text)
        if not sentences:
            raise TranslationError("中文日记为空，无法翻译。")

        content = self._post(
            client,
            [
                {"role": "system", "content": PAIR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(sentences, ensure_ascii=False),
                },
            ],
        )
        parsed = _parse_json_payload(content)
        translations = (
            parsed.get("translations") if isinstance(parsed, dict) else parsed
        )
        if not isinstance(translations, list) or len(translations) != len(sentences):
            raise TranslationError("翻译结果与中文句子数量不一致，请重试。")

        pairs: list[TranslationPair] = []
        for chinese, item in zip(sentences, translations):
            if isinstance(item, dict):
                item = item.get("english") or item.get("translation") or ""
            if not isinstance(item, str) or not item.strip():
                raise TranslationError("翻译服务没有返回完整的英文内容，请重试。")
            pairs.append(
                TranslationPair(chinese=chinese, english=item.strip())
            )
        return pairs

    def translate(self, chinese_text: str) -> str:
        if self._client is not None:
            return self._request(self._client, chinese_text)
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                return self._request(client, chinese_text)
        except httpx.HTTPError as exc:
            raise TranslationError("暂时无法连接翻译服务，请检查网络后再试。") from exc

    def translate_pairs(self, chinese_text: str) -> list[TranslationPair]:
        if self._client is not None:
            return self._request_pairs(self._client, chinese_text)
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                return self._request_pairs(client, chinese_text)
        except httpx.HTTPError as exc:
            raise TranslationError("暂时无法连接翻译服务，请检查网络后再试。") from exc


def get_translator() -> Translator:
    """Return the configured provider, refusing to guess a missing credential."""
    provider = settings.TRANSLATION_PROVIDER
    if provider == "mock":
        return MockTranslator()
    if provider == "deepseek":
        if not settings.DEEPSEEK_API_KEY:
            raise TranslationError("DeepSeek API Key 尚未配置，暂时无法使用真实翻译。")
        return DeepSeekTranslator(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
        )
    raise TranslationError("翻译服务配置错误，请联系管理员。")
