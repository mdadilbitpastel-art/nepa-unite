import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0003_product_min_order_qty"),
        ("users", "0007_buyeraddress"),
    ]

    operations = [
        migrations.CreateModel(
            name="WishlistItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("product", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="wishlisted_by",
                    to="products.product",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="wishlist",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "products_wishlistitem",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="wishlistitem",
            constraint=models.UniqueConstraint(
                fields=("user", "product"), name="uniq_wishlist_per_user_product"
            ),
        ),
        migrations.CreateModel(
            name="ProductReview",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("rating", models.PositiveSmallIntegerField()),
                ("title", models.CharField(blank=True, default="", max_length=140)),
                ("body", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="reviews",
                    to="products.product",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="reviews_written",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "products_productreview",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="productreview",
            constraint=models.UniqueConstraint(
                fields=("product", "user"), name="uniq_review_per_user_product"
            ),
        ),
        migrations.AddConstraint(
            model_name="productreview",
            constraint=models.CheckConstraint(
                check=models.Q(("rating__gte", 1)) & models.Q(("rating__lte", 5)),
                name="review_rating_1_to_5",
            ),
        ),
    ]
