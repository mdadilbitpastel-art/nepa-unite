from django.urls import path

from webhooks.views import StripeWebhookView

urlpatterns = [
    path("webhooks/stripe", StripeWebhookView.as_view(), name="webhooks-stripe"),
]
