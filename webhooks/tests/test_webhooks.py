"""Stripe + outgoing webhook coverage."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from orders.models import Order
from payments.models import Payment
from webhooks.handlers import (
    handle_charge_dispute_created,
    handle_payment_failed,
    handle_payment_succeeded,
)
from webhooks.models import WebhookDelivery, WebhookEndpoint


# ---------------------------------------------------------------------------
# Stripe receiver — signature verification
# ---------------------------------------------------------------------------
def test_stripe_webhook_rejects_invalid_signature(db, api_client):
    response = api_client.post(
        "/api/v1/webhooks/stripe",
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="bogus",
    )
    assert response.status_code == 400


def test_stripe_webhook_accepts_valid_signature(db, api_client):
    event = {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_x"}}}
    with patch("webhooks.views.stripe.Webhook.construct_event", return_value=event), \
         patch("webhooks.views.process_stripe_event") as task:
        response = api_client.post(
            "/api/v1/webhooks/stripe",
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=x",
        )
    assert response.status_code == 200
    task.delay.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
@pytest.fixture
def order(db, buyer_user, tenant):
    return Order.objects.create(
        buyer=buyer_user, tenant=tenant, total_amount=Decimal("100"),
    )


def test_handle_payment_succeeded_marks_completed_and_confirms_order(db, order):
    p = Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_ok",
        amount=Decimal("100"), platform_fee=Decimal("5"),
    )
    handle_payment_succeeded(
        {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_ok"}}}
    )
    p.refresh_from_db()
    order.refresh_from_db()
    assert p.status == Payment.Status.COMPLETED
    assert order.status == Order.Status.CONFIRMED


def test_handle_payment_failed_marks_failed_and_notifies(db, order):
    p = Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_fail",
        amount=Decimal("100"), platform_fee=Decimal("5"),
    )
    with patch("webhooks.handlers.notify") as notify_mock:
        handle_payment_failed(
            {"type": "payment_intent.payment_failed",
             "data": {"object": {"id": "pi_fail"}}}
        )
    p.refresh_from_db()
    assert p.status == Payment.Status.FAILED
    notify_mock.assert_called_once()


def test_handle_dispute_created_marks_disputed(db, order):
    p = Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_disputed",
        amount=Decimal("100"), platform_fee=Decimal("5"),
        status=Payment.Status.COMPLETED,
    )
    with patch("webhooks.handlers.notify"):
        handle_charge_dispute_created({
            "type": "charge.dispute.created",
            "data": {"object": {"id": "dp_x", "payment_intent": "pi_disputed"}}
        })
    p.refresh_from_db()
    assert p.status == Payment.Status.DISPUTED


# ---------------------------------------------------------------------------
# Outgoing webhook delivery — success, retry schedule, terminal failure
# ---------------------------------------------------------------------------
@pytest.fixture
def endpoint(db, buyer_user):
    return WebhookEndpoint.objects.create(
        owner=buyer_user,
        url="https://buyer.example.com/hook",
        secret="topsecret",
        event_types=[],  # all events
    )


def _delivery(endpoint):
    return WebhookDelivery.objects.create(
        endpoint=endpoint,
        event_type="order.created",
        payload={"hello": "world"},
    )


def test_outgoing_delivery_success(db, endpoint):
    from webhooks.tasks import deliver_webhook
    delivery = _delivery(endpoint)
    fake_response = MagicMock(status_code=200, text="ok")
    with patch("webhooks.tasks.requests.post", return_value=fake_response):
        deliver_webhook(str(delivery.pk))
    delivery.refresh_from_db()
    assert delivery.status == WebhookDelivery.Status.DELIVERED


def test_outgoing_delivery_schedules_retry_on_500(db, endpoint, settings):
    from webhooks.tasks import deliver_webhook
    settings.OUTGOING_WEBHOOK_RETRY_DELAYS = [60, 300, 1800, 7200, 86400]
    delivery = _delivery(endpoint)
    fake_response = MagicMock(status_code=500, text="boom")
    with patch("webhooks.tasks.requests.post", return_value=fake_response), \
         patch("webhooks.tasks.deliver_webhook.apply_async") as retry:
        deliver_webhook(str(delivery.pk))
    delivery.refresh_from_db()
    assert delivery.status == WebhookDelivery.Status.PENDING
    assert delivery.attempt == 1
    retry.assert_called_once()
    assert retry.call_args.kwargs["countdown"] == 60


def test_outgoing_delivery_fails_after_max_attempts(db, endpoint, settings):
    from webhooks.tasks import deliver_webhook
    settings.OUTGOING_WEBHOOK_RETRY_DELAYS = [1, 1, 1, 1, 1]
    delivery = _delivery(endpoint)
    delivery.attempt = 4  # next call is attempt 5 -> terminal
    delivery.save()
    fake_response = MagicMock(status_code=500, text="boom")
    with patch("webhooks.tasks.requests.post", return_value=fake_response), \
         patch("webhooks.tasks._notify_admin_endpoint_failed") as notify_admin:
        deliver_webhook(str(delivery.pk))
    delivery.refresh_from_db()
    assert delivery.status == WebhookDelivery.Status.FAILED
    notify_admin.assert_called_once()


def test_emit_platform_event_creates_one_delivery_per_endpoint(db, endpoint):
    from webhooks.tasks import emit_platform_event
    with patch("webhooks.tasks.deliver_webhook.delay") as deliver:
        emit_platform_event(
            event_type="order.created",
            payload={"order_id": "abc"},
        )
    assert WebhookDelivery.objects.count() == 1
    deliver.assert_called_once()


def test_emit_platform_event_ignores_unknown_types(db, endpoint):
    from webhooks.tasks import emit_platform_event
    emit_platform_event(event_type="bogus.event", payload={})
    assert WebhookDelivery.objects.count() == 0
