"""HTML-form definitions for the dev-mode auth UI."""

from __future__ import annotations

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from users.models import CustomUser, WorkflowTemplate


class SignupForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "you@business.com",
                                       "autocomplete": "email",
                                       "autofocus": "autofocus"}),
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"placeholder": "min 8 characters",
                                          "autocomplete": "new-password"}),
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "repeat password",
                                          "autocomplete": "new-password"}),
        label="Confirm password",
    )
    business_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "Your business"}),
    )
    role = forms.ChoiceField(
        choices=[
            (CustomUser.Role.SELLER, "Seller — I list products for sale"),
        ],
        widget=forms.HiddenInput(),
        initial=CustomUser.Role.SELLER,
    )
    vertical_type = forms.ChoiceField(
        choices=WorkflowTemplate.Vertical.choices,
        label="Industry / vertical",
    )
    logo = forms.ImageField(
        required=False,
        label="Company logo",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].lower()
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def clean_password(self) -> str:
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("password")
        pw_confirm = cleaned.get("password_confirm")
        if pw and pw_confirm and pw != pw_confirm:
            raise ValidationError({"password_confirm": "Passwords don't match."})
        return cleaned


class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "you@business.com",
                                       "autocomplete": "email",
                                       "autofocus": "autofocus"}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••",
                                          "autocomplete": "current-password"}),
    )


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "you@business.com",
                                       "autocomplete": "email",
                                       "autofocus": "autofocus"}),
    )


class ResetPasswordForm(forms.Form):
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"placeholder": "min 8 characters",
                                          "autocomplete": "new-password",
                                          "autofocus": "autofocus"}),
        label="New password",
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        label="Confirm new password",
    )

    def clean_password(self) -> str:
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("password")
        pw_confirm = cleaned.get("password_confirm")
        if pw and pw_confirm and pw != pw_confirm:
            raise ValidationError({"password_confirm": "Passwords don't match."})
        return cleaned


class ProfileForm(forms.Form):
    first_name = forms.CharField(
        max_length=150, required=False,
        widget=forms.TextInput(attrs={"placeholder": "First name"}),
    )
    last_name = forms.CharField(
        max_length=150, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Last name"}),
    )
    phone = forms.CharField(
        max_length=30, required=False,
        widget=forms.TextInput(attrs={"placeholder": "+1 (555) 123-4567"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "you@business.com"}),
    )
    business_name = forms.CharField(
        max_length=255, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Your business"}),
    )
    logo = forms.ImageField(
        required=False, label="Company logo",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )
    address_line1 = forms.CharField(
        max_length=255, required=False, label="Street address",
        widget=forms.TextInput(attrs={"placeholder": "123 Main Street"}),
    )
    address_line2 = forms.CharField(
        max_length=255, required=False, label="Apt / Suite / Unit",
        widget=forms.TextInput(attrs={"placeholder": "Suite 200 (optional)"}),
    )
    city = forms.CharField(
        max_length=100, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Scranton"}),
    )
    state = forms.CharField(
        max_length=100, required=False,
        widget=forms.TextInput(attrs={"placeholder": "PA"}),
    )
    zip_code = forms.CharField(
        max_length=20, required=False, label="ZIP code",
        widget=forms.TextInput(attrs={"placeholder": "18501"}),
    )
    country = forms.CharField(
        max_length=100, required=False,
        widget=forms.TextInput(attrs={"placeholder": "US"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].lower()
        qs = CustomUser.objects.filter(email__iexact=email)
        if self._user:
            qs = qs.exclude(pk=self._user.pk)
        if qs.exists():
            raise ValidationError("An account with this email already exists.")
        return email


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Current password",
                                          "autocomplete": "current-password"}),
    )
    new_password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"placeholder": "New password (min 8 chars)",
                                          "autocomplete": "new-password"}),
    )
    new_password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Confirm new password",
                                          "autocomplete": "new-password"}),
        label="Confirm new password",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def clean_current_password(self) -> str:
        pw = self.cleaned_data["current_password"]
        if self._user and not self._user.check_password(pw):
            raise ValidationError("Current password is incorrect.")
        return pw

    def clean_new_password(self) -> str:
        pw = self.cleaned_data["new_password"]
        validate_password(pw)
        return pw

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("new_password")
        pw2 = cleaned.get("new_password_confirm")
        if pw and pw2 and pw != pw2:
            raise ValidationError({"new_password_confirm": "Passwords don't match."})
        return cleaned
