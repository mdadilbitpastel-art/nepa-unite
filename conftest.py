"""Root pytest conftest — promotes the users-app fixtures to every test file."""

from users.tests.conftest import (  # noqa: F401
    admin_user,
    api_client,
    auditor_user,
    buyer_user,
    force_login,
    mock_celery_eager,
    mock_send_email,
    seller_user,
    tenant,
)
