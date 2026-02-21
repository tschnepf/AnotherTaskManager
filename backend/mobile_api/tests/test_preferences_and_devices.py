import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from mobile_api.models import MobileDevice


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_AUTH_ENABLED=False,
    APNS_USE_SANDBOX=True,
    APNS_BUNDLE_ID="com.example.taskhub",
)
def test_preferences_split_and_device_registration():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="prefs@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    me_get = client.get("/api/mobile/v1/me/preferences")
    assert me_get.status_code == 200
    notif_get = client.get("/api/mobile/v1/notifications/preferences")
    assert notif_get.status_code == 200

    me_patch = client.patch(
        "/api/mobile/v1/me/preferences",
        {"show_completed_default": True, "start_of_week": "sunday"},
        format="json",
    )
    assert me_patch.status_code == 200
    assert me_patch.data["show_completed_default"] is True

    notif_patch = client.patch(
        "/api/mobile/v1/notifications/preferences",
        {"timezone": "America/New_York", "due_soon_offset_minutes": 45},
        format="json",
    )
    assert notif_patch.status_code == 200
    assert notif_patch.data["timezone"] == "America/New_York"

    register = client.post(
        "/api/mobile/v1/devices/register",
        {
            "apns_token": "abc123token",
            "apns_environment": MobileDevice.APNsEnvironment.SANDBOX,
            "device_installation_id": "install-1",
            "app_bundle_id": "com.example.taskhub",
            "app_version": "1.0",
            "app_build": "100",
            "ios_version": "18.0",
            "timezone": "America/New_York",
        },
        format="json",
    )
    assert register.status_code == 201
    device_id = register.data["id"]

    patch = client.patch(
        f"/api/mobile/v1/devices/{device_id}",
        {"app_version": "1.0.1", "app_build": "101"},
        format="json",
    )
    assert patch.status_code == 200
    assert patch.data["app_version"] == "1.0.1"

    bad_bundle = client.post(
        "/api/mobile/v1/devices/register",
        {
            "apns_token": "token-2",
            "apns_environment": MobileDevice.APNsEnvironment.SANDBOX,
            "app_bundle_id": "com.wrong.bundle",
        },
        format="json",
    )
    assert bad_bundle.status_code == 400


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_AUTH_ENABLED=False,
    APNS_USE_SANDBOX=True,
)
def test_xcode_compat_register_and_unregister():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="xcode-device@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    register = client.post(
        "/api/mobile/v1/devices/register",
        {"token": "xcode-token-1", "platform": "ios", "app_version": "1.2.3"},
        format="json",
    )
    assert register.status_code == 201
    assert register.data["app_version"] == "1.2.3"

    token_hash = MobileDevice.hash_apns_token("xcode-token-1")
    assert MobileDevice.objects.filter(
        user=user,
        organization=org,
        apns_token_hash=token_hash,
        apns_environment=MobileDevice.APNsEnvironment.SANDBOX,
    ).exists()

    unregister = client.post(
        "/api/mobile/v1/devices/unregister",
        {"token": "xcode-token-1", "platform": "ios"},
        format="json",
    )
    assert unregister.status_code == 200
    assert unregister.data["unregistered"] is True
    assert unregister.data["deleted"] is True

    assert not MobileDevice.objects.filter(
        user=user,
        organization=org,
        apns_token_hash=token_hash,
        apns_environment=MobileDevice.APNsEnvironment.SANDBOX,
    ).exists()


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_AUTH_ENABLED=False,
    APNS_USE_SANDBOX=True,
)
def test_xcode_compat_rejects_non_ios_platform():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="xcode-device-bad@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    register = client.post(
        "/api/mobile/v1/devices/register",
        {"token": "xcode-token-2", "platform": "android", "app_version": "1.2.3"},
        format="json",
    )
    assert register.status_code == 400

    unregister = client.post(
        "/api/mobile/v1/devices/unregister",
        {"token": "xcode-token-2", "platform": "android"},
        format="json",
    )
    assert unregister.status_code == 400
