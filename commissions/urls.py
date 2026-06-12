from django.urls import path

from commissions.views import (
    CommissionListView,
    CommissionRateDetailView,
    CommissionRateListCreateView,
    CommissionSummaryView,
)

urlpatterns = [
    path("commissions/", CommissionListView.as_view(), name="commission-list"),
    path(
        "commissions/summary/",
        CommissionSummaryView.as_view(),
        name="commission-summary",
    ),
    path(
        "commissions/rates/",
        CommissionRateListCreateView.as_view(),
        name="commission-rate-list",
    ),
    path(
        "commissions/rates/<uuid:pk>/",
        CommissionRateDetailView.as_view(),
        name="commission-rate-detail",
    ),
]
