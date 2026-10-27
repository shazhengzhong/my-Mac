"""One-time local setup for the first family and its owner account."""

from getpass import getpass

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Family, RecoveryCode, User
from accounts.phones import normalize_phone


class Command(BaseCommand):
    help = "创建一个家庭和首位管理员账号；只能在空数据库中运行一次。"

    def add_arguments(self, parser):
        parser.add_argument("--family-name", help="家庭名称")
        parser.add_argument("--phone", help="管理员手机号")
        parser.add_argument("--display-name", help="管理员显示名")

    def _ask(self, label: str, provided: str | None, default: str | None = None) -> str:
        if provided:
            return provided.strip()
        suffix = f"（默认：{default}）" if default else ""
        value = input(f"{label}{suffix}: ").strip()
        if not value and default:
            return default
        return value

    def handle(self, *args, **options):
        if Family.objects.exists():
            raise CommandError("已经存在家庭，不能再次运行初始化命令。请使用家庭邀请码。")

        family_name = self._ask("家庭名称", options.get("family_name"), "我的家庭")
        if not family_name or len(family_name) > 100:
            raise CommandError("家庭名称不能为空，且不能超过 100 个字符。")

        raw_phone = self._ask("管理员手机号", options.get("phone"))
        try:
            phone = normalize_phone(raw_phone)
        except ValidationError as exc:
            raise CommandError(exc.messages[0]) from exc

        display_name = self._ask("管理员显示名", options.get("display_name"))
        if not display_name or len(display_name) > 50:
            raise CommandError("显示名不能为空，且不能超过 50 个字符。")

        password1 = getpass("设置管理员密码（输入时不会显示）: ")
        password2 = getpass("再次输入管理员密码: ")
        if password1 != password2:
            raise CommandError("两次输入的密码不一致。")

        candidate = User(phone=phone, display_name=display_name)
        try:
            password_validation.validate_password(password1, user=candidate)
        except ValidationError as exc:
            raise CommandError("密码不符合要求：" + "；".join(exc.messages)) from exc

        with transaction.atomic():
            family = Family.objects.create(name=family_name)
            owner = User.objects.create_user(
                phone=phone,
                password=password1,
                display_name=display_name,
                family=family,
                role=User.Role.OWNER,
            )
            recovery_codes = RecoveryCode.issue(owner)

        self.stdout.write(self.style.SUCCESS(f"家庭“{family.name}”和管理员账号已创建。"))
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("以下恢复码只显示这一次，请立即抄写或存入密码管理器："))
        for code in recovery_codes:
            self.stdout.write(f"  {code}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("每个恢复码只能使用一次。全部丢失后，账号将无法通过应用找回。"))
        self.stdout.write("下一步：运行 python manage.py runserver 127.0.0.1:8000")
