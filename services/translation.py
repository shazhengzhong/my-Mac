"""Translation provider adapters with a mock-first safety default."""

from typing import Protocol

import httpx
from django.conf import settings

MOCK_TRANSLATION = (
    "Today I wrote a short diary in Chinese.\n"
    "It was a quiet and ordinary day.\n"
    "I am practicing my English pronunciation one sentence at a time."
)

SYSTEM_PROMPT = (
    "You translate private Chinese diary entries into natural, idiomatic American English. "
    "Preserve the meaning, names, dates, and the writer's tone. Do not add facts, explanations, "
    "or commentary. Return only the English translation, with exactly one complete English "
    "sentence on each line. Do not use markdown or wrap the whole result in quotation marks."
)


class TranslationError(Exception):
    """A user-safe translation failure; never include secrets or diary content."""


class Translator(Protocol):
    source: str
    model: str

    def translate(self, chinese_text: str) -> str: ...


class MockTranslator:
    """Development-only text with no network call and no cost."""

    source = "mock"
    model = "mock"

    def translate(self, chinese_text: str) -> str:
        return MOCK_TRANSLATION


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

    def _request(self, client: httpx.Client, chinese_text: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": chinese_text},
            ],
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

    def translate(self, chinese_text: str) -> str:
        if self._client is not None:
            return self._request(self._client, chinese_text)
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                return self._request(client, chinese_text)
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
