"""Security response headers for every Django response."""

from __future__ import annotations

from django.conf import settings


class SecurityHeadersMiddleware:
    HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob: https://res.cloudinary.com"
        ),
        "Referrer-Policy": "same-origin",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        for header, value in self.HEADERS.items():
            response.setdefault(header, value)
        if settings.DEBUG:
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response
