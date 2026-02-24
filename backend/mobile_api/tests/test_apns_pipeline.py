import pytest
from django.test import override_settings

from core.models import Organization, User
from mobile_api.apns import APNSDeliveryResult
from mobile_api.models import MobileDevice, NotificationDelivery
from mobile_api.notifications import enqueue_notification
from mobile_api.tasks import process_pending_notifications
from tasks.models import Task


def _make_device(user, org, token: str, installation_id: str = "install-1") -> MobileDevice:
    device = MobileDevice(
        user=user,
        organization=org,
        apns_environment=MobileDevice.APNsEnvironment.SANDBOX,
        device_installation_id=installation_id,
        app_bundle_id="com.example.taskhub",
    )
    device.set_apns_token(token)
    device.save()
    return device


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    APNS_ENABLED=True,
    APNS_KEY_ID="key-id",
    APNS_TEAM_ID="team-id",
    APNS_BUNDLE_ID="com.example.taskhub",
    APNS_PRIVATE_KEY_B64="ZmFrZQ==",
    APNS_PROVIDER="mock",
)
def test_apns_pipeline_sends_pending_delivery():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="push@example.com", password="StrongPass123!", organization=org)
    device = _make_device(user, org, token="push-token-1")

    enqueue_notification(device=device, dedupe_key="push-1", payload={"title": "hello"})
    result = process_pending_notifications(batch_size=10)
    assert result["claimed"] == 1
    delivery = NotificationDelivery.objects.get(dedupe_key="push-1")
    assert delivery.state == NotificationDelivery.State.SENT


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    APNS_ENABLED=True,
    APNS_KEY_ID="key-id",
    APNS_TEAM_ID="team-id",
    APNS_BUNDLE_ID="com.example.taskhub",
    APNS_PRIVATE_KEY_B64="ZmFrZQ==",
    APNS_PROVIDER="mock",
)
def test_apns_pipeline_cleans_dead_tokens(monkeypatch):
    from mobile_api import notifications as notifications_mod

    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="push-dead@example.com", password="StrongPass123!", organization=org)
    device = _make_device(user, org, token="push-token-dead", installation_id="install-dead")

    enqueue_notification(device=device, dedupe_key="push-dead", payload={"title": "dead"})

    monkeypatch.setattr(
        notifications_mod,
        "send_push_notification",
        lambda **kwargs: APNSDeliveryResult(ok=False, status=410, reason="Unregistered"),
    )

    result = process_pending_notifications(batch_size=10)
    assert result["claimed"] == 1

    delivery = NotificationDelivery.objects.get(dedupe_key="push-dead")
    assert delivery.state == NotificationDelivery.State.CANCELED
    assert not MobileDevice.objects.filter(id=device.id).exists()


@pytest.mark.django_db(transaction=True)
@override_settings(
    MOBILE_API_ENABLED=True,
    APNS_ENABLED=True,
    APNS_KEY_ID="key-id",
    APNS_TEAM_ID="team-id",
    APNS_BUNDLE_ID="com.example.taskhub",
    APNS_PRIVATE_KEY_B64="ZmFrZQ==",
    APNS_PROVIDER="mock",
    MOBILE_TASK_CHANGE_PUSH_ENABLED=True,
    MOBILE_TASK_CHANGE_PUSH_DEDUPE_WINDOW_SECONDS=3600,
    MOBILE_TASK_CHANGE_PUSH_TRIGGER_ASYNC=False,
)
def test_task_changes_enqueue_sync_hint_notifications_with_dedupe():
    org = Organization.objects.create(name="Org")
    owner = User.objects.create_user(email="owner@example.com", password="StrongPass123!", organization=org)
    teammate = User.objects.create_user(email="teammate@example.com", password="StrongPass123!", organization=org)
    _make_device(owner, org, token="sync-token-owner", installation_id="sync-owner")
    _make_device(teammate, org, token="sync-token-teammate", installation_id="sync-teammate")

    Task.objects.create(
        organization=org,
        created_by_user=owner,
        title="First task",
        area=Task.Area.WORK,
    )
    deliveries = list(NotificationDelivery.objects.all())
    sync_hints = [delivery for delivery in deliveries if (delivery.payload or {}).get("type") == "task_change_sync_hint"]
    assert len(sync_hints) == 2
    assert all(str(delivery.dedupe_key).startswith("task-sync:") for delivery in sync_hints)

    Task.objects.create(
        organization=org,
        created_by_user=owner,
        title="Second task",
        area=Task.Area.WORK,
    )
    deliveries_after = list(NotificationDelivery.objects.all())
    sync_hints_after = [
        delivery for delivery in deliveries_after if (delivery.payload or {}).get("type") == "task_change_sync_hint"
    ]
    assert len(sync_hints_after) == 2
