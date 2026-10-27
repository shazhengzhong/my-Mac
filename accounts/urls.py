"""URL routes for family accounts."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.PhoneLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("join/", views.join_family, name="join"),
    path("invite/", views.create_invitation, name="create_invitation"),
    path("members/", views.members, name="members"),
    path("recovery/", views.recovery_reset, name="recovery_reset"),
    path("settings/", views.account_settings, name="account_settings"),
    path(
        "settings/password/",
        views.AccountPasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "settings/recovery-codes/",
        views.regenerate_recovery_codes,
        name="regenerate_recovery_codes",
    ),
]
