"""HTML form definitions for the seller dashboard."""

from __future__ import annotations

import json
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from products.categories import CATEGORY_FIELDS, INDUSTRY_CATEGORIES
from products.models import Product
from users.models import Tenant


ATTR_FIELDS = CATEGORY_FIELDS["_common"]


class ProductForm(forms.ModelForm):
    category = forms.ChoiceField(
        choices=[("", "Select category…")],
        required=True,
        label="Category",
    )

    weight = forms.DecimalField(required=False, max_digits=10, decimal_places=2,
                                widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}))
    dimensions = forms.CharField(required=False, max_length=100,
                                 widget=forms.TextInput(attrs={"placeholder": "30 x 20 x 15 cm"}))
    material = forms.CharField(required=False, max_length=100,
                               widget=forms.TextInput(attrs={"placeholder": "e.g. Stainless steel"}))
    brand = forms.CharField(required=False, max_length=100,
                            widget=forms.TextInput(attrs={"placeholder": "e.g. DeWalt"}))
    model_number = forms.CharField(required=False, max_length=100,
                                   widget=forms.TextInput(attrs={"placeholder": "e.g. DCD771C2"}))
    color = forms.CharField(required=False, max_length=100,
                            widget=forms.TextInput(attrs={"placeholder": "e.g. Black, Silver"}))
    warranty = forms.CharField(required=False, max_length=100,
                               widget=forms.TextInput(attrs={"placeholder": "e.g. 2 years"}))
    country_of_origin = forms.CharField(required=False, max_length=100,
                                        widget=forms.TextInput(attrs={"placeholder": "e.g. USA"}))

    class Meta:
        model = Product
        fields = ("sku", "name", "description", "price",
                  "inventory_count", "min_order_qty", "primary_image")
        widgets = {
            "sku": forms.TextInput(attrs={"placeholder": "WIDGET-001"}),
            "name": forms.TextInput(attrs={"placeholder": "Cordless drill, 18V"}),
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "Short product description."}),
            "price": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "placeholder": "0.00"}),
            "inventory_count": forms.NumberInput(attrs={"step": "1", "min": "0", "placeholder": "0"}),
            "min_order_qty": forms.NumberInput(attrs={"step": "1", "min": "1", "placeholder": "1"}),
            "primary_image": forms.FileInput(attrs={
                "accept": "image/*",
                "data-image-preview": "#product-image-preview-icon",
            }),
        }
        help_texts = {
            "sku": "Unique within your business.",
            "price": "Per-unit list price in USD.",
        }

    def __init__(self, *args, tenant: Tenant | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenant = tenant
        self.fields["description"].required = True
        self.fields["primary_image"].required = True

        vertical = ""
        if tenant:
            vertical = tenant.vertical_type or ""

        cats = INDUSTRY_CATEGORIES.get(vertical, INDUSTRY_CATEGORIES.get("other", []))
        self.fields["category"].choices = [("", "Select category…")] + [
            (c, c) for c in cats
        ]

        if self.instance and self.instance.pk:
            attrs = self.instance.attributes or {}
            self.fields["category"].initial = attrs.get("category", "")
            for f in ATTR_FIELDS:
                if f["name"] in attrs and f["name"] in self.fields:
                    self.fields[f["name"]].initial = attrs[f["name"]]

        self.industry_categories_json = json.dumps(INDUSTRY_CATEGORIES)
        self.attr_fields = ATTR_FIELDS

    def clean_sku(self) -> str:
        sku = self.cleaned_data["sku"].strip()
        if not sku:
            raise ValidationError("SKU cannot be blank.")
        if self._tenant:
            qs = Product.objects.filter(tenant=self._tenant, sku=sku)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError("A product with this SKU already exists in your catalog.")
        return sku

    def clean_price(self) -> Decimal:
        price = self.cleaned_data["price"]
        if price <= 0:
            raise ValidationError("Price must be greater than zero.")
        return price

    def save(self, commit=True):
        product = super().save(commit=False)
        attrs = product.attributes or {}
        attrs["category"] = self.cleaned_data.get("category", "")
        for f in ATTR_FIELDS:
            val = self.cleaned_data.get(f["name"], "")
            if val:
                attrs[f["name"]] = str(val)
            elif f["name"] in attrs:
                del attrs[f["name"]]
        product.attributes = attrs
        if commit:
            product.save()
        return product
