from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """GET /api/health/ — checks DB + Redis connectivity."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        db_ok, db_error = self._check_db()
        redis_ok, redis_error = self._check_redis()

        overall = db_ok and redis_ok
        body = {
            "status": "ok" if overall else "degraded",
            "db": {"ok": db_ok, "error": db_error},
            "redis": {"ok": redis_ok, "error": redis_error},
        }
        http_status = (
            status.HTTP_200_OK if overall else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return Response(body, status=http_status)

    @staticmethod
    def _check_db() -> tuple[bool, str | None]:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True, None
        except Exception as exc:  # noqa: BLE001 - report any failure
            return False, str(exc)

    @staticmethod
    def _check_redis() -> tuple[bool, str | None]:
        try:
            cache.set("__healthcheck__", "ok", timeout=5)
            return cache.get("__healthcheck__") == "ok", None
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
