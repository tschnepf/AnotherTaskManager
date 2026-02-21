from django.urls import path

from mobile_api.views import (
    IntentCreateTaskView,
    MePreferenceView,
    MobileDeltaSyncView,
    MobileDeviceDetailView,
    MobileDeviceRegisterView,
    MobileDeviceUnregisterView,
    MobileIdentityLinkDetailView,
    MobileIdentityLinkListCreateView,
    MobileMetaView,
    MobileSessionView,
    MobileTaskDetailView,
    MobileTaskListCreateView,
    NotificationPreferenceView,
    WidgetSnapshotView,
)

urlpatterns = [
    path("meta", MobileMetaView.as_view()),
    path("session", MobileSessionView.as_view()),
    path("tasks", MobileTaskListCreateView.as_view()),
    path("tasks/<uuid:task_id>", MobileTaskDetailView.as_view()),
    path("sync/delta", MobileDeltaSyncView.as_view()),
    path("me/preferences", MePreferenceView.as_view()),
    path("notifications/preferences", NotificationPreferenceView.as_view()),
    path("devices/register", MobileDeviceRegisterView.as_view()),
    path("devices/unregister", MobileDeviceUnregisterView.as_view()),
    path("devices/<uuid:device_id>", MobileDeviceDetailView.as_view()),
    path("intents/create-task", IntentCreateTaskView.as_view()),
    path("widget/snapshot", WidgetSnapshotView.as_view()),
    path("admin/identity-links", MobileIdentityLinkListCreateView.as_view()),
    path("admin/identity-links/<int:link_id>", MobileIdentityLinkDetailView.as_view()),
]
