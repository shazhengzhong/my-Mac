"""Small non-sensitive endpoints used to verify the application boots."""

from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse


def health(request):
    """Return a deliberately minimal public health response."""
    return JsonResponse({"status": "ok", "app": "family-english-diary"})


def service_worker(request):
    """Serve the PWA service worker from the site root so its scope is /."""
    path = Path(settings.BASE_DIR) / "static" / "js" / "service-worker.js"
    response = HttpResponse(
        path.read_text(encoding="utf-8"),
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response
