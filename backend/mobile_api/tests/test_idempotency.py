import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User


@pytest.mark.django_db
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_idempotency_required_and_conflict():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="idem@example.com", password="StrongPass123!", organization=org)
    token = RefreshToken.for_user(user)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    missing = client.post("/api/mobile/v1/tasks", {"title": "A", "area": "work"}, format="json")
    assert missing.status_code == 400
    assert missing.data["error"]["code"] == "validation_error"
    assert "request_id" in missing.data

    first = client.post(
        "/api/mobile/v1/tasks",
        {"title": "A", "area": "work"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="idem-key",
    )
    assert first.status_code == 201

    replay = client.post(
        "/api/mobile/v1/tasks",
        {"title": "A", "area": "work"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="idem-key",
    )
    assert replay.status_code == 201
    assert replay.data["id"] == first.data["id"]

    conflict = client.post(
        "/api/mobile/v1/tasks",
        {"title": "B", "area": "work"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="idem-key",
    )
    assert conflict.status_code == 409
    assert conflict.data["error"]["code"] == "idempotency_conflict"
