"""Idempotently create an admin user from environment variables.

Render's free tier has no Shell/SSH, so we can't run `createsuperuser`
interactively. Instead this command runs during the build (see build.sh)
and creates the admin from DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD
if it doesn't already exist. Safe to run on every deploy.
"""

import os

from django.core.management.base import BaseCommand

from users.models import CustomUser


class Command(BaseCommand):
    help = "Create an admin user from env vars if one does not already exist."

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "").strip()

        if not email or not password:
            self.stdout.write(
                "DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD not set — "
                "skipping admin creation."
            )
            return

        email = CustomUser.objects.normalize_email(email)

        if CustomUser.objects.filter(email__iexact=email).exists():
            self.stdout.write(f"Admin '{email}' already exists — skipping.")
            return

        CustomUser.objects.create_superuser(
            email=email,
            password=password,
            auth0_sub=f"env-admin:{email}",
        )
        self.stdout.write(self.style.SUCCESS(f"Admin '{email}' created."))
