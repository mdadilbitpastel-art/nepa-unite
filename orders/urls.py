from rest_framework.routers import DefaultRouter

from orders.views import CartViewSet, OrderViewSet

router = DefaultRouter()
router.register(r"orders", OrderViewSet, basename="orders")
router.register(r"cart", CartViewSet, basename="cart")

urlpatterns = router.urls
