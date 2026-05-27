"""Background tasks for the notifications app — welcome and approval emails."""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task
def send_welcome_email(user_email: str) -> None:
    send_mail(
        subject="Welcome to NEPA Unite",
        message=(
            "Thanks for registering. Your account is pending admin approval; "
            "we'll email you when it's active."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user_email],
        fail_silently=False,
    )


@shared_task
def send_approval_email(user_email: str) -> None:
    send_mail(
        subject="Your NEPA Unite account is approved",
        message="Your account has been approved and is now active.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user_email],
        fail_silently=False,
    )


@shared_task
def send_seller_onboarding_email(user_email: str) -> None:
    send_mail(
        subject="Finish setting up your NEPA Unite seller account",
        message=(
            "Your seller account is approved. Before you can list products and "
            "receive payouts, complete Stripe Connect onboarding from your "
            "dashboard — look for the 'Connect Stripe' banner on the "
            "My products page."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user_email],
        fail_silently=False,
    )


@shared_task
def send_suspension_email(user_email: str) -> None:
    send_mail(
        subject="Your NEPA Unite account has been suspended",
        message=(
            "An administrator has suspended your account. "
            "Reach out to support if you believe this is a mistake."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user_email],
        fail_silently=False,
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_new_order_notification(self, seller_email: str, order_id: str, total: str) -> None:
    """Notify seller about a new confirmed order."""
    try:
        send_mail(
            subject=f"New order #{order_id[:8]} — Action required",
            message=(
                f"You have a new order (#{order_id[:8]}) worth ${total}.\n\n"
                "Please fulfill it within 48 hours to avoid escalation.\n\n"
                "Log in to your NEPA Unite dashboard to view and process this order."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[seller_email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_new_order_notification retrying: %s", exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_order_status_email(self, seller_email: str, order_id: str, new_status: str, note: str = "") -> None:
    """Notify seller when admin changes order status."""
    try:
        body = f"Order #{order_id[:8]} has been moved to: {new_status}."
        if note:
            body += f"\n\nAdmin note: {note}"
        send_mail(
            subject=f"Order #{order_id[:8]} — Status update: {new_status}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[seller_email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_order_status_email retrying: %s", exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_password_reset_email(self, to_email: str, reset_url: str) -> None:
    """Send a password-reset link to the user."""
    try:
        send_mail(
            subject="Reset your NEPA Unite password",
            message=(
                "We received a request to reset the password for your "
                f"NEPA Unite account ({to_email}).\n\n"
                f"Click the link below to set a new password:\n{reset_url}\n\n"
                "This link will expire shortly. If you didn't request a "
                "password reset, you can safely ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_password_reset_email retrying after error: %s", exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_ses_email(self, to_email: str, subject: str, body: str) -> None:
    """Send an email via AWS SES (or Django's configured EMAIL_BACKEND).

    When EMAIL_BACKEND is set to django_ses.SESBackend the same call goes
    through SES; locally we keep the console backend. Either way we retry
    on transient failures.
    """
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_ses_email retrying after error: %s", exc)
        raise self.retry(exc=exc)
