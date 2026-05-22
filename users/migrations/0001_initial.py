import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="WorkflowTemplate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("vertical_type", models.CharField(choices=[("dental", "Dental"), ("architectural", "Architectural"), ("dry_cleaning", "Dry cleaning"), ("law_office", "Law office"), ("other", "Other")], max_length=32)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "users_workflowtemplate"},
        ),
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("vertical_type", models.CharField(choices=[("dental", "Dental"), ("architectural", "Architectural"), ("dry_cleaning", "Dry cleaning"), ("law_office", "Law office"), ("other", "Other")], max_length=32)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("active", "Active"), ("suspended", "Suspended")], default="pending", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("workflow_template", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.PROTECT, related_name="tenants", to="users.workflowtemplate")),
            ],
            options={"db_table": "users_tenant"},
        ),
        migrations.CreateModel(
            name="CustomUser",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("auth0_sub", models.CharField(max_length=255, unique=True)),
                ("role", models.CharField(choices=[("admin", "Admin"), ("buyer", "Buyer"), ("seller", "Seller"), ("auditor", "Auditor")], max_length=16)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("active", "Active"), ("suspended", "Suspended")], default="pending", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(blank=True, db_column="tenant_id", null=True, on_delete=models.deletion.PROTECT, related_name="users", to="users.tenant")),
            ],
            options={"db_table": "users_customuser"},
        ),
    ]
