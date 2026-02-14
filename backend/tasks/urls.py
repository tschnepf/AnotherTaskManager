from django.urls import include, path
from rest_framework.routers import DefaultRouter

from tasks.views import (
    ProjectViewSet,
    TagViewSet,
    TaskViewSet,
    bookmarklet_capture_view,
)

router = DefaultRouter()
router.register(r"tasks", TaskViewSet, basename="task")
router.register(r"projects", ProjectViewSet, basename="project")
router.register(r"tags", TagViewSet, basename="tag")

urlpatterns = [
    path("", include(router.urls)),
    path("capture/bookmarklet", bookmarklet_capture_view),
]
