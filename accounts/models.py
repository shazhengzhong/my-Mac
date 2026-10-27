"""Family, user, invitation, and recovery-code models."""

from datetime import timedelta
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from .phones import normalize_phone
from .tokens import (
    generate_invite_code,
    generate_recovery_codes,
    hash_secret,
    normalize_invite_code,
    normalize_recovery_code,
)


class Family(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone: str, password: str | None = None, **extra_fields):
        if not phone:
            raise ValueError("手机号不能为空")
        if not password:
            raise ValueError("密码不能为空")
        if not extra_fields.get("display_name"):
            raise ValueError("显示名不能为空")
        if not extra_fields.get("family"):
            raise ValueError("用户必须属于一个家庭")

        user = self.model(phone=normalize_phone(phone), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        OWNER = "owner", "家庭管理员"
        MEMBER = "member", "家庭成员"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=16, unique=True)
    display_name = models.CharField(max_length=50)
    family = models.ForeignKey(Family, on_delete=models.PROTECT, related_name="members")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["family"],
                condition=Q(role="owner"),
                name="accounts_one_owner_per_family",
            )
        ]

    def save(self, *args, **kwargs):
        # Backstop for callers that bypass forms; manager also normalizes.
        self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

    @property
    def is_owner(self) -> bool:
        return self.role == self.Role.OWNER

    def get_full_name(self) -> str:
        return self.display_name

    def get_short_name(self) -> str:
        return self.display_name

    def __str__(self) -> str:
        return self.display_name


class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="invitations")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_invitations",
    )
    expected_phone = models.CharField(max_length=16)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="used_invitations",
        null=True,
        blank=True,
    )

    def save(self, *args, **kwargs):
        self.expected_phone = normalize_phone(self.expected_phone)
        super().save(*args, **kwargs)

    def is_usable_for(self, phone: str) -> bool:
        if self.used_at or self.revoked_at or self.expires_at <= timezone.now():
            return False
        try:
            normalized = normalize_phone(phone)
        except ValidationError:
            return False
        return self.expected_phone == normalized

    @classmethod
    def issue(cls, *, family, created_by, expected_phone: str):
        """Create an invitation and return (invitation, raw_code_once)."""
        if created_by.family_id != family.id or not created_by.is_owner:
            raise ValueError("只有家庭管理员可以生成邀请")
        raw_code = generate_invite_code()
        normalized = normalize_invite_code(raw_code)
        invitation = cls.objects.create(
            family=family,
            created_by=created_by,
            expected_phone=normalize_phone(expected_phone),
            token_hash=hash_secret(normalized),
            expires_at=timezone.now() + timedelta(days=7),
        )
        return invitation, raw_code

    def __str__(self) -> str:
        return f"邀请 {self.pk}"


class RecoveryCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recovery_codes",
    )
    code_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, user, count: int = 10) -> list[str]:
        """Invalidate previous unused codes and return a fresh raw set once."""
        raw_codes = generate_recovery_codes(count)
        now = timezone.now()
        with transaction.atomic():
            cls.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
            cls.objects.bulk_create(
                [
                    cls(
                        user=user,
                        code_hash=hash_secret(normalize_recovery_code(raw)),
                    )
                    for raw in raw_codes
                ]
            )
        return raw_codes
