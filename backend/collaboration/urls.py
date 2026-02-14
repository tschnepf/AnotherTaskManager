from django.urls import include, path
from rest_framework.routers import DefaultRouter

from collaboration.views import SavedViewViewSet

router = DefaultRouter()
router.register(r"views", SavedViewViewSet, basename="saved-view")

urlpatterns = [
    path("", include(router.urls)),
]
