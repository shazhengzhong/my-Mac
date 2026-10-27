"""URL configuration for the family English diary app."""

from django.urls import include, path

from accounts import views as account_views

from .views import health

urlpatterns = [
    path("", account_views.home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("diaries/", include("diaries.urls")),
    path("health/", health, name="health"),
]
