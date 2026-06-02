"""Template context processors."""

from __future__ import annotations

from django.conf import settings


def session_settings(request):
    """Expose the inactivity timeout to templates (for the client idle timer)."""
    return {
        "inactivity_timeout": getattr(settings, "SESSION_INACTIVITY_TIMEOUT", 300),
    }
