from django.urls import path

from core.auth_views import (
    LoginView,
    RefreshView,
    logout_view,
    register_view,
    tenant_check_view,
)
from core.backup_views import database_backup_view, database_restore_view
from core.email_oauth_views import (
    gmail_oauth_disconnect_view,
    gmail_oauth_exchange_view,
    gmail_oauth_initiate_view,
    gmail_oauth_sync_view,
)
from core.email_imap_views import imap_sync_view
from core.settings_views import email_capture_settings_view

urlpatterns = [
    path("auth/register", register_view),
    path("auth/login", LoginView.as_view()),
    path("auth/refresh", RefreshView.as_view()),
    path("auth/logout", logout_view),
    path("auth/tenant-check/<uuid:organization_id>", tenant_check_view),
    path("settings/email-capture", email_capture_settings_view),
    path("settings/email-capture/oauth/google/initiate", gmail_oauth_initiate_view),
    path("settings/email-capture/oauth/google/exchange", gmail_oauth_exchange_view),
    path("settings/email-capture/oauth/google/disconnect", gmail_oauth_disconnect_view),
    path("settings/email-capture/oauth/google/sync", gmail_oauth_sync_view),
    path("settings/email-capture/imap/sync", imap_sync_view),
    path("ops/database/backup", database_backup_view),
    path("ops/database/restore", database_restore_view),
]
