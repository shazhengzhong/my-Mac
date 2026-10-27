"""Small non-sensitive endpoints used to verify the application boots."""

from django.http import JsonResponse


def health(request):
    """Return a deliberately minimal public health response."""
    return JsonResponse({"status": "ok", "app": "family-english-diary"})
