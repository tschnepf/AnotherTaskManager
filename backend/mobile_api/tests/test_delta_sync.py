import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from mobile_api.sync import decode_cursor
from tasks.models import TaskChangeEvent


@pytest.mark.django_db(transaction=True)
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_delta_sync_uses_opaque_cursor_tokens():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="sync@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    client.post(
        "/api/mobile/v1/tasks",
        {"title": "Task A", "area": "work"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="sync-key-1",
    )
    res = client.get("/api/mobile/v1/sync/delta")
    assert res.status_code == 200
    assert res.data["events"]
    assert str(res.data["next_cursor"]).startswith("v1.")
    assert all(str(item["cursor"]).startswith("v1.") for item in res.data["events"])

    follow_up = client.get("/api/mobile/v1/sync/delta", {"cursor": res.data["next_cursor"]})
    assert follow_up.status_code == 200


@pytest.mark.django_db(transaction=True)
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_delta_sync_cursor_expired_contract():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="sync-expired@example.com", password="StrongPass123!", organization=org)
    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    for idx in range(3):
        client.post(
            "/api/mobile/v1/tasks",
            {"title": f"Task {idx}", "area": "work"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"sync-expired-{idx}",
        )

    first = client.get("/api/mobile/v1/sync/delta")
    first_cursor = first.data["events"][0]["cursor"]
    first_cursor_id = decode_cursor(first_cursor)

    # Simulate retention purge by removing older events.
    TaskChangeEvent.objects.filter(id__lte=first_cursor_id + 1).delete()

    expired = client.get("/api/mobile/v1/sync/delta", {"cursor": first_cursor})
    assert expired.status_code == 410
    assert expired.data["error"]["code"] == "cursor_expired"
    assert "request_id" in expired.data
