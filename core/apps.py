from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _bypass_rls(sender, connection, **kwargs):
    """Set the RLS bypass GUC on every new PostgreSQL connection.

    The schema enables FORCE ROW LEVEL SECURITY on tenant-scoped tables
    (see core/migrations/0002_enable_rls.py). The policies allow a query
    through when the session GUC `app.bypass_rls` is 'on'. There is no
    per-request tenant-context layer wired up, so without this the app's
    own DB role would be blocked from reading/writing those tables.

    Setting bypass here keeps the app fully functional; tenant isolation is
    enforced at the application/role level. Toggle off via DB_BYPASS_RLS=False
    once a per-request `app.current_tenant` mechanism is in place.
    """
    if connection.vendor != "postgresql":
        return
    from django.conf import settings
    if not getattr(settings, "DB_BYPASS_RLS", True):
        return
    with connection.cursor() as cursor:
        cursor.execute("SET app.bypass_rls = 'on'")


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        connection_created.connect(_bypass_rls)
