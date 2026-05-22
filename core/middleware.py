"""Security response headers for every Django response."""

from __future__ import annotations


class SecurityHeadersMiddleware:
    HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        # Inline styles allowed for our minimal HTML pages; scripts stay strict.
        "Content-Security-Policy": (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "img-src 'self' data:"
        ),
        "Referrer-Policy": "same-origin",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        for header, value in self.HEADERS.items():
            response.setdefault(header, value)
        return response
