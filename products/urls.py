from rest_framework.routers import DefaultRouter

from products.views import (
    JobViewSet,
    ProductReviewViewSet,
    ProductViewSet,
    WishlistViewSet,
)

router = DefaultRouter()
router.register(r"products", ProductViewSet, basename="products")
router.register(r"wishlist", WishlistViewSet, basename="wishlist")
router.register(r"reviews", ProductReviewViewSet, basename="reviews")
router.register(r"jobs", JobViewSet, basename="jobs")

urlpatterns = router.urls
