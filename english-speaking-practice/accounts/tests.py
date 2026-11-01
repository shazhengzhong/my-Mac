"""Account, invitation, recovery, and access-control tests."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Family, Invitation, RecoveryCode, User
from .phones import mask_phone, normalize_phone
from .tokens import hash_secret, normalize_invite_code, normalize_recovery_code

MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"
PASSWORD = "Brisk-Cobalt-Orbit-42"
NEW_PASSWORD = "Quiet-Lantern-River-84"
OWNER_PHONE = "+8613800000000"
MEMBER_PHONE = "+8613900000000"
NEW_MEMBER_PHONE = "+8613600000000"


class PhoneUtilityTests(TestCase):
    def test_normalizes_mainland_and_international_numbers(self):
        self.assertEqual(normalize_phone("138 0013 8000"), "+8613800138000")
        self.assertEqual(normalize_phone("+86 138-0013-8000"), "+8613800138000")
        self.assertEqual(normalize_phone("0086 13800138000"), "+8613800138000")
        self.assertEqual(normalize_phone("8613800138000"), "+8613800138000")
        self.assertEqual(normalize_phone("+1 (415) 555-2671"), "+14155552671")

    def test_rejects_invalid_numbers(self):
        for raw in ("", "12345", "1380013800", "abc", "13800138000x"):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                normalize_phone(raw)

    def test_masks_phone(self):
        self.assertEqual(mask_phone("+8613800138000"), "138****8000")
        self.assertNotIn("13800138000", mask_phone("+8613800138000"))


class AccountModelTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name="测试家庭")
        self.owner = User.objects.create_user(
            phone="13800000000",
            password=PASSWORD,
            display_name="管理员",
            family=self.family,
            role=User.Role.OWNER,
        )

    def test_phone_is_normalized_and_unique(self):
        self.assertEqual(self.owner.phone, OWNER_PHONE)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                phone="+86 138 0000 0000",
                password=PASSWORD,
                display_name="重复",
                family=self.family,
            )

    def test_one_owner_per_family(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                phone="13800000001",
                password=PASSWORD,
                display_name="第二管理员",
                family=self.family,
                role=User.Role.OWNER,
            )

    def test_invitation_is_hashed_and_phone_bound(self):
        invitation, raw_code = Invitation.issue(
            family=self.family,
            created_by=self.owner,
            expected_phone="139 0000 0000",
        )
        self.assertNotEqual(invitation.token_hash, raw_code)
        self.assertEqual(
            invitation.token_hash,
            hash_secret(normalize_invite_code(raw_code)),
        )
        self.assertEqual(invitation.expected_phone, MEMBER_PHONE)
        self.assertTrue(invitation.is_usable_for(MEMBER_PHONE))
        self.assertFalse(invitation.is_usable_for("+8613600000000"))

    def test_only_owner_can_create_invitation(self):
        member = User.objects.create_user(
            phone=MEMBER_PHONE,
            password=PASSWORD,
            display_name="成员",
            family=self.family,
        )
        with self.assertRaises(ValueError):
            Invitation.issue(
                family=self.family,
                created_by=member,
                expected_phone=NEW_MEMBER_PHONE,
            )

    def test_recovery_codes_are_hashed_and_one_time(self):
        raw_codes = RecoveryCode.issue(self.owner)
        self.assertEqual(len(raw_codes), 10)
        self.assertEqual(
            RecoveryCode.objects.filter(
                user=self.owner, code_hash=hash_secret(normalize_recovery_code(raw_codes[0]))
            ).count(),
            1,
        )
        self.assertFalse(
            RecoveryCode.objects.filter(code_hash=raw_codes[0].replace("-", "")).exists()
        )


class AuthenticationTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name="测试家庭")
        self.owner = User.objects.create_user(
            phone=OWNER_PHONE,
            password=PASSWORD,
            display_name="管理员",
            family=self.family,
            role=User.Role.OWNER,
        )
        self.member = User.objects.create_user(
            phone=MEMBER_PHONE,
            password=PASSWORD,
            display_name="成员",
            family=self.family,
        )

    def test_home_requires_login(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_login_accepts_formatted_phone(self):
        response = self.client.post(
            reverse("login"),
            {"username": "138 0000 0000", "password": PASSWORD},
        )
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(self.client.session["_auth_user_id"], str(self.owner.pk))

    def test_login_rejects_bad_credentials(self):
        response = self.client.post(
            reverse("login"),
            {"username": OWNER_PHONE, "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        self.client.force_login(self.owner, backend=MODEL_BACKEND)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_route_is_not_exposed(self):
        self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_login_is_locked_after_repeated_failures(self):
        for _ in range(5):
            self.client.post(
                reverse("login"),
                {"username": OWNER_PHONE, "password": "definitely-wrong"},
            )
        response = self.client.post(
            reverse("login"),
            {"username": OWNER_PHONE, "password": PASSWORD},
        )
        self.assertIn(response.status_code, {200, 403, 429})
        self.assertNotIn("_auth_user_id", self.client.session)


class OwnerPagesTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name="测试家庭")
        self.owner = User.objects.create_user(
            phone=OWNER_PHONE,
            password=PASSWORD,
            display_name="管理员",
            family=self.family,
            role=User.Role.OWNER,
        )
        self.member = User.objects.create_user(
            phone=MEMBER_PHONE,
            password=PASSWORD,
            display_name="成员",
            family=self.family,
        )
        self.client.force_login(self.owner, backend=MODEL_BACKEND)

    def test_owner_can_generate_invitation(self):
        response = self.client.post(
            reverse("create_invitation"),
            {"phone": "136 0000 0000"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/invite_create.html")
        invitation = Invitation.objects.get(expected_phone=NEW_MEMBER_PHONE)
        raw_code = response.context["invite_code"]
        self.assertTrue(raw_code)
        self.assertEqual(
            invitation.token_hash,
            hash_secret(normalize_invite_code(raw_code)),
        )
        self.assertContains(response, raw_code)

    def test_member_cannot_access_admin_pages(self):
        self.client.force_login(self.member, backend=MODEL_BACKEND)
        for name in ("create_invitation", "members"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_members_page_hides_phone_numbers_and_content(self):
        response = self.client.get(reverse("members"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成员")
        self.assertNotContains(response, self.member.phone)
        self.assertNotContains(response, "日记内容")

    def test_anonymous_cannot_access_owner_pages(self):
        self.client.logout()
        for name in ("create_invitation", "members"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)


class JoinFlowTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name="测试家庭")
        self.owner = User.objects.create_user(
            phone=OWNER_PHONE,
            password=PASSWORD,
            display_name="管理员",
            family=self.family,
            role=User.Role.OWNER,
        )
        self.invitation, self.invite_code = Invitation.issue(
            family=self.family,
            created_by=self.owner,
            expected_phone=NEW_MEMBER_PHONE,
        )

    def post_join(self, **overrides):
        data = {
            "invite_code": self.invite_code,
            "phone": NEW_MEMBER_PHONE,
            "display_name": "新成员",
            "password1": NEW_PASSWORD,
            "password2": NEW_PASSWORD,
        }
        data.update(overrides)
        return self.client.post(reverse("join"), data)

    def test_valid_invitation_creates_one_account_and_shows_codes_once(self):
        response = self.post_join()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/recovery_codes.html")
        self.assertIn("Cache-Control", response)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(len(response.context["codes"]), 10)

        user = User.objects.get(phone=NEW_MEMBER_PHONE)
        self.assertEqual(user.family, self.family)
        self.assertEqual(user.role, User.Role.MEMBER)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.invitation.refresh_from_db()
        self.assertIsNotNone(self.invitation.used_at)

        self.client.logout()
        second = self.post_join(phone="+8613700000000")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(User.objects.filter(phone="+8613700000000").count(), 0)

    def test_wrong_phone_is_rejected(self):
        response = self.post_join(phone="+8613700000000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(phone="+8613700000000").count(), 0)
        self.invitation.refresh_from_db()
        self.assertIsNone(self.invitation.used_at)

    def test_mismatched_passwords_are_rejected(self):
        response = self.post_join(password2="Different-Strong-Pass-99")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(phone=NEW_MEMBER_PHONE).exists())
        self.invitation.refresh_from_db()
        self.assertIsNone(self.invitation.used_at)

    def test_expired_invitation_is_rejected(self):
        self.invitation.expires_at = timezone.now() - timedelta(minutes=1)
        self.invitation.save(update_fields=["expires_at"])
        response = self.post_join()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(phone=NEW_MEMBER_PHONE).exists())


class RecoveryFlowTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name="测试家庭")
        self.owner = User.objects.create_user(
            phone=OWNER_PHONE,
            password=PASSWORD,
            display_name="管理员",
            family=self.family,
            role=User.Role.OWNER,
        )
        self.member = User.objects.create_user(
            phone=MEMBER_PHONE,
            password=PASSWORD,
            display_name="成员",
            family=self.family,
        )
        self.codes = RecoveryCode.issue(self.member)

    def reset(self, code, new_password=NEW_PASSWORD):
        return self.client.post(
            reverse("recovery_reset"),
            {
                "phone": self.member.phone,
                "recovery_code": code,
                "new_password1": new_password,
                "new_password2": new_password,
            },
        )

    def test_recovery_code_resets_password_once(self):
        response = self.reset(self.codes[0])
        self.assertRedirects(response, reverse("login"))
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(NEW_PASSWORD))

        reused = self.reset(self.codes[0], new_password="Another-Long-Pass-77")
        self.assertEqual(reused.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(NEW_PASSWORD))

    def test_invalid_recovery_code_is_generic(self):
        response = self.reset("AAAA-AAAA-AAAA-AAAA")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "手机号或恢复码无效")
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(PASSWORD))

    def test_regenerating_codes_invalidates_old_ones(self):
        self.client.force_login(self.member, backend=MODEL_BACKEND)
        response = self.client.post(reverse("regenerate_recovery_codes"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["codes"]), 10)
        self.assertEqual(
            RecoveryCode.objects.filter(user=self.member, used_at__isnull=True).count(),
            10,
        )
        self.client.logout()
        old_code_response = self.reset(self.codes[0], new_password="Old-Code-Still-Bad-31")
        self.assertEqual(old_code_response.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(PASSWORD))

    def test_recovery_reset_invalidates_other_sessions(self):
        other_client = Client()
        other_client.force_login(self.member, backend=MODEL_BACKEND)
        self.assertEqual(other_client.get(reverse("home")).status_code, 200)

        response = self.reset(self.codes[0])
        self.assertRedirects(response, reverse("login"))

        self.assertEqual(other_client.get(reverse("home")).status_code, 302)
        self.assertNotIn("_auth_user_id", other_client.session)


class PageSmokeTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name="测试家庭")
        self.owner = User.objects.create_user(
            phone=OWNER_PHONE,
            password=PASSWORD,
            display_name="管理员",
            family=self.family,
            role=User.Role.OWNER,
        )
        self.client.force_login(self.owner, backend=MODEL_BACKEND)

    def test_authenticated_pages_render(self):
        for name in (
            "home",
            "account_settings",
            "password_change",
            "create_invitation",
            "members",
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_public_pages_render(self):
        public_client = Client()
        for name in ("login", "join", "recovery_reset"):
            with self.subTest(name=name):
                response = public_client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "csrfmiddlewaretoken")

    def test_settings_shows_masked_phone(self):
        response = self.client.get(reverse("account_settings"))
        self.assertContains(response, "138****0000")
        self.assertNotContains(response, self.owner.phone)


class BootstrapFamilyCommandTests(TestCase):
    def test_bootstraps_one_family_and_owner(self):
        output = StringIO()
        with patch(
            "accounts.management.commands.bootstrap_family.getpass",
            side_effect=[PASSWORD, PASSWORD],
        ):
            call_command(
                "bootstrap_family",
                family_name="我家",
                phone="13800000000",
                display_name="首位管理员",
                stdout=output,
            )
        self.assertEqual(Family.objects.count(), 1)
        owner = User.objects.get(phone=OWNER_PHONE)
        self.assertEqual(owner.role, User.Role.OWNER)
        self.assertEqual(owner.family.name, "我家")
        self.assertEqual(RecoveryCode.objects.filter(user=owner).count(), 10)
        self.assertIn("恢复码", output.getvalue())

    def test_refuses_second_family(self):
        Family.objects.create(name="已有家庭")
        with patch(
            "accounts.management.commands.bootstrap_family.getpass",
            side_effect=[PASSWORD, PASSWORD],
        ), self.assertRaises(CommandError):
            call_command("bootstrap_family")
        self.assertEqual(Family.objects.count(), 1)
