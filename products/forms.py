"""HTML form definitions for the seller dashboard."""

from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from products.models import Product
from users.models import Tenant


class ProductForm(forms.ModelForm):
    """Create or edit a product from the seller's dashboard.

    Same instance handles both flows — pass `tenant` for SKU uniqueness
    scoping, and bind to an existing Product (`instance=`) for edit.
    Mirrors the API serializer's validation (price > 0, SKU unique
    per tenant). Vertical-specific `attributes` stay API-only for now.
    """

    class Meta:
        model = Product
        fields = ("sku", "name", "description", "price",
                  "inventory_count", "primary_image", "status")
        widgets = {
            "sku": forms.TextInput(attrs={
                "placeholder": "WIDGET-001", "autofocus": "autofocus"
            }),
            "name": forms.TextInput(attrs={
                "placeholder": "Cordless drill, 18V"
            }),
            "description": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": "Short product description.",
            }),
            "price": forms.NumberInput(attrs={
                "step": "0.01", "min": "0.01", "placeholder": "0.00"
            }),
            "inventory_count": forms.NumberInput(attrs={
                "step": "1", "min": "0", "placeholder": "0"
            }),
            # FileInput (not ClearableFileInput) — we don't want Django's
            # "Currently: <filename> [Clear]" inline UI. The current image
            # is shown via the preview icon, and image is required so
            # there's no clear path anyway. The data-image-preview hook
            # is picked up by core/static/js/image_preview.js.
            "primary_image": forms.FileInput(attrs={
                "accept": "image/*",
                "data-image-preview": "#product-image-preview-icon",
            }),
        }
        help_texts = {
            "sku": "Unique within your business. Letters, numbers, dashes.",
            "price": "Per-unit list price in USD.",
            "inventory_count": "Units currently in stock.",
            "primary_image": "JPG / PNG / WebP, up to ~5 MB.",
        }

    def __init__(self, *args, tenant: Tenant | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenant = tenant
        # All fields are required from the dashboard form even when the model
        # allows blanks — the API + legacy rows can still skip these, but the
        # HTML UI enforces a complete listing.
        self.fields["description"].required = True
        self.fields["primary_image"].required = True
        # Restrict status choices to Active / Inactive — DELETED is reserved
        # for the soft-delete action button, never user-selectable.
        self.fields["status"] = forms.ChoiceField(
            label="Status",
            choices=[
                (Product.Status.ACTIVE, "Active — visible in the catalog"),
                (Product.Status.INACTIVE, "Inactive — hidden from buyers"),
            ],
            initial=Product.Status.ACTIVE,
            help_text="Inactive listings stay in your dashboard but are hidden from buyers and search.",
        )

    def clean_sku(self) -> str:
        sku = self.cleaned_data["sku"].strip()
        if not sku:
            raise ValidationError("SKU cannot be blank.")
        if self._tenant:
            qs = Product.objects.filter(tenant=self._tenant, sku=sku)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(
                    "A product with this SKU already exists in your catalog."
                )
        return sku

    def clean_price(self) -> Decimal:
        price = self.cleaned_data["price"]
        if price <= 0:
            raise ValidationError("Price must be greater than zero.")
        return price
