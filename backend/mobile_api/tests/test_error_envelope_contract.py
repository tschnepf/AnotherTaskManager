import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from mobile_api.throttles import MobileAuthRateThrottle
from mobile_api.sync import decode_cursor
from tasks.models import TaskChangeEvent


@pytest.mark.django_db
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_mobile_errors_use_standard_envelope():
    client = APIClient()
    unauth = client.get("/api/mobile/v1/session")
    assert unauth.status_code == 401
    assert set(unauth.data.keys()) >= {"error", "request_id"}
    assert set(unauth.data["error"].keys()) >= {"code", "message", "details"}
    tasks_unauth = client.get("/api/mobile/v1/tasks")
    assert tasks_unauth.status_code == 401

    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="err@example.com", password="StrongPass123!", organization=org)
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    missing_idempotency = client.post(
        "/api/mobile/v1/tasks",
        {"title": "Needs key", "area": "work"},
        format="json",
    )
    assert missing_idempotency.status_code == 201
    assert "id" in missing_idempotency.data


@pytest.mark.django_db(transaction=True)
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_cursor_expired_includes_request_id():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="cursorerr@example.com", password="StrongPass123!", organization=org)
    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    for idx in range(3):
        client.post(
            "/api/mobile/v1/tasks",
            {"title": f"T{idx}", "area": "work"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"cursor-{idx}",
        )

    sync = client.get("/api/mobile/v1/sync/delta")
    first_cursor = sync.data["events"][0]["cursor"]
    first_cursor_id = decode_cursor(first_cursor)
    TaskChangeEvent.objects.filter(id__lte=first_cursor_id + 1).delete()

    expired = client.get("/api/mobile/v1/sync/delta", {"cursor": first_cursor})
    assert expired.status_code == 410
    assert expired.data["error"]["code"] == "cursor_expired"
    assert "request_id" in expired.data


@pytest.mark.django_db
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_mobile_throttle_includes_retry_after_header():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="throttle@example.com", password="StrongPass123!", organization=org)
    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    cache.clear()
    original_rates = MobileAuthRateThrottle.THROTTLE_RATES
    MobileAuthRateThrottle.THROTTLE_RATES = {**dict(original_rates), "mobile_auth": "1/min"}
    try:
        first = client.get("/api/mobile/v1/session")
        assert first.status_code == 200

        second = client.get("/api/mobile/v1/session")
        assert second.status_code == 429
        assert "Retry-After" in second.headers
        assert str(second.headers["Retry-After"]).strip()
    finally:
        MobileAuthRateThrottle.THROTTLE_RATES = original_rates
