from django.contrib import admin
from django.urls import include, path

from core.views import health_live, health_ready

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/live", health_live),
    path("health/ready", health_ready),
    path("api/mobile/v1/", include("mobile_api.urls")),
    path("", include("core.urls")),
    path("", include("tasks.urls")),
    path("", include("collaboration.urls")),
]
