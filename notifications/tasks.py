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
