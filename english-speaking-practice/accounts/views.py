"""Views for family accounts, invitations, and password recovery."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .forms import (
    GENERIC_INVITE_ERROR,
    GENERIC_RECOVERY_ERROR,
    InvitationCreateForm,
    JoinForm,
    PhoneAuthenticationForm,
    RecoveryResetForm,
)
from .models import Invitation, RecoveryCode, User
from .phones import mask_phone
from .tokens import hash_secret


class PhoneLoginView(LoginView):
    authentication_form = PhoneAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


class AccountPasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("account_settings")

    def form_valid(self, form):
        messages.success(self.request, "密码已修改，其他设备上的登录已失效。")
        return super().form_valid(form)


def _owner_only(user) -> None:
    if not user.is_owner:
        raise PermissionDenied("只有家庭管理员可以访问这个页面。")


def _recovery_code_response(request, codes: list[str], *, new_account: bool):
    response = render(
        request,
        "accounts/recovery_codes.html",
        {"codes": codes, "new_account": new_account},
    )
    response["Cache-Control"] = "no-store"
    return response


@login_required
@never_cache
def home(request):
    active_codes = request.user.recovery_codes.filter(used_at__isnull=True).count()
    diary_count = request.user.diary_entries.count()
    return render(
        request,
        "accounts/home.html",
        {
            "active_recovery_codes": active_codes,
            "diary_count": diary_count,
        },
    )


@login_required
@never_cache
def account_settings(request):
    active_codes = request.user.recovery_codes.filter(used_at__isnull=True).count()
    return render(
        request,
        "accounts/settings.html",
        {
            "active_recovery_codes": active_codes,
            "masked_phone": mask_phone(request.user.phone),
        },
    )


@login_required
@require_POST
@never_cache
def set_accent(request):
    accent = (request.POST.get("accent") or "").strip()
    if accent not in User.Accent.values:
        messages.error(request, "未识别的发音选项。")
        return redirect("home")

    request.user.accent = accent
    request.user.save(update_fields=["accent"])

    next_url = request.POST.get("next") or ""
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("home")
    return redirect(next_url)


@login_required
@never_cache
def create_invitation(request):
    _owner_only(request.user)
    form = InvitationCreateForm(request.POST or None)
    invite_code = None
    invite_expires_at = None

    if request.method == "POST" and form.is_valid():
        invitation, invite_code = Invitation.issue(
            family=request.user.family,
            created_by=request.user,
            expected_phone=form.cleaned_data["phone"],
        )
        invite_expires_at = invitation.expires_at
        form = InvitationCreateForm()

    active_invitations = (
        Invitation.objects.filter(
            family=request.user.family,
            used_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .only("expected_phone", "expires_at")
        .order_by("expires_at")
    )
    invitation_rows = [
        {
            "masked_phone": mask_phone(invitation.expected_phone),
            "expires_at": invitation.expires_at,
        }
        for invitation in active_invitations
    ]

    response = render(
        request,
        "accounts/invite_create.html",
        {
            "form": form,
            "invite_code": invite_code,
            "invite_expires_at": invite_expires_at,
            "active_invitations": invitation_rows,
        },
    )
    if invite_code:
        response["Cache-Control"] = "no-store"
    return response


@login_required
@never_cache
def members(request):
    _owner_only(request.user)
    member_rows = request.user.family.members.only(
        "display_name", "role", "date_joined"
    ).order_by("date_joined")
    return render(request, "accounts/members.html", {"members": member_rows})


class _InvitationUnavailable(Exception):
    pass


@never_cache
def join_family(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = JoinForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        invite_code = form.cleaned_data["invite_code"]
        display_name = form.cleaned_data["display_name"]
        password = form.cleaned_data["password1"]

        try:
            with transaction.atomic():
                invitation = (
                    Invitation.objects.select_for_update()
                    .select_related("family")
                    .filter(
                        token_hash=hash_secret(invite_code),
                        used_at__isnull=True,
                        revoked_at__isnull=True,
                        expires_at__gt=timezone.now(),
                    )
                    .first()
                )
                if invitation is None or not invitation.is_usable_for(phone):
                    raise _InvitationUnavailable
                if User.objects.filter(phone=phone).exists():
                    raise _InvitationUnavailable

                user = User.objects.create_user(
                    phone=phone,
                    password=password,
                    display_name=display_name,
                    family=invitation.family,
                    role=User.Role.MEMBER,
                )
                invitation.used_at = timezone.now()
                invitation.used_by = user
                invitation.save(update_fields=["used_at", "used_by"])
                recovery_codes = RecoveryCode.issue(user)
        except (_InvitationUnavailable, IntegrityError):
            form.add_error(None, GENERIC_INVITE_ERROR)
        else:
            login(
                request,
                user,
                backend="django.contrib.auth.backends.ModelBackend",
            )
            return _recovery_code_response(request, recovery_codes, new_account=True)

    return render(request, "accounts/join.html", {"form": form})


@never_cache
def recovery_reset(request):
    form = RecoveryResetForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        recovery_code = form.cleaned_data["recovery_code"]
        new_password = form.cleaned_data["new_password1"]
        code_hash = hash_secret(recovery_code)

        reset_succeeded = False
        with transaction.atomic():
            user = (
                User.objects.select_for_update()
                .filter(phone=phone, is_active=True)
                .first()
            )
            recovery = None
            if user is not None:
                recovery = (
                    RecoveryCode.objects.select_for_update()
                    .filter(user=user, code_hash=code_hash, used_at__isnull=True)
                    .first()
                )
            if recovery is not None:
                user.set_password(new_password)
                user.save(update_fields=["password"])
                recovery.used_at = timezone.now()
                recovery.save(update_fields=["used_at"])
                reset_succeeded = True

        if reset_succeeded:
            messages.success(request, "密码已重置，请使用新密码登录。")
            return redirect("login")
        form.add_error(None, GENERIC_RECOVERY_ERROR)

    return render(request, "accounts/recovery_reset.html", {"form": form})


@login_required
@require_POST
@never_cache
def regenerate_recovery_codes(request):
    codes = RecoveryCode.issue(request.user)
    return _recovery_code_response(request, codes, new_account=False)
