"""URL configuration for the family English diary app."""

from django.urls import include, path

from accounts import views as account_views

from .views import health, service_worker

urlpatterns = [
    path("", account_views.home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("diaries/", include("diaries.urls")),
    path("health/", health, name="health"),
    path("service-worker.js", service_worker, name="service_worker"),
]
