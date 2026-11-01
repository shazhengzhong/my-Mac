"""Photo OCR provider adapters with a mock-first safety default."""

import base64
from dataclasses import dataclass
import datetime
import hashlib
import hmac
import io
import json
import time
from typing import Protocol

import httpx
from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    # HEIC is optional; JPEG/PNG/BMP still work without the plugin.
    pass

MAX_OCR_IMAGE_BYTES = 5 * 1024 * 1024
MAX_OCR_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_OCR_IMAGE_PIXELS = 40_000_000
MAX_OCR_CROP_DIMENSION = 2400
MAX_OCR_TEXT_CHARS = 5000

MOCK_OCR_TEXT = (
    "The weather is lovely today. I took a walk with my family.\n"
    "We saw a small bird near the river. It made me feel happy."
)

_JSON_CONTENT_TYPE = "application/json; charset=utf-8"
_SIGNED_HEADERS = "content-type;host"


class OCRError(Exception):
    """A user-safe OCR failure; never include secrets or image contents."""


@dataclass(frozen=True)
class OCRResult:
    text: str
    provider: str
    model: str
    line_count: int


class OCRProvider(Protocol):
    provider: str
    model: str

    def recognize(self, image_bytes: bytes) -> OCRResult: ...


def _detect_image_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"BM"):
        return "image/bmp"
    return None


def validate_ocr_image(data: bytes) -> str:
    """Validate size and magic bytes, returning a normalized image type."""
    if not data:
        raise OCRError("没有收到照片，请重新选择。")
    if len(data) > MAX_OCR_IMAGE_BYTES:
        raise OCRError("照片不能超过 5MB，请压缩或先截图后再上传。")
    image_type = _detect_image_type(data)
    if image_type is None:
        raise OCRError("只支持 JPG、PNG 或 BMP 照片，请换一张图片。")
    return image_type


def prepare_ocr_image(
    data: bytes,
    crop: tuple[float, float, float, float] | None,
) -> bytes:
    """Apply browser crop coordinates, orient and compress an OCR photo.

    Crop values are fractions of the displayed (EXIF-oriented) image:
    (x, y, width, height), each between 0 and 1. The result is always a
    JPEG no larger than the OCR provider limit.
    """
    if not data:
        raise OCRError("没有收到照片，请重新选择。")
    if len(data) > MAX_OCR_UPLOAD_BYTES:
        raise OCRError("照片太大，请选择 25MB 以内的图片。")

    if crop is not None:
        x, y, width, height = crop
        if not (
            0 <= x < 1
            and 0 <= y < 1
            and 0 < width <= 1
            and 0 < height <= 1
            and x + width <= 1.0001
            and y + height <= 1.0001
        ):
            raise OCRError("裁剪区域无效，请重新选择照片和裁剪范围。")

    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > MAX_OCR_IMAGE_PIXELS:
            raise OCRError("照片分辨率太高，请先缩小或截图后再上传。")
        image.load()
    except OCRError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise OCRError("只支持 JPG、PNG、BMP 或 HEIC 图片，请换一张。")

    image = ImageOps.exif_transpose(image)

    if crop is not None:
        x, y, width, height = crop
        image_width, image_height = image.size
        left = min(image_width - 1, max(0, round(x * image_width)))
        top = min(image_height - 1, max(0, round(y * image_height)))
        right = min(
            image_width,
            max(left + 1, round((x + width) * image_width)),
        )
        bottom = min(
            image_height,
            max(top + 1, round((y + height) * image_height)),
        )
        image = image.crop((left, top, right, bottom))

    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")

    for attempt in range(5):
        max_side = max(800, round(MAX_OCR_CROP_DIMENSION * (0.8**attempt)))
        image_width, image_height = image.size
        scale = min(1.0, max_side / max(image_width, image_height))
        output_width = max(1, round(image_width * scale))
        output_height = max(1, round(image_height * scale))
        output = (
            image
            if scale >= 1
            else image.resize(
                (output_width, output_height),
                Image.Resampling.LANCZOS,
            )
        )
        for quality in (90, 82, 72):
            buffer = io.BytesIO()
            output.save(
                buffer,
                format="JPEG",
                quality=quality,
                optimize=True,
            )
            if buffer.tell() <= MAX_OCR_IMAGE_BYTES:
                return buffer.getvalue()

    raise OCRError("照片压缩后仍然太大，请把裁剪方框缩小一点再试。")


class MockOCRProvider:
    """Development-only OCR text with no network call and no cost."""

    provider = "mock"
    model = "mock"

    def recognize(self, image_bytes: bytes) -> OCRResult:
        if not image_bytes:
            raise OCRError("没有收到照片，请重新选择。")
        lines = MOCK_OCR_TEXT.splitlines()
        return OCRResult(
            text=MOCK_OCR_TEXT,
            provider=self.provider,
            model=self.model,
            line_count=len(lines),
        )


def _authorization_headers(
    *,
    secret_id: str,
    secret_key: str,
    region: str,
    action: str,
    version: str,
    payload: bytes,
    host: str,
    timestamp: int,
) -> dict[str, str]:
    """Build Tencent Cloud TC3-HMAC-SHA256 headers for an OCR request."""
    date = datetime.datetime.fromtimestamp(
        timestamp, datetime.timezone.utc
    ).strftime("%Y-%m-%d")
    canonical_headers = f"content-type:{_JSON_CONTENT_TYPE}\nhost:{host}\n"
    hashed_payload = hashlib.sha256(payload).hexdigest()
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            "",
            canonical_headers,
            _SIGNED_HEADERS,
            hashed_payload,
        ]
    )
    credential_scope = f"{date}/ocr/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = hmac.new(
        ("TC3" + secret_key).encode("utf-8"),
        date.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    secret_service = hmac.new(
        secret_date,
        b"ocr",
        hashlib.sha256,
    ).digest()
    secret_signing = hmac.new(
        secret_service,
        b"tc3_request",
        hashlib.sha256,
    ).digest()
    signature = hmac.new(
        secret_signing,
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={_SIGNED_HEADERS}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": _JSON_CONTENT_TYPE,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": region,
    }


class TencentOCRProvider:
    """Tencent Cloud GeneralBasicOCR adapter using signed HTTPS requests."""

    provider = "tencent_ocr"
    model = "GeneralBasicOCR"

    def __init__(
        self,
        *,
        secret_id: str,
        secret_key: str,
        region: str = "ap-guangzhou",
        endpoint: str = "ocr.tencentcloudapi.com",
        action: str = "GeneralBasicOCR",
        version: str = "2018-11-19",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
        timestamp: int | None = None,
    ):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.region = region
        self.endpoint = endpoint
        self.action = action
        self.version = version
        self.timeout = timeout
        self._client = client
        self._timestamp = timestamp

    def _request(self, client: httpx.Client, image_bytes: bytes) -> OCRResult:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        body = json.dumps(
            {"ImageBase64": encoded, "LanguageType": "zh"},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = (
            self._timestamp
            if self._timestamp is not None
            else int(time.time())
        )
        headers = _authorization_headers(
            secret_id=self.secret_id,
            secret_key=self.secret_key,
            region=self.region,
            action=self.action,
            version=self.version,
            payload=body,
            host=self.endpoint,
            timestamp=timestamp,
        )
        try:
            response = client.post(
                f"https://{self.endpoint}/",
                headers=headers,
                content=body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            code = (
                exc.response.status_code
                if exc.response is not None
                else "unknown"
            )
            raise OCRError(
                f"OCR 服务返回错误（{code}），请稍后再试。"
            ) from exc
        except httpx.TimeoutException as exc:
            raise OCRError("OCR 服务响应超时，请稍后再试。") from exc
        except httpx.HTTPError as exc:
            raise OCRError("暂时无法连接 OCR 服务，请检查网络后再试。") from exc

        try:
            data = response.json()
            result = data["Response"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OCRError("OCR 服务返回了无法识别的内容，请稍后再试。") from exc

        if "Error" in result:
            error = result.get("Error") or {}
            code = error.get("Code") or "unknown"
            raise OCRError(
                f"OCR 识别失败（{code}），请稍后再试或检查腾讯云配置。"
            )

        detections = result.get("TextDetections")
        if not isinstance(detections, list):
            raise OCRError("OCR 服务返回了无法识别的内容，请稍后再试。")
        lines = [
            str(item.get("DetectedText", "")).strip()
            for item in detections
            if isinstance(item, dict) and str(item.get("DetectedText", "")).strip()
        ]
        if not lines:
            raise OCRError("没有识别到文字，请换一张更清晰的照片。")
        return OCRResult(
            text="\n".join(lines),
            provider=self.provider,
            model=self.model,
            line_count=len(lines),
        )

    def recognize(self, image_bytes: bytes) -> OCRResult:
        if not image_bytes:
            raise OCRError("没有收到照片，请重新选择。")
        if self._client is not None:
            return self._request(self._client, image_bytes)
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout, connect=10.0)
            ) as client:
                return self._request(client, image_bytes)
        except httpx.HTTPError as exc:
            raise OCRError(
                "暂时无法连接 OCR 服务，请检查网络后再试。"
            ) from exc


def get_ocr_provider() -> OCRProvider:
    """Return the configured OCR provider, refusing to guess credentials."""
    provider = settings.OCR_PROVIDER
    if provider == "mock":
        return MockOCRProvider()
    if provider == "tencent":
        if not settings.TENCENTCLOUD_SECRET_ID or not settings.TENCENTCLOUD_SECRET_KEY:
            raise OCRError(
                "腾讯云 OCR 的 SecretId/SecretKey 尚未配置，暂时无法识别照片。"
            )
        return TencentOCRProvider(
            secret_id=settings.TENCENTCLOUD_SECRET_ID,
            secret_key=settings.TENCENTCLOUD_SECRET_KEY,
            region=settings.TENCENT_OCR_REGION,
            endpoint=settings.TENCENT_OCR_ENDPOINT,
            action=settings.TENCENT_OCR_ACTION,
            version=settings.TENCENT_OCR_VERSION,
            timeout=settings.TENCENT_OCR_TIMEOUT,
        )
    raise OCRError("OCR 服务配置错误，请联系管理员。")
