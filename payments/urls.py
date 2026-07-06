from django.urls import path

from payments.views import (
    DisburseView,
    OrderInvoiceView,
    OrderPaymentsView,
    PaymentConfigView,
    PaymentIntentView,
    PaymentSyncView,
    SellerOnboardView,
)

urlpatterns = [
    path("payments/config", PaymentConfigView.as_view(), name="payments-config"),
    path("payments/intent", PaymentIntentView.as_view(), name="payments-intent"),
    path("payments/disburse", DisburseView.as_view(), name="payments-disburse"),
    path("payments/<uuid:order_id>/sync", PaymentSyncView.as_view(), name="payments-sync"),
    path("payments/<uuid:order_id>", OrderPaymentsView.as_view(), name="payments-order"),
    path("sellers/onboard", SellerOnboardView.as_view(), name="sellers-onboard"),
    path("orders/<uuid:order_id>/invoice", OrderInvoiceView.as_view(), name="order-invoice"),
]
