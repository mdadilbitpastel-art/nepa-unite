"""Primary / read-replica DB router.

Active in staging+production via settings. Development leaves
DATABASE_ROUTERS empty so all queries hit the default DB.
"""


class PrimaryReplicaRouter:
    READ_DB = "replica"
    WRITE_DB = "default"

    def db_for_read(self, model, **hints):
        from django.conf import settings
        return self.READ_DB if "replica" in settings.DATABASES else self.WRITE_DB

    def db_for_write(self, model, **hints):
        return self.WRITE_DB

    def allow_relation(self, obj1, obj2, **hints):
        db_set = {self.READ_DB, self.WRITE_DB}
        return obj1._state.db in db_set and obj2._state.db in db_set

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Migrations only ever run against the primary.
        return db == self.WRITE_DB
