import pytest
from django.test import override_settings
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User


@pytest.mark.django_db
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_intents_idempotency_and_widget_snapshot():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="intent@example.com", password="StrongPass123!", organization=org)
    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    first = client.post(
        "/api/mobile/v1/intents/create-task",
        {"title": "From Siri"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="intent-key-1",
    )
    assert first.status_code == 201

    replay = client.post(
        "/api/mobile/v1/intents/create-task",
        {"title": "From Siri"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="intent-key-1",
    )
    assert replay.status_code == 201
    assert replay.data["id"] == first.data["id"]

    snapshot = client.get("/api/mobile/v1/widget/snapshot")
    assert snapshot.status_code == 200
    assert "generated_at" in snapshot.data
    assert "." not in snapshot.data["generated_at"]
    assert snapshot.data["generated_at"].endswith("Z")
    assert parse_datetime(snapshot.data["generated_at"]) is not None
    assert isinstance(snapshot.data["tasks"], list)
