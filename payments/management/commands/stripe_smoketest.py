"""python manage.py stripe_smoketest [order_id] [--keep]

End-to-end Stripe test-mode smoke test, no frontend required:

  1. Confirm the secret key talks to Stripe (Balance.retrieve).
  2. Create a PaymentIntent for a draft order.
  3. Confirm it with Stripe's test card token `pm_card_visa`
     (what the card widget would do in the browser).
  4. Reconcile into the DB (Payment -> completed, Order -> confirmed).

By default it picks the most recent draft order; pass an order id to target a
specific one. The order really moves to `confirmed` (that is the point of the
test) -- use a throwaway draft order, or pass --keep to skip the DB reconcile
step if you only want to verify the Stripe side.
"""

from __future__ import annotations

import stripe
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from orders.models import Order
from payments import stripe_service


class Command(BaseCommand):
    help = "Run an end-to-end Stripe test-mode payment against a draft order."

    def add_arguments(self, parser):
        parser.add_argument(
            "order_id",
            nargs="?",
            default=None,
            help="Order UUID to pay. Defaults to the latest draft order.",
        )
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Only exercise the Stripe side; skip the DB reconcile/confirm.",
        )
        parser.add_argument(
            "--create",
            action="store_true",
            help="Create a throwaway $50 draft order if none exists (test only).",
        )

    def _create_throwaway_order(self) -> Order:
        """Build a minimal $50 draft order for the payment test.

        create_payment_intent only needs an order with a buyer, a tenant and a
        positive total_amount, so we keep this deliberately minimal (no items).
        """
        from decimal import Decimal

        from users.models import CustomUser, Tenant

        buyer = (
            CustomUser.objects.filter(role=CustomUser.Role.BUYER)
            .order_by("created_at")
            .first()
        )
        if buyer is None:
            raise CommandError(
                "No buyer account exists to attach a test order to. "
                "Sign up a buyer first."
            )
        tenant = buyer.tenant or Tenant.objects.first()
        if tenant is None:
            raise CommandError("No tenant exists to attach a test order to.")

        return Order.objects.create(
            buyer=buyer,
            tenant=tenant,
            total_amount=Decimal("50.00"),
            status=Order.Status.DRAFT,
        )

    def handle(self, *args, **options):
        ok = self.style.SUCCESS
        fail = self.style.ERROR

        # --- 1. Key + connectivity -----------------------------------------
        mode = stripe_service.stripe_mode()
        if mode == "unset":
            raise CommandError(
                "STRIPE_SECRET_KEY is not configured. Set it in .env and "
                "recreate the container (docker compose up -d --force-recreate web)."
            )
        healthy, health_err = stripe_service.stripe_health()
        if not healthy:
            raise CommandError(f"Stripe connectivity check failed: {health_err}")
        self.stdout.write(ok(f"1. Stripe reachable - key valid ({mode} mode)."))

        # --- 2. Pick an order ----------------------------------------------
        if options["order_id"]:
            try:
                order = Order.objects.get(pk=options["order_id"])
            except Order.DoesNotExist:
                raise CommandError(f"No order with id {options['order_id']}.")
        else:
            order = Order.objects.filter(status=Order.Status.DRAFT).order_by(
                "-created_at"
            ).first()
            if order is None and options["create"]:
                order = self._create_throwaway_order()
                self.stdout.write(ok(f"   Created throwaway draft order {order.pk}."))
            if order is None:
                raise CommandError(
                    "No draft order found. Re-run with --create to make a "
                    "throwaway one, or pass an order id."
                )
        self.stdout.write(
            f"   Using order {order.pk} (status={order.status}, "
            f"total=${order.total_amount})."
        )

        # --- 3. Create the PaymentIntent -----------------------------------
        stripe.api_key = settings.STRIPE_SECRET_KEY
        result = stripe_service.create_payment_intent(str(order.pk))
        pi_id = result["payment_intent_id"]
        self.stdout.write(ok(f"2. PaymentIntent created: {pi_id}"))

        # --- 4. Confirm with the test card ---------------------------------
        intent = stripe.PaymentIntent.confirm(
            pi_id,
            payment_method="pm_card_visa",
            return_url="https://example.com/return",
        )
        styled = ok if intent.status == "succeeded" else fail
        self.stdout.write(styled(f"3. Stripe status after confirm: {intent.status}"))

        if options["keep"]:
            self.stdout.write(
                "   --keep set: skipping DB reconcile (order left untouched)."
            )
            return

        # --- 5. Reconcile into the DB --------------------------------------
        synced = stripe_service.sync_payment_status(str(order.pk))
        order.refresh_from_db()
        payment = order.payments.order_by("-created_at").first()
        self.stdout.write(ok(f"4. Synced status: {synced}"))
        self.stdout.write(
            f"   Payment row: {payment.status} | Order: {order.status}"
        )

        if intent.status == "succeeded" and order.status == Order.Status.CONFIRMED:
            self.stdout.write(
                ok("\nSUCCESS - full payment loop works end to end.")
            )
        else:
            self.stdout.write(
                fail(
                    "\nSomething is off - check the statuses above and your "
                    "Stripe dashboard (test mode)."
                )
            )
