from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models


class WorkflowTemplate(models.Model):
    class Vertical(models.TextChoices):
        AUTOMOTIVE = "automotive", "Automotive"
        ARCHITECTURAL = "architectural", "Architectural"
        CONSTRUCTION = "construction", "Construction"
        DENTAL = "dental", "Dental"
        DRY_CLEANING = "dry_cleaning", "Dry Cleaning"
        EDUCATION = "education", "Education"
        ELECTRONICS = "electronics", "Electronics"
        FOOD_BEVERAGE = "food_beverage", "Food & Beverage"
        HEALTHCARE = "healthcare", "Healthcare"
        HOSPITALITY = "hospitality", "Hospitality"
        LAW_OFFICE = "law_office", "Law Office"
        LOGISTICS = "logistics", "Logistics & Shipping"
        MANUFACTURING = "manufacturing", "Manufacturing"
        REAL_ESTATE = "real_estate", "Real Estate"
        RETAIL = "retail", "Retail"
        TECHNOLOGY = "technology", "Technology"
        TEXTILES = "textiles", "Textiles & Apparel"
        WHOLESALE = "wholesale", "Wholesale"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vertical_type = models.CharField(max_length=32, choices=Vertical.choices)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users_workflowtemplate"

    def __str__(self) -> str:
        return f"WorkflowTemplate[{self.vertical_type}]"


class Tenant(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    vertical_type = models.CharField(
        max_length=32, choices=WorkflowTemplate.Vertical.choices
    )
    workflow_template = models.ForeignKey(
        WorkflowTemplate,
        on_delete=models.PROTECT,
        related_name="tenants",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    logo = models.ImageField(upload_to="tenant_logos/", blank=True, default="")
    address_line1 = models.CharField(max_length=255, blank=True, default="")
    address_line2 = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=100, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")
    country = models.CharField(max_length=100, blank=True, default="US")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users_tenant"

    def __str__(self) -> str:
        return self.name


class CustomUserManager(BaseUserManager):
    def create_user(self, email: str, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_unusable_password()  # Auth0 owns the password
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("role", CustomUser.Role.ADMIN)
        extra_fields.setdefault("status", CustomUser.Status.ACTIVE)
        user = self.create_user(email=email, **extra_fields)
        if password:
            user.set_password(password)
            user.save(using=self._db)
        return user


class CustomUser(AbstractBaseUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        BUYER = "buyer", "Buyer"
        SELLER = "seller", "Seller"
        AUDITOR = "auditor", "Auditor"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True, default="")
    last_name = models.CharField(max_length=150, blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    auth0_sub = models.CharField(max_length=255, unique=True)
    role = models.CharField(max_length=16, choices=Role.choices)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="users",
        db_column="tenant_id",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    stripe_account_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = ["auth0_sub", "role"]

    objects = CustomUserManager()

    class Meta:
        db_table = "users_customuser"

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        # Pending users can log in (so we can route them to the
        # "awaiting approval" page); suspended users cannot.
        return self.status in (self.Status.ACTIVE, self.Status.PENDING)

    @property
    def is_staff(self) -> bool:
        return self.role == self.Role.ADMIN

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    def __str__(self) -> str:
        return f"{self.email} ({self.role})"
