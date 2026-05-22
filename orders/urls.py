from rest_framework.routers import DefaultRouter

from orders.views import OrderViewSet

router = DefaultRouter()
router.register(r"orders", OrderViewSet, basename="orders")

urlpatterns = router.urls
