from rest_framework.routers import DefaultRouter

from orders.views import CartViewSet, OrderViewSet, ReturnViewSet

router = DefaultRouter()
router.register(r"orders", OrderViewSet, basename="orders")
router.register(r"cart", CartViewSet, basename="cart")
router.register(r"returns", ReturnViewSet, basename="return")

urlpatterns = router.urls
