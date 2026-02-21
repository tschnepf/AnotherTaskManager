import pytest
from django.test import override_settings

from core.models import Organization, User
from mobile_api.apns import APNSDeliveryResult
from mobile_api.models import MobileDevice, NotificationDelivery
from mobile_api.notifications import enqueue_notification
from mobile_api.tasks import process_pending_notifications


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
