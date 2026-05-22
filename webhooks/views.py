"""Stripe webhook receiver.

Verifies the Stripe-Signature header, persists the raw event, and dispatches
to handlers asynchronously so the endpoint returns 200 quickly.
"""

from __future__ import annotations

import logging

import stripe
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from webhooks.tasks import process_stripe_event

logger = logging.getLogger(__name__)


class StripeWebhookView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.body
        sig_header = request.headers.get("Stripe-Signature", "")
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=settings.STRIPE_WEBHOOK_SECRET,
            )
        except (ValueError, stripe.error.SignatureVerificationError) as exc:
            logger.warning("Invalid Stripe webhook signature: %s", exc)
            return Response(
                {"detail": "invalid signature"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        process_stripe_event.delay(event)
        return Response({"received": True})
