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
            (CustomUser.Role.BUYER, "Buyer — I purchase from member businesses"),
            (CustomUser.Role.SELLER, "Seller — I list products for sale"),
        ],
        widget=forms.Select(),
    )
    vertical_type = forms.ChoiceField(
        choices=WorkflowTemplate.Vertical.choices,
        label="Industry / vertical",
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
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
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
