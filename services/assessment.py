"""Word-level pronunciation assessment providers.

The default is an offline mock. Tencent Cloud's new SOE (口语评测新版) endpoint
speaks WebSocket with an HMAC-SHA1 signed URL. It expects 16 kHz, 16-bit, mono
WAV audio, which is exactly what the browser recorder produces.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import random
import time
from typing import Any, Callable, Protocol
from urllib.parse import quote, urlencode
import uuid

import websocket
from django.conf import settings

TENCENT_SOE_HOST = "soe.cloud.tencent.com"
TENCENT_SOE_PATH = "/soe/api/"
TENCENT_SOE_URL = f"wss://{TENCENT_SOE_HOST}{TENCENT_SOE_PATH}"
TENCENT_SOE_OK_CODE = 0


class AssessmentError(Exception):
    """A user-safe assessment failure; never include secrets or diary content."""


@dataclass(frozen=True)
class AssessmentResult:
    provider: str
    model: str
    overall_score: float | None
    accuracy: float | None
    fluency: float | None
    completeness: float | None
    match_tag: int | None
    detail: dict


class Assessor(Protocol):
    provider: str
    model: str

    def assess(self, word: str, audio: bytes) -> AssessmentResult: ...


class MockAssessor:
    """Deterministic offline scores for UI and test coverage."""

    provider = "mock"
    model = "mock"

    def assess(self, word: str, audio: bytes) -> AssessmentResult:
        if not word or not audio:
            raise AssessmentError("单词或录音为空，无法测评。")
        return AssessmentResult(
            provider=self.provider,
            model=self.model,
            overall_score=86.0,
            accuracy=88.0,
            fluency=82.0,
            completeness=100.0,
            match_tag=0,
            detail={"mock": True, "audio_bytes": len(audio)},
        )


class TencentSOEAssessor:
    """Tencent Cloud SOE new version (English word mode)."""

    provider = "tencent_soe"
    model = "16k_en"

    def __init__(
        self,
        *,
        app_id: str,
        secret_id: str,
        secret_key: str,
        engine: str = "16k_en",
        score_coeff: float = 1.0,
        timeout: int = 20,
        connection_factory: Callable[..., Any] | None = None,
    ):
        if not app_id or not secret_id or not secret_key:
            raise AssessmentError("腾讯云口语评测凭据尚未配置。")
        if engine not in {"16k_en", "16k_zh"}:
            raise AssessmentError("口语评测引擎配置无效。")
        if not 1.0 <= score_coeff <= 4.0:
            raise AssessmentError("口语评测苛刻度必须在 1.0 到 4.0 之间。")
        self.app_id = app_id
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.model = engine
        self.score_coeff = score_coeff
        self.timeout = timeout
        self._connection_factory = connection_factory or websocket.create_connection

    def _signature_source(self, params: dict[str, Any]) -> str:
        ordered = "&".join(
            f"{key}={params[key]}" for key in sorted(params)
        )
        return f"{TENCENT_SOE_HOST}{TENCENT_SOE_PATH}{self.app_id}?{ordered}"

    def _build_signed_url(
        self,
        word: str,
        *,
        voice_id: str | None = None,
        timestamp: int | None = None,
        nonce: str | None = None,
        expired: int | None = None,
    ) -> str:
        voice_id = voice_id or str(uuid.uuid4())
        timestamp = int(time.time()) if timestamp is None else timestamp
        nonce = nonce or str(random.randint(1, 9_999_999_999))
        expired = expired if expired is not None else timestamp + 24 * 60 * 60
        params: dict[str, Any] = {
            "eval_mode": 0,
            "expired": expired,
            "keyword": "",
            "nonce": nonce,
            "rec_mode": 1,
            "ref_text": word,
            "score_coeff": self.score_coeff,
            "secretid": self.secret_id,
            "sentence_info_enabled": 0,
            "server_engine_type": self.model,
            "text_mode": 0,
            "timestamp": timestamp,
            "voice_format": 1,
            "voice_id": voice_id,
        }
        source = self._signature_source(params)
        digest = hmac.new(
            self.secret_key.encode("utf-8"),
            source.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        signature = base64.b64encode(digest).decode("ascii")
        query = urlencode(sorted(params.items()), quote_via=quote, safe="")
        return (
            f"{TENCENT_SOE_URL}{self.app_id}?{query}"
            f"&signature={quote(signature, safe='')}"
        )

    @staticmethod
    def _lookup(result: dict, *keys: str) -> Any:
        for key in keys:
            if key in result and result[key] is not None:
                return result[key]
        words = result.get("Words") or result.get("words") or []
        if words and isinstance(words[0], dict):
            for key in keys:
                if key in words[0] and words[0][key] is not None:
                    return words[0][key]
        return None

    @classmethod
    def _score(cls, result: dict, *keys: str) -> float | None:
        value = cls._lookup(result, *keys)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number >= 0 else None

    @classmethod
    def _parse_result(cls, result: dict | str) -> AssessmentResult:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError as exc:
                raise AssessmentError("评测服务返回了无法识别的内容。") from exc
        if not isinstance(result, dict):
            raise AssessmentError("评测服务返回了无法识别的内容。")

        match_tag = cls._lookup(result, "MatchTag", "match_tag")
        try:
            match_tag = int(match_tag) if match_tag is not None else None
        except (TypeError, ValueError):
            match_tag = None

        detail = {
            "words": result.get("Words") or result.get("words") or [],
            "phones": result.get("Phone") or result.get("phone") or [],
            "stress": cls._lookup(result, "Stress", "stress"),
            "detected_stress": cls._lookup(result, "DetectedStress", "detected_stress"),
        }
        return AssessmentResult(
            provider=cls.provider,
            model=cls.model,
            overall_score=cls._score(result, "SuggestedScore", "suggested_score"),
            accuracy=cls._score(result, "PronAccuracy", "pron_accuracy"),
            fluency=cls._score(result, "PronFluency", "pron_fluency"),
            completeness=cls._score(result, "PronCompletion", "pron_completion"),
            match_tag=match_tag,
            detail=detail,
        )

    @staticmethod
    def _error_message(code: Any, message: str) -> str:
        text = (message or "").lower()
        if code in {4001, 4002, 4003, 4004, 4005} or "signature" in text or "auth" in text:
            return "腾讯云鉴权失败，请检查 SecretId、SecretKey 和 AppID。"
        if code == 4103 or "oov" in text or "not in" in text:
            return "这个词不在评测词典里，暂时无法测评。"
        if code == 4115 or ("engine" in text and "match" in text):
            return "评测引擎不匹配，请检查英文引擎配置。"
        if "quota" in text or "limit" in text or "frequency" in text:
            return "腾讯云评测额度不足或请求过于频繁。"
        if "audio" in text or "format" in text:
            return "音频格式不符合评测要求。"
        return "单词测评失败，请稍后再试。"

    def assess(self, word: str, audio: bytes) -> AssessmentResult:
        if not word or not audio:
            raise AssessmentError("单词或录音为空，无法测评。")

        url = self._build_signed_url(word)
        connection = None
        last_result = None
        try:
            connection = self._connection_factory(url, timeout=self.timeout)
            connection.send_binary(audio)
            connection.send(json.dumps({"type": "end"}))
            while True:
                message = connection.recv()
                if isinstance(message, bytes):
                    message = message.decode("utf-8", "replace")
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError as exc:
                    raise AssessmentError("评测服务返回了无法识别的内容。") from exc
                if not isinstance(payload, dict):
                    raise AssessmentError("评测服务返回了无法识别的内容。")

                try:
                    code = int(payload.get("code", TENCENT_SOE_OK_CODE))
                except (TypeError, ValueError):
                    code = -1
                if code != TENCENT_SOE_OK_CODE:
                    raise AssessmentError(
                        self._error_message(code, str(payload.get("message", "")))
                    )
                result = payload.get("result")
                if result:
                    last_result = result
                if str(payload.get("final", 0)) == "1":
                    if last_result is None:
                        raise AssessmentError("评测服务没有返回分数。")
                    return self._parse_result(last_result)
        except AssessmentError:
            raise
        except (TimeoutError, websocket.WebSocketTimeoutException) as exc:
            raise AssessmentError("腾讯云评测服务响应超时，请稍后再试。") from exc
        except (OSError, websocket.WebSocketException) as exc:
            raise AssessmentError("无法连接腾讯云评测服务，请检查网络后重试。") from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


def get_assessor() -> Assessor:
    """Return the configured assessor, refusing to guess missing credentials."""
    provider = settings.ASSESSMENT_PROVIDER
    if provider == "mock":
        return MockAssessor()
    if provider == "tencent":
        missing = [
            name
            for name, value in (
                ("TENCENT_SOE_APP_ID", settings.TENCENT_SOE_APP_ID),
                ("TENCENTCLOUD_SECRET_ID", settings.TENCENTCLOUD_SECRET_ID),
                ("TENCENTCLOUD_SECRET_KEY", settings.TENCENTCLOUD_SECRET_KEY),
            )
            if not value
        ]
        if missing:
            raise AssessmentError("腾讯云口语评测尚未配置完整凭据。")
        return TencentSOEAssessor(
            app_id=settings.TENCENT_SOE_APP_ID,
            secret_id=settings.TENCENTCLOUD_SECRET_ID,
            secret_key=settings.TENCENTCLOUD_SECRET_KEY,
            engine=settings.TENCENT_SOE_ENGINE,
            score_coeff=settings.TENCENT_SOE_SCORE_COEFF,
            timeout=settings.TENCENT_SOE_TIMEOUT,
        )
    raise AssessmentError("单词测评服务配置错误，请联系管理员。")
