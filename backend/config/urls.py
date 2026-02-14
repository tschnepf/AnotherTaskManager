from django.contrib import admin
from django.conf import settings
from django.views.static import serve
from django.urls import re_path
from django.urls import include, path

from core.views import health_live, health_ready

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/live", health_live),
    path("health/ready", health_ready),
    path("", include("core.urls")),
    path("", include("tasks.urls")),
    path("", include("collaboration.urls")),
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
