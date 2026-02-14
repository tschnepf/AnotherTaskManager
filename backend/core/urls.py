from django.urls import path

from core.auth_views import (
    LoginView,
    RefreshView,
    logout_view,
    register_view,
    tenant_check_view,
)

urlpatterns = [
    path("auth/register", register_view),
    path("auth/login", LoginView.as_view()),
    path("auth/refresh", RefreshView.as_view()),
    path("auth/logout", logout_view),
    path("auth/tenant-check/<uuid:organization_id>", tenant_check_view),
]
