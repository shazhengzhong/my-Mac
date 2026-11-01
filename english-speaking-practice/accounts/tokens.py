"""High-entropy invitation and recovery-code generation helpers."""

import base64
import hashlib
import re
import secrets

INVITE_CODE_LENGTH = 20
RECOVERY_CODE_LENGTH = 16
_CODE_ALPHABET = re.compile(r"[^A-Z2-7]")


class InvalidCode(ValueError):
    """Raised when a user-supplied one-time code has an invalid shape."""


def _random_base32(byte_count: int) -> str:
    return base64.b32encode(secrets.token_bytes(byte_count)).decode("ascii").rstrip("=")


def _grouped(value: str) -> str:
    return "-".join(value[index : index + 4] for index in range(0, len(value), 4))


def normalize_invite_code(raw: str) -> str:
    cleaned = _CODE_ALPHABET.sub("", (raw or "").strip().upper())
    if len(cleaned) != INVITE_CODE_LENGTH:
        raise InvalidCode("邀请码格式不正确")
    return cleaned


def normalize_recovery_code(raw: str) -> str:
    cleaned = _CODE_ALPHABET.sub("", (raw or "").strip().upper())
    if len(cleaned) != RECOVERY_CODE_LENGTH:
        raise InvalidCode("恢复码格式不正确")
    return cleaned


def generate_invite_code() -> str:
    """Generate a 96-bit human-copyable invitation code."""
    return _grouped(_random_base32(12))


def generate_recovery_code() -> str:
    """Generate an 80-bit human-copyable recovery code."""
    return _grouped(_random_base32(10))


def generate_recovery_codes(count: int = 10) -> list[str]:
    if count < 1 or count > 20:
        raise ValueError("count must be between 1 and 20")
    return [generate_recovery_code() for _ in range(count)]


def hash_secret(normalized_code: str) -> str:
    """Store only a digest of a high-entropy one-time code."""
    return hashlib.sha256(normalized_code.encode("ascii")).hexdigest()
