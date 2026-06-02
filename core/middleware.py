"""Security response headers + session inactivity timeout."""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class SecurityHeadersMiddleware:
    HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' https://cdn.jsdelivr.net https://js.stripe.com; "
            "img-src 'self' data: blob: https://res.cloudinary.com; "
            "connect-src 'self' https://api.stripe.com; "
            "frame-src https://js.stripe.com https://hooks.stripe.com"
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


class InactivityLogoutMiddleware:
    """Log session users out after a period of inactivity.

    We stamp the last-seen time on the session and, on the next request, sign
    the user out if more than ``SESSION_INACTIVITY_TIMEOUT`` seconds (default
    5 minutes) have passed with no activity. Each request resets the timer, so
    it is a *sliding* window.

    Only affects session-authenticated users (the HTML dashboard). API requests
    authenticate per-view via Auth0 JWT and carry no Django session, so
    ``request.user`` is anonymous here and they are skipped — their lifetime is
    governed by the token's own expiry.
    """

    SESSION_KEY = "last_activity"

    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout = int(getattr(settings, "SESSION_INACTIVITY_TIMEOUT", 300))

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            now = int(time.time())
            last = request.session.get(self.SESSION_KEY)
            if last is not None and (now - last) > self.timeout:
                logout(request)
                messages.info(
                    request,
                    "You were signed out after 5 minutes of inactivity. "
                    "Please sign in again.",
                )
                login_url = reverse("login")
                if request.method == "GET" and request.path != login_url:
                    return redirect(f"{login_url}?next={request.path}")
                return redirect(login_url)
            # Active request — slide the window forward.
            request.session[self.SESSION_KEY] = now

        return self.get_response(request)
