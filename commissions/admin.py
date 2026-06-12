from django.contrib import admin

from commissions.models import Commission, CommissionRate


@admin.register(CommissionRate)
class CommissionRateAdmin(admin.ModelAdmin):
    list_display = ("category", "percent", "min_fee", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("category",)


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "order", "seller", "category", "base_amount",
        "rate_percent", "commission_amount", "status", "created_at",
    )
    list_filter = ("status", "category")
    search_fields = ("order__id", "seller__email")
    readonly_fields = (
        "order", "order_item", "seller", "category", "base_amount",
        "rate_percent", "commission_amount", "earned_at", "reversed_at",
        "created_at", "updated_at",
    )
