from rest_framework.routers import DefaultRouter

from products.views import JobViewSet, ProductViewSet

router = DefaultRouter()
router.register(r"products", ProductViewSet, basename="products")
router.register(r"jobs", JobViewSet, basename="jobs")

urlpatterns = router.urls
