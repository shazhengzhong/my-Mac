"""Forms for phone login, invitation-only signup, and recovery."""

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Invitation, User
from .phones import normalize_phone
from .tokens import (
    InvalidCode,
    hash_secret,
    normalize_invite_code,
    normalize_recovery_code,
)

GENERIC_INVITE_ERROR = "邀请码无效、已过期，或与这个手机号不匹配。"
GENERIC_RECOVERY_ERROR = "手机号或恢复码无效。"


def _phone_field(*, label: str = "手机号", widget_attrs: dict | None = None, **kwargs) -> forms.CharField:
    attrs = {
        "autocomplete": "tel",
        "inputmode": "tel",
        "placeholder": "例如 13800138000",
    }
    if widget_attrs:
        attrs.update(widget_attrs)
    return forms.CharField(
        label=label,
        max_length=20,
        widget=forms.TextInput(attrs=attrs),
        **kwargs,
    )


class PhoneAuthenticationForm(AuthenticationForm):
    username = _phone_field(widget_attrs={"autofocus": True})
    password = forms.CharField(
        label="密码",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "手机号或密码不正确。",
        "inactive": "这个账号目前不可用。",
    }

    def clean_username(self) -> str:
        value = self.cleaned_data.get("username", "")
        try:
            return normalize_phone(value)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages[0]) from exc


class JoinForm(forms.Form):
    invite_code = forms.CharField(
        label="邀请码",
        max_length=40,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "placeholder": "XXXX-XXXX-XXXX-XXXX-XXXX",
            }
        ),
    )
    phone = _phone_field()
    display_name = forms.CharField(
        label="你的名字",
        max_length=50,
        widget=forms.TextInput(attrs={"autocomplete": "nickname"}),
    )
    password1 = forms.CharField(
        label="设置密码",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="至少 12 位，不要使用常见密码。",
    )
    password2 = forms.CharField(
        label="再次输入密码",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_invite_code(self) -> str:
        try:
            return normalize_invite_code(self.cleaned_data.get("invite_code", ""))
        except InvalidCode as exc:
            raise forms.ValidationError("邀请码格式不正确。") from exc

    def clean_phone(self) -> str:
        try:
            return normalize_phone(self.cleaned_data.get("phone", ""))
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages[0]) from exc

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        phone = cleaned_data.get("phone")
        display_name = cleaned_data.get("display_name", "")
        invite_code = cleaned_data.get("invite_code")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "两次输入的密码不一致。")
        elif password1:
            candidate = User(phone=phone or "", display_name=display_name)
            try:
                password_validation.validate_password(password1, user=candidate)
            except ValidationError as exc:
                self.add_error("password1", exc)

        if invite_code and phone:
            invitation = (
                Invitation.objects.filter(
                    token_hash=hash_secret(invite_code),
                    used_at__isnull=True,
                    revoked_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                .only("expected_phone")
                .first()
            )
            if (
                invitation is None
                or invitation.expected_phone != phone
                or User.objects.filter(phone=phone).exists()
            ):
                self.add_error("invite_code", GENERIC_INVITE_ERROR)

        return cleaned_data


class InvitationCreateForm(forms.Form):
    phone = _phone_field(label="受邀家人的手机号")

    def clean_phone(self) -> str:
        try:
            phone = normalize_phone(self.cleaned_data.get("phone", ""))
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages[0]) from exc
        if User.objects.filter(phone=phone).exists():
            raise forms.ValidationError("这个手机号已经有账号，不需要再邀请。")
        return phone


class RecoveryResetForm(forms.Form):
    phone = _phone_field()
    recovery_code = forms.CharField(
        label="一次性恢复码",
        max_length=25,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "placeholder": "XXXX-XXXX-XXXX-XXXX",
            }
        ),
    )
    new_password1 = forms.CharField(
        label="新密码",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="至少 12 位。",
    )
    new_password2 = forms.CharField(
        label="再次输入新密码",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_phone(self) -> str:
        try:
            return normalize_phone(self.cleaned_data.get("phone", ""))
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages[0]) from exc

    def clean_recovery_code(self) -> str:
        try:
            return normalize_recovery_code(self.cleaned_data.get("recovery_code", ""))
        except InvalidCode as exc:
            raise forms.ValidationError("恢复码格式不正确。") from exc

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("new_password1")
        password2 = cleaned_data.get("new_password2")
        phone = cleaned_data.get("phone")
        if password1 and password2 and password1 != password2:
            self.add_error("new_password2", "两次输入的密码不一致。")
        elif password1:
            existing = User.objects.filter(phone=phone).first() if phone else None
            candidate = existing or User(phone=phone or "", display_name="")
            try:
                password_validation.validate_password(password1, user=candidate)
            except ValidationError as exc:
                self.add_error("new_password1", exc)
        return cleaned_data
