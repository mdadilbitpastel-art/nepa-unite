"""Session inactivity auto-logout (InactivityLogoutMiddleware)."""

from __future__ import annotations

import time

from django.test import Client
from django.urls import reverse

from core.middleware import InactivityLogoutMiddleware


def test_idle_session_is_logged_out(db, buyer_user, settings):
    settings.SESSION_INACTIVITY_TIMEOUT = 300
    client = Client()
    client.force_login(buyer_user)

    # Simulate the last activity being > 5 minutes ago.
    session = client.session
    session[InactivityLogoutMiddleware.SESSION_KEY] = int(time.time()) - 301
    session.save()

    response = client.get(reverse("dashboard"))

    # Bounced to login, and the session is no longer authenticated.
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))
    assert "_auth_user_id" not in client.session


def test_active_session_stays_logged_in(db, buyer_user, settings):
    settings.SESSION_INACTIVITY_TIMEOUT = 300
    client = Client()
    client.force_login(buyer_user)

    # Last activity just now — within the window.
    session = client.session
    session[InactivityLogoutMiddleware.SESSION_KEY] = int(time.time())
    session.save()

    client.get(reverse("dashboard"))

    # Still authenticated; timer slid forward.
    assert "_auth_user_id" in client.session
    assert InactivityLogoutMiddleware.SESSION_KEY in client.session


def test_first_request_sets_timer_without_logout(db, buyer_user):
    client = Client()
    client.force_login(buyer_user)
    # No last_activity yet → must NOT log out on first request.
    client.get(reverse("dashboard"))
    assert "_auth_user_id" in client.session
    assert InactivityLogoutMiddleware.SESSION_KEY in client.session


def test_keepalive_ok_for_active_session(db, buyer_user):
    client = Client()
    client.force_login(buyer_user)
    response = client.get(reverse("keepalive"))
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_keepalive_redirects_when_timed_out(db, buyer_user, settings):
    settings.SESSION_INACTIVITY_TIMEOUT = 300
    client = Client()
    client.force_login(buyer_user)
    session = client.session
    session[InactivityLogoutMiddleware.SESSION_KEY] = int(time.time()) - 301
    session.save()

    response = client.get(reverse("keepalive"))
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


def test_keepalive_requires_login(db):
    response = Client().get(reverse("keepalive"))
    assert response.status_code == 302  # login_required bounce
