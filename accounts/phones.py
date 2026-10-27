"""Phone number validation and masking helpers."""

import re

from django.core.exceptions import ValidationError

_INVALID_MESSAGE = "请输入 11 位中国大陆手机号，或带 + 的国际号码。"
_SEPARATORS = re.compile(r"[\s\-().]")


def normalize_phone(raw: str) -> str:
    """Return a stable E.164-like phone representation.

    Chinese mobile numbers are accepted without a country code. Other numbers
    must include a leading ``+``. The number is an account identifier only; it
    is not verified by SMS in this project.
    """
    value = _SEPARATORS.sub("", (raw or "").strip())

    if not value:
        raise ValidationError(_INVALID_MESSAGE)

    if value.startswith("00"):
        value = "+" + value[2:]

    if value.startswith("+"):
        digits = value[1:]
        if not digits.isdigit() or not (8 <= len(digits) <= 15):
            raise ValidationError(_INVALID_MESSAGE)
        return "+" + digits

    # Accept a pasted Chinese number that includes the 86 country code.
    if value.isdigit() and len(value) == 13 and value.startswith("86"):
        value = value[2:]

    if (
        value.isdigit()
        and len(value) == 11
        and value.startswith("1")
        and value[1] in "3456789"
    ):
        return "+86" + value

    raise ValidationError(_INVALID_MESSAGE)


def mask_phone(phone: str) -> str:
    """Return a display-safe phone value for owner-facing invitation lists."""
    if phone.startswith("+86") and len(phone) == 14:
        national = phone[3:]
        return f"{national[:3]}****{national[-4:]}"
    if phone.startswith("+") and len(phone) >= 8:
        return f"{phone[:4]}****{phone[-4:]}"
    return "****"
