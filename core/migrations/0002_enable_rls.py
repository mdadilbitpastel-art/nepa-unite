"""Enable PostgreSQL Row-Level Security on all tenant-scoped tables.

Each request must set the session GUC `app.current_tenant` to the caller's
tenant UUID (cast to text). The policies below filter every read/write so a
connection can only see rows belonging to that tenant.

Admins (and other privileged connections) can opt out by also setting
`app.bypass_rls = 'on'` on the session.
"""

from django.db import migrations


RLS_TABLES = [
    # table_name, tenant column expression (must equal current_setting('app.current_tenant'))
    ("users_customuser", "tenant_id::text"),
    ("users_tenant", "id::text"),
    ("products_product", "tenant_id::text"),
    ("products_productimage", (
        "(SELECT tenant_id::text FROM products_product p "
        "WHERE p.id = products_productimage.product_id)"
    )),
    ("orders_order", "tenant_id::text"),
    ("orders_orderitem", (
        "(SELECT tenant_id::text FROM orders_order o "
        "WHERE o.id = orders_orderitem.order_id)"
    )),
    ("payments_payment", (
        "(SELECT tenant_id::text FROM orders_order o "
        "WHERE o.id = payments_payment.order_id)"
    )),
    ("payments_invoice", (
        "(SELECT tenant_id::text FROM orders_order o "
        "WHERE o.id = payments_invoice.order_id)"
    )),
]


def _enable_sql() -> str:
    parts: list[str] = []
    for table, expr in RLS_TABLES:
        parts.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        parts.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        parts.append(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        parts.append(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ("
            f"  current_setting('app.bypass_rls', true) = 'on' "
            f"  OR {expr} = current_setting('app.current_tenant', true)"
            f") "
            f"WITH CHECK ("
            f"  current_setting('app.bypass_rls', true) = 'on' "
            f"  OR {expr} = current_setting('app.current_tenant', true)"
            f");"
        )
    return "\n".join(parts)


def _disable_sql() -> str:
    parts: list[str] = []
    for table, _ in RLS_TABLES:
        parts.append(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        parts.append(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        parts.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    return "\n".join(parts)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("users", "0001_initial"),
        ("products", "0001_initial"),
        ("orders", "0001_initial"),
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=_enable_sql(), reverse_sql=_disable_sql()),
    ]
